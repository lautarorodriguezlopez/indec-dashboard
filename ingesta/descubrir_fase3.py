"""Exploración de solo lectura para la fase 3 (nuevas fuentes oficiales).
No escribe datos: imprime qué hay disponible en cada fuente. Se borra al terminar la fase."""

from __future__ import annotations

import json
import ssl
import urllib.parse
import urllib.request

UA = {"User-Agent": "indec-dashboard/1.0 (+https://github.com/lautarorodriguezlopez/indec-dashboard)",
      "Accept": "application/json"}


def get(url: str, raw: bool = False, rango: str | None = None):
    h = dict(UA)
    if rango:
        h["Range"] = rango
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=60) as r:
        b = r.read()
        return (b, dict(r.headers)) if raw else json.loads(b)


def bloque(nombre, fn):
    print(f"\n===== {nombre} =====", flush=True)
    try:
        fn()
    except ssl.SSLError as e:
        print("SSL ERROR:", e)
    except Exception as e:  # noqa: BLE001
        print("ERROR:", type(e).__name__, str(e)[:300])


def bcra_monetarias():
    d = get("https://api.bcra.gob.ar/estadisticas/v4.0/monetarias?limit=3000")
    res = d.get("results", d)
    print("total:", len(res))
    for v in res:
        print(json.dumps({k: v.get(k) for k in ("idVariable", "descripcion", "categoria", "periodicidad", "unidadExpresion",
                                                 "moneda", "primerFechaInformada", "ultFechaInformada", "ultValorInformado")},
                         ensure_ascii=False))


def bcra_detalle():
    d = get("https://api.bcra.gob.ar/estadisticas/v4.0/monetarias/1?desde=2026-10-20&hasta=2026-11-14&limit=50")
    print(json.dumps(d, ensure_ascii=False)[:1500])


def bcra_usd():
    d = get("https://api.bcra.gob.ar/estadisticascambiarias/v1.0/Cotizaciones/USD?fechadesde=2026-11-01&fechahasta=2026-11-14")
    print(json.dumps(d, ensure_ascii=False)[:1500])


def buscar(q):
    def f():
        d = get("https://apis.datos.gob.ar/series/api/search/?" + urllib.parse.urlencode({"q": q, "limit": 12}))
        for it in d.get("data", []):
            fl, ds = it.get("field", {}), it.get("dataset", {})
            print(json.dumps({"id": fl.get("id"), "titulo": fl.get("title"), "desc": (fl.get("description") or "")[:120],
                              "frec": fl.get("frequency"), "unidad": fl.get("units"), "desde": fl.get("time_index_start"),
                              "hasta": fl.get("time_index_end"), "dataset": ds.get("title"),
                              "org": (ds.get("publisher") or {}).get("name")}, ensure_ascii=False))
    return f


def combustibles():
    d = get("https://datos.gob.ar/api/3/action/package_search?" + urllib.parse.urlencode({"q": "precios surtidor", "rows": 6}))
    for p in d["result"]["results"]:
        print("PAQUETE:", p["name"], "|", p["title"])
        for r in p.get("resources", []):
            print("   ", json.dumps({k: r.get(k) for k in ("name", "format", "url", "size", "last_modified")}, ensure_ascii=False))


def combustibles_head():
    d = get("https://datos.gob.ar/api/3/action/package_search?" + urllib.parse.urlencode({"q": "precios surtidor", "rows": 6}))
    for p in d["result"]["results"]:
        for r in p.get("resources", []):
            if (r.get("format") or "").lower() == "csv":
                try:
                    b, h = get(r["url"], raw=True, rango="bytes=0-3000")
                    print("URL:", r["url"], "| content-length:", h.get("Content-Length"), "| content-range:", h.get("Content-Range"))
                    print(b.decode("utf-8", "replace")[:1500])
                except Exception as e:  # noqa: BLE001
                    print("URL:", r["url"], "ERROR", e)


bloque("BCRA monetarias v4 (lista)", bcra_monetarias)
bloque("BCRA monetarias v4 (detalle id 1)", bcra_detalle)
bloque("BCRA cambiarias USD", bcra_usd)
for q in ("recaudacion tributaria", "resultado primario", "resultado financiero sector publico", "empleo registrado",
          "trabajadores registrados SIPA", "RIPTE", "salario minimo vital y movil", "deuda publica bruta",
          "gasto publico", "jubilacion minima", "tipo de cambio", "reservas internacionales", "tasa badlar"):
    bloque(f"datos.gob.ar: {q}", buscar(q))
bloque("Combustibles: paquetes CKAN", combustibles)
bloque("Combustibles: cabecera de los CSV", combustibles_head)
