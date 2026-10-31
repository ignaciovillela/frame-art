"""Traducción de la ficha (título y descripción) con un traductor de mentira: sin red. `cd app && python -m unittest discover -s ../tests`."""
import os
import sys
import tempfile
import unittest

os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["PLUGINS_DIR"] = os.path.join(os.environ["DATA_DIR"], "sin-plugins")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))

import frame_art  # noqa: E402
import plugins  # noqa: E402
from frameart import Translator  # noqa: E402

CALLS = []


class Fake(Translator):
    id, label = "fake", "Falso"

    def translate(self, cfg, texts, source, target):
        CALLS.append(list(texts))
        if os.environ.get("FAKE_FAIL"):
            raise RuntimeError("sin servicio")
        return [f"[{target}] {t}" for t in texts]


INFO = {"title": "Mount Etna", "artist": "Thomas Cole", "year": "1840s", "desc": "A view.", "lang": "en"}


class Translate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        plugins.installed_names = lambda: [m["name"] for m in plugins.catalog()]
        plugins.load_all()
        plugins.REGISTRY["fake"] = Fake()
        cls.cfg = frame_art.load_settings()
        cls.cfg["plugins"]["google_translate"]["enabled"] = False
        cls.cfg["plugins"]["fake"] = {"enabled": True}

    def setUp(self):
        CALLS.clear()
        os.environ.pop("FAKE_FAIL", None)

    def test_title_and_description_translated_artist_untouched(self):
        out = frame_art.localize(INFO, self.cfg, [], ("desc", "title"))
        self.assertEqual((out["title"], out["desc"]), ("[es] Mount Etna", "[es] A view."))
        self.assertEqual((out["artist"], out["year"], out["title_orig"], out["lang"]), ("Thomas Cole", "1840s", "Mount Etna", "es"))

    def test_initial_capital_of_the_original_is_kept(self):
        self.assertEqual(frame_art._keep_case("Utopia", "utopía"), "Utopía")
        self.assertEqual(frame_art._keep_case("iPhone", "iPhone"), "iPhone")        # el original en minúscula no se toca
        self.assertEqual(frame_art._keep_case("Hello", "Hola"), "Hola")

    def test_title_only_when_the_band_asks_for_it(self):
        out = frame_art.localize(INFO, self.cfg, [], ("desc",))
        self.assertEqual(out["title"], "Mount Etna")
        self.assertNotIn("title_orig", out)

    def test_sources_without_language_are_left_alone(self):
        own = {"title": "Mi foto", "artist": "", "year": "2020", "desc": "", "lang": ""}
        self.assertEqual(frame_art.localize(own, self.cfg, [], ("desc", "title")), own)

    def test_failure_keeps_the_original_and_warns_once(self):
        os.environ["FAKE_FAIL"] = "1"
        warnings = []
        info = {**INFO, "title": "Otro título", "desc": "Otra descripción."}
        out = frame_art.localize(info, self.cfg, warnings, ("desc", "title"))
        self.assertEqual(out, info)
        self.assertEqual(len(warnings), 1)

    def test_cache_means_each_text_is_requested_once(self):
        info = {**INFO, "title": "Cacheado", "desc": "Texto cacheado."}
        frame_art.localize(info, self.cfg, [], ("desc", "title"))
        frame_art.localize(info, self.cfg, [], ("desc", "title"))
        self.assertEqual(len(CALLS), 1)

    def test_caption_shows_translated_title_with_optional_original(self):
        cap = plugins.REGISTRY["caption"]
        info = {"title": "Monte Etna", "title_orig": "Mount Etna"}
        self.assertEqual(cap.display_title(info, {"show_original": False}), "Monte Etna")
        self.assertEqual(cap.display_title(info, {"show_original": True}), "Monte Etna (Mount Etna)")
        same = {"title": "Hello Sun IV", "title_orig": "hello sun iv"}
        self.assertEqual(cap.display_title(same, {"show_original": True}), "Hello Sun IV")   # sin duplicar si no cambió
        self.assertEqual(cap.translate_fields({"translate_title": True}), ("desc", "title"))
        self.assertEqual(cap.translate_fields({"translate_title": False}), ("desc",))


if __name__ == "__main__":
    unittest.main()
