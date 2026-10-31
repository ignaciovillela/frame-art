"""Wake-on-LAN del plugin de la Samsung, sin red ni TV. `cd app && python -m unittest discover -s ../tests`."""
import os
import sys
import tempfile
import unittest

os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["PLUGINS_DIR"] = os.path.join(os.environ["DATA_DIR"], "sin-plugins")
os.environ.pop("TV_HOST", None)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))

import plugins  # noqa: E402

plugins.installed_names = lambda: [m["name"] for m in plugins.catalog()]
plugins.load_all()
import importlib  # noqa: E402

samsung = importlib.import_module("frameart_plugin_official_samsung_frame_plugin_py")
magic_packet = samsung.magic_packet

MAC = "10:2b:41:01:b3:bd"
BASE = {"host": "192.168.1.89", "wake": True, "wake_from": 10, "wake_to": 20, "mac": MAC, "broadcast": ""}


class Wake(unittest.TestCase):
    def setUp(self):
        self.tv = samsung.SamsungFrame()
        self.tv.data_dir = tempfile.mkdtemp()
        self.sent, self.now, self.up_after = [], [0.0], None
        self.tv._sleep = lambda s: self.now.__setitem__(0, self.now[0] + s)
        self.tv._clock = lambda: self.now[0]
        self.tv._hour = lambda: 15
        self.tv._send_magic = lambda mac, bcast: self.sent.append((mac, bcast))
        self.tv._fetch_mac = lambda host: MAC
        self.tv._reachable = lambda host, timeout=4: self.up_after is not None and self.now[0] >= self.up_after

    def test_magic_packet_format(self):
        p = magic_packet("10:2b:41:01:b3:bd")
        self.assertEqual((len(p), p[:6], p[6:12]), (102, b"\xff" * 6, bytes.fromhex("102b4101b3bd")))
        self.assertEqual(p[6:], p[6:12] * 16)
        with self.assertRaises(ValueError):
            magic_packet("10:2b:41")

    def test_reachable_tv_is_not_woken(self):
        self.up_after = 0
        self.assertIsNone(self.tv.ready(BASE))
        self.assertEqual(self.sent, [])

    def test_off_tv_without_wake_just_reports_it(self):
        self.assertIn("apagada", self.tv.ready({**BASE, "wake": False}))
        self.assertEqual(self.sent, [])

    def test_outside_the_window_it_is_not_woken(self):
        self.tv._hour = lambda: 3
        self.assertIn("horario", self.tv.ready(BASE))
        self.assertEqual(self.sent, [])
        self.tv._hour = lambda: 20          # la hora final no está incluida
        self.assertIn("horario", self.tv.ready(BASE))

    def test_window_crossing_midnight(self):
        cfg = {**BASE, "wake_from": 22, "wake_to": 6}
        for hour, expected in ((23, True), (3, True), (12, False), (6, False)):
            self.tv._hour = lambda h=hour: h
            self.assertEqual(self.tv._in_window(cfg), expected, hour)

    def test_wakes_and_waits_for_the_tv(self):
        self.up_after = 4
        self.assertIsNone(self.tv.ready(BASE))
        self.assertEqual(self.sent, [(MAC, "192.168.1.255")])      # broadcast deducido de la IP de la TV
        self.assertTrue(self.tv._woke)

    def test_custom_broadcast_is_used(self):
        self.up_after = 1
        self.tv.ready({**BASE, "broadcast": "10.0.0.255"})
        self.assertEqual(self.sent, [(MAC, "10.0.0.255")])

    def test_gives_up_with_an_actionable_message(self):
        msg = self.tv.ready(BASE)
        self.assertIn("no la despertó", msg)
        self.assertIn("UDP/9", msg)
        self.assertFalse(self.tv._woke)

    def test_unknown_mac_is_reported_and_learned_when_the_tv_is_on(self):
        cfg = {**BASE, "mac": ""}
        self.assertIn("MAC", self.tv.ready(cfg))
        self.assertEqual(self.sent, [])
        self.up_after = 0                                    # la TV está encendida: aprende la MAC
        self.assertIsNone(self.tv.ready(cfg))
        self.up_after = None                                 # y luego apagada, ya puede despertarla
        self.up_after = self.now[0] + 3
        self.assertIsNone(self.tv.ready(cfg))
        self.assertEqual(self.sent[0][0], MAC)


if __name__ == "__main__":
    unittest.main()
