# -*- coding: utf-8 -*-
# Descarga → GeoJSON → MBTiles (Tippecanoe) → stats.json (cuantiles/min/max).
import ssl, certifi, requests, pandas as pd, subprocess, shutil, os, json
from pathlib import Path
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

RUTA_BASE = Path("data")
URL = "https://sedeaplicaciones.minetur.gob.es/ServiciosRESTCarburantes/PreciosCarburantes/EstacionesTerrestres/"

class TLS12LegacyCiphersAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        import ssl as _ssl
        ctx = _ssl.create_default_context(cafile=certifi.where())
        ctx.minimum_version = _ssl.TLSVersion.TLSv1_2; ctx.maximum_version = _ssl.TLSVersion.TLSv1_2
        try: ctx.set_ciphers("ECDHE+AESGCM:ECDHE+AES:RSA+AES:AES128-SHA:AES256-SHA:!aNULL:!eNULL:!MD5:@SECLEVEL=1")
        except _ssl.SSLError: ctx.set_ciphers("DEFAULT:@SECLEVEL=1")
        try: ctx.set_alpn_protocols(["http/1.1"])
        except Exception: pass
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)

def make_session():
    s = requests.Session(); s.trust_env = False; s.headers.update({"User-Agent":"Mozilla/5.0"})
    retries = Retry(total=5, connect=5, read=5, backoff_factor=0.6, status_forcelist=(429,502,503,504), allowed_methods=frozenset(["GET"]))
    s.mount("https://", TLS12LegacyCiphersAdapter(max_retries=retries)); return s

def df_to_geojson(df: pd.DataFrame, ruta_geojson: Path) -> None:
    feats=[]
    for _, r in df.iterrows():
        lon=r.get("Longitud (WGS84)"); lat=r.get("Latitud")
        if pd.notnull(lon) and pd.notnull(lat):
            props={k:(None if pd.isna(v) else v) for k,v in r.to_dict().items() if k not in ["Latitud","Longitud (WGS84)"]}
            feats.append({"type":"Feature","geometry":{"type":"Point","coordinates":[float(lon), float(lat)]},"properties":props})
    ruta_geojson.write_text(json.dumps({"type":"FeatureCollection","features":feats}, ensure_ascii=False), encoding="utf-8")

def qbreaks(series: pd.Series, classes=8):
    s = pd.to_numeric(series, errors="coerce").dropna()
    if s.empty: return None
    qs = [s.quantile(i/classes) for i in range(1, classes)]
    # Garantiza estrictamente creciente
    out=[]; last=None
    for v in qs:
        v=float(v)
        if last is None or v>last: out.append(v); last=v
        else: out.append(last + 1e-6); last=out[-1]
    return out

def main():
    fecha_archivo = datetime.now().strftime("%d_%m_%Y")

    s = make_session(); resp = s.get(URL, timeout=30); data = resp.json()
    if "ListaEESSPrecio" not in data: return
    df = pd.DataFrame(data["ListaEESSPrecio"])
    df["FechaDescarga"] = datetime.now().strftime("%d/%m/%Y")

    columnas = ["Rótulo","Horario","Dirección","Municipio","Provincia",
                "Precio Gasoleo A","Precio Gasolina 95 E5",
                "FechaDescarga","Latitud","Longitud (WGS84)"]
    df = df[[c for c in columnas if c in df.columns]]

    def _to_float(s): 
        return pd.to_numeric(
            s.astype(str).str.replace(",",".").str.replace("\xa0","").str.strip(),
            errors='coerce'
        )

    for c in ["Precio Gasoleo A","Precio Gasolina 95 E5","Latitud","Longitud (WGS84)"]:
        if c in df.columns: df[c] = _to_float(df[c])

    RUTA_BASE.mkdir(parents=True, exist_ok=True)
    ruta_excel   = RUTA_BASE / f"estaciones_carburantes_{fecha_archivo}.xlsx"
    ruta_geojson = RUTA_BASE / "estaciones.geojson"
    ruta_mbtiles = RUTA_BASE / "estaciones.mbtiles"
    ruta_stats   = RUTA_BASE / "stats.json"

    df.to_excel(ruta_excel, index=False)

    df_valid = df.dropna(subset=["Latitud","Longitud (WGS84)"]).copy()
    if df_valid.empty: return
    df_to_geojson(df_valid, ruta_geojson)

    tippecanoe_path = shutil.which("tippecanoe")
    cmd = [tippecanoe_path, "-o", str(ruta_mbtiles), "-r1", "-z12", "-Z3", "-l","estaciones", str(ruta_geojson), "--force"]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if res.returncode != 0:
        print(res.stderr); return

    g95 = df_valid["Precio Gasolina 95 E5"]
    di  = df_valid["Precio Gasoleo A"]
    stats = {
        "Precio Gasolina 95 E5": {
            "min": float(pd.to_numeric(g95, errors="coerce").dropna().min()) if not g95.empty else None,
            "max": float(pd.to_numeric(g95, errors="coerce").dropna().max()) if not g95.empty else None,
            "breaks": qbreaks(g95, 8)
        },
        "Precio Gasoleo A": {
            "min": float(pd.to_numeric(di, errors="coerce").dropna().min()) if not di.empty else None,
            "max": float(pd.to_numeric(di, errors="coerce").dropna().max()) if not di.empty else None,
            "breaks": qbreaks(di, 8)
        }
    }
    ruta_stats.write_text(json.dumps(stats, ensure_ascii=False), encoding="utf-8")
    print("OK: MBTiles y stats.json generados.")

if __name__ == "__main__":
    main()
