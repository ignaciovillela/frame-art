"""Traductor: endpoint público de Google Translate (no oficial, sin clave; puede cambiar o limitar sin aviso)."""
import requests

from frameart import Translator, UA


class GoogleTranslate(Translator):
    id = "google_translate"
    label = "Google Translate (no oficial)"
    description = "Traduce las descripciones a tu idioma sin clave API. Es un endpoint no documentado: si falla, la ficha queda en el idioma original."
    enabled_by_default = True

    def translate(self, cfg: dict, texts: list, source: str, target: str) -> list:
        out = []
        for text in texts:
            r = requests.get("https://translate.googleapis.com/translate_a/single", headers=UA, timeout=15,
                             params={"client": "gtx", "sl": source or "auto", "tl": target, "dt": "t", "q": text})
            r.raise_for_status()
            out.append("".join(part[0] for part in r.json()[0]))
        return out
