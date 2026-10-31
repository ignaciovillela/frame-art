# Escribir un plugin

Hay dos formas de repartir un plugin: **para ti** (un archivo en `./plugins/`) o **para todos** (una carpeta en el catálogo
oficial `app/official/`, con PR; ver [CONTRIBUTING.md](../CONTRIBUTING.md)). El código es el mismo; el catálogo solo añade un `manifest.json`
y aparece en la web con un botón para instalarlo o quitarlo. Nada del catálogo se carga si no está instalado.

Un plugin se añade **dejando un archivo en `./plugins/`** (montada en `/plugins`) y pulsando «Recargar plugins» en la web.
No hace falta modificar el código ni levantar otro contenedor. Hay tres tipos y tres formas de entregarlos:

| Tipo | Para qué | Clase |
|---|---|---|
| Fuente | de dónde salen las imágenes | `Source` |
| Franja | algo que se dibuja sobre el paspartú, arriba o abajo | `Band` |
| Traductor | traduce los textos de las fichas | `Translator` |
| Disposición | cuántas obras se muestran juntas y dónde va cada una | `Layout` |
| Pantalla | adónde se envía la imagen (Samsung Frame, una carpeta, otra TV) | `Display` |

1. **Archivo `.json`** (solo fuentes): sin programar, para APIs que devuelven JSON.
2. **Archivo `.py`**: cualquier tipo. Define una o más clases con un `id` único.
3. **Paquete pip**: publica tu plugin con el entry point `frameart.plugins` y añade `EXTRA_PIP=tu-paquete` al compose.

Un plugin con el mismo `id` que uno integrado lo **reemplaza**. Un plugin roto se muestra en la web y no impide arrancar.
Los plugins ejecutan código en el contenedor: instala solo los que conozcas.

## Ajustes

Cada plugin declara `settings`; la web dibuja el formulario y guarda los valores en `data/settings.json`.
Todos los plugins tienen además un interruptor «activo».

```python
settings = [
    {"key": "url",   "label": "URL",       "type": "text", "default": ""},
    {"key": "clave", "label": "Clave API", "type": "password"},                 # nunca vuelve a la web
    {"key": "n",     "label": "Cantidad",  "type": "number", "default": 10, "min": 1, "max": 50},
    {"key": "tema",  "label": "Tema",      "type": "select", "choices": [["a", "A"], ["b", "B"]]},
    {"key": "album", "label": "Álbum",     "type": "select", "choices_from": "albums"},  # → choices("albums", cfg)
]
```
Tipos: `bool`, `number`, `range` (deslizador con `unit`, `lo`, `hi` y `track` opcionales), `text`, `password`, `select`, `location` y `hidden`. Para validar o transformar al guardar,
implementa `normalize(raw, merged, current)` (lanza `ValueError` para rechazar).

## Acciones de plugin

Un plugin puede responder a peticiones de la web con `action(name, body, cfg)`; la web las llama con
`POST /api/plugins/<id>/action/<name>`. Devuelve JSON; `ValueError` o `UserError` llegan a la web como aviso. El pronóstico la usa
(`search`) para convertir una dirección, un lugar o coordenadas pegadas («-33.59, -70.55») en candidatos {label, city, lat, lon}
con OpenStreetMap/Nominatim: sin clave, identificado con el User-Agent de la app, a un máximo de una petición por segundo y con caché.

## Fuente en JSON

```json
{
  "type": "json-source", "id": "cleveland", "label": "Cleveland Museum of Art", "lang": "en",
  "settings": [{"key": "query", "label": "Búsqueda", "type": "text", "default": "landscape"}],
  "list": {"url": "https://…/artworks/?q={query}&limit=100&fields=id", "ids": "data", "id_field": "id"},
  "item": {"url": "https://…/artworks/{id}", "root": "data", "image": "images.print.url",
           "title": "title", "artist": "creators.0.description", "year": "creation_date"}
}
```
- `list.url` devuelve la lista; `ids` es la ruta a la lista de ids (o de objetos, con `id_field`). Los `{ajuste}` se sustituyen.
- `item.url` devuelve una obra (`{id}`); `root` es la ruta al objeto si viene envuelto.
- La imagen sale de `item.image` (ruta a una URL) o de `item.image_template` (URL con `{campos}` de la obra, p. ej. IIIF).
- `title`, `artist`, `year`, `desc` son rutas opcionales para la ficha; `lang` es el idioma de esos textos.

Ejemplo completo en `app/official/cleveland/source.json`.

## Fuente en Python

```python
from frameart import Source

class MiFuente(Source):
    id = "mi_fuente"
    label = "Mi fuente"
    settings = [{"key": "ruta", "label": "Ruta", "type": "text", "default": "/fotos"}]

    def candidates(self, cfg):            # lista barata; w/h opcionales
        return [{"key": "uno.jpg", "title": "Uno", "w": None, "h": None}]

    def probe(self, cfg, item):           # opcional: (ancho, alto) sin bajar la imagen completa
        return None

    def fetch(self, cfg, item):           # (bytes de la imagen, ficha | None)
        return open(item["key"], "rb").read(), {"title": "Uno", "artist": "", "year": "", "desc": "", "lang": "es"}
```
- La imagen se descarga **una vez**: el núcleo la guarda en caché (`CACHE_MB`).
- Si la fuente trae obras verticales, `probe` evita bajar originales que luego se descartan (las verticales van de a tres).
- `lang` es el idioma de la ficha; si difiere del idioma elegido, el primer traductor activo traduce `desc`.
- Usa `http_get` (de `frameart`), que ya manda el User-Agent de la app y falla ante errores HTTP. Respeta robots.txt y los términos del sitio.
- Lanza `UserError("mensaje")` para errores que el usuario puede entender y corregir.

## Franja

```python
from PIL import ImageDraw
from frameart import Band, font

class Hora(Band):
    id = "hora"
    label = "Hora"
    position = "top"          # o "bottom"
    min_height = 150          # alto mínimo; el margen del paspartú crece si hace falta
    refresh_hours = 1         # opcional: recompone con esa frecuencia (datos que caducan)

    def prepare(self, cfg, items):         # (datos | None, aviso | None); None = no se dibuja
        import time
        return time.strftime("%H:%M"), None

    def draw(self, ctx, data):             # ctx: canvas, bg, W, H, margin, rect, cy, cells, lang, cfg
        ImageDraw.Draw(ctx.canvas).text((ctx.W / 2, ctx.cy), data, font=font(54), fill=(90, 90, 90), anchor="mm")
```
`ctx.cells` trae una entrada por obra (`left`, `width`, `cx`, `item`); `ctx.cy` es el centro vertical de tu franja.

## Traductor

```python
from frameart import Translator

class MiTraductor(Translator):
    id = "mi_traductor"
    label = "Mi traductor"
    settings = [{"key": "url", "label": "URL", "type": "text"}]

    def translate(self, cfg, texts, source, target):   # misma cantidad de textos que entran
        return [mi_api(t, source, target) for t in texts]
```
Las traducciones se guardan en `data/translations.json`, así cada texto se pide una sola vez. Con varios traductores activos se usa el primero.

## Disposición

```python
from frameart import PORTRAIT, Layout

class Mosaico(Layout):
    id = "mosaico"
    label = "Mosaico de cuatro"

    def extras(self, cfg, size):                 # obras que faltan además de la primera (size = ancho, alto)
        return [None, None, None]                # True = vertical, False = horizontal, None = cualquiera

    def cells(self, cfg, sizes, box_w, box_h, margin):
        w, h = box_w // 2, box_h // 2            # (x, y, ancho, alto, recorte máximo) por obra, dentro del área útil
        return [(i % 2 * w, i // 2 * h, w, h, 0.75) for i in range(len(sizes))]
```
Solo hay **una disposición activa**, la que se elige en la web. El núcleo pone el paspartú, el bisel y las franjas; la disposición solo
reparte el área útil. Si la lista de `cells` es más corta que las obras, las sobrantes no se dibujan.

## Pantalla

```python
from frameart import Display, UserError

class MiTV(Display):
    id = "mi_tv"
    label = "Mi TV"
    size = (3840, 2160)                          # resolución del lienzo (o redefine canvas(cfg))
    settings = [{"key": "host", "label": "IP", "type": "text", "default": ""}]

    def ready(self, cfg):                        # None = lista; si no, el motivo en español
        return None if cfg["host"] else "Falta la IP"

    def push(self, cfg, jpeg):                   # envía el JPEG; UserError con un mensaje claro si falla
        ...
```
Pueden estar **varias pantallas activas** a la vez: cada una recibe su composición (una por tamaño de lienzo). Si una falla y otra no, se
avisa en la web; si fallan todas, es un error. `ready` se consulta antes de descargar nada, así que con la TV apagada no se baja ninguna obra.
Referencia mínima: `app/official/folder_display/plugin.py`; completa: `app/official/samsung_frame/plugin.py`.

## Paquete pip

```toml
[project.entry-points."frameart.plugins"]
mi_plugin = "mi_paquete.plugin:MiFuente"      # una clase, o un módulo con varias
```
