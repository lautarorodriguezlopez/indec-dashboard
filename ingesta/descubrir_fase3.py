"""Exploración de solo lectura para la fase 3 (segunda pasada). Se borra al cerrar la fase."""
from __future__ import annotations
import json, time, urllib.parse, urllib.request

UA = {"User-Agent": "indec-dashboard/1.0 (+https://github.com/lautarorodriguezlopez/indec-dashboard)"}

def get(url, timeout=60):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return json.loads(r.read())

def bloque(n, fn):
    print(f"\n===== {n} =====", flush=True)
    t = time.time()
    try: fn()
    except Exception as e: print("ERROR:", type(e).__name__, str(e)[:300])
    print(f"({time.time()-t:.1f}s)")

def bcra_hist():
    d = get("https://api.bcra.gob.ar/estadisticas/v4.0/monetarias/5?desde=2018-01-01&hasta=2026-11-15&limit=3000")
    r = d["results"][0]["detalle"]
    print("meta:", d.get("metadata"), "filas:", len(r), "primera:", r[-1], "ultima:", r[0])

def series():
    ids = ["172.3_TL_RECAION_M_0_0_17", "172.3_TL_RECA_IA_M_0_0_24", "452.3_RESULTADO_RIO_0_M_18_54",
           "151.1_TL_SIN_TAC_2012_M_15", "151.1_AARIADODAD_2012_M_31", "151.1_IPENDIEDAD_2012_M_41",
           "151.1_AARIADOTAC_2012_M_25", "158.1_REPTE_0_0_5", "57.1_SMVMM_0_M_34", "58.1_MP_0_M_13"]
    d = get("https://apis.datos.gob.ar/series/api/series/?" + urllib.parse.urlencode(
        {"ids": ",".join(ids), "limit": 3, "sort": "desc", "format": "json", "metadata": "simple"}))
    for f in d["meta"][1:]:
        print(json.dumps({k: f["field"].get(k) for k in ("id", "description", "units", "time_index_start", "time_index_end")}, ensure_ascii=False))
    for fila in d["data"]: print(fila)

def comb(url):
    def f():
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=240) as r:
            print("status", r.status, "len", r.headers.get("Content-Length"), "type", r.headers.get("Content-Type"))
            b = r.read(4000)
            print(b.decode("utf-8", "replace"))
    return f

bloque("BCRA historia id 5", bcra_hist)
bloque("Series nuevas datos.gob.ar", series)
base = "datos.energia.gob.ar/dataset/1c181390-5045-475e-94dc-410429be4b17/resource/80ac25de-a44a-4445-9215-090cf55cfda5/download/precios-en-surtidor-resolucin-3142016.csv"
bloque("Combustibles https", comb("https://" + base))
bloque("Combustibles http", comb("http://" + base))
bloque("Georef provincias", lambda: print(json.dumps(get("https://apis.datos.gob.ar/georef/api/provincias?campos=id,nombre&max=30"), ensure_ascii=False)[:2500]))
