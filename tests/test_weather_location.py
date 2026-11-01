"""Búsqueda de direcciones del pronóstico (Nominatim simulado, sin red). `cd app && python -m unittest discover -s ../tests`."""
import importlib
import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["PLUGINS_DIR"] = os.path.join(os.environ["DATA_DIR"], "sin-plugins")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))

import plugins  # noqa: E402

plugins.installed_names = lambda: [m["name"] for m in plugins.catalog()]
plugins.load_all()
weather = importlib.import_module("frameart_plugin_official_weather_plugin_py")


class FakeResponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


SEARCH = [
    {"display_name": "Avenida Concha y Toro 1234, Puente Alto, Región Metropolitana, Chile", "lat": "-33.6", "lon": "-70.57",
     "address": {"road": "Avenida Concha y Toro", "house_number": "1234", "city": "Puente Alto", "state": "Región Metropolitana"}},
    {"display_name": "Puente Alto, Provincia de Cordillera, Chile", "lat": "-33.61", "lon": "-70.58", "address": {"municipality": "Puente Alto"}},
]
# lo que devolvió OpenStreetMap para «cardenal fresno 882»: la misma calle en tres tramos y sin número
STREET = [{"display_name": f"Cardenal Fresno, {b}, Puente Alto, Chile", "lat": lat, "lon": "-70.5471",
           "address": {"road": "Cardenal Fresno", "suburb": b, "city": "Puente Alto"}}
          for b, lat in (("Barrio Terrandina", "-33.5913"), ("Pircas del Maipo", "-33.5941"), ("Altos del Raco", "-33.5961"))]


class Search(unittest.TestCase):
    def setUp(self):
        self.w = weather.Weather()
        weather._nominatim["cache"].clear()
        weather._nominatim["last"] = 0.0
        self.sleeps = []
        patcher = mock.patch.object(weather.time, "sleep", lambda s: self.sleeps.append(s))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_address_gives_candidates_with_short_city_names(self):
        with mock.patch.object(weather.requests, "get", return_value=FakeResponse(SEARCH)) as get:
            out = self.w.action("search", {"q": "Concha y Toro 1234, Puente Alto"}, {})
        self.assertEqual([o["city"] for o in out], ["Puente Alto", "Puente Alto"])
        self.assertEqual((out[0]["lat"], out[0]["lon"]), (-33.6, -70.57))
        self.assertEqual(out[0]["title"], "Avenida Concha y Toro 1234, Puente Alto")
        self.assertEqual(out[0]["note"], "")                                            # el número existe: sin aviso
        self.assertIn("nominatim.openstreetmap.org/search", get.call_args.args[0])
        self.assertIn("frame-art", get.call_args.kwargs["headers"]["User-Agent"])      # identificada, como pide su política

    def test_street_in_pieces_is_shown_once_and_warns_about_the_missing_number(self):
        with mock.patch.object(weather.requests, "get", return_value=FakeResponse(STREET)):
            out = self.w.action("search", {"q": "cardenal fresno 882, Santiago, chile"}, {})
        self.assertEqual(len(out), 1)                                                   # tres tramos de la misma calle = un resultado
        self.assertEqual(out[0]["title"], "Cardenal Fresno, Puente Alto")
        self.assertIn("882", out[0]["note"])                                           # se avisa que OpenStreetMap no tiene ese número
        with mock.patch.object(weather.requests, "get", return_value=FakeResponse(STREET)):
            out = self.w.action("search", {"q": "cardenal fresno, Puente Alto"}, {})
        self.assertEqual(out[0]["note"], "")                                            # sin número pedido, sin aviso

    def test_exact_house_numbers_go_first(self):
        mixed = [STREET[0], SEARCH[0]]
        with mock.patch.object(weather.requests, "get", return_value=FakeResponse(mixed)):
            out = self.w.action("search", {"q": "concha y toro 1234"}, {})
        self.assertEqual(out[0]["title"], "Avenida Concha y Toro 1234, Puente Alto")

    def test_wanted_number_ignores_postal_codes_and_finds_the_house_number(self):
        self.assertEqual(weather.wanted_number("cardenal fresno 882, Santiago, chile"), "882")
        self.assertEqual(weather.wanted_number("Av. Siempre Viva 742B"), "742B")
        self.assertEqual(weather.wanted_number("Puente Alto 8207897"), "")
        self.assertEqual(weather.wanted_number("Plaza de Armas"), "")

    def test_pasted_coordinates_skip_the_search(self):
        reverse = {"display_name": "Puente Alto, Chile", "address": {"city": "Puente Alto"}}
        with mock.patch.object(weather.requests, "get", return_value=FakeResponse(reverse)) as get:
            out = self.w.action("search", {"q": "-33,5913, -70.5471"}, {})
        self.assertEqual(out, [{"title": "Puente Alto", "label": "Puente Alto, Chile", "city": "Puente Alto", "lat": -33.5913, "lon": -70.5471, "note": ""}])
        self.assertIn("/reverse", get.call_args.args[0])

    def test_coordinates_still_work_without_network(self):
        with mock.patch.object(weather.requests, "get", side_effect=weather.requests.ConnectionError("sin red")):
            out = self.w.action("search", {"q": "-33.5 -70.5"}, {})
        self.assertEqual((out[0]["lat"], out[0]["lon"], out[0]["city"]), (-33.5, -70.5, "Mi ubicación"))

    def test_invalid_input_is_rejected(self):
        for q, msg in (("ab", "3 caracteres"), ("95, 10", "fuera de rango"), ("10, 200", "fuera de rango")):
            with self.assertRaises(ValueError) as ctx:
                self.w.action("search", {"q": q}, {})
            self.assertIn(msg, str(ctx.exception))
        with self.assertRaises(ValueError):
            self.w.action("otra", {}, {})

    def test_repeated_search_uses_the_cache_and_requests_are_spaced(self):
        with mock.patch.object(weather.requests, "get", return_value=FakeResponse(SEARCH)) as get:
            self.w.action("search", {"q": "Puente Alto"}, {})
            self.w.action("search", {"q": "Puente Alto"}, {})      # igual: no vuelve a pedir
            self.w.action("search", {"q": "Santiago"}, {})        # distinta: espera ~1 s desde la anterior
        self.assertEqual(get.call_count, 2)
        self.assertTrue(self.sleeps and self.sleeps[-1] > 0, self.sleeps)

    def test_picked_place_is_saved_as_is_without_geocoding_again(self):
        merged = {"city": "Santiago", "lat": -33.45, "lon": -70.67, "hours": 10}
        with mock.patch.object(weather.requests, "get", side_effect=AssertionError("no debe consultar la red")):
            out = self.w.normalize({"picked": True, "city": "Puente Alto", "lat": "-33.6", "lon": "-70.57"}, dict(merged), merged)
        self.assertEqual((out["city"], out["lat"], out["lon"]), ("Puente Alto", -33.6, -70.57))
        with self.assertRaises(ValueError):
            self.w.normalize({"picked": True, "city": "X", "lat": "120", "lon": "0"}, dict(merged), merged)


if __name__ == "__main__":
    unittest.main()
