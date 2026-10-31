"""Pantalla: guarda la imagen terminada en una carpeta, para cualquier TV o marco que lea de ahí
(servidor de medios, USB, Home Assistant, presentación de fotos de una LG…). También sirve de referencia para escribir otras pantallas."""
import os

from frameart import Display, UserError


class FolderDisplay(Display):
    id = "folder_display"
    label = "Carpeta (cualquier TV o marco)"
    description = "Escribe la imagen en una carpeta (monta un volumen en el contenedor). Un servidor de medios o la propia TV la leen de ahí."
    settings = [
        {"key": "path", "label": "Carpeta", "type": "text", "default": "/data/salida", "placeholder": "/data/salida"},
        {"key": "name", "label": "Nombre del archivo", "type": "text", "default": "frame-art.jpg"},
        {"key": "width", "label": "Ancho (px)", "type": "number", "default": 3840, "min": 640, "max": 7680, "step": 1},
    ]

    def canvas(self, cfg: dict) -> tuple:
        w = int(cfg.get("width", 3840))
        return w, w * 9 // 16

    def ready(self, cfg: dict):
        folder = cfg["path"]
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as exc:
            return f"No se puede usar la carpeta «{folder}» ({type(exc).__name__}): ¿está montada y con permisos de escritura?"
        return None if os.access(folder, os.W_OK) else f"La carpeta «{folder}» no es escribible"

    def push(self, cfg: dict, jpeg: bytes) -> None:
        name = os.path.basename(cfg["name"]) or "frame-art.jpg"
        dest = os.path.join(cfg["path"], name)
        tmp = dest + ".tmp"
        try:
            with open(tmp, "wb") as f:
                f.write(jpeg)
            os.replace(tmp, dest)   # el lector nunca ve un archivo a medio escribir
        except OSError as exc:
            raise UserError(f"No se pudo escribir {dest} ({type(exc).__name__})") from exc
