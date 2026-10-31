"""Disposiciones y pantallas (plugins): sin red ni TV. `cd app && python -m unittest discover -s ../tests`."""
import io
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
from frameart import UserError  # noqa: E402

PORTRAIT, LANDSCAPE = (2160, 3840), (3840, 2160)


def jpeg(size) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (110, 90, 70)).save(out, "JPEG")
    return out.getvalue()


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        plugins.installed_names = lambda: [m["name"] for m in plugins.catalog()]
        plugins.load_all()
        cls.cfg = frame_art.load_settings()


class Layouts(Base):
    def test_extras(self):
        reg = plugins.REGISTRY
        self.assertEqual(reg["auto"].extras({}, PORTRAIT), [True, True])
        self.assertEqual(reg["auto"].extras({}, LANDSCAPE), [])
        self.assertEqual(reg["diptych"].extras({}, PORTRAIT), [True])
        self.assertEqual(reg["single"].extras({}, PORTRAIT), [])

    def test_cells_fit_inside_the_box(self):
        box_w, box_h = 3480, 1800
        for lid, n in (("auto", 1), ("auto", 3), ("single", 1), ("diptych", 2)):
            cells = plugins.REGISTRY[lid].cells({}, [PORTRAIT] * n, box_w, box_h, 180)
            self.assertEqual(len(cells), n, lid)
            for x, y, w, h, crop in cells:
                self.assertTrue(0 <= x and x + w <= box_w and 0 <= y and y + h <= box_h, (lid, x, y, w, h))
                self.assertTrue(0 < crop <= 1)

    def test_render_with_every_layout(self):
        for lid, n in (("auto", 3), ("single", 1), ("diptych", 2)):
            warnings = []
            out = frame_art.render([jpeg(PORTRAIT)] * n, {**self.cfg, "layout": lid}, [], [{"info": None}] * n, warnings)
            self.assertEqual(Image.open(io.BytesIO(out)).size, LANDSCAPE)
            self.assertEqual(warnings, [])

    def test_unknown_layout_falls_back_to_an_installed_one(self):
        self.assertEqual(frame_art.active_layout({**self.cfg, "layout": "no-existe"}).kind, "layout")

    def test_render_at_other_resolution(self):
        out = frame_art.render([jpeg(LANDSCAPE)], self.cfg, [], [{"info": None}], [], (1920, 1080))
        self.assertEqual(Image.open(io.BytesIO(out)).size, (1920, 1080))


class Displays(Base):
    def test_folder_display_writes_atomically(self):
        d = plugins.REGISTRY["folder_display"]
        folder = os.path.join(os.environ["DATA_DIR"], "salida")
        cfg = {"path": folder, "name": "../../x.jpg", "width": 1920}
        self.assertIsNone(d.ready(cfg))
        d.push(cfg, b"JPEGDATA")
        with open(os.path.join(folder, "x.jpg"), "rb") as f:   # sin salirse de la carpeta
            self.assertEqual(f.read(), b"JPEGDATA")
        self.assertEqual([f for f in os.listdir(folder) if f.endswith(".tmp")], [])
        self.assertEqual(d.canvas(cfg), (1920, 1080))

    def test_folder_display_reports_unusable_folder(self):
        reason = plugins.REGISTRY["folder_display"].ready({"path": "/proc/no-se-puede"})
        self.assertTrue(reason and "carpeta" in reason.lower())

    def test_samsung_needs_a_host(self):
        os.environ.pop("TV_HOST", None)
        self.assertIn("IP de la TV", plugins.REGISTRY["samsung_frame"].ready({"host": ""}))
        with self.assertRaises(UserError):
            plugins.REGISTRY["samsung_frame"].push({"host": ""}, b"x")


if __name__ == "__main__":
    unittest.main()
