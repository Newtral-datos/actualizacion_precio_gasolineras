# -*- coding: utf-8 -*-
# Descarga el histórico del precio medio nacional de la gasolina 95 y el gasóleo A,
# día a día, desde FECHA_INICIO hasta ayer, y lo guarda en un CSV.
# Script independiente: no necesita ningún otro archivo del proyecto.
#
# Se puede interrumpir con Ctrl+C: lo descargado se guarda y, al volver a ejecutarlo,
# sigue donde lo dejó (solo descarga los días que faltan en el CSV).
import argparse, sys, time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import certifi, requests, pandas as pd
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

URL_HIST = ("https://sedeaplicaciones.minetur.gob.es/ServiciosRESTCarburantes/"
            "PreciosCarburantes/EstacionesTerrestresHist/{fecha}")
FECHA_INICIO = date(2021, 1, 1)
RUTA_CSV = Path("datos_grafico") / "evolucion_precios.csv"
ZONA = ZoneInfo("Europe/Madrid")
PAUSA_SEG = 1.0      # espera entre peticiones, para no saturar el servidor del ministerio
GUARDAR_CADA = 20    # guarda el CSV cada 20 días descargados

# Precios fuera de este rango se consideran errores de la fuente y se descartan
PRECIO_MIN, PRECIO_MAX = 0.5, 4.0

# Nombre de la columna en el CSV → columna de la API
SERIES = {"Gasolina 95 E5": "Precio Gasolina 95 E5", "Diésel": "Precio Gasoleo A"}


# ---------- Conexión (el servidor del ministerio necesita TLS 1.2 y cifrados antiguos) ----------
class TLS12LegacyCiphersAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        import ssl as _ssl
        ctx = _ssl.create_default_context(cafile=certifi.where())
        ctx.minimum_version = _ssl.TLSVersion.TLSv1_2
        ctx.maximum_version = _ssl.TLSVersion.TLSv1_2
        try:
            ctx.set_ciphers("ECDHE+AESGCM:ECDHE+AES:RSA+AES:AES128-SHA:AES256-SHA:!aNULL:!eNULL:!MD5:@SECLEVEL=1")
        except _ssl.SSLError:
            ctx.set_ciphers("DEFAULT:@SECLEVEL=1")
        try:
            ctx.set_alpn_protocols(["http/1.1"])
        except Exception:
            pass
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


def make_session():
    s = requests.Session()
    s.trust_env = False
    s.headers.update({"User-Agent": "Mozilla/5.0"})
    retries = Retry(total=5, connect=5, read=5, backoff_factor=0.6,
                    status_forcelist=(429, 502, 503, 504), allowed_methods=frozenset(["GET"]))
    s.mount("https://", TLS12LegacyCiphersAdapter(max_retries=retries))
    return s


def a_float(s: pd.Series) -> pd.Series:
    return pd.to_numeric(
        s.astype(str).str.replace(",", ".").str.replace("\xa0", "").str.strip(),
        errors="coerce",
    )


def leer_historico() -> pd.DataFrame:
    if RUTA_CSV.exists():
        return pd.read_csv(RUTA_CSV, dtype={"fecha": str})
    return pd.DataFrame(columns=["fecha", *SERIES])


def media_del_dia(sesion, dia: date):
    """Precio medio nacional de un día concreto. Devuelve None si ese día no hay datos."""
    resp = sesion.get(URL_HIST.format(fecha=dia.strftime("%d-%m-%Y")), timeout=120)
    resp.raise_for_status()
    estaciones = resp.json().get("ListaEESSPrecio") or []
    if not estaciones:
        return None

    df = pd.DataFrame(estaciones)
    fila = {"fecha": dia.isoformat()}
    for nombre, col in SERIES.items():
        if col not in df.columns:
            raise KeyError(f"Falta la columna '{col}'. Columnas disponibles: {list(df.columns)}")
        precios = a_float(df[col])
        precios = precios[precios.between(PRECIO_MIN, PRECIO_MAX)]   # quita vacíos y anómalos
        fila[nombre] = round(precios.mean(), 3) if not precios.empty else None
    return fila


def guardar(historico: pd.DataFrame, nuevas: list) -> pd.DataFrame:
    if nuevas:
        nuevas_df = pd.DataFrame(nuevas)
        # Si el CSV aún está vacío no se concatena (evita un aviso de pandas)
        historico = nuevas_df if historico.empty else pd.concat([historico, nuevas_df], ignore_index=True)
    historico = (historico.drop_duplicates("fecha", keep="last")
                          .sort_values("fecha")
                          .reset_index(drop=True))
    RUTA_CSV.parent.mkdir(parents=True, exist_ok=True)
    historico.to_csv(RUTA_CSV, index=False, encoding="utf-8")

    return historico


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-dias", type=int, default=None,
                    help="Descargar como mucho este número de días (los más recientes)")
    args = ap.parse_args()

    historico = leer_historico()
    hechas = set(historico["fecha"])
    ayer = datetime.now(ZONA).date() - timedelta(days=1)
    todas = [FECHA_INICIO + timedelta(days=i) for i in range((ayer - FECHA_INICIO).days + 1)]
    pendientes = [d for d in todas if d.isoformat() not in hechas]
    if args.max_dias:
        pendientes = pendientes[-args.max_dias:]

    if not pendientes:
        print("El histórico ya está al día.")
        guardar(historico, [])
        return
    print(f"Días por descargar: {len(pendientes)} ({pendientes[0]} → {pendientes[-1]})")

    sesion = make_session()
    nuevas, fallos, sin_datos = [], [], []
    try:
        for i, dia in enumerate(pendientes, 1):
            try:
                fila = media_del_dia(sesion, dia)
            except KeyError:
                raise                      # cambio de formato: parar, no tiene sentido seguir
            except Exception as e:
                print(f"  {dia}: error ({e.__class__.__name__}). Se reintentará en la próxima ejecución.")
                fallos.append(dia)
            else:
                if fila is None:
                    sin_datos.append(dia)
                else:
                    nuevas.append(fila)
                    print(f"  {dia}: gasolina {fila['Gasolina 95 E5']} | diésel {fila['Diésel']}  ({i}/{len(pendientes)})")
            if len(nuevas) >= GUARDAR_CADA:
                historico = guardar(historico, nuevas); nuevas = []
            time.sleep(PAUSA_SEG)
    finally:
        guardar(historico, nuevas)        # se guarda también si se interrumpe o hay un error

    if sin_datos:
        print(f"Días sin datos en la API: {[str(d) for d in sin_datos]}")
    if fallos:
        print(f"Días con error: {len(fallos)}")
        sys.exit(1)                        # marca la ejecución en rojo en GitHub para que se vea


if __name__ == "__main__":
    main()
    