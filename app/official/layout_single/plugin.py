"""Disposición: siempre una sola obra, también las verticales."""
from frameart import Layout


class Single(Layout):
    id = "single"
    label = "Una sola obra"
    description = "Una obra por pantalla, sea horizontal o vertical (las verticales dejan más paspartú a los lados)."

    def cells(self, cfg: dict, sizes: list, box_w: int, box_h: int, margin: int) -> list:
        return [(0, 0, box_w, box_h, 0.9)]
