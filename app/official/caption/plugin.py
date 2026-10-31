"""Banda inferior: ficha de la obra en una sola línea (título · autor · año — descripción)."""
from PIL import ImageDraw

from frameart import Band, font, format_year, shade


class Caption(Band):
    id = "caption"
    label = "Ficha de la obra"
    description = "Título, autor, año y una descripción breve bajo cada obra, en una sola línea."
    position = "bottom"
    min_height = 150
    enabled_by_default = True
    settings = [
        {"key": "translate_title", "label": "Traducir el título", "type": "bool", "default": True},
        {"key": "show_original", "label": "Mostrar el título original entre paréntesis", "type": "bool", "default": False},
    ]

    def translate_fields(self, cfg: dict) -> tuple:
        return ("desc", "title") if cfg.get("translate_title") else ("desc",)

    @staticmethod
    def display_title(info: dict, cfg: dict) -> str:
        """Título tal como se muestra: traducido y, si se pide, con el original entre paréntesis."""
        title, orig = info.get("title") or "", info.get("title_orig") or ""
        if cfg.get("show_original") and orig and orig.strip().lower() != title.strip().lower():
            return f"{title} ({orig})"
        return title

    def prepare(self, cfg: dict, items: list) -> tuple:
        return (True if any(i.get("info") for i in items) else None), None

    def draw(self, ctx, data) -> None:
        d = ImageDraw.Draw(ctx.canvas)
        light = sum(ctx.bg) / 3 >= 90
        ink = shade(ctx.bg, -0.55) if light else shade(ctx.bg, 0.6)
        f = font(38)
        for cell in ctx.cells:
            info = cell.item.get("info")
            if info:
                self._line(d, info, f, ink, cell.cx, ctx.cy, cell.width, ctx.lang, self.display_title(info, ctx.cfg))

    @staticmethod
    def _line(d, info: dict, f, ink: tuple, cx: float, cy: float, width: int, lang: str, title: str) -> None:
        sep, dash = "   ·   ", "   —   "
        year = format_year(info.get("year", ""), lang)
        text = sep.join(x for x in (title, info.get("artist")) if x)
        if year and d.textlength((text + sep if text else "") + year, font=f) <= width:
            text = text + sep + year if text else year
        desc = info.get("desc")
        room = width - d.textlength(text + dash, font=f)
        if desc and room > 400:  # la descripción entra solo si queda espacio razonable; se recorta con puntos suspensivos
            full = desc
            while d.textlength(desc, font=f) > room:
                desc = desc[:-1]
            text += dash + (desc if desc == full else desc.rstrip(" ,;:.") + "…")
        elif d.textlength(text, font=f) > width:
            while text and d.textlength(text + "…", font=f) > width:
                text = text[:-1]
            text = text.rstrip(" ,;:·—") + "…"
        d.text((cx, cy), text, font=f, fill=ink, anchor="mm")
