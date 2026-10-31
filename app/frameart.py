"""API pública para plugins de Frame Art.

Un plugin es un archivo .py (o un .json declarativo, ver docs/PLUGINS.md) en la carpeta de plugins.
Hay tres tipos:
  Source      de dónde salen las imágenes (galerías, Immich, una API cualquiera)
  Band        franja de texto/iconos sobre el paspartú (clima, ficha de la obra…)
  Translator  traduce los textos de las fichas

Cada plugin declara sus ajustes en `settings` y la interfaz web los dibuja sola.
"""
import json
import logging
import os
import re
from dataclasses import dataclass, field

import requests
from PIL import ImageFont

USER_AGENT = os.environ.get("FRAMEART_USER_AGENT", "frame-art/1.0 (+https://github.com/ignaciovillela/frame-art; uso personal)")
UA = {"User-Agent": USER_AGENT}
DATA = os.environ.get("DATA_DIR", "/data")
log = logging.getLogger("frame-art")
FONT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", "LiberationSans-Regular.ttf")


class UserError(Exception):
    """Error con mensaje apto para mostrar al usuario (se ve tal cual en la interfaz)."""


def font(size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(FONT, size)  # con tildes y raya larga; la fuente por defecto de Pillow no las trae
    except OSError:
        return ImageFont.load_default(size=size)


def shade(c: tuple, f: float) -> tuple:
    """f<0 oscurece, f>0 aclara."""
    t = 255 if f > 0 else 0
    return tuple(int(v + (t - v) * abs(f)) for v in c)


def read_json(path: str, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def http_get(url: str, timeout: int = 30, **kw) -> requests.Response:
    """GET identificándose con el User-Agent de la app y fallando ante códigos de error."""
    headers = {**UA, **kw.pop("headers", {})}
    r = requests.get(url, headers=headers, timeout=timeout, **kw)
    r.raise_for_status()
    return r


def get_path(obj, path: str):
    """Navega 'a.b.0.c' dentro de dicts y listas; devuelve None si no existe."""
    for part in filter(None, path.split(".")):
        if isinstance(obj, dict):
            obj = obj.get(part)
        elif isinstance(obj, list) and part.lstrip("-").isdigit() and -len(obj) <= int(part) < len(obj):
            obj = obj[int(part)]
        else:
            return None
    return obj


def format_year(year: str, lang: str) -> str:
    """'1840s' → 'década de 1840' en español; el resto se deja tal cual."""
    m = re.fullmatch(r"(\d{4})s", year or "")
    return f"década de {m.group(1)}" if m and lang == "es" else (year or "")


# Campos de `settings`: {"key", "label", "type", "default", ...}. Tipos:
#   bool · number (min, max, step) · text · password (nunca se devuelve a la web) · select (choices=[[valor, etiqueta]]
#   o choices_from="nombre", que llama a Plugin.choices) · location (ciudad + botón de ubicación) · hidden


class Plugin:
    id = ""                  # único; es la clave en settings.json
    label = ""
    description = ""
    kind = ""
    settings: list = []
    enabled_by_default = False
    data_dir = ""            # lo asigna el cargador: carpeta propia del plugin dentro de /data

    def path(self, *parts: str) -> str:
        os.makedirs(self.data_dir, exist_ok=True)
        return os.path.join(self.data_dir, *parts)

    def choices(self, name: str, cfg: dict) -> list:
        """Opciones dinámicas de un campo select con choices_from: lista de {"value", "label"}."""
        return []

    def normalize(self, raw: dict, merged: dict, current: dict) -> dict:
        """Valida/transforma los ajustes ya fusionados antes de guardarlos. `raw` es lo que envió la web
        y `current` lo guardado hasta ahora. Para rechazar un valor, lanzar ValueError con el motivo."""
        return merged


class Source(Plugin):
    kind = "source"

    def candidates(self, cfg: dict) -> list:
        """Lista de obras: {"key": str único, "title": str, "w": int|None, "h": int|None, "info": dict|None}."""
        raise NotImplementedError

    def probe(self, cfg: dict, item: dict):
        """(ancho, alto) sin descargar la imagen completa, o None si no se puede saber barato."""
        return None

    def fetch(self, cfg: dict, item: dict) -> tuple:
        """(bytes de la imagen, ficha). Ficha: {"title","artist","year","desc","lang"} o None."""
        raise NotImplementedError


class Band(Plugin):
    kind = "band"
    position = "bottom"      # top | bottom
    min_height = 150         # alto mínimo de la franja (el margen del paspartú crece si hace falta)
    refresh_hours = None     # si se indica, la imagen se vuelve a componer con esa frecuencia

    def prepare(self, cfg: dict, items: list) -> tuple:
        """(datos | None, aviso | None). Con None la franja no se dibuja ni reserva espacio."""
        return True, None

    def draw(self, ctx: "RenderCtx", data) -> None:
        raise NotImplementedError


class Translator(Plugin):
    kind = "translator"

    def translate(self, cfg: dict, texts: list, source: str, target: str) -> list:
        """Traduce cada texto de `texts`; debe devolver una lista del mismo largo."""
        raise NotImplementedError


@dataclass
class Cell:
    """Una obra ya colocada: `left`/`width` es su columna; `cx` el centro de la imagen."""
    left: int
    width: int
    cx: int
    item: dict


@dataclass
class RenderCtx:
    canvas: object                       # PIL.Image sobre el que se dibuja
    bg: tuple                            # color del paspartú
    W: int
    H: int
    margin: int
    matte: bool
    rect: tuple                          # (x0, y0, x1, y1) de la franja asignada
    cy: float                            # centro vertical de la franja
    cells: list = field(default_factory=list)
    lang: str = "es"
    cfg: dict = field(default_factory=dict)
