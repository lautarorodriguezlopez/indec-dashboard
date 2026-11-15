"""Auditoría de series de datos.gob.ar (API de Series de Tiempo, sin token).

Busca candidatas para los grupos nuevos del sitio (consumo, construcción,
turismo, macro trimestral y expectativas) y para cada una informa fuente,
frecuencia y fecha del último dato, para decidir cuáles están vivas.
Solo lee: no modifica nada.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request

API = "https://apis.datos.gob.ar/series/api"
HEADERS = {
    "User-Agent": "indec-dashboard/1.0 (+https://github.com/lautarorodriguezlopez/indec-dashboard)",
    "Accept": "application/json",
}
GRUPOS = {
    "consumo": ["supermercados ventas", "autoservicios mayoristas", "centros de compras ventas"],
    "construccion": ["ISAC construccion", "indicador sintetico actividad construccion", "permisos de edificacion", "insumos construccion"],
    "turismo": ["turismo internacional", "ocupacion hotelera", "pernoctes", "turistas no residentes", "turistas residentes egreso"],
    "macro": ["PIB precios constantes trimestral", "producto interno bruto desestacionalizado", "cuenta corriente balanza de pagos", "deuda externa bruta", "coeficiente de Gini", "distribucion del ingreso decil"],
    "expectativas": ["utilizacion capacidad instalada", "capacidad instalada industria", "tendencia de negocios", "expectativas industria"],
}


def get(url: str) -> dict:
    for intento in range(3):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            err = e
            time.sleep(3 * (intento + 1))
    raise err


salida = {}
for grupo, consultas in GRUPOS.items():
    vistos = {}
    for q in consultas:
        url = f"{API}/search/?" + urllib.parse.urlencode({"q": q, "limit": 25})
        try:
            res = get(url)
        except Exception as e:  # noqa: BLE001
            print(f"ERROR {q}: {e}", file=sys.stderr)
            continue
        for item in res.get("data", []):
            f, d = item.get("field", {}), item.get("dataset", {})
            sid = f.get("id")
            if not sid or sid in vistos:
                continue
            vistos[sid] = {
                "id": sid,
                "titulo": f.get("description") or f.get("title"),
                "unidad": f.get("units"),
                "frecuencia": f.get("frequency"),
                "desde": f.get("time_index_start"),
                "hasta": f.get("time_index_end"),
                "dataset": d.get("title"),
                "fuente": d.get("source"),
                "publicador": d.get("publisher", {}).get("name") if isinstance(d.get("publisher"), dict) else d.get("publisher"),
                "consulta": q,
            }
        time.sleep(0.5)
    salida[grupo] = list(vistos.values())
    print(f"{grupo}: {len(vistos)} candidatas", file=sys.stderr)

print(json.dumps(salida, ensure_ascii=False))
