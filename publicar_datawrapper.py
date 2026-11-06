"""
Republica en Datawrapper los gráficos que leen los CSV de este repositorio.

Los gráficos leen el CSV desde el servidor de Datawrapper, que solo lo vuelve a descargar
durante los 30 días siguientes a la última publicación. Republicar cada día reinicia ese
plazo, así que los gráficos no se quedan congelados.

El token se lee del secret DATAWRAPPER_TOKEN_GASOLINERAS. Un gráfico con el ID vacío se salta con un aviso.

Uso: python publicar_datawrapper.py
"""

import os
import sys
import time
import urllib.error
import urllib.request

# ID de cada gráfico: los 5 caracteres de su URL (datawrapper.dwcdn.net/<ID>/).
GRAFICOS = {
    "Precio de la gasolina y el diésel desde 2021 (datos_grafico/)": "DrrRr",
    "El precio de la gasolina hoy en cada provincia (datos_mapa/gasolina.csv)": "ypEyM",
    "El precio del diésel hoy en cada provincia (datos_mapa/gasoleo.csv)": "2dQMs",
}

URL_PUBLICAR = "https://api.datawrapper.de/v3/charts/{id}/publish"
INTENTOS = 3


def publicar(id_grafico: str, token: str) -> None:
    """Republica un gráfico. Reintenta si falla la red o Datawrapper da un error 5xx."""
    peticion = urllib.request.Request(
        URL_PUBLICAR.format(id=id_grafico),
        method="POST",
        headers={"Authorization": f"Bearer {token}"},
    )
    for intento in range(1, INTENTOS + 1):
        try:
            with urllib.request.urlopen(peticion, timeout=60):
                return
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise RuntimeError(f"Datawrapper rechaza el token ({e.code}): no existe, ha caducado, "
                                   f"le falta el permiso chart:write o el gráfico es de otra cuenta.")
            if e.code == 404:
                raise RuntimeError("Datawrapper no encuentra el gráfico (404): revisa el ID en GRAFICOS.")
            error = f"error {e.code}"
        except urllib.error.URLError as e:
            error = f"sin conexión ({e.reason})"
        if intento == INTENTOS:
            raise RuntimeError(f"No se ha podido republicar tras {INTENTOS} intentos: {error}.")
        print(f"  Intento {intento} fallido ({error}), reintentando…")
        time.sleep(intento * 10)


def main():
    token = os.environ.get("DATAWRAPPER_TOKEN_GASOLINERAS")
    if not token:
        print("::error title=Datawrapper::Falta el secret DATAWRAPPER_TOKEN_GASOLINERAS en el repositorio.")
        sys.exit(1)

    fallos = 0
    for nombre, id_grafico in GRAFICOS.items():
        if not id_grafico:
            print(f"::warning title={nombre} - Datawrapper::Falta el ID del gráfico en publicar_datawrapper.py. No se republica.")
            continue
        print(f"Republicando {nombre} ({id_grafico})…")
        try:
            publicar(id_grafico, token)
            print(f"  OK: https://datawrapper.dwcdn.net/{id_grafico}/")
        except RuntimeError as e:
            print(f"::error title={nombre} - Datawrapper::{e}")
            fallos += 1
    # Si falla uno, los demás se republican igual, pero el job termina en rojo para que se vea.
    sys.exit(1 if fallos else 0)


if __name__ == "__main__":
    main()
