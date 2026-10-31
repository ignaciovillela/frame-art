"""Disposición: una obra sola; si es vertical, de a tres (tríptico) con otras dos verticales."""
from frameart import PORTRAIT, Layout


def columns(n: int, box_w: int, box_h: int, margin: int) -> list:
    gap = max(margin // 2, 30) if n > 1 else 0
    w = (box_w - gap * (n - 1)) // n
    return [(i * (w + gap), 0, w, box_h, 0.9 if n == 1 else 0.75) for i in range(n)]


class Auto(Layout):
    id = "auto"
    label = "Automática (obra sola o tríptico)"
    description = "Las obras horizontales van solas; las verticales se muestran de a tres."
    enabled_by_default = True

    def extras(self, cfg: dict, size: tuple) -> list:
        return [True, True] if size[0] / size[1] < PORTRAIT else []

    def cells(self, cfg: dict, sizes: list, box_w: int, box_h: int, margin: int) -> list:
        return columns(len(sizes), box_w, box_h, margin)
