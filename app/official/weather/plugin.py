"""Banda superior: pronóstico del día y de las próximas horas (Open-Meteo, sin clave API)."""
import time

import requests
from PIL import Image, ImageChops, ImageDraw

from frameart import UA, Band, font, read_json, shade, write_json, log

WMO = {
    0: ("Despejado", "sun"), 1: ("Mayormente despejado", "sun"), 2: ("Parcialmente nublado", "partly"),
    3: ("Nublado", "cloud"), 45: ("Niebla", "cloud"), 48: ("Niebla", "cloud"),
    51: ("Llovizna", "rain"), 53: ("Llovizna", "rain"), 55: ("Llovizna", "rain"),
    61: ("Lluvia ligera", "rain"), 63: ("Lluvia", "rain"), 65: ("Lluvia fuerte", "rain"),
    71: ("Nieve", "snow"), 73: ("Nieve", "snow"), 75: ("Nieve fuerte", "snow"),
    80: ("Chubascos", "rain"), 81: ("Chubascos", "rain"), 82: ("Chubascos fuertes", "rain"),
    95: ("Tormenta", "storm"), 96: ("Tormenta", "storm"), 99: ("Tormenta", "storm"),
}


def draw_icon(d: ImageDraw.ImageDraw, kind: str, x: int, y: int, s: int) -> None:
    """Icono monocromo (máscara) de clima dentro del cuadro (x, y, x+s, y+s)."""
    import math
    w = max(3, s // 14)
    partly = kind in ("partly", "partly_night")

    def cloud(top: float, grow: float, fill: int) -> None:
        g = grow
        d.ellipse((x + s * 0.15 - g, top + s * 0.18 - g, x + s * 0.55 + g, top + s * 0.58 + g), fill=fill)
        d.ellipse((x + s * 0.35 - g, top - g, x + s * 0.8 + g, top + s * 0.55 + g), fill=fill)
        d.rounded_rectangle((x + s * 0.15 - g, top + s * 0.3 - g, x + s * 0.88 + g, top + s * 0.58 + g), radius=s * 0.12, fill=fill)

    if kind in ("sun", "partly"):
        cx, cy, r = (x + s * 0.38, y + s * 0.38, s * 0.2) if partly else (x + s / 2, y + s / 2, s * 0.22)
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)
        for i in range(8):
            a = i * math.pi / 4
            d.line((cx + math.cos(a) * r * 1.4, cy + math.sin(a) * r * 1.4,
                    cx + math.cos(a) * r * 1.9, cy + math.sin(a) * r * 1.9), fill=255, width=w)
    if kind in ("moon", "partly_night"):
        cx, cy, r = (x + s * 0.38, y + s * 0.38, s * 0.26) if partly else (x + s / 2, y + s / 2, s * 0.32)
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)
        d.ellipse((cx - r * 0.35, cy - r * 1.15, cx + r * 1.45, cy + r * 0.65), fill=0)
    if kind not in ("sun", "moon"):
        top = y + s * (0.38 if partly else 0.25)
        if partly:
            cloud(top, w * 1.5, 0)  # hueco entre astro y nube
        cloud(top, 0, 255)
        if kind == "storm":
            bx, by = x + s * 0.5, top + s * 0.5
            d.polygon([(bx + s * 0.06, by), (bx - s * 0.1, by + s * 0.2), (bx, by + s * 0.2),
                       (bx - s * 0.08, by + s * 0.42), (bx + s * 0.14, by + s * 0.14), (bx + s * 0.03, by + s * 0.14)], fill=255)
        for i in range(3):
            lx = x + s * (0.28 + 0.2 * i)
            if kind == "rain":
                d.line((lx, top + s * 0.68, lx - s * 0.06, top + s * 0.88), fill=255, width=w)
            elif kind == "snow":
                ly = top + s * 0.78
                d.ellipse((lx - w, ly - w, lx + w, ly + w), fill=255)


class Weather(Band):
    id = "weather"
    label = "Pronóstico"
    description = "Temperatura, lluvia y las próximas horas, en relieve sobre el paspartú."
    position = "top"
    min_height = 150
    refresh_hours = 3
    enabled_by_default = True
    settings = [
        {"key": "city", "label": "Ubicación", "type": "location", "default": "Santiago", "placeholder": "Ciudad o comuna"},
        {"key": "lat", "type": "hidden", "default": -33.45},
        {"key": "lon", "type": "hidden", "default": -70.67},
        {"key": "hours", "label": "Horas a mostrar", "type": "number", "default": 10, "min": 3, "max": 12, "step": 1},
    ]

    def normalize(self, raw: dict, merged: dict, current: dict) -> dict:
        """Convierte lo que pide la web (ciudad o geolocalización del navegador) en ciudad + coordenadas."""
        if raw.get("geo"):
            lat, lon = float(raw["lat"]), float(raw["lon"])
            name = "Mi ubicación"
            try:
                r = requests.get("https://nominatim.openstreetmap.org/reverse", headers=UA, timeout=15, params={
                    "format": "jsonv2", "lat": lat, "lon": lon, "zoom": 13, "accept-language": "es"})
                addr = r.json().get("address", {})
                name = next((addr[k] for k in ("city", "town", "village", "municipality", "suburb", "city_district", "county") if k in addr), name)
            except Exception as exc:  # noqa: BLE001
                log.info("sin geocodificación inversa: %s", exc)
            merged.update(lat=lat, lon=lon, city=name)
        elif raw.get("city") and raw["city"].strip().lower() != str(current.get("city", "")).lower():
            r = requests.get("https://geocoding-api.open-meteo.com/v1/search", timeout=15,
                             params={"name": raw["city"].strip(), "count": 1, "language": "es"})
            found = (r.json().get("results") or [None])[0]
            if not found:
                raise ValueError(f"No encontré «{raw['city']}»")
            merged.update(lat=found["latitude"], lon=found["longitude"], city=found["name"])
        return merged

    def prepare(self, cfg: dict, items: list) -> tuple:
        """(clima, aviso). Si falla la red usa la última lectura guardada."""
        n = int(cfg["hours"])
        cache = self.path("weather.json")
        try:
            r = requests.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": cfg["lat"], "longitude": cfg["lon"], "timezone": "auto", "forecast_days": 2,
                    "current": "temperature_2m",
                    "hourly": "weather_code,temperature_2m,is_day",
                    "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                },
                timeout=20,
            )
            r.raise_for_status()
            j = r.json()
            d, h = j["daily"], j["hourly"]
            now_h = j["current"]["time"][:13] + ":00"
            start = h["time"].index(now_h) if now_h in h["time"] else 0
            hours = [(int(h["time"][i][11:13]), round(h["temperature_2m"][i]), h["weather_code"][i], bool(h["is_day"][i]))
                     for i in range(start, min(start + 12, len(h["time"])))]
            weather = {
                "hours": hours, "now": round(j["current"]["temperature_2m"]), "max": round(d["temperature_2m_max"][0]),
                "min": round(d["temperature_2m_min"][0]), "rain": d["precipitation_probability_max"][0],
                "code": d["weather_code"][0], "ts": time.time(), "lat": cfg["lat"], "lon": cfg["lon"],
            }
            write_json(cache, weather)
            return {**weather, "hours": hours[:n]}, None
        except Exception as exc:  # noqa: BLE001
            log.info("sin clima: %s", exc)
            cached = read_json(cache, None)
            if cached and (cached["lat"], cached["lon"]) == (cfg["lat"], cfg["lon"]) and time.time() - cached["ts"] < 12 * 3600:
                age = (time.time() - cached["ts"]) / 3600
                # las horas solo sirven si la lectura es reciente; si no, se deja solo el resumen del día
                cached["hours"] = [] if age > 3 else cached["hours"][:n]
                return cached, f"Sin conexión con el servicio del clima: se usan datos de hace {age:.0f} h"
            return None, "Sin clima: no hay conexión con el servicio y no hay datos guardados"

    def draw(self, ctx, weather: dict) -> None:
        canvas, W, H, bg, margin, yc = ctx.canvas, ctx.W, ctx.H, ctx.bg, ctx.margin, ctx.cy
        text = "    ·    ".join([f"Hoy en {ctx.cfg['city']}", f"{weather['min']}° / {weather['max']}°", f"Lluvia {weather['rain']}%"])
        f, fs = font(54), font(30)
        mask = Image.new("L", (W, H), 0)
        md = ImageDraw.Draw(mask)
        hours = weather.get("hours", [])
        tw = md.textlength(text, font=f)
        isz = 76
        cell = min(175, (W - 2 * max(margin, 100) - tw - 110) / len(hours)) if hours else 0
        total = tw + (110 + cell * len(hours) if hours else 0)
        x0 = (W - total) / 2
        md.text((x0, yc), text, font=f, fill=255, anchor="lm")
        hx = x0 + tw + 110
        for i, (hour, temp, code, is_day) in enumerate(hours):
            kind = WMO.get(code, ("", "cloud"))[1]
            if not is_day:
                kind = {"sun": "moon", "partly": "partly_night"}.get(kind, kind)
            cx = hx + cell * i + cell / 2
            draw_icon(md, kind, int(cx - isz / 2), int(yc - 66), isz)
            md.text((cx, yc + 46), f"{hour:02d}h  {temp}°", font=fs, fill=255, anchor="mm")
        tone = shade(bg, 0.1 if sum(bg) / 3 < 90 else -0.1)   # casi igual al fondo
        # relieve: reflejo arriba-izquierda, sombra abajo-derecha, relleno tono sobre tono
        for dx, color in ((2, shade(bg, 0.3)), (-2, shade(bg, -0.4))):
            canvas.paste(color, (0, 0), ImageChops.offset(mask, -dx, -dx))
        canvas.paste(tone, (0, 0), mask)
