"""Frame Art: rota obras en el modo Arte de una Samsung Frame, con paspartú y complementos.

Todo lo que cambia según el gusto de cada quien es un plugin (ver docs/PLUGINS.md):
fuentes de imágenes (reframed, Immich, las tuyas), franjas sobre el paspartú (pronóstico, ficha de la obra)
y traductores. Interfaz web en WEB_PORT.
"""
import hashlib
import io
import json
import os
import random
import sys
import threading
import time
import urllib.parse
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests
from PIL import Image, ImageDraw, ImageOps

import plugins
from frameart import DATA, PORTRAIT, Cell, RenderCtx, UserError, read_json, run_with_timeout, shade, write_json

ENV_INTERVAL = float(os.environ.get("INTERVAL_HOURS", "6"))
RETRY = int(os.environ.get("RETRY_MINUTES", "10")) * 60
WEB_PORT = int(os.environ.get("WEB_PORT", "8099"))
CACHE_MB = float(os.environ.get("CACHE_MB", "500"))
APP = os.path.dirname(os.path.abspath(__file__))
SETTINGS = os.path.join(DATA, "settings.json")
LIBRARY = os.path.join(DATA, "library.json")
CURRENT = os.path.join(DATA, "current")
THUMBS = os.path.join(DATA, "thumbs")
CACHE = os.path.join(DATA, "cache")
TRANSLATIONS = os.path.join(DATA, "translations.json")
RENDERED = os.path.join(DATA, "current_rendered.jpg")
HISTORY_MAX = 24

Image.MAX_IMAGE_PIXELS = 250_000_000
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stdout)
log = logging.getLogger("frame-art")

lock = threading.Lock()        # una sola operación contra la TV a la vez
lib_lock = threading.Lock()
status = {"busy": False, "message": "iniciando", "level": "ok", "updated": None, "title": None, "warnings": []}

MATTE_COLORS = {  # nombre -> color de fondo
    "blanco": (250, 250, 248),
    "crema": (238, 230, 212),
    "gris": (200, 200, 198),
    "negro": (20, 20, 20),
}
CORE_DEFAULTS = {"matte": True, "matte_color": "crema", "margin": 180, "interval_hours": ENV_INTERVAL,
                 "only_favorites": False, "language": "es", "layout": "auto"}
LIMITS = {"margin": (0, 400), "interval_hours": (0.25, 168)}


def set_status(message: str, busy: bool | None = None, level: str = "ok") -> None:
    status["message"] = message
    status["level"] = level
    status["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    if busy is not None:
        status["busy"] = busy


# ───────────────────────── ajustes ─────────────────────────

def _field_default(f: dict):
    return f.get("default", False if f["type"] == "bool" else "")


def plugin_defaults(p) -> dict:
    return {"enabled": p.enabled_by_default, **{f["key"]: _field_default(f) for f in p.settings}}


def migrate(raw: dict) -> dict:
    """Ajustes de antes de los plugins (claves planas) → estructura por plugin."""
    if "plugins" in raw or not any(k in raw for k in ("weather", "source", "caption", "immich_url")):
        return raw
    src = raw.get("source", "reframed")
    pl = {
        "weather": {"enabled": raw.get("weather", True), **{k: raw[k] for k in ("city", "lat", "lon", "hours") if k in raw}},
        "caption": {"enabled": raw.get("caption", True)},
        "reframed": {"enabled": src in ("reframed", "mixto"), "artist": raw.get("artist", "")},
        "immich": {"enabled": src in ("immich", "mixto"), "url": raw.get("immich_url", ""), "key": raw.get("immich_key", ""),
                   "album": raw.get("immich_album", "")},
    }
    core = {k: raw[k] for k in CORE_DEFAULTS if k in raw}
    return {**core, "plugins": pl}


def load_settings() -> dict:
    raw = migrate(read_json(SETTINGS, {}))
    cfg = {**CORE_DEFAULTS, **{k: raw[k] for k in CORE_DEFAULTS if k in raw}, "plugins": {}}
    stored = raw.get("plugins", {})
    for pid in set(stored) | set(plugins.REGISTRY):
        p = plugins.REGISTRY.get(pid)
        cfg["plugins"][pid] = {**(plugin_defaults(p) if p else {}), **stored.get(pid, {})}
    return cfg


def _coerce(f: dict, val, default):
    t = f["type"]
    if t == "bool":
        return bool(val)
    if t == "number":
        try:
            num = float(val)
        except (TypeError, ValueError):
            raise ValueError(f"Valor inválido para «{f.get('label', f['key'])}»")
        num = min(f.get("max", num), max(f.get("min", num), num))
        return int(num) if isinstance(default, int) and not isinstance(default, bool) else num
    if t == "hidden":
        return type(default)(val) if default != "" else val
    return str(val).strip()


def save_settings(body: dict) -> dict:
    """body = {"core": {...}, "plugins": {id: {...}}}. Solo se tocan las claves recibidas."""
    cur = load_settings()
    core = body.get("core", {})
    for key, default in CORE_DEFAULTS.items():
        if key not in core:
            continue
        val = core[key]
        if isinstance(default, bool):
            cur[key] = bool(val)
        elif key in LIMITS:
            lo, hi = LIMITS[key]
            try:
                cur[key] = type(default)(min(hi, max(lo, float(val))))
            except (TypeError, ValueError):
                raise ValueError(f"Valor inválido para {key}")
        else:
            cur[key] = str(val).strip()
    if cur["matte_color"] not in MATTE_COLORS:
        cur["matte_color"] = "crema"
    cur["language"] = (cur["language"] or "es").lower()[:8]
    for pid, raw in body.get("plugins", {}).items():
        p = plugins.REGISTRY.get(pid)
        if not p:
            continue
        before, merged = cur["plugins"][pid], dict(cur["plugins"][pid])
        if "enabled" in raw:
            merged["enabled"] = bool(raw["enabled"])
        for f in p.settings:
            k = f["key"]
            if k not in raw:
                continue
            if f["type"] == "password" and not str(raw[k]).strip():
                continue  # la clave no se envía de vuelta a la interfaz; vacío = no cambiar
            merged[k] = _coerce(f, raw[k], _field_default(f))
        cur["plugins"][pid] = p.normalize(raw, merged, before)
    write_json(SETTINGS, cur)
    return cur


def public_settings() -> dict:
    s = load_settings()
    out = {**s, "plugins": {}}
    for pid, vals in s["plugins"].items():
        p = plugins.REGISTRY.get(pid)
        if not p:
            continue
        vals, hidden = dict(vals), {}
        for f in p.settings:
            if f["type"] == "password":
                hidden[f["key"]] = bool(vals.pop(f["key"], ""))
        out["plugins"][pid] = {**vals, "_set": hidden}
    return out


def plugin_schema() -> dict:
    items = [{"id": p.id, "label": p.label, "kind": p.kind, "description": p.description, "settings": p.settings,
              **({"position": p.position} if p.kind == "band" else {})} for p in plugins.REGISTRY.values()]
    installed = set(plugins.installed_names())
    cat = [{**m, "installed": m["name"] in installed} for m in plugins.catalog()]
    return {"plugins": sorted(items, key=lambda x: x["label"].lower()), "errors": plugins.ERRORS, "mattes": list(MATTE_COLORS), "layout": load_settings()["layout"],
            "catalog": cat}


def enabled(cfg: dict, kind: str) -> list:
    return [p for p in plugins.of_kind(kind) if cfg["plugins"].get(p.id, {}).get("enabled")]


# ───────────────────────── imágenes: caché en disco y elección ─────────────────────────

def cache_base(k: str) -> str:
    return os.path.join(CACHE, hashlib.sha1(k.encode()).hexdigest()[:20])


def prune_cache() -> None:
    """Borra lo menos usado hasta bajar del límite (CACHE_MB)."""
    try:
        files = [(e.stat().st_atime, e.stat().st_size, e.path) for e in os.scandir(CACHE) if e.is_file()]
    except OSError:
        return
    total = sum(s for _, s, _ in files)
    for _, size, path in sorted(files):
        if total <= CACHE_MB * 1_048_576:
            break
        try:
            os.remove(path)
            total -= size
        except OSError:
            pass


def fetch_item(cfg: dict, item: dict) -> tuple:
    """(JPEG, ficha). Cada obra se descarga una sola vez: después sale de la caché en disco."""
    base = cache_base(key_of(item))
    if os.path.exists(base + ".jpg"):
        try:
            with open(base + ".jpg", "rb") as f:
                data = f.read()
            os.utime(base + ".jpg")
            return data, read_json(base + ".json", {}).get("info") or item.get("info")
        except OSError:
            pass
    src = plugins.get(item["source"], "source")
    try:
        raw, info = src.fetch(cfg["plugins"][src.id], item)
    except (requests.ConnectionError, requests.Timeout) as exc:
        raise UserError(f"No se pudo descargar la imagen ({type(exc).__name__}): revisa la conexión") from exc
    info = info or item.get("info")
    data, _ = to_jpeg(raw)
    os.makedirs(CACHE, exist_ok=True)
    with open(base + ".jpg", "wb") as f:
        f.write(data)
    write_json(base + ".json", {"info": info})
    prune_cache()
    return data, info


def with_info(item: dict, info: dict | None) -> dict:
    """Copia mínima de la obra para guardar; el título pasa a ser «Obra — Autor» si la ficha lo trae."""
    out = {**{k: item[k] for k in ("source", "key", "title")}, "info": info}
    if info:
        if info.get("title"):
            out["title"] = f"{info['title']} — {info['artist']}" if info.get("artist") else info["title"]
    return out


def list_candidates(src, cfg: dict) -> list:
    try:
        cands = src.candidates(cfg["plugins"][src.id])
    except (UserError, ValueError):
        raise
    except Exception as exc:  # noqa: BLE001
        raise UserError(f"{src.label}: no se pudo obtener la lista de obras ({type(exc).__name__})") from exc
    return [{**c, "source": src.id} for c in cands]


def pick_random(cfg: dict, portrait: bool | None, exclude: set, tries: int = 12) -> tuple:
    lib = load_library()
    blocked, favs = set(lib["blocked"]), set(lib["favorites"])
    sources = enabled(cfg, "source")
    if not sources:
        raise UserError("No hay ninguna fuente de imágenes activada")
    cache: dict = {}
    for _ in range(tries):
        src = random.choice(sources)
        pcfg = cfg["plugins"][src.id]
        if cfg["only_favorites"]:
            cands = [{**lib["items"][k], "w": None, "h": None} for k in favs if k in lib["items"] and lib["items"][k]["source"] == src.id]
        else:
            if src.id not in cache:
                cache[src.id] = list_candidates(src, cfg)
            cands = cache[src.id]
        cands = [c for c in cands if key_of(c) not in blocked and key_of(c) not in exclude]
        if portrait is not None:
            known = [c for c in cands if c.get("w") and c.get("h")]
            if known:
                cands = [c for c in known if (c["w"] / c["h"] < PORTRAIT) == portrait]
        if not cands:
            continue
        item = random.choice(cands)
        exclude = exclude | {key_of(item)}
        if portrait is not None and not (item.get("w") and item.get("h")):
            try:  # orientación barata (sin bajar el original) para no descargar obras que se van a descartar
                dims = src.probe(pcfg, item)
            except UserError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.info("sin proporción de %s: %s", item["key"], exc)
                dims = None
            if dims and (dims[0] / dims[1] < PORTRAIT) != portrait:
                continue
        try:
            data, info = fetch_item(cfg, item)
        except UserError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.info("imagen descartada (%s): %s", item["key"], exc)
            continue
        size = Image.open(io.BytesIO(data)).size
        if portrait is not None and (size[0] / size[1] < PORTRAIT) != portrait:
            continue
        return with_info(item, info), data
    where = ", ".join(s.label for s in sources)
    extra = " entre las favoritas" if cfg["only_favorites"] else ""
    raise UserError(f"No encontré una imagen{' vertical' if portrait else ''} válida en {where}{extra}")


# ───────────────────────── traducción ─────────────────────────

def _keep_case(original: str, translated: str) -> str:
    """Los traductores bajan la mayúscula inicial de textos cortos («Utopia» → «utopía»): se conserva la del original."""
    if original[:1].isupper() and translated[:1].islower():
        return translated[:1].upper() + translated[1:]
    return translated


def localize(info: dict | None, cfg: dict, warnings: list, fields: tuple = ("desc",)) -> dict | None:
    """Ficha en el idioma elegido, usando el primer traductor activo; si falla se deja el original con un aviso.

    `fields` son los campos a traducir; el autor nunca se traduce. Si se traduce el título, el original queda en `title_orig`."""
    target = cfg["language"]
    if not info or not info.get("lang") or info["lang"] == target:
        return info
    texts = [info[k] for k in fields if info.get(k)]
    if not texts:
        return info
    cache = read_json(TRANSLATIONS, {})
    ck = lambda t: f"{info['lang']}>{target}|{t}"  # noqa: E731
    missing = [t for t in texts if ck(t) not in cache]
    if missing:
        translators = enabled(cfg, "translator")
        if not translators:
            return info
        tr = translators[0]
        try:
            for t, out in zip(missing, tr.translate(cfg["plugins"][tr.id], missing, info["lang"], target)):
                cache[ck(t)] = out
            write_json(TRANSLATIONS, cache)
        except Exception as exc:  # noqa: BLE001
            log.info("sin traducción (%s): %s", tr.id, exc)
            msg = f"No se pudo traducir con «{tr.label}» ({type(exc).__name__}): la ficha queda en {info['lang']}"
            if msg not in warnings:
                warnings.append(msg)
            return info
    done = {k: _keep_case(info[k], cache[ck(info[k])]) for k in fields if info.get(k)}
    return {**info, **done, **({"title_orig": info["title"]} if "title" in done else {}), "lang": target}


# ───────────────────────── biblioteca (historial, favoritas, ocultas) ─────────────────────────

def load_library() -> dict:
    lib = read_json(LIBRARY, {})
    return {"items": lib.get("items", {}), "history": lib.get("history", []),
            "favorites": lib.get("favorites", []), "blocked": lib.get("blocked", [])}


def to_jpeg(data: bytes) -> tuple[bytes, tuple[int, int]]:
    """Normaliza a JPEG con la orientación EXIF aplicada; si ya es un JPEG derecho se deja intacto."""
    img = Image.open(io.BytesIO(data))
    if img.format == "JPEG" and img.getexif().get(274, 1) == 1:
        return data, img.size
    img = ImageOps.exif_transpose(img).convert("RGB")
    out = io.BytesIO()
    img.save(out, "JPEG", quality=94)
    return out.getvalue(), img.size

def key_of(item: dict) -> str:
    return f"{item['source']}|{item['key']}"

def thumb_name(k: str) -> str:
    return hashlib.sha1(k.encode()).hexdigest()[:16] + ".jpg"

def remember(item: dict, data: bytes) -> None:
    """Guarda la obra en el historial junto con una miniatura."""
    os.makedirs(THUMBS, exist_ok=True)
    k = key_of(item)
    img = Image.open(io.BytesIO(data))
    img.draft("RGB", (640, 640))
    img = img.convert("RGB")
    img.thumbnail((360, 360))
    img.save(os.path.join(THUMBS, thumb_name(k)), "JPEG", quality=80)
    with lib_lock:
        lib = load_library()
        lib["items"][k] = {**item, "thumb": thumb_name(k)}
        lib["history"] = [k] + [x for x in lib["history"] if x != k]
        for old in lib["history"][HISTORY_MAX:]:
            if old not in lib["favorites"] and old not in lib["blocked"]:
                lib["items"].pop(old, None)
                try:
                    os.remove(os.path.join(THUMBS, thumb_name(old)))
                except OSError:
                    pass
        lib["history"] = lib["history"][:HISTORY_MAX]
        write_json(LIBRARY, lib)

def toggle(listname: str, k: str, on: bool) -> None:
    with lib_lock:
        lib = load_library()
        if k not in lib["items"]:
            raise ValueError("obra desconocida")
        cur = [x for x in lib[listname] if x != k]
        lib[listname] = cur + [k] if on else cur
        write_json(LIBRARY, lib)

def library_view() -> dict:
    lib = load_library()
    cur = {key_of(i) for i in read_json(os.path.join(CURRENT, "current.json"), {"items": []})["items"]}

    def view(keys):
        return [{"id": k, "title": lib["items"][k]["title"], "source": lib["items"][k]["source"], "thumb": lib["items"][k]["thumb"],
                 "favorite": k in lib["favorites"], "blocked": k in lib["blocked"], "current": k in cur}
                for k in keys if k in lib["items"]]
    return {"history": view(lib["history"]), "favorites": view(lib["favorites"]), "blocked": view(lib["blocked"])}

# ───────────────────────── composición de la imagen ─────────────────────────

def _bevel(canvas: Image.Image, box: tuple, width: int, light: tuple, dark: tuple) -> None:
    """Bisel de ventana a 45° (ingletes) alrededor de box; luz desde arriba-izquierda."""
    d = ImageDraw.Draw(canvas)
    i = box
    o = (box[0] - width, box[1] - width, box[2] + width, box[3] + width)
    d.polygon([(o[0], o[1]), (o[2], o[1]), (i[2], i[1]), (i[0], i[1])], fill=dark)
    d.polygon([(o[0], o[1]), (o[0], o[3]), (i[0], i[3]), (i[0], i[1])], fill=dark)
    d.polygon([(o[0], o[3]), (o[2], o[3]), (i[2], i[3]), (i[0], i[3])], fill=light)
    d.polygon([(o[2], o[1]), (o[2], o[3]), (i[2], i[3]), (i[2], i[1])], fill=light)


def fit(img: Image.Image, cw: int, ch: int, max_crop: float) -> Image.Image:
    """Llena la celda recortando lo mínimo; si habría que recortar demasiado, la obra se deja entera."""
    cover = max(cw / img.width, ch / img.height)
    contain = min(cw / img.width, ch / img.height)
    if contain / cover >= max_crop:
        w, h = min(img.width, round(cw / cover)), min(img.height, round(ch / cover))
        left, top = (img.width - w) // 2, (img.height - h) // 2
        img = img.crop((left, top, left + w, top + h))
    scale = min(cw / img.width, ch / img.height)
    return img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)


def active_layout(cfg: dict):
    """La disposición elegida; si ya no está instalada se usa la primera que haya."""
    chosen = plugins.REGISTRY.get(cfg["layout"])
    if chosen and chosen.kind == "layout":
        return chosen
    layouts = plugins.of_kind("layout")
    if not layouts:
        raise UserError("No hay ninguna disposición instalada: instala una desde el catálogo de plugins")
    return sorted(layouts, key=lambda p: p.id)[0]


def render(images: list, cfg: dict, bands: list, items: list, warnings: list, size: tuple = (3840, 2160)) -> bytes:
    """Compone las obras sobre un lienzo con paspartú equidistante y las franjas de los plugins.

    bands = [(plugin, ajustes del plugin, datos de prepare)]; las franjas de arriba y de abajo ocupan el margen.
    La disposición (plugin) decide dónde va cada obra dentro del área útil.
    """
    W, H = size
    if not cfg["matte"] and not bands and len(images) == 1:
        return images[0]
    imgs = [Image.open(io.BytesIO(b)).convert("RGB") for b in images]
    layout = active_layout(cfg)
    matte = cfg["matte"]
    bg = MATTE_COLORS[cfg["matte_color"] if matte else "negro"]
    k = W / 3840   # márgenes y alturas de franja están pensados para 4K
    extra = 0 if matte else 50  # sin paspartú las franjas necesitan algo más de alto
    groups = {pos: [b for b in bands if b[0].position == pos] for pos in ("top", "bottom")}
    need = {pos: sum(b[0].min_height + extra for b in g) * k for pos, g in groups.items()}
    margin = int(max(int(cfg["margin"]) * k, *need.values())) if matte else 0
    top, bottom = (margin, margin) if matte else (int(need["top"]), int(need["bottom"]))
    canvas = Image.new("RGB", (W, H), bg)
    box_w, box_h = W - 2 * margin, H - top - bottom
    rects = layout.cells(cfg["plugins"].get(layout.id, {}), [im.size for im in imgs], box_w, box_h, margin)
    cells = []
    for img, (x, y, w, h, max_crop), item in zip(imgs, rects, items):
        placed = fit(img, w, h, max_crop)
        px = margin + x + (w - placed.width) // 2
        py = top + y + (h - placed.height) // 2
        if matte:
            _bevel(canvas, (px, py, px + placed.width, py + placed.height), max(2, int(14 * k)), shade(bg, 0.5), shade(bg, -0.35))
        canvas.paste(placed, (px, py))
        cells.append(Cell(left=margin + x, width=w, cx=px + placed.width // 2, item=item))
    for pos, y in (("top", 0), ("bottom", H - bottom)):
        total = top if pos == "top" else bottom
        for plugin, pcfg, data in groups[pos]:
            h = total * (plugin.min_height + extra) * k / need[pos]
            ctx = RenderCtx(canvas=canvas, bg=bg, W=W, H=H, margin=margin, matte=matte, rect=(0, y, W, y + h), cy=y + h / 2,
                            cells=cells, lang=cfg["language"], cfg=pcfg)
            try:
                plugin.draw(ctx, data)
            except Exception as exc:  # noqa: BLE001
                log.exception("el plugin %s falló al dibujar", plugin.id)
                warnings.append(f"«{plugin.label}» falló al dibujar ({type(exc).__name__}): {exc}")
            y += h
    out = io.BytesIO()
    canvas.save(out, "JPEG", quality=92)
    return out.getvalue()


# ───────────────────────── flujo principal ─────────────────────────

def save_current(items: list[dict], datas: list[bytes]) -> None:
    os.makedirs(CURRENT, exist_ok=True)
    for i, d in enumerate(datas):
        with open(os.path.join(CURRENT, f"{i}.jpg"), "wb") as f:
            f.write(d)
    write_json(os.path.join(CURRENT, "current.json"), {"items": items, "count": len(datas)})


def load_current() -> tuple[list[dict], list[bytes]] | None:
    meta = read_json(os.path.join(CURRENT, "current.json"), None)
    if not meta:
        return None
    try:
        return meta["items"], [open(os.path.join(CURRENT, f"{i}.jpg"), "rb").read() for i in range(meta["count"])]
    except OSError:
        return None


def choose(cfg: dict, first: tuple | None) -> tuple:
    """Elige la obra principal y, si la disposición lo pide, las acompañantes."""
    item, data = first or pick_random(cfg, None, set())
    items, datas = [item], [data]
    layout = active_layout(cfg)
    exclude = {key_of(item)}
    for orientation in layout.extras(cfg["plugins"].get(layout.id, {}), Image.open(io.BytesIO(data)).size):
        try:
            extra, d = pick_random(cfg, orientation, exclude, tries=8)
        except UserError as exc:
            log.info("sin más obras para la disposición: %s", exc)
            break
        exclude.add(key_of(extra))
        items.append(extra)
        datas.append(d)
    return items, datas


def apply(action: str = "same", show: str | None = None) -> None:
    """action: 'new' (otra al azar), 'same' (re-renderiza la actual), 'show' (obra concreta de la biblioteca)."""
    with lock:
        set_status("trabajando…", busy=True)
        warnings: list = []
        try:
            cfg = load_settings()
            displays = enabled(cfg, "display")
            if not displays:
                raise UserError("No hay ninguna pantalla activada: instala y activa una desde el catálogo de plugins")
            ready, problems = [], {}
            for d in displays:   # antes de buscar y descargar nada: si ninguna pantalla responde, no hay nada que hacer
                reason = d.ready(cfg["plugins"][d.id])
                if reason:
                    problems[d.id] = reason
                else:
                    ready.append(d)
            if not ready:
                raise UserError(" · ".join(f"{d.label}: {problems[d.id]}" for d in displays))
            warnings += [f"{d.label}: {problems[d.id]}" for d in displays if d.id in problems]
            current = load_current() if action == "same" else None
            if action == "show":
                lib = load_library()
                if show not in lib["items"]:
                    raise UserError("Esa obra ya no está en la biblioteca")
                item = {k: lib["items"][show].get(k) for k in ("source", "key", "title", "info")}
                set_status("descargando la obra…")
                data, info = fetch_item(cfg, item)
                items, datas = choose(cfg, (with_info(item, info or item.get("info")), data))
            elif current is None:
                set_status("buscando una imagen…")
                items, datas = choose(cfg, None)
            else:
                items, datas = current
                for it in items:  # obras guardadas antes de existir las fichas
                    if "info" not in it:
                        try:
                            it["info"] = fetch_item(cfg, it)[1]
                        except Exception:  # noqa: BLE001
                            it["info"] = None
                save_current(items, datas)
            if current is None:
                save_current(items, datas)
                for it, d in zip(items, datas):
                    remember(it, d)
            status["title"] = " | ".join(i["title"] for i in items)
            band_plugins = enabled(cfg, "band")
            fields = tuple(sorted({f for b in band_plugins for f in b.translate_fields(cfg["plugins"][b.id])}))
            shown = [{**i, "info": localize(i.get("info"), cfg, warnings, fields)} for i in items]
            bands = []
            for b in band_plugins:
                set_status(f"preparando «{b.label}»…")
                try:
                    data_b, warn = b.prepare(cfg["plugins"][b.id], shown)
                except Exception as exc:  # noqa: BLE001
                    log.exception("el plugin %s falló", b.id)
                    warnings.append(f"«{b.label}» falló ({type(exc).__name__}): {exc}")
                    continue
                if warn:
                    warnings.append(warn)
                if data_b is not None:
                    bands.append((b, cfg["plugins"][b.id], data_b))
            failed = []
            renders: dict = {}   # una composición por tamaño de lienzo distinto
            for d in ready:
                pcfg = cfg["plugins"][d.id]
                size = tuple(d.canvas(pcfg))
                if size not in renders:
                    set_status("componiendo imagen…")
                    renders[size] = render(datas, cfg, bands, shown, warnings, size)
                    if len(renders) == 1:
                        with open(RENDERED, "wb") as f:
                            f.write(renders[size])
                set_status(f"enviando a «{d.label}»…")
                try:
                    run_with_timeout(lambda d=d, pcfg=pcfg, jpg=renders[size]: d.push(pcfg, jpg), d.push_timeout)
                except TimeoutError:
                    log.error("%s: sin respuesta en %s s", d.id, d.push_timeout)
                    failed.append(f"{d.label}: no respondió en {d.push_timeout} s")
                except UserError as exc:
                    log.error("%s: %s", d.id, exc)
                    failed.append(f"{d.label}: {exc}")
                except Exception as exc:  # noqa: BLE001
                    log.exception("la pantalla %s falló", d.id)
                    failed.append(f"{d.label}: {type(exc).__name__}: {exc}")
            if failed and len(failed) == len(ready):
                raise UserError(" · ".join(failed))
            warnings += failed
            status["warnings"] = warnings
            set_status("listo" + (" (con avisos)" if warnings else ""), busy=False, level="warn" if warnings else "ok")
        except UserError as exc:
            log.error("falló: %s", exc)
            status["warnings"] = warnings
            set_status(str(exc), busy=False, level="error")
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("falló")
            status["warnings"] = warnings
            set_status(f"Error inesperado: {type(exc).__name__}: {exc}", busy=False, level="error")
            raise


def apply_async(action: str, show: str | None = None) -> bool:
    if lock.locked():
        return False

    def run():
        try:
            apply(action, show)
        except Exception:  # noqa: BLE001
            pass
    threading.Thread(target=run, daemon=True).start()
    return True


# ───────────────────────── web ─────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:  # silenciar acceso
        pass

    def _send(self, body: bytes, ctype: str, code: int = 200, cache: str = "no-store") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(json.dumps(obj).encode(), "application/json", code)

    def _choices(self, path: str) -> None:
        _, _, pid, _, name = path.strip("/").split("/", 4)
        try:
            p = plugins.get(pid)
            self._json(p.choices(urllib.parse.unquote(name), load_settings()["plugins"][pid]))
        except UserError as exc:
            self._json({"error": str(exc)}, 502)
        except Exception as exc:  # noqa: BLE001
            self._json({"error": f"{type(exc).__name__}: {exc}"}, 502)

    def do_GET(self) -> None:  # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        try:
            if path == "/":
                with open(os.path.join(APP, "page.html"), "rb") as f:
                    self._send(f.read(), "text/html; charset=utf-8")
            elif path == "/api/status":
                self._json(status)
            elif path == "/api/settings":
                self._json(public_settings())
            elif path == "/api/plugins":
                self._json(plugin_schema())
            elif path.startswith("/api/plugins/") and "/choices/" in path:
                self._choices(path)
            elif path == "/api/library":
                self._json(library_view())
            elif path.startswith("/thumb/"):
                with open(os.path.join(THUMBS, os.path.basename(path)), "rb") as f:
                    self._send(f.read(), "image/jpeg", cache="max-age=86400")
            elif path == "/preview.jpg":
                with open(RENDERED, "rb") as f:
                    img = Image.open(f)
                    img.thumbnail((1280, 720))
                    out = io.BytesIO()
                    img.convert("RGB").save(out, "JPEG", quality=85)
                self._send(out.getvalue(), "image/jpeg")
            else:
                self._send(b"not found", "text/plain", 404)
        except UserError as exc:
            self._json({"error": str(exc)}, 502)
        except OSError:
            self._send(b"", "image/jpeg", 404)

    def do_POST(self) -> None:  # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}") if n else {}
            if self.path == "/api/change":
                self._json({"started": apply_async("new")})
            elif self.path == "/api/show":
                self._json({"started": apply_async("show", body["id"])})
            elif self.path == "/api/settings":
                save_settings(body)
                self._json({"started": False if body.get("noapply") else apply_async("same")})
            elif self.path == "/api/plugins/reload":
                plugins.load_all()
                self._json(plugin_schema())
            elif self.path in ("/api/catalog/install", "/api/catalog/uninstall"):
                plugins.set_installed(body["name"], self.path.endswith("/install"))
                plugins.load_all()
                self._json(plugin_schema())
            elif self.path == "/api/favorite":
                toggle("favorites", body["id"], bool(body["on"]))
                self._json({"ok": True})
            elif self.path == "/api/block":
                toggle("blocked", body["id"], bool(body["on"]))
                self._json({"ok": True})
            else:
                self._send(b"not found", "text/plain", 404)
        except (ValueError, TypeError, KeyError, requests.RequestException) as exc:
            self._json({"error": str(exc)}, 400)


def refresh_seconds() -> float | None:
    """Cada cuánto hay que volver a componer por los plugins con datos que caducan (clima…)."""
    hours = [b.refresh_hours for b in enabled(load_settings(), "band") if b.refresh_hours]
    return min(hours) * 3600 if hours else None


def background() -> None:
    next_rotate = next_refresh = time.time()
    first = True
    while True:
        now = time.time()
        try:
            if now >= next_rotate:
                apply("same" if first and load_current() else "new")   # al arrancar se conserva la obra actual
                first = False
                next_rotate = time.time() + load_settings()["interval_hours"] * 3600
                next_refresh = time.time() + (refresh_seconds() or 3 * 3600)
            elif now >= next_refresh:
                if refresh_seconds():
                    apply("same")
                next_refresh = time.time() + (refresh_seconds() or 3 * 3600)
        except Exception:  # noqa: BLE001
            log.error("reintento en %d min", RETRY // 60)
            if now >= next_rotate:
                next_rotate = time.time() + RETRY
            else:
                next_refresh = time.time() + RETRY
        time.sleep(30)


def main() -> None:
    plugins.load_all()
    threading.Thread(target=background, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", WEB_PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
