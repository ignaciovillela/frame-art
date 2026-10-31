"""Disposición: las verticales van de a dos (díptico); las horizontales, solas."""
from frameart import PORTRAIT, Layout


class Diptych(Layout):
    id = "diptych"
    label = "Díptico (verticales de a dos)"
    description = "Las obras horizontales van solas; las verticales se muestran de a dos."

    def extras(self, cfg: dict, size: tuple) -> list:
        return [True] if size[0] / size[1] < PORTRAIT else []

    def cells(self, cfg: dict, sizes: list, box_w: int, box_h: int, margin: int) -> list:
        n = len(sizes)
        gap = max(margin // 2, 30) if n > 1 else 0
        w = (box_w - gap * (n - 1)) // n
        return [(i * (w + gap), 0, w, box_h, 0.9 if n == 1 else 0.75) for i in range(n)]
