"""Banda superior: pronóstico del día y de las próximas horas (Open-Meteo, sin clave API)."""
import time

import requests
from PIL import Image, ImageChops, ImageDraw

from frameart import UA, Band, font, read_json, shade, write_json, log

# Código WMO (Open-Meteo) -> (icono, nivel). El nivel (1-3) es la cantidad de gotas o copos: poca, moderada, mucha.
ICONS = {
    0: ("sun", 1), 1: ("sun", 1), 2: ("partly", 1), 3: ("cloud", 1), 45: ("fog", 1), 48: ("fog", 1),
    51: ("rain", 1), 53: ("rain", 1), 55: ("rain", 2), 56: ("sleet", 1), 57: ("sleet", 1),
    61: ("rain", 1), 63: ("rain", 2), 65: ("rain", 3), 66: ("sleet", 1), 67: ("sleet", 1),
    71: ("snow", 1), 73: ("snow", 2), 75: ("snow", 3), 77: ("snow", 1),
    80: ("rain", 1), 81: ("rain", 2), 82: ("rain", 3), 85: ("snow", 1), 86: ("snow", 3),
    95: ("storm", 1), 96: ("storm_hail", 1), 99: ("storm_hail", 1),
}
DRY_STORM_MM = 0.2   # una tormenta eléctrica con menos precipitación que esto (mm en la hora) se dibuja sin lluvia

# Color de acento (claro / oscuro) para los estados «no normales»; el cuerpo del icono (nube, sol, luna) siempre es neutro.
ACCENT = {"rain": ((86, 120, 168), (120, 160, 215)), "snow": ((110, 150, 180), (170, 205, 230)),
          "storm": ((196, 140, 30), (230, 180, 70)), "fog": None}
TINT_MAX = 1.0       # con el 100 % el acento sustituye al tono del paspartú; lo habitual es 30-60 %


def icon_for(code: int, is_day: bool, precip: float = 0.0) -> tuple:
    """(icono, nivel) para un código WMO; de noche el sol es luna; una tormenta casi sin precipitación va sin lluvia."""
    kind, level = ICONS.get(code, ("cloud", 1))
    if kind == "storm" and precip < DRY_STORM_MM:
        kind = "storm_dry"
    if not is_day:
        kind = {"sun": "moon", "partly": "partly_night"}.get(kind, kind)
    return kind, level


def draw_icon(layer, kind: str, x: int, y: int, s: int, level: int = 1) -> None:
    """Icono de clima dentro del cuadro (x, y, x+s, y+s). `layer(nombre)` da el ImageDraw de una capa: «body» (sol, luna, nube)
    o una de acento («rain», «snow», «storm», «fog»), que luego puede teñirse."""
    import math
    body = layer("body")
    w = max(3, s // 14)
    partly = kind in ("partly", "partly_night")
    wet = kind in ("rain", "snow", "sleet", "storm", "storm_dry", "storm_hail", "fog")

    def cloud(top: float, grow: float, fill: int) -> None:
        g = grow
        body.ellipse((x + s * 0.15 - g, top + s * 0.18 - g, x + s * 0.55 + g, top + s * 0.58 + g), fill=fill)
        body.ellipse((x + s * 0.35 - g, top - g, x + s * 0.8 + g, top + s * 0.55 + g), fill=fill)
        body.rounded_rectangle((x + s * 0.15 - g, top + s * 0.3 - g, x + s * 0.88 + g, top + s * 0.58 + g), radius=s * 0.12, fill=fill)

    def drop(d, px: float, py: float, length: float = 0.15) -> None:
        d.line((x + s * px, y + s * py, x + s * (px - 0.05), y + s * (py + length)), fill=255, width=w)

    def flake(d, px: float, py: float) -> None:
        r = w * 0.95
        d.ellipse((x + s * px - r, y + s * py - r, x + s * px + r, y + s * py + r), fill=255)

    def pattern(d, mark, n: int) -> None:   # 2, 3 ó 5 marcas: poca, moderada, mucha
        rows = {1: [(0.40, 0.80), (0.60, 0.80)], 2: [(0.30, 0.78), (0.50, 0.78), (0.70, 0.78)],
                3: [(0.28, 0.74), (0.50, 0.74), (0.72, 0.74), (0.39, 0.90), (0.61, 0.90)]}[n]
        for px, py in rows:
            mark(d, px, py)

    if kind in ("sun", "partly"):
        cx, cy, r = (x + s * 0.38, y + s * 0.38, s * 0.2) if partly else (x + s / 2, y + s / 2, s * 0.22)
        body.ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)
        for i in range(8):
            a = i * math.pi / 4
            body.line((cx + math.cos(a) * r * 1.4, cy + math.sin(a) * r * 1.4,
                       cx + math.cos(a) * r * 1.9, cy + math.sin(a) * r * 1.9), fill=255, width=w)
    if kind in ("moon", "partly_night"):
        cx, cy, r = (x + s * 0.38, y + s * 0.38, s * 0.26) if partly else (x + s / 2, y + s / 2, s * 0.32)
        body.ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)
        body.ellipse((cx - r * 0.35, cy - r * 1.15, cx + r * 1.45, cy + r * 0.65), fill=0)
    if kind in ("sun", "moon"):
        return
    top = y + s * (0.38 if partly else (0.10 if wet else 0.25))   # con precipitación la nube sube para dejar sitio debajo
    if partly:
        cloud(top, w * 1.5, 0)  # hueco entre astro y nube
    cloud(top, 0, 255)
    if kind == "rain":
        pattern(layer("rain"), lambda d, px, py: drop(d, px, py, 0.14 if level == 1 else 0.15), level)
    elif kind == "snow":
        pattern(layer("snow"), flake, level)
    elif kind == "sleet":
        drop(layer("rain"), 0.38, 0.80)
        flake(layer("snow"), 0.62, 0.86)
    elif kind in ("storm", "storm_dry", "storm_hail"):
        bolt = layer("storm")
        shift = -0.17 if kind != "storm_dry" else 0.0   # con precipitación el rayo va a la izquierda y las gotas o el granizo a la derecha
        bolt.polygon([(x + s * (px + shift), y + s * py) for px, py in
                      ((0.56, 0.60), (0.38, 0.86), (0.49, 0.86), (0.41, 1.08), (0.64, 0.79), (0.52, 0.79))], fill=255)
        if kind == "storm":
            for px, py in ((0.58, 0.78), (0.74, 0.78), (0.66, 0.93)):
                drop(layer("rain"), px, py, 0.13)
        elif kind == "storm_hail":
            for px, py in ((0.58, 0.82), (0.74, 0.82), (0.66, 0.97)):
                flake(layer("snow"), px, py)
    elif kind == "fog":
        for ly, x0, x1 in ((0.80, 0.18, 0.82), (0.96, 0.30, 0.70)):
            layer("fog").line((x + s * x0, y + s * ly, x + s * x1, y + s * ly), fill=255, width=w)


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
        {"key": "tint_amount", "label": "Color en lluvia, nieve y tormenta", "type": "range", "default": 0, "min": 0, "max": 100, "step": 10, "unit": "%",
         "lo": "Sin color", "hi": "Intenso", "track": ["#d9d3c4", "#5b86c0"]},
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
                    "hourly": "weather_code,temperature_2m,is_day,precipitation",
                    "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                },
                timeout=20,
            )
            r.raise_for_status()
            j = r.json()
            d, h = j["daily"], j["hourly"]
            now_h = j["current"]["time"][:13] + ":00"
            start = h["time"].index(now_h) if now_h in h["time"] else 0
            hours = [(int(h["time"][i][11:13]), round(h["temperature_2m"][i]), h["weather_code"][i], bool(h["is_day"][i]),
                      float(h["precipitation"][i] or 0))
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
        masks: dict = {}

        def layer(name: str) -> ImageDraw.ImageDraw:
            if name not in masks:
                masks[name] = Image.new("L", (W, H), 0)
            return ImageDraw.Draw(masks[name])
        md = layer("body")
        hours = weather.get("hours", [])
        tw = md.textlength(text, font=f)
        isz = 76
        cell = min(175, (W - 2 * max(margin, 100) - tw - 110) / len(hours)) if hours else 0
        total = tw + (110 + cell * len(hours) if hours else 0)
        x0 = (W - total) / 2
        md.text((x0, yc), text, font=f, fill=255, anchor="lm")
        hx = x0 + tw + 110
        for i, hour_data in enumerate(hours):
            hour, temp, code, is_day, *rest = hour_data   # las lecturas guardadas antes de añadir la precipitación traen 4 valores
            kind, level = icon_for(code, is_day, rest[0] if rest else DRY_STORM_MM)
            cx = hx + cell * i + cell / 2
            draw_icon(layer, kind, int(cx - isz / 2), int(yc - 66), isz, level)
            md.text((cx, yc + 46), f"{hour:02d}h  {temp}°", font=fs, fill=255, anchor="mm")
        dark = sum(bg) / 3 < 90
        tone = shade(bg, 0.1 if dark else -0.1)   # casi igual al fondo
        # relieve: reflejo arriba-izquierda y sombra abajo-derecha de todas las capas, y encima el relleno tono sobre tono
        for mask in masks.values():
            for dx, color in ((2, shade(bg, 0.3)), (-2, shade(bg, -0.4))):
                canvas.paste(color, (0, 0), ImageChops.offset(mask, -dx, -dx))
        for name, mask in masks.items():
            fill, accent = tone, ACCENT.get(name)
            amount = max(0, min(100, float(ctx.cfg.get("tint_amount") or 0))) / 100 * TINT_MAX
            if amount and accent:   # el acento se mezcla con el tono del paspartú en la proporción elegida
                fill = tuple(round(t + (a - t) * amount) for t, a in zip(tone, accent[1 if dark else 0]))
            canvas.paste(fill, (0, 0), mask)
