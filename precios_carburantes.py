# -*- coding: utf-8 -*-
# Descarga de precios de carburantes (MINETUR) → comprobación de columnas →
# medias por provincia y media nacional → un CSV y un metadata.json por
# combustible en datos_mapa/, uno para cada mapa de Datawrapper.
import json
import certifi, requests, pandas as pd
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

RUTA_MAPA = Path("datos_mapa")    # lo que lee Datawrapper
URL = "https://sedeaplicaciones.minetur.gob.es/ServiciosRESTCarburantes/PreciosCarburantes/EstacionesTerrestres/"
ZONA = ZoneInfo("Europe/Madrid")  # GitHub trabaja en hora UTC; así las fechas salen en hora española

COL_PROVINCIA = "Provincia"
COL_ID_PROVINCIA = "IDProvincia"  # código INE de la provincia (01-52)
COLS_PRECIO = ["Precio Gasoleo A", "Precio Gasolina 95 E5"]
COLUMNAS = ["Rótulo", "Horario", "Dirección", "Municipio", COL_PROVINCIA, COL_ID_PROVINCIA,
            *COLS_PRECIO, "Latitud", "Longitud (WGS84)"]

# Un mapa por combustible: nombre del archivo → columna de precio de la API
MAPAS = {
    "gasoleo": ("Precio Gasoleo A", "del gasóleo A"),
    "gasolina": ("Precio Gasolina 95 E5", "de la gasolina 95"),
}

# Nombres legibles por código INE (para el tooltip) (la API los da en mayúsculas y con formatos raros: "CORUÑA (A)")
NOMBRES_INE = {
    "01": "Álava", "02": "Albacete", "03": "Alicante", "04": "Almería", "05": "Ávila",
    "06": "Badajoz", "07": "Illes Balears", "08": "Barcelona", "09": "Burgos", "10": "Cáceres",
    "11": "Cádiz", "12": "Castellón", "13": "Ciudad Real", "14": "Córdoba", "15": "A Coruña",
    "16": "Cuenca", "17": "Girona", "18": "Granada", "19": "Guadalajara", "20": "Gipuzkoa",
    "21": "Huelva", "22": "Huesca", "23": "Jaén", "24": "León", "25": "Lleida",
    "26": "La Rioja", "27": "Lugo", "28": "Madrid", "29": "Málaga", "30": "Murcia",
    "31": "Navarra", "32": "Ourense", "33": "Asturias", "34": "Palencia", "35": "Las Palmas",
    "36": "Pontevedra", "37": "Salamanca", "38": "Santa Cruz de Tenerife", "39": "Cantabria",
    "40": "Segovia", "41": "Sevilla", "42": "Soria", "43": "Tarragona", "44": "Teruel",
    "45": "Toledo", "46": "Valencia", "47": "Valladolid", "48": "Bizkaia", "49": "Zamora",
    "50": "Zaragoza", "51": "Ceuta", "52": "Melilla",
}

# El mapa de Datawrapper usa la forma castellana de algunos nombres.
# Solo hace falta poner aquí los que no coinciden con NOMBRES_INE.
NOMBRES_DATAWRAPPER = {
    "07": "Baleares", "15": "La Coruña", "17": "Gerona",
    "25": "Lérida", "32": "Orense",
}


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


# ---------- Descarga y comprobaciones ----------
def descargar_datos():
    s = make_session()
    resp = s.get(URL, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    if "ListaEESSPrecio" not in data:
        raise ValueError(f"La respuesta no contiene 'ListaEESSPrecio'. Claves recibidas: {list(data.keys())}")

    df = pd.DataFrame(data["ListaEESSPrecio"])
    if df.empty:
        raise ValueError("La API ha devuelto una lista de estaciones vacía.")

    return df, data.get("Fecha")


def comprobar_columnas(df: pd.DataFrame) -> None:
    """Que existan provincia (nombre y código) y precios, y que la provincia tenga datos."""
    for col in [COL_PROVINCIA, COL_ID_PROVINCIA]:
        if col not in df.columns:
            raise KeyError(f"No existe la columna '{col}' en los datos descargados.\n"
                           f"Columnas disponibles: {list(df.columns)}")

    vacias = df[COL_PROVINCIA].isna() | (df[COL_PROVINCIA].astype(str).str.strip() == "")
    if vacias.all():
        raise ValueError(f"La columna '{COL_PROVINCIA}' existe pero está vacía en todas las filas.")
    if vacias.any():
        print(f"Aviso: {vacias.sum()} estaciones sin provincia; no contarán en las medias provinciales.")

    print(f"OK: columna '{COL_PROVINCIA}' encontrada "
          f"({df[COL_PROVINCIA].nunique()} provincias distintas, {len(df)} estaciones).")

    faltan = [c for c in COLS_PRECIO if c not in df.columns]
    if faltan:
        raise KeyError(f"Faltan columnas de precio: {faltan}. Columnas disponibles: {list(df.columns)}")


# ---------- Limpieza ----------
def a_float(s: pd.Series) -> pd.Series:
    return pd.to_numeric(
        s.astype(str).str.replace(",", ".").str.replace("\xa0", "").str.strip(),
        errors="coerce",
    )


def limpiar(df: pd.DataFrame) -> pd.DataFrame:
    df = df[[c for c in COLUMNAS if c in df.columns]].copy()
    for c in COLS_PRECIO + ["Latitud", "Longitud (WGS84)"]:
        if c in df.columns:
            df[c] = a_float(df[c])
    df[COL_PROVINCIA] = df[COL_PROVINCIA].astype(str).str.strip()
    df.loc[df[COL_PROVINCIA] == "", COL_PROVINCIA] = pd.NA
    # Código INE siempre con dos cifras ("8" → "08")
    df[COL_ID_PROVINCIA] = df[COL_ID_PROVINCIA].astype(str).str.strip().str.zfill(2)
    return df


# ---------- Cálculos ----------
def media_nacional(df: pd.DataFrame) -> pd.DataFrame:
    # Media de todas las estaciones de España (no media de las medias provinciales)
    filas = []
    for c in COLS_PRECIO:
        filas.append({
            "Carburante": c.replace("Precio ", ""),
            "Media nacional (€/l)": round(df[c].mean(), 3),
            "Nº estaciones con precio": int(df[c].count()),
        })
    return pd.DataFrame(filas)


# ---------- Datos para los mapas de Datawrapper ----------
def fmt(x):  # 1.4567 → "1,457"
    return f"{x:.3f}".replace(".", ",")


def tabla_mapa(df: pd.DataFrame, col_precio: str, actualizado: str) -> pd.DataFrame:
    """Una fila por provincia para un combustible, agrupando por código INE."""
    media_nac = df[col_precio].mean()

    t = (df[df[COL_ID_PROVINCIA].isin(NOMBRES_INE.keys())]
           .groupby(COL_ID_PROVINCIA)
           .agg(precio=(col_precio, "mean"), estaciones=(col_precio, "count"))
           .reset_index()
           .rename(columns={COL_ID_PROVINCIA: "codigo_ine"}))

    # clave_mapa: lo que reconoce Datawrapper. provincia: nombre oficial para el tooltip
    t.insert(1, "clave_mapa", t["codigo_ine"].map(lambda c: NOMBRES_DATAWRAPPER.get(c, NOMBRES_INE[c])))
    t.insert(2, "provincia", t["codigo_ine"].map(NOMBRES_INE))
    # Diferencia con la media nacional, en céntimos por litro (positivo = más cara)
    t["dif_cent"] = ((t["precio"] - media_nac) * 100).round(1) + 0.0  # + 0.0 evita "-0.0"
    t["precio"] = t["precio"].round(3)
    t["media_nacional"] = round(media_nac, 3)
    t["actualizado"] = actualizado
    return t.sort_values("codigo_ine")


def exportar_mapas(df: pd.DataFrame, actualizado: str) -> None:
    RUTA_MAPA.mkdir(parents=True, exist_ok=True)
    for nombre, (col_precio, etiqueta) in MAPAS.items():
        t = tabla_mapa(df, col_precio, actualizado)
        t.to_csv(RUTA_MAPA / f"{nombre}.csv", index=False, encoding="utf-8")

        # Nota al pie que se actualiza sola en Datawrapper
        nota = (f"Datos actualizados: {actualizado}. "
                f"Precio medio nacional {etiqueta}: {fmt(df[col_precio].mean())} €/l.")
        meta = {"annotate": {"notes": nota}}
        (RUTA_MAPA / f"metadata_{nombre}.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        faltan = sorted(set(NOMBRES_INE) - set(t["codigo_ine"]))
        if faltan:
            print(f"Aviso ({nombre}): provincias sin datos este día: {[NOMBRES_INE[c] for c in faltan]}")


# ---------- Principal ----------
def main():
    ahora = datetime.now(ZONA)
    df_raw, fecha_api = descargar_datos()
    comprobar_columnas(df_raw)

    df = limpiar(df_raw)
    nac = media_nacional(df)
    actualizado = fecha_api or ahora.strftime("%d/%m/%Y %H:%M")

    exportar_mapas(df, actualizado)

    print(f"\nDatos del ministerio actualizados a: {actualizado}")
    print("\nMedia nacional:")
    print(nac.to_string(index=False))
    print(f"\nArchivos de los mapas en: {RUTA_MAPA}/ ({', '.join(f'{n}.csv' for n in MAPAS)})")


if __name__ == "__main__":
    main()
