"""Composición de la imagen y migración de ajustes, sin red ni TV: `cd app && python -m unittest discover -s ../tests`."""
import io
import json
import os
import sys
import tempfile
import unittest

os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["PLUGINS_DIR"] = os.path.join(os.environ["DATA_DIR"], "sin-plugins")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))

from PIL import Image  # noqa: E402

import frame_art  # noqa: E402
import plugins  # noqa: E402

INFO = {"title": "Obra de prueba", "artist": "Autora", "year": "1840s", "desc": "Una descripción con tildes y ñ.", "lang": "es"}
WEATHER = {"hours": [(15, 18, 0, True), (16, 17, 3, True)], "now": 18, "max": 20, "min": 9, "rain": 10, "code": 0}


def jpeg(w: int, h: int) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (w, h), (120, 90, 60)).save(out, "JPEG")
    return out.getvalue()


class Render(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        plugins.installed_names = lambda: [m["name"] for m in plugins.catalog()]
        plugins.load_all()
        cls.cfg = frame_art.load_settings()

    def bands(self):
        reg = plugins.REGISTRY
        return [(reg["weather"], self.cfg["plugins"]["weather"], WEATHER), (reg["caption"], self.cfg["plugins"]["caption"], True)]

    def render(self, images, **over):
        warnings = []
        items = [{"info": INFO} for _ in images]
        out = frame_art.render(images, {**self.cfg, **over}, self.bands(), items, warnings)
        return Image.open(io.BytesIO(out)), warnings

    def test_single_landscape_with_bands(self):
        img, warnings = self.render([jpeg(3840, 2160)])
        self.assertEqual(img.size, (3840, 2160))
        self.assertEqual(warnings, [])

    def test_triptych_of_portraits(self):
        img, warnings = self.render([jpeg(2160, 3840)] * 3)
        self.assertEqual(img.size, (3840, 2160))
        self.assertEqual(warnings, [])

    def test_matte_is_equidistant(self):
        """Con paspartú, la obra queda a la misma distancia de los cuatro bordes (cuadro de color liso)."""
        img, _ = self.render([jpeg(3840, 2160)], margin=180)
        bg = img.getpixel((5, 5))
        xs = [x for x in range(img.width) if img.getpixel((x, 1080)) != bg]
        self.assertAlmostEqual(xs[0], img.width - 1 - xs[-1], delta=20)

    def test_without_matte_or_bands_returns_original(self):
        original = jpeg(3840, 2160)
        out = frame_art.render([original], {**self.cfg, "matte": False}, [], [{"info": None}], [])
        self.assertEqual(out, original)

    def test_failing_band_is_reported_not_fatal(self):
        class Broken(plugins.Band):
            id, label = "roto", "Roto"

            def draw(self, ctx, data):
                raise RuntimeError("boom")
        warnings = []
        frame_art.render([jpeg(3840, 2160)], self.cfg, [(Broken(), {}, True)], [{"info": None}], warnings)
        self.assertEqual(len(warnings), 1)


class Settings(unittest.TestCase):
    def test_migrates_flat_settings(self):
        old = {"matte": True, "weather": False, "hours": 8, "city": "Lima", "lat": -12.0, "lon": -77.0, "source": "mixto",
               "artist": "monet", "immich_url": "http://x", "immich_key": "k", "caption": True}
        new = frame_art.migrate(old)
        self.assertEqual(new["plugins"]["weather"], {"enabled": False, "city": "Lima", "lat": -12.0, "lon": -77.0, "hours": 8})
        self.assertTrue(new["plugins"]["reframed"]["enabled"] and new["plugins"]["immich"]["enabled"])
        self.assertEqual(new["plugins"]["reframed"]["artist"], "monet")

    def test_password_is_never_returned(self):
        plugins.installed_names = lambda: [m["name"] for m in plugins.catalog()]
        plugins.load_all()
        frame_art.save_settings({"plugins": {"immich": {"url": "http://x", "key": "CLAVE-SECRETA"}}})
        self.assertEqual(frame_art.load_settings()["plugins"]["immich"]["key"], "CLAVE-SECRETA")
        shown = frame_art.public_settings()["plugins"]["immich"]
        self.assertNotIn("CLAVE-SECRETA", json.dumps(shown))
        self.assertTrue(shown["_set"]["key"])
        frame_art.save_settings({"plugins": {"immich": {"key": ""}}})   # vacío = no cambiar
        self.assertEqual(frame_art.load_settings()["plugins"]["immich"]["key"], "CLAVE-SECRETA")


if __name__ == "__main__":
    unittest.main()
