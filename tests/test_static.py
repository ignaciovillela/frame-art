"""Logo, favicon y manifest: existen, tienen el formato correcto y solo se sirve la lista permitida. Sin red."""
import json
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["PLUGINS_DIR"] = os.path.join(os.environ["DATA_DIR"], "sin-plugins")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))

from PIL import Image  # noqa: E402

import frame_art  # noqa: E402

STATIC = frame_art.STATIC_DIR


class Static(unittest.TestCase):
    def test_every_allowed_file_exists_and_is_served(self):
        for path, ctype in frame_art.STATIC.items():
            got = frame_art.static_file(path)
            self.assertIsNotNone(got, path)
            self.assertTrue(got[0] and got[1] == ctype, path)

    def test_nothing_outside_the_list_is_served(self):
        for path in ("/../frame_art.py", "/static/../frame_art.py", "/logo-full.svg", "/manifest.json", "/etc/passwd", "//favicon.svg"):
            self.assertIsNone(frame_art.static_file(path), path)

    def test_svgs_are_well_formed(self):
        for name in ("logo.svg", "favicon.svg", "logo-full.svg"):
            self.assertTrue(ET.parse(os.path.join(STATIC, name)).getroot().tag.endswith("svg"), name)

    def test_png_sizes(self):
        for name, size in (("icon-192.png", 192), ("icon-512.png", 512), ("icon-maskable-512.png", 512), ("apple-touch-icon.png", 180)):
            self.assertEqual(Image.open(os.path.join(STATIC, name)).size, (size, size), name)

    def test_ico_has_the_usual_sizes(self):
        self.assertEqual(Image.open(os.path.join(STATIC, "favicon.ico")).info["sizes"], {(16, 16), (32, 32), (48, 48)})

    def test_manifest_points_to_existing_icons(self):
        with open(os.path.join(STATIC, "manifest.webmanifest")) as f:
            m = json.load(f)
        self.assertEqual((m["name"], m["display"]), ("Frame Art", "standalone"))
        for icon in m["icons"]:
            self.assertTrue(os.path.exists(os.path.join(STATIC, icon["src"])), icon["src"])

    def test_page_links_the_icons(self):
        with open(os.path.join(os.path.dirname(STATIC), "page.html")) as f:
            html = f.read()
        for ref in ('rel="icon"', 'rel="apple-touch-icon"', 'rel="manifest"', 'name="theme-color"', 'src="logo.svg"'):
            self.assertIn(ref, html)


if __name__ == "__main__":
    unittest.main()
