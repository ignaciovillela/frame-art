"""Ejemplo mínimo de fuente en Python: una carpeta local con imágenes.

Cópialo a ./plugins/, ajusta la ruta (móntala como volumen en el compose) y recarga los plugins desde la web.
"""
import os

from frameart import Source


class CarpetaLocal(Source):
    id = "carpeta_local"
    label = "Carpeta local"
    description = "Imágenes de una carpeta montada en el contenedor."
    settings = [{"key": "ruta", "label": "Ruta", "type": "text", "default": "/fotos"}]

    def candidates(self, cfg):
        carpeta = cfg["ruta"]
        return [{"key": n, "title": os.path.splitext(n)[0]} for n in sorted(os.listdir(carpeta))
                if n.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))]

    def fetch(self, cfg, item):
        with open(os.path.join(cfg["ruta"], item["key"]), "rb") as f:
            return f.read(), None   # sin ficha; podrías devolver {"title", "artist", "year", "desc", "lang"}
