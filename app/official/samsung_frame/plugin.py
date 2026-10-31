"""Pantalla: Samsung The Frame (2021 o posterior) en modo Arte, por la red local con samsungtvws.

Puede encender la TV con Wake-on-LAN cuando está apagada (ver «Encender la TV» en el README): hay que activar en la TV
«Encender con dispositivo móvil». El magic packet se manda por broadcast y también directo a la IP de la TV (UDP/9): desde un
contenedor en red bridge solo el segundo llega, y para eso el servidor necesita la MAC de la TV fija en su tabla ARP.
"""
import os
import socket
import time

import requests
from samsungtvws import SamsungTVWS

from frameart import DATA, Display, UserError, log, read_json, run_with_timeout, write_json

# Rutas históricas (se conservan para no tener que volver a emparejar la TV ni perder lo que subimos)
TOKEN = os.path.join(DATA, "token.txt")
STATE = os.path.join(DATA, "state.json")
WAKE_TIMEOUT = 45      # segundos esperando a que la TV abra su puerto tras el magic packet
SETTLE = 6             # segundos extra para que arranquen sus servicios antes de hablarle


def magic_packet(mac: str) -> bytes:
    raw = bytes.fromhex(mac.replace(":", "").replace("-", "").strip())
    if len(raw) != 6:
        raise ValueError("la MAC debe tener 6 bytes (aa:bb:cc:dd:ee:ff)")
    return b"\xff" * 6 + raw * 16


class SamsungFrame(Display):
    id = "samsung_frame"
    label = "Samsung The Frame"
    description = "Sube la imagen al modo Arte de la TV. La primera vez la TV pide aceptar la conexión de «FrameArt»."
    enabled_by_default = True
    settings = [
        {"key": "host", "label": "IP de la TV", "type": "text", "default": "", "placeholder": "192.168.1.50 (o variable TV_HOST)"},
        {"key": "wake", "label": "Encender la TV si está apagada (Wake-on-LAN)", "type": "bool", "default": False},
        {"key": "wake_from", "label": "Solo encenderla desde las (hora, 0-23)", "type": "number", "default": 10, "min": 0, "max": 23, "step": 1},
        {"key": "wake_to", "label": "… y hasta las (hora, 1-24)", "type": "number", "default": 20, "min": 1, "max": 24, "step": 1},
        {"key": "mac", "label": "MAC de la TV", "type": "text", "default": "", "placeholder": "se detecta sola cuando la TV está encendida"},
        {"key": "broadcast", "label": "Dirección de broadcast", "type": "text", "default": "", "placeholder": "se deduce de la IP de la TV (x.y.z.255)"},
    ]

    def __init__(self):
        self._woke = False
        # ganchos para las pruebas
        self._sleep = time.sleep
        self._clock = time.time
        self._hour = lambda: time.localtime().tm_hour

    # ── utilidades ──
    @staticmethod
    def _host(cfg: dict) -> str:
        return (cfg.get("host") or os.environ.get("TV_HOST", "")).strip()

    @staticmethod
    def _reachable(host: str, timeout: float = 4) -> bool:
        try:
            socket.create_connection((host, 8002), timeout=timeout).close()
            return True
        except OSError:
            return False

    def _fetch_mac(self, host: str) -> str:
        """La TV encendida informa de la MAC de la interfaz activa en su API de información."""
        info = requests.get(f"http://{host}:8001/api/v2/", timeout=6).json()
        return info["device"]["wifiMac"]

    def _mac(self, cfg: dict, host: str) -> str:
        if cfg.get("mac", "").strip():
            return cfg["mac"].strip()
        cached = read_json(self.path("mac.json"), {})
        if cached.get("host") == host:
            return cached.get("mac", "")
        return ""

    def _learn_mac(self, cfg: dict, host: str) -> None:
        if cfg.get("mac", "").strip() or read_json(self.path("mac.json"), {}).get("host") == host:
            return
        try:
            write_json(self.path("mac.json"), {"host": host, "mac": self._fetch_mac(host)})
        except Exception as exc:  # noqa: BLE001
            log.info("no se pudo leer la MAC de la TV: %s", exc)

    def _send_magic(self, mac: str, targets: list) -> None:
        packet = magic_packet(mac)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            for _ in range(3):
                for target in targets:   # broadcast de la red y directo a la TV (el único que cruza un NAT de Docker)
                    s.sendto(packet, (target, 9))
                self._sleep(0.2)
        finally:
            s.close()

    def _in_window(self, cfg: dict) -> bool:
        a, b, h = int(cfg.get("wake_from", 10)), int(cfg.get("wake_to", 20)), self._hour()
        return a <= h < b if a <= b else (h >= a or h < b)   # admite ventanas que cruzan la medianoche

    # ── Display ──
    def ready(self, cfg: dict):
        host = self._host(cfg)
        if not host:
            return "Falta la IP de la TV: indícala en los ajustes de «Samsung The Frame» (o en TV_HOST)"
        if self._reachable(host):
            self._learn_mac(cfg, host)
            return None
        off = "TV no disponible: está apagada o fuera de la red"
        if not cfg.get("wake"):
            return off
        if not self._in_window(cfg):
            return f"{off} (fuera del horario de encendido automático: {int(cfg.get('wake_from', 10))}:00–{int(cfg.get('wake_to', 20))}:00)"
        mac = self._mac(cfg, host)
        if not mac:
            return f"{off}; no se conoce su MAC para encenderla (se aprende sola la próxima vez que esté encendida, o escríbela en los ajustes)"
        broadcast = cfg.get("broadcast", "").strip() or ".".join(host.split(".")[:3] + ["255"])
        try:
            self._send_magic(mac, [broadcast, host])
        except (OSError, ValueError) as exc:
            return f"{off}; no se pudo enviar el Wake-on-LAN ({type(exc).__name__}: {exc})"
        log.info("Wake-on-LAN enviado a %s (%s)", mac, broadcast)
        t0 = self._clock()
        while self._clock() - t0 < WAKE_TIMEOUT:
            if self._reachable(host, timeout=1.5):
                self._sleep(SETTLE)
                self._woke = True
                return None
            self._sleep(1)
        return (f"{off}; el Wake-on-LAN no la despertó en {WAKE_TIMEOUT} s (¿está activo «Encender con dispositivo móvil» en la TV "
                f"y el servidor conoce su MAC en la tabla ARP? Ver «Encender la TV» en el README)")

    def push(self, cfg: dict, jpeg: bytes) -> None:
        host = self._host(cfg)
        reason = self.ready(cfg)
        if reason:
            raise UserError(reason)
        woke, self._woke = self._woke, False
        tv = SamsungTVWS(host=host, port=8002, name="FrameArt", token_file=TOKEN, timeout=60)
        try:
            try:
                art = tv.art()
                supported = art.supported()
            except Exception as exc:  # noqa: BLE001
                raise UserError(f"No se pudo conectar con la TV ({type(exc).__name__}): revisa que acepte la conexión de FrameArt") from exc
            if not supported:
                raise UserError("La TV no soporta el modo Arte")
            state = read_json(STATE, {"uploaded": []})
            try:
                content_id = art.upload(jpeg, matte="none", file_type="JPEG")
                mode = art.get_artmode()
                if woke and mode != "on":   # a veces arranca en modo TV: se pasa a modo Arte para que se vea la obra
                    try:   # la librería espera una respuesta que la TV a veces no manda; no hay que quedarse colgado
                        run_with_timeout(lambda: art.set_artmode(True), 15)
                    except TimeoutError:
                        log.info("la TV no confirmó el cambio a modo Arte; se sigue igual")
                art.select_image(content_id, show=woke or mode == "on")
            except Exception as exc:  # noqa: BLE001
                raise UserError(f"Falló la subida a la TV ({type(exc).__name__}: {exc})") from exc
            # borrar solo lo que subió este script, nunca las obras de Samsung ni las del usuario
            for old in state["uploaded"]:
                try:
                    art.delete(old)
                except Exception as exc:  # noqa: BLE001
                    log.info("no se pudo borrar %s: %s", old, exc)
            write_json(STATE, {"uploaded": [content_id]})
            log.info("subida: %s", content_id)
        finally:
            tv.close()
