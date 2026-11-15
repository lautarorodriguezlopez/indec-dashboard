"""Valida una lista de IDs de la API de Series de Tiempo: título, unidad,
frecuencia, rango y últimos valores. Uso: python ingesta/validar_series.py ID [ID ...]"""

from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request

API = "https://apis.datos.gob.ar/series/api/series/"
HEADERS = {"User-Agent": "indec-dashboard/1.0 (+https://github.com/lautarorodriguezlopez/indec-dashboard)",
           "Accept": "application/json"}

out = []
for sid in sys.argv[1:]:
    url = API + "?" + urllib.parse.urlencode({"ids": sid, "metadata": "full", "last": 3, "format": "json"})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=30) as r:
            j = json.load(r)
        m = j["meta"][1]["field"]
        d = j["meta"][1].get("dataset", {})
        out.append({"id": sid, "ok": True, "titulo": m.get("description"), "unidad": m.get("units"),
                    "frecuencia": m.get("frequency") or j["meta"][0].get("frequency"),
                    "desde": m.get("time_index_start"), "hasta": m.get("time_index_end"),
                    "dataset": d.get("title"), "ultimos": j["data"]})
    except Exception as e:  # noqa: BLE001
        out.append({"id": sid, "ok": False, "error": str(e)[:120]})
    time.sleep(0.3)
print(json.dumps(out, ensure_ascii=False))
