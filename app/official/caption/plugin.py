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
                self._line(d, info, f, ink, cell.cx, ctx.cy, cell.width, ctx.lang)

    @staticmethod
    def _line(d, info: dict, f, ink: tuple, cx: float, cy: float, width: int, lang: str) -> None:
        sep, dash = "   ·   ", "   —   "
        year = format_year(info.get("year", ""), lang)
        text = sep.join(x for x in (info.get("title"), info.get("artist")) if x)
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
