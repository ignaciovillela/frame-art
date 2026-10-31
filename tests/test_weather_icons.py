"""Iconos del pronóstico: niveles de lluvia, tormenta con y sin lluvia, color opcional. Sin red."""
import importlib
import os
import sys
import tempfile
import unittest

os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["PLUGINS_DIR"] = os.path.join(os.environ["DATA_DIR"], "sin-plugins")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))

from PIL import Image, ImageDraw  # noqa: E402

import plugins  # noqa: E402
from frameart import RenderCtx  # noqa: E402

plugins.installed_names = lambda: [m["name"] for m in plugins.catalog()]
plugins.load_all()
weather = importlib.import_module("frameart_plugin_official_weather_plugin_py")


def ink(kind: str, level: int = 1) -> dict:
    """Píxeles dibujados por capa para un icono."""
    masks = {}

    def layer(name):
        masks.setdefault(name, Image.new("L", (120, 120), 0))
        return ImageDraw.Draw(masks[name])
    weather.draw_icon(layer, kind, 10, 10, 76, level)
    return {name: sum(1 for v in m.getdata() if v) for name, m in masks.items()}


class Icons(unittest.TestCase):
    def test_codes_map_to_kinds_and_levels(self):
        f = weather.icon_for
        self.assertEqual(f(0, True), ("sun", 1))
        self.assertEqual(f(0, False), ("moon", 1))
        self.assertEqual(f(2, False), ("partly_night", 1))
        self.assertEqual([f(c, True)[1] for c in (61, 63, 65)], [1, 2, 3])        # lluvia: poca, moderada, fuerte
        self.assertEqual([f(c, True)[1] for c in (80, 81, 82)], [1, 2, 3])        # chubascos
        self.assertEqual([f(c, True)[1] for c in (71, 73, 75)], [1, 2, 3])        # nieve
        self.assertEqual(f(56, True)[0], "sleet")
        self.assertEqual(f(45, True)[0], "fog")
        self.assertEqual(f(999, True)[0], "cloud")                                # código desconocido: nube

    def test_thunderstorm_with_and_without_rain(self):
        self.assertEqual(weather.icon_for(95, True, 0.0)[0], "storm_dry")
        self.assertEqual(weather.icon_for(95, True, 2.5)[0], "storm")
        self.assertEqual(weather.icon_for(96, True, 0.0)[0], "storm_hail")

    def test_more_rain_means_more_drops(self):
        drops = [ink("rain", n)["rain"] for n in (1, 2, 3)]
        self.assertTrue(drops[0] < drops[1] < drops[2], drops)
        flakes = [ink("snow", n)["snow"] for n in (1, 2, 3)]
        self.assertTrue(flakes[0] < flakes[1] < flakes[2], flakes)

    def test_storm_with_rain_has_drops_the_dry_one_does_not(self):
        self.assertIn("rain", ink("storm"))
        self.assertNotIn("rain", ink("storm_dry"))
        self.assertIn("storm", ink("storm_dry"))                                  # el rayo está siempre

    def test_normal_states_have_no_accent_layer(self):
        for kind in ("sun", "moon", "partly", "partly_night", "cloud"):
            self.assertEqual(set(ink(kind)), {"body"}, kind)                      # nada que teñir
        self.assertEqual(set(ink("rain")), {"body", "rain"})

    def test_every_code_draws_and_tint_changes_only_accent_pixels(self):
        bg = (238, 230, 212)
        hours = [(h, 15, code, True, 1.0) for h, code in enumerate(weather.ICONS)]
        plain = {}
        for tint in (False, True):
            img = Image.new("RGB", (3840, 180), bg)
            ctx = RenderCtx(canvas=img, bg=bg, W=3840, H=180, margin=180, matte=True, rect=(0, 0, 3840, 180), cy=90,
                            cfg={"city": "Santiago", "tint_amount": 50 if tint else 0})
            weather.Weather().draw(ctx, {"hours": hours[:12], "min": 9, "max": 20, "rain": 40})
            plain[tint] = img
        self.assertNotEqual(plain[False].tobytes(), plain[True].tobytes())        # el color se nota

    def test_amount_of_color_scales_the_accent(self):
        """0 % = idéntico al tono neutro; cuanto más porcentaje, más se aleja el acento del tono del paspartú."""
        from PIL import ImageChops
        bg = (238, 230, 212)

        def render(amount):
            img = Image.new("RGB", (3840, 180), bg)
            ctx = RenderCtx(canvas=img, bg=bg, W=3840, H=180, margin=180, matte=True, rect=(0, 0, 3840, 180), cy=90,
                            cfg={"city": "X", "tint_amount": amount})
            weather.Weather().draw(ctx, {"hours": [(10, 12, 65, True, 5.0)], "min": 5, "max": 14, "rain": 80})
            return img
        base = render(0)

        def strength(amount):   # diferencia máxima por canal respecto de la versión sin color
            return max(hi for _, hi in ImageChops.difference(base, render(amount)).getextrema())
        self.assertEqual(strength(0), 0)
        self.assertTrue(0 < strength(30) < strength(60) < strength(100), (strength(30), strength(60), strength(100)))

    def test_old_cached_readings_with_four_values_still_draw(self):
        bg = (20, 20, 20)
        img = Image.new("RGB", (3840, 180), bg)
        ctx = RenderCtx(canvas=img, bg=bg, W=3840, H=180, margin=180, matte=True, rect=(0, 0, 3840, 180), cy=90, cfg={"city": "X"})
        weather.Weather().draw(ctx, {"hours": [[10, 12, 95, True], [11, 11, 63, False]], "min": 5, "max": 14, "rain": 80})


if __name__ == "__main__":
    unittest.main()
