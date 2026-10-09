# precio_gasolineras

Precio medio del gasóleo A y de la gasolina 95 por provincia, actualizado cada día para dos mapas de Datawrapper.

Un script en Python descarga los precios de todas las gasolineras de España desde la API del Ministerio, calcula la media de cada provincia y la compara con la media nacional. GitHub Actions lo ejecuta cada mañana y guarda los resultados en este repositorio, de donde los lee Datawrapper.

## Cómo funciona

1. **Descarga.** [`precios_carburantes.py`](precios_carburantes.py) pide el listado completo de estaciones de servicio a la [API REST de carburantes del Ministerio](https://sedeaplicaciones.minetur.gob.es/ServiciosRESTCarburantes/PreciosCarburantes/EstacionesTerrestres/).
2. **Comprobación.** Si faltan las columnas de provincia o de precio, o la respuesta llega vacía, el script se detiene con un error en vez de publicar datos incorrectos.
3. **Limpieza.** Convierte los precios a números (la API usa coma decimal) y normaliza el código INE de la provincia a dos cifras.
4. **Cálculo.** Agrupa por código INE y calcula, para cada combustible:
   - el precio medio de la provincia,
   - el número de estaciones con precio,
   - la diferencia con la media nacional, en céntimos por litro.

   La media nacional es la media de todas las estaciones de España, no la media de las medias provinciales.
5. **Exportación.** Escribe un CSV y un JSON de metadatos por combustible en [`datos_mapa/`](datos_mapa/).

## Archivos de salida

| Archivo | Contenido |
|---|---|
| `datos_mapa/gasoleo.csv` | Una fila por provincia con el precio del gasóleo A |
| `datos_mapa/gasolina.csv` | Una fila por provincia con el precio de la gasolina 95 E5 |
| `datos_mapa/metadata_gasoleo.json` | Nota al pie del mapa del gasóleo |
| `datos_mapa/metadata_gasolina.json` | Nota al pie del mapa de la gasolina |

### Columnas de los CSV

| Columna | Descripción | Ejemplo |
|---|---|---|
| `codigo_ine` | Código INE de la provincia (01–52) | `15` |
| `clave_mapa` | Nombre que reconoce el mapa de provincias de Datawrapper | `La Coruña` |
| `provincia` | Nombre oficial, para mostrar en el tooltip | `A Coruña` |
| `precio` | Precio medio en la provincia (€/l, 3 decimales) | `1.905` |
| `estaciones` | Estaciones con precio para ese combustible | `477` |
| `dif_cent` | Diferencia con la media nacional en céntimos/l (positivo = más cara) | `-0.1` |
| `media_nacional` | Precio medio en España (€/l) | `1.907` |
| `actualizado` | Fecha y hora de los datos según el Ministerio | `05/10/2026 12:40:15` |

`clave_mapa` y `provincia` solo difieren en cinco provincias (Baleares, La Coruña, Gerona, Lérida y Orense), porque el mapa de Datawrapper usa la forma castellana del nombre. Las equivalencias están en `NOMBRES_DATAWRAPPER`, dentro del script.

### Metadatos

Cada JSON contiene la nota al pie del mapa, con la fecha de los datos y la media nacional, para que Datawrapper la actualice sola:

```json
{
  "annotate": {
    "notes": "Datos actualizados: 05/10/2026 12:40:15. Precio medio nacional del gasóleo A: 1,907 €/l."
  }
}
```

## Conectar con Datawrapper

Cada mapa usa un mapa coroplético de provincias de España con datos externos enlazados por URL:

- **Datos:** `https://raw.githubusercontent.com/SarahIshtar/precio_gasolineras/main/datos_mapa/gasoleo.csv` (o `gasolina.csv`)
- **Metadatos:** `https://raw.githubusercontent.com/SarahIshtar/precio_gasolineras/main/datos_mapa/metadata_gasoleo.json` (o `metadata_gasolina.json`)
- **Columna de enlace con el mapa:** `clave_mapa`

## Actualización automática

El workflow [`.github/workflows/actualizar_datos.yml`](.github/workflows/actualizar_datos.yml) se ejecuta todos los días a las 06:00 UTC (8:00 en horario de verano peninsular, 7:00 en invierno). Instala las dependencias, ejecuta el script y, si los datos han cambiado, hace un commit `Datos actualizados AAAA-MM-DD` con la carpeta `datos_mapa/`.

Para lanzarlo a mano: pestaña **Actions** → *Actualizar precios de carburantes* → **Run workflow**.

## Ejecutarlo en local

Requiere Python 3.9 o superior (el workflow usa 3.11).

```bash
pip install -r requirements.txt
python precios_carburantes.py
```

El script sobrescribe los archivos de `datos_mapa/` y muestra por pantalla la media nacional de cada combustible y los avisos, por ejemplo si alguna provincia se ha quedado sin datos ese día.

## Notas

- **Conexión con el Ministerio.** El servidor solo acepta TLS 1.2 con cifrados antiguos, así que el script usa un adaptador de `requests` configurado para ello (`TLS12LegacyCiphersAdapter`) y reintenta hasta cinco veces si la API falla.
- **Estaciones sin provincia.** No cuentan en las medias provinciales, pero sí en la nacional.
- **Ceuta y Melilla** aparecen en los CSV si tienen estaciones con precio ese día.
- **Añadir otro combustible.** Basta con añadir una entrada a `MAPAS` en el script (y su columna a `COLS_PRECIO`) con el nombre de la columna de la API, por ejemplo `"Precio Gasolina 98 E5"`.

## Fuente

Ministerio para la Transición Ecológica y el Reto Demográfico, [Geoportal de gasolineras](https://geoportalgasolineras.es/) / servicio REST de precios de carburantes.
