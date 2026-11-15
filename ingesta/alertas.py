"""Revisa el estado de la ingesta y falla si hay algo que atender.

Corre como último paso del workflow: si falla, GitHub te manda un mail
avisando que la corrida no salió bien. Motivos:
- algún servicio del Catálogo API-INDEC no se pudo actualizar;
- alguna serie de datos.gob.ar no respondió;
- al token le quedan menos de DIAS_AVISO días;
- (solo los lunes, para no mandar un mail por día) hay series atrasadas.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

DIAS_AVISO = 15
DIR = Path(__file__).resolve().parent.parent / "data" / "parquet"

estado = json.loads((DIR / "estado.json").read_text(encoding="utf-8"))
problemas, avisos = [], []

for s in estado["servicios"]:
    if not s.get("ok"):
        problemas.append(f"{s['tabla']}: {s.get('error')}")

dias = estado.get("token_dias_restantes")
if dias is not None and dias < DIAS_AVISO:
    problemas.append(
        f"el token vence el {estado['token_vence']} (quedan {dias} días): "
        "generá uno nuevo en api.indec.gob.ar y actualizá el secreto INDEC_API_TOKEN"
    )

archivo_series = DIR / "estado_series.json"
if archivo_series.exists():
    es = json.loads(archivo_series.read_text(encoding="utf-8"))
    for s in es["series"]:
        if not s.get("ok"):
            problemas.append(f"serie {s['clave']} ({s['id']}): {s.get('error')}")
        elif s.get("atrasada"):
            avisos.append(f"serie {s['clave']} atrasada: último dato {s.get('ultimo')} ({s.get('dias')} días)")
else:
    problemas.append("no se generó estado_series.json (falló la ingesta de datos.gob.ar)")

for a in avisos:
    print(f"::warning::{a}")
if avisos and date.today().weekday() == 0:  # lunes: resumen semanal por mail
    problemas.append(f"{len(avisos)} serie(s) de datos.gob.ar atrasadas (ver avisos)")

if problemas:
    for p in problemas:
        print(f"::error::{p}")
    sys.exit(1)

print(f"Todo OK: {estado['servicios_ok']} de {estado['servicios_total']} servicios y todas las series al día.")
