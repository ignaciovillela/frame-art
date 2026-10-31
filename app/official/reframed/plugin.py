"""Fuente: reframed.gallery, colección gratuita (solo uso personal) de pinturas clásicas en 4K.

Su FAQ: https://www.reframed.gallery/faq. Se leen el sitemap público y las páginas de obra (robots.txt lo permite)
y se descargan los originales del CDN, una sola vez por obra gracias a la caché en disco del núcleo.
"""
import html
import io
import json
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET

from PIL import Image

from frameart import Source, http_get, read_json, write_json

SITE = "https://www.reframed.gallery"
OG_IMAGE = re.compile(r'property="og:image"\s+content="([^"]+)"')
LD_JSON = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
YEAR = re.compile(r"\b(?:in|around|circa|c\.|by)\s+(?:the\s+)?(?:early\s+|late\s+|mid-?)?(\d{4}s?)\b")


def pretty(slug: str) -> str:
    return urllib.parse.unquote(slug).replace("-", " ").strip().title()


def parse_info(page: str) -> dict | None:
    for m in LD_JSON.finditer(page):
        try:
            d = json.loads(m.group(1))
        except ValueError:
            continue
        if d.get("@type") != "VisualArtwork":
            continue
        desc = " ".join((d.get("description") or "").split("\n\n")[0].split())
        year = YEAR.search(desc)
        short = re.split(r"(?<=[.!?])\s+", desc)[0] if desc else ""
        if len(short) > 170:
            short = short[:167].rsplit(" ", 1)[0].rstrip(",;:") + "…"
        artist = d.get("artist")
        return {"title": d.get("name") or "", "artist": (artist.get("name") if isinstance(artist, dict) else artist) or "",
                "year": year.group(1) if year else "", "desc": short, "lang": "en"}
    return None


class Reframed(Source):
    id = "reframed"
    label = "Pinturas (reframed.gallery)"
    description = "Pinturas clásicas ya recortadas a 4K. Solo uso personal; los originales se descargan una vez y quedan en caché."
    enabled_by_default = True
    settings = [{"key": "artist", "label": "Artista", "type": "select", "choices_from": "artists", "default": ""}]

    def __init__(self):
        self._sitemap = (0.0, [])
        self._meta = None

    # ── metadatos guardados por obra: dimensiones, ficha y URL del original ──
    def _meta_all(self) -> dict:
        if self._meta is None:
            self._meta = read_json(self.path("meta.json"), {})
        return self._meta

    def _save_meta(self, key: str, **values) -> dict:
        meta = self._meta_all()
        meta[key] = {**meta.get(key, {}), **values}
        write_json(self.path("meta.json"), meta)
        return meta[key]

    def _page_meta(self, key: str) -> dict:
        m = self._meta_all().get(key, {})
        if m.get("original"):
            return m
        page = http_get(key).text
        og = OG_IMAGE.search(page)
        if not og or "/originals/" not in og.group(1):
            raise ValueError("la obra no tiene imagen original")
        thumb = html.unescape(og.group(1))
        name = thumb.split("/originals/", 1)[1]
        return self._save_meta(key, original=f"https://cdn.reframed.gallery/originals/{name}", thumb=thumb, info=parse_info(page))

    # ── Source ──
    def _urls(self) -> list:
        ts, urls = self._sitemap
        if urls and time.time() - ts < 6 * 3600:
            return urls
        root = ET.fromstring(http_get(f"{SITE}/sitemap.xml").content)
        locs = [e.text for e in root.iter() if e.tag.endswith("loc") and e.text]
        parts = [urllib.parse.urlparse(u).path.strip("/").split("/") for u in locs]
        # /artista/obra tiene exactamente dos segmentos; las colecciones no son obras
        urls = [u for u, p in zip(locs, parts) if len(p) == 2 and p[0] != "collections"]
        self._sitemap = (time.time(), urls)
        return urls

    def choices(self, name: str, cfg: dict) -> list:
        slugs = sorted({urllib.parse.urlparse(u).path.strip("/").split("/")[0] for u in self._urls()})
        return [{"value": s, "label": pretty(s)} for s in slugs]

    def candidates(self, cfg: dict) -> list:
        meta, out = self._meta_all(), []
        for u in self._urls():
            artist, work = urllib.parse.urlparse(u).path.strip("/").split("/")
            if cfg.get("artist") and artist != cfg["artist"]:
                continue
            m = meta.get(u, {})
            out.append({"key": u, "title": f"{pretty(work)} — {pretty(artist)}", "w": m.get("w"), "h": m.get("h")})
        return out

    def probe(self, cfg: dict, item: dict):
        """Proporción a partir de la miniatura del propio sitio (decenas de KB) en vez del original de varios MB."""
        m = self._page_meta(item["key"])
        if not m.get("w"):
            w, h = Image.open(io.BytesIO(http_get(m["thumb"], timeout=60).content)).size
            m = self._save_meta(item["key"], w=w, h=h)
        return m["w"], m["h"]

    def fetch(self, cfg: dict, item: dict) -> tuple:
        m = self._page_meta(item["key"])
        return http_get(m["original"], timeout=120).content, m.get("info")
