"""Revisa data/parquet/estado.json y falla si hay algo que atender.

Corre como último paso del workflow: si falla, GitHub te manda un mail
avisando que la corrida no salió bien. Motivos:
- algún servicio no se pudo actualizar;
- al token le quedan menos de DIAS_AVISO días.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

DIAS_AVISO = 15
ESTADO = Path(__file__).resolve().parent.parent / "data" / "parquet" / "estado.json"

estado = json.loads(ESTADO.read_text(encoding="utf-8"))
problemas = []

for s in estado["servicios"]:
    if not s.get("ok"):
        problemas.append(f"{s['tabla']}: {s.get('error')}")

dias = estado.get("token_dias_restantes")
if dias is not None and dias < DIAS_AVISO:
    problemas.append(
        f"el token vence el {estado['token_vence']} (quedan {dias} días): "
        "generá uno nuevo en api.indec.gob.ar y actualizá el secreto INDEC_API_TOKEN"
    )

if problemas:
    for p in problemas:
        print(f"::error::{p}")
    sys.exit(1)

print(f"Todo OK: {estado['servicios_ok']} de {estado['servicios_total']} servicios actualizados.")
