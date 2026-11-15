"""Ingesta de variables del BCRA (API pública de Estadísticas Monetarias v4,
sin token y sin costo).

- Catálogo: ingesta/bcra.json (lista blanca de idVariable).
- Baja la historia desde 2018 en una sola consulta por variable.
- Tolerante a fallos: si una variable no responde, conserva sus datos anteriores.
- Nunca corta la corrida: los problemas quedan en estado_bcra.json.

Salida: data/parquet/bcra.parquet y data/parquet/estado_bcra.json
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
DIR = RAIZ / "data" / "parquet"
ARCHIVO = DIR / "bcra.parquet"
ESTADO = DIR / "estado_bcra.json"
API = "https://api.bcra.gob.ar/estadisticas/v4.0/monetarias/"
HEADERS = {
    "User-Agent": "indec-dashboard/1.0 (+https://github.com/lautarorodriguezlopez/indec-dashboard)",
    "Accept": "application/json",
}
DESDE = "2018-01-01"
HOY = date.today()
# Días sin dato nuevo antes de marcar la variable como atrasada
MAX_DIAS = {"D": 10, "M": 70}


def bajar(vid: int) -> list[dict]:
    q = urllib.parse.urlencode({"desde": DESDE, "hasta": HOY.isoformat(), "limit": 3000})
    error = None
    for intento in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(f"{API}{vid}?{q}", headers=HEADERS), timeout=40) as r:
                res = json.load(r).get("results") or []
            filas = res[0].get("detalle", []) if res else []
            if not filas:
                raise RuntimeError("la API devolvió 0 filas")
            return filas
        except Exception as e:  # noqa: BLE001
            error = e
            time.sleep(4 * (intento + 1))
    raise RuntimeError(f"{type(error).__name__}: {error}")


def main() -> int:
    DIR.mkdir(parents=True, exist_ok=True)
    catalogo = json.loads((RAIZ / "ingesta" / "bcra.json").read_text(encoding="utf-8"))["variables"]
    previo = pd.read_parquet(ARCHIVO) if ARCHIVO.exists() else pd.DataFrame()
    partes, estado = [], []
    for v in catalogo:
        reg = {k: v[k] for k in ("clave", "id", "grupo", "nombre", "unidad", "frecuencia")}
        try:
            df = pd.DataFrame(bajar(v["id"]))[["fecha", "valor"]]
            df["fecha"] = pd.to_datetime(df["fecha"]).dt.date
            df = df.dropna(subset=["valor"])
            reg.update(ok=True, error=None)
        except Exception as e:  # noqa: BLE001
            reg.update(ok=False, error=" ".join(str(e).split())[:200])
            df = previo[previo["clave"] == v["clave"]][["fecha", "valor"]] if len(previo) else pd.DataFrame(columns=["fecha", "valor"])
        if len(df):
            for k in ("clave", "id", "grupo", "nombre", "unidad", "frecuencia"):
                df[k] = v[k]
            partes.append(df)
            ultimo = min(max(df["fecha"]), HOY)
            dias = (HOY - ultimo).days
            reg.update(ultimo=ultimo.isoformat(), filas=int(len(df)), dias=dias,
                       atrasada=dias > MAX_DIAS.get(v["frecuencia"], 10))
        else:
            reg.update(ultimo=None, filas=0, dias=None, atrasada=True)
        estado.append(reg)
        print(f"{'OK' if reg['ok'] else 'FALLÓ':5} {v['clave']:<22} último {reg.get('ultimo')}"
              f"{'  (ATRASADA)' if reg.get('atrasada') else ''}", flush=True)
        time.sleep(0.3)

    if partes:
        todo = pd.concat(partes, ignore_index=True)
        todo["fecha"] = pd.to_datetime(todo["fecha"])
        todo["id"] = todo["id"].astype("int32")
        todo.sort_values(["clave", "fecha"]).to_parquet(ARCHIVO, index=False)

    ESTADO.write_text(json.dumps({
        "generado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fuente": "API de Estadísticas Monetarias v4 del BCRA",
        "series_ok": sum(1 for r in estado if r["ok"]),
        "series_total": len(estado),
        "atrasadas": sum(1 for r in estado if r["atrasada"]),
        "series": estado,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nVariables OK: {sum(r['ok'] for r in estado)} de {len(estado)} · atrasadas: {sum(r['atrasada'] for r in estado)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:  # noqa: BLE001  # nunca cortar la corrida principal
        print(f"bcra.py falló sin cortar la corrida: {type(e).__name__}: {e}")
        raise SystemExit(0)
