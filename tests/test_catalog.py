"""Revisa el catálogo oficial: `cd app && python -m unittest discover -s ../tests` (necesita requests y pillow).

Todo plugin oficial nuevo debe pasar esto antes de abrir el PR; no hace llamadas de red.
"""
import os
import sys
import tempfile
import unittest

os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["PLUGINS_DIR"] = os.path.join(os.environ["DATA_DIR"], "sin-plugins")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))

import plugins  # noqa: E402

FIELD_TYPES = {"bool", "number", "text", "password", "select", "location", "hidden"}


class Catalog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifests = plugins.catalog(report=True)
        plugins.installed_names = lambda: [m["name"] for m in cls.manifests]   # instalar todo para probarlo
        plugins._ensure_requires = lambda manifest: None                       # sin pip en las pruebas
        plugins.load_all()

    def test_manifests_ok(self):
        self.assertTrue(self.manifests, "el catálogo está vacío")
        self.assertEqual([e for e in plugins.ERRORS if "manifest" in e["origin"]], [])

    def test_everything_loads(self):
        self.assertEqual(plugins.ERRORS, [])

    def test_each_folder_provides_its_kind(self):
        for m in self.manifests:
            kinds = {p.kind for p in plugins.REGISTRY.values() if p.origin == m["name"]}
            self.assertIn(m["kind"], kinds, f"{m['name']}: la carpeta no aporta ningún plugin de tipo «{m['kind']}»")

    def test_unique_ids_and_valid_settings(self):
        for p in plugins.REGISTRY.values():
            self.assertTrue(p.id and p.label, p)
            keys = [f["key"] for f in p.settings]
            self.assertEqual(len(keys), len(set(keys)), f"{p.id}: claves de ajustes repetidas")
            for f in p.settings:
                self.assertIn(f["type"], FIELD_TYPES, f"{p.id}.{f['key']}")
                if f["type"] != "hidden":
                    self.assertTrue(f.get("label"), f"{p.id}.{f['key']} sin label")

    def test_essential_kinds_ship_a_default(self):
        for kind in ("layout", "display"):
            self.assertTrue([m for m in self.manifests if m["kind"] == kind and m["default"]], f"ningún plugin «{kind}» viene por defecto")

    def test_terms_are_documented_for_network_sources(self):
        for m in self.manifests:
            if m["kind"] == "source" and m["name"] != "immich":
                self.assertTrue(m["terms"], f"{m['name']}: indica en `terms` las condiciones de uso de la fuente")


if __name__ == "__main__":
    unittest.main()
