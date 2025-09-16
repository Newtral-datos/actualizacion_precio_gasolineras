import ssl, certifi, requests, pandas as pd, subprocess, shutil, time, os, json
from pathlib import Path
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

MAPBOX_ACCESS_TOKEN = os.getenv("MAPBOX_ACCESS_TOKEN", "")
TILESET_ID = os.getenv("MAPBOX_TILESET_ID", "")
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

def upload_mbtiles_to_mapbox(ruta_mbtiles: Path, tileset_id: str, access_token: str) -> bool:
    from mapbox import Uploader
    if not ruta_mbtiles.exists() or "." not in tileset_id or not access_token.startswith("sk."): return False
    username = tileset_id.split(".")[0]; uploader = Uploader(access_token=access_token)
    with open(ruta_mbtiles, "rb") as src: resp = uploader.upload(src, tileset=tileset_id, name="precios_gasolineras")
    if resp.status_code != 201: return False
    upload_id = resp.json().get("id"); status_url = f"https://api.mapbox.com/uploads/v1/{username}/{upload_id}?access_token={access_token}"
    for _ in range(240):
        st = requests.get(status_url, timeout=20); info = st.json()
        if info.get("error"): return False
        if info.get("complete"): return True
        time.sleep(5)
    return False

def df_to_geojson(df: pd.DataFrame, ruta_geojson: Path) -> None:
    feats=[]
    for _, r in df.iterrows():
        lon=r.get("Longitud (WGS84)"); lat=r.get("Latitud")
        if pd.notnull(lon) and pd.notnull(lat):
            props={k:(None if pd.isna(v) else v) for k,v in r.to_dict().items() if k not in ["Latitud","Longitud (WGS84)"]}
            feats.append({"type":"Feature","geometry":{"type":"Point","coordinates":[float(lon), float(lat)]},"properties":props})
    ruta_geojson.write_text(json.dumps({"type":"FeatureCollection","features":feats}, ensure_ascii=False), encoding="utf-8")

def main():
    fecha_archivo = datetime.now().strftime("%d_%m_%Y"); fecha_descarga = datetime.now().strftime("%d/%m/%Y")
    s = make_session(); resp = s.get(URL, timeout=30); data = resp.json()
    if "ListaEESSPrecio" not in data: return
    df = pd.DataFrame(data["ListaEESSPrecio"]); df["FechaDescarga"] = fecha_descarga
    columnas = ["Rótulo","Horario","Dirección","Municipio","Provincia","Precio Gasoleo A","Precio Gasolina 95 E5","FechaDescarga","Latitud","Longitud (WGS84)"]
    df = df[[c for c in columnas if c in df.columns]]
    def _to_float(s): return pd.to_numeric(s.astype(str).str.replace(",",".").str.replace("\xa0","").str.strip(), errors='coerce')
    for c in ["Precio Gasoleo A","Precio Gasolina 95 E5","Latitud","Longitud (WGS84)"]:
        if c in df.columns: df[c] = _to_float(df[c])

    RUTA_BASE.mkdir(parents=True, exist_ok=True)
    ruta_excel = RUTA_BASE / f"estaciones_carburantes_{fecha_archivo}.xlsx"
    ruta_geojson = RUTA_BASE / "estaciones.geojson"
    ruta_mbtiles = RUTA_BASE / "estaciones.mbtiles"

    df.to_excel(ruta_excel, index=False)
    df_valid = df.dropna(subset=["Latitud","Longitud (WGS84)"]).copy()
    if df_valid.empty: return
    df_to_geojson(df_valid, ruta_geojson)

    tippecanoe_path = shutil.which("tippecanoe")
    cmd = [tippecanoe_path, "-o", str(ruta_mbtiles), "-r1", "-z12", "-Z3", "-l","estaciones", str(ruta_geojson), "--force"]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if res.returncode != 0: print(res.stderr); return

    ok = upload_mbtiles_to_mapbox(ruta_mbtiles, TILESET_ID, MAPBOX_ACCESS_TOKEN)
    print("OK" if ok else "FAIL")

if __name__ == "__main__":
    main()
