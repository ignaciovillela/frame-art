# Contribuir plugins oficiales

El repo trae un **catálogo** (`app/official/`) de plugins que cualquiera puede instalar desde la web con un botón.
No se carga nada que no esté instalado, así que añadir uno nuevo no afecta a quien no lo quiere.
Los plugins que no encajen en el catálogo igual se pueden compartir como archivos sueltos o paquetes pip ([guía](docs/PLUGINS.md)).

## Estructura

```
app/official/<nombre>/
  manifest.json      # obligatorio
  plugin.py          # y/o source.json (fuente declarativa)
```

`manifest.json`:

```json
{
  "label": "Nombre visible",
  "kind": "source",                      // source | band | translator | layout | display
  "description": "Qué hace, en una o dos frases.",
  "author": "tu nombre o usuario",
  "license": "MIT",
  "terms": "Condiciones de uso de la fuente o servicio, con enlace.",
  "requires": [],                        // dependencias pip, con versión: ["paquete>=1.2"]
  "default": false                       // true solo para lo esencial (se instala en una instalación nueva)
}
```

## Reglas

1. **Respeta a quien aloja los datos.** Lee sus términos y su `robots.txt`; usa `frameart.http_get` (identifica la app con su User-Agent)
   y nunca finjas ser un navegador para saltarte un bloqueo o un captcha. Si una fuente no acepta clientes identificados, no va al catálogo.
2. **Anota las condiciones en `terms`** (uso personal, atribución, límites). Es obligatorio para las fuentes de red.
3. **Sin obras ni datos en el repo.** El plugin descarga; nada del catálogo se redistribuye.
4. **Descarga lo mínimo.** El núcleo ya cachea imágenes; si la fuente trae obras verticales y horizontales, implementa `probe` para no bajar
   originales que se van a descartar.
5. **Dependencias:** lo mejor es no tener ninguna. Si hacen falta, decláralas en `requires` (se instalan solas al instalar el plugin).
6. **Nunca guardes secretos fuera de `settings`**; los campos `password` no vuelven a la web.
7. **Errores claros:** `UserError("mensaje en español")` para lo que el usuario puede corregir; el resto se registra y no tumba la app.
8. **Textos de la interfaz en español**, como el resto de la app.

## Antes del PR

```sh
cd app && python -m unittest discover -s ../tests     # valida manifiestos, ajustes y que todo cargue (sin red)
```

El CI (`.github/workflows/ci.yml`) corre lo mismo en cada PR, más pyflakes y la validación del compose, sin llamadas de red.
Describe en el PR qué fuente o servicio usa, bajo qué condiciones, y cómo lo probaste (con una captura de la TV o del render si es una franja).
