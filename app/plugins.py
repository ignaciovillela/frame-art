"""Carga de plugins: oficiales del catálogo (official/, solo los instalados), del usuario (PLUGINS_DIR, .py y .json)
y paquetes pip (entry point 'frameart.plugins')."""
import importlib.metadata
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse

from frameart import DATA, Band, Display, Layout, Plugin, Source, Translator, UserError, get_path, http_get, log, read_json, write_json

APP = os.path.dirname(os.path.abspath(__file__))
OFFICIAL_DIR = os.path.join(APP, "official")
INSTALLED = os.path.join(DATA, "installed_plugins.json")
PLUGINS_DIR = os.environ.get("PLUGINS_DIR", "/plugins")
KINDS = (Source, Band, Translator, Layout, Display)

REGISTRY: dict = {}      # id -> instancia
ERRORS: list = []        # [{"origin", "error"}] para mostrarlos en la interfaz


class JsonSource(Source):
    """Fuente declarativa: dos URLs (lista y detalle) y la ruta de cada campo en la respuesta JSON."""

    def __init__(self, spec: dict):
        self.id, self.label = spec["id"], spec.get("label", spec["id"])
        self.description = spec.get("description", "")
        self.settings = spec.get("settings", [])
        self.enabled_by_default = False
        self.spec = spec
        self._list = (0.0, None, [])

    def _fmt(self, template: str, cfg: dict, **extra) -> str:
        values = {**{f["key"]: f.get("default", "") for f in self.settings}, **cfg, **extra}
        return template.format_map({k: urllib.parse.quote(str(v), safe="") for k, v in values.items()})

    def candidates(self, cfg: dict) -> list:
        lst = self.spec["list"]
        url = self._fmt(lst["url"], cfg)
        ts, last_url, cached = self._list
        if cached and last_url == url and time.time() - ts < 3600:
            return cached
        data = http_get(url).json()
        out = []
        for x in (get_path(data, lst.get("ids", "")) or [])[: int(lst.get("max", 1000))]:
            key = get_path(x, lst.get("id_field", "id")) if isinstance(x, (dict, list)) else x
            if key is not None:
                out.append({"key": str(key), "title": f"{self.label} {key}", "w": None, "h": None})
        self._list = (time.time(), url, out)
        return out

    def fetch(self, cfg: dict, item: dict) -> tuple:
        it = self.spec["item"]
        data = http_get(self._fmt(it["url"], cfg, id=item["key"])).json()
        root = get_path(data, it["root"]) if it.get("root") else data   # p. ej. "data" si la API envuelve el objeto
        image = get_path(root, it["image"]) if it.get("image") else None
        if not image and it.get("image_template"):  # URL armada con campos de la obra, p. ej. IIIF con {image_id}
            fields = {k: v for k, v in (root or {}).items() if isinstance(v, (str, int))}
            image = it["image_template"].format_map(_Missing(fields)) if fields else None
        if not image:
            raise ValueError("la obra no trae imagen")
        content = http_get(image, timeout=120).content
        info = {k: " ".join(str(get_path(root, it[k]) or "").split()) for k in ("title", "artist", "year", "desc") if it.get(k)}
        info["lang"] = self.spec.get("lang", "en")
        return content, info if any(info.get(k) for k in ("title", "artist", "year", "desc")) else None


class _Missing(dict):
    def __missing__(self, key):
        raise ValueError(f"la obra no trae «{key}»")


_origin = {"name": ""}   # carpeta del catálogo que se está cargando


def _register(plugin: Plugin, origin: str) -> None:
    if plugin.id in REGISTRY:
        log.info("el plugin %s (%s) reemplaza al anterior", plugin.id, origin)
    plugin.data_dir = os.path.join(DATA, "plugins", plugin.id)
    plugin.origin = _origin["name"]
    REGISTRY[plugin.id] = plugin


def _from_module(mod, name: str):
    for obj in vars(mod).values():
        if isinstance(obj, type) and issubclass(obj, KINDS) and obj not in KINDS and obj.id and obj.__module__ == name:
            yield obj()


def _load_py(path: str) -> None:
    name = "frameart_plugin_" + re.sub(r"\W", "_", os.path.relpath(path, APP if path.startswith(APP) else os.path.dirname(path)))
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    found = list(_from_module(mod, name))
    if not found:
        raise ValueError("el archivo no define ninguna clase Source, Band o Translator con `id`")
    for p in found:
        _register(p, path)


def _load_json(path: str) -> None:
    with open(path) as f:
        spec = json.load(f)
    if spec.get("type", "json-source") != "json-source":
        raise ValueError(f"tipo de plugin declarativo desconocido: {spec.get('type')}")
    for key in ("id", "list", "item"):
        if key not in spec:
            raise ValueError(f"falta «{key}»")
    if "url" not in spec["list"] or "url" not in spec["item"] or not ({"image", "image_template"} & set(spec["item"])):
        raise ValueError("«list.url», «item.url» y «item.image» (o «item.image_template») son obligatorios")
    _register(JsonSource(spec), path)


def _load_entry_points() -> None:
    for ep in importlib.metadata.entry_points(group="frameart.plugins"):
        try:
            obj = ep.load()
            if isinstance(obj, type) and issubclass(obj, KINDS):
                _register(obj(), ep.name)
            else:
                for p in _from_module(obj, obj.__name__):
                    _register(p, ep.name)
        except Exception as exc:  # noqa: BLE001
            ERRORS.append({"origin": f"pip:{ep.name}", "error": f"{type(exc).__name__}: {exc}"})
            log.exception("plugin %s falló al cargar", ep.name)


# ───────────────────────── catálogo oficial ─────────────────────────
# Cada carpeta de official/ trae manifest.json + el código del plugin. Solo se cargan los instalados:
# así no todo el mundo carga lo que no usa (Immich, fuentes extra…) ni instala sus dependencias.

MANIFEST_KEYS = {"label", "kind", "description"}


def catalog(report: bool = False) -> list:
    out = []
    for name in sorted(os.listdir(OFFICIAL_DIR)) if os.path.isdir(OFFICIAL_DIR) else []:
        mp = os.path.join(OFFICIAL_DIR, name, "manifest.json")
        if not os.path.isfile(mp):
            continue
        try:
            with open(mp) as f:
                m = json.load(f)
            missing = MANIFEST_KEYS - set(m)
            if missing:
                raise ValueError(f"faltan {sorted(missing)}")
            out.append({"requires": [], "default": False, "author": "", "license": "", "terms": "", **m, "name": name})
        except (OSError, ValueError) as exc:
            if report:
                ERRORS.append({"origin": mp, "error": f"manifest inválido: {exc}"})
    return out


def installed_names() -> list:
    """Plugins oficiales instalados. En la primera ejecución: los marcados `default`, más Immich si ya se usaba."""
    data = read_json(INSTALLED, None)
    if data is None:
        names = [m["name"] for m in catalog() if m["default"]]
        old = read_json(os.path.join(DATA, "settings.json"), {})   # instalaciones anteriores al catálogo
        if old.get("source") in ("immich", "mixto") or old.get("immich_url") or old.get("plugins", {}).get("immich", {}).get("enabled"):
            names.append("immich")
        data = {"installed": names}
        write_json(INSTALLED, data)
    # La disposición y la pantalla son imprescindibles: si faltan (instalaciones anteriores a estos tipos), se instalan las de por defecto
    cat = {m["name"]: m for m in catalog()}
    for kind in ("layout", "display"):
        if not any(cat.get(n, {}).get("kind") == kind for n in data["installed"]):
            data["installed"] += [m["name"] for m in cat.values() if m["kind"] == kind and m["default"]]
            write_json(INSTALLED, data)
    return data["installed"]


def set_installed(name: str, on: bool) -> None:
    if name not in {m["name"] for m in catalog()}:
        raise ValueError(f"No existe el plugin oficial «{name}»")
    names = [n for n in installed_names() if n != name]
    write_json(INSTALLED, {"installed": names + [name] if on else names})


def _ensure_requires(manifest: dict) -> None:
    """Instala con pip las dependencias que declara un plugin oficial del catálogo (nunca las de plugins del usuario)."""
    for req in manifest.get("requires", []):
        dist = re.split(r"[<>=!~ ;\[]", req, maxsplit=1)[0]
        try:
            importlib.metadata.version(dist)
        except importlib.metadata.PackageNotFoundError:
            log.info("instalando dependencia %s", req)
            subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--no-cache-dir", req], check=True, timeout=300)


def _load_folder(folder: str, label: str) -> None:
    _origin["name"] = label
    for fname in sorted(os.listdir(folder)):
        path = os.path.join(folder, fname)
        if fname.startswith(("_", ".")) or fname == "manifest.json" or not fname.endswith((".py", ".json")):
            continue
        try:
            _load_py(path) if fname.endswith(".py") else _load_json(path)
        except Exception as exc:  # noqa: BLE001
            ERRORS.append({"origin": path, "error": f"{type(exc).__name__}: {exc}"})
            log.exception("plugin %s falló al cargar", path)


def load_all() -> None:
    """(Re)carga todo. Un plugin roto se registra en ERRORS y no impide arrancar."""
    REGISTRY.clear()
    ERRORS.clear()
    cat = {m["name"]: m for m in catalog(report=True)}
    for name in installed_names():
        if name not in cat:
            ERRORS.append({"origin": f"official/{name}", "error": "instalado pero ya no existe en el catálogo"})
            continue
        try:
            _ensure_requires(cat[name])
        except Exception as exc:  # noqa: BLE001
            ERRORS.append({"origin": f"official/{name}", "error": f"no se pudieron instalar las dependencias: {exc}"})
            continue
        _load_folder(os.path.join(OFFICIAL_DIR, name), name)
    if os.path.isdir(PLUGINS_DIR):
        _load_folder(PLUGINS_DIR, "")
    _origin["name"] = ""
    _load_entry_points()
    log.info("plugins cargados: %s", ", ".join(sorted(REGISTRY)) or "ninguno")


def of_kind(kind: str) -> list:
    return [p for p in REGISTRY.values() if p.kind == kind]


def get(plugin_id: str, kind: str | None = None) -> Plugin:
    p = REGISTRY.get(plugin_id)
    if not p or (kind and p.kind != kind):
        raise UserError(f"El plugin «{plugin_id}» ya no está instalado")
    return p
