"""Fuente: tu biblioteca de Immich (fotos propias, todas o de un álbum)."""
import io

import requests
from PIL import Image

from frameart import Source, UserError


class Immich(Source):
    id = "immich"
    label = "Immich"
    description = "Tus propias fotos. Las verticales se muestran de a tres. La clave API se crea en Immich → Ajustes → Claves API (permisos asset.read y album.read)."
    settings = [
        {"key": "url", "label": "URL", "type": "text", "default": "", "placeholder": "http://192.168.1.x:2283"},
        {"key": "key", "label": "Clave API", "type": "password", "default": ""},
        {"key": "album", "label": "Álbum", "type": "select", "choices_from": "albums", "default": "", "empty": "Toda la biblioteca"},
    ]

    def normalize(self, raw: dict, merged: dict, current: dict) -> dict:
        merged["url"] = merged["url"].strip().rstrip("/")
        return merged

    def _call(self, cfg: dict, path: str, method: str = "GET", **kw) -> requests.Response:
        if not cfg["url"] or not cfg["key"]:
            raise UserError("Immich no está configurado: falta la URL o la clave API")
        try:
            r = requests.request(method, f"{cfg['url']}/api{path}", headers={"x-api-key": cfg["key"]}, timeout=90, **kw)
        except requests.RequestException as exc:
            raise UserError(f"Immich no disponible en {cfg['url']} ({type(exc).__name__})") from exc
        if r.status_code in (401, 403):
            raise UserError("Immich rechazó la clave API (¿le faltan permisos de lectura de assets y álbumes?)")
        if not r.ok:
            raise UserError(f"Immich respondió {r.status_code} en {path.split('?')[0]}")
        return r

    def choices(self, name: str, cfg: dict) -> list:
        return [{"value": a["id"], "label": f"{a['albumName']} ({a.get('assetCount', 0)})"} for a in self._call(cfg, "/albums").json()]

    def candidates(self, cfg: dict) -> list:
        body = {"type": "IMAGE", "size": 100, "withExif": True}
        if cfg["album"]:
            body["albumIds"] = [cfg["album"]]
        data = self._call(cfg, "/search/random", "POST", json=body).json()
        assets = data if isinstance(data, list) else data.get("assets", {}).get("items", [])
        out = []
        for a in assets:
            exif = a.get("exifInfo") or {}
            when = str(exif.get("dateTimeOriginal") or a.get("fileCreatedAt") or "")[:4]
            info = {"title": exif.get("description") or "", "artist": "", "year": when if when.isdigit() else "", "desc": "", "lang": ""}
            out.append({"key": a["id"], "title": a.get("originalFileName") or "Immich", "w": a.get("width"), "h": a.get("height"),
                        "info": info if info["title"] or info["year"] else None})
        return out

    def fetch(self, cfg: dict, item: dict) -> tuple:
        """Original si Pillow puede abrirlo (JPEG/PNG/WebP); si no (HEIC, RAW…), la vista grande generada por Immich."""
        key = item["key"]
        for path in (f"/assets/{key}/original", f"/assets/{key}/thumbnail?size=fullsize", f"/assets/{key}/thumbnail?size=preview"):
            try:
                data = self._call(cfg, path).content
                Image.open(io.BytesIO(data)).verify()
                return data, item.get("info")
            except UserError as exc:
                if "rechazó" in str(exc) or "no disponible" in str(exc):
                    raise
            except Exception:  # noqa: BLE001
                pass
        raise ValueError("Immich: no se pudo leer la imagen")
