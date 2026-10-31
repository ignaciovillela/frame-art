"""Pantalla: Samsung The Frame (2021 o posterior) en modo Arte, por la red local con samsungtvws."""
import os
import socket

from samsungtvws import SamsungTVWS

from frameart import DATA, Display, UserError, log, read_json, write_json

# Rutas históricas (se conservan para no tener que volver a emparejar la TV ni perder lo que subimos)
TOKEN = os.path.join(DATA, "token.txt")
STATE = os.path.join(DATA, "state.json")


class SamsungFrame(Display):
    id = "samsung_frame"
    label = "Samsung The Frame"
    description = "Sube la imagen al modo Arte de la TV. La primera vez la TV pide aceptar la conexión de «FrameArt»."
    enabled_by_default = True
    settings = [{"key": "host", "label": "IP de la TV", "type": "text", "default": "",
                 "placeholder": "192.168.1.50 (o variable TV_HOST)"}]

    @staticmethod
    def _host(cfg: dict) -> str:
        return (cfg.get("host") or os.environ.get("TV_HOST", "")).strip()

    def ready(self, cfg: dict):
        host = self._host(cfg)
        if not host:
            return "Falta la IP de la TV: indícala en los ajustes de «Samsung The Frame» (o en TV_HOST)"
        try:
            socket.create_connection((host, 8002), timeout=4).close()
            return None
        except OSError:
            return "TV no disponible: está apagada o fuera de la red"

    def push(self, cfg: dict, jpeg: bytes) -> None:
        host = self._host(cfg)
        reason = self.ready(cfg)
        if reason:
            raise UserError(reason)
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
                art.select_image(content_id, show=art.get_artmode() == "on")
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
