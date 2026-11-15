"""Ingesta de series del INDEC publicadas en la API de Series de Tiempo de
datos.gob.ar (sin token). Complementa a ingestar.py con datos que no están en
el Catálogo API-INDEC (consumo, construcción, industria, turismo, macro).

- Catálogo de series: ingesta/series.json (lista blanca de IDs).
- Tolerante a fallos: si una serie no responde, conserva sus datos anteriores.
- Control de frescura: marca como "atrasada" la serie cuyo último dato es más
  viejo de lo esperable para su frecuencia.
- Nunca corta la corrida: los problemas quedan en estado_series.json y los
  revisa ingesta/alertas.py.

Salida: data/parquet/series_extra.parquet y data/parquet/estado_series.json
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
ARCHIVO = DIR / "series_extra.parquet"
ESTADO = DIR / "estado_series.json"
API = "https://apis.datos.gob.ar/series/api/series/"
HEADERS = {
    "User-Agent": "indec-dashboard/1.0 (+https://github.com/lautarorodriguezlopez/indec-dashboard)",
    "Accept": "application/json",
}
# Días máximos entre el inicio del último período y hoy antes de marcarla atrasada
MAX_DIAS = {"M": 135, "T": 280}
HOY = date.today()


def bajar(sid: str) -> list[list]:
    url = API + "?" + urllib.parse.urlencode({"ids": sid, "format": "json", "limit": 5000, "metadata": "none"})
    error = None
    for intento in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=40) as r:
                datos = json.load(r).get("data", [])
            if not datos:
                raise RuntimeError("la API devolvió 0 filas")
            return datos
        except Exception as e:  # noqa: BLE001
            error = e
            time.sleep(4 * (intento + 1))
    raise RuntimeError(f"{type(error).__name__}: {error}")


def main() -> int:
    DIR.mkdir(parents=True, exist_ok=True)
    catalogo = json.loads((RAIZ / "ingesta" / "series.json").read_text(encoding="utf-8"))["series"]
    previo = pd.read_parquet(ARCHIVO) if ARCHIVO.exists() else pd.DataFrame()
    partes, estado = [], []

    for s in catalogo:
        reg = {k: s[k] for k in ("clave", "id", "grupo", "nombre", "unidad", "frecuencia")}
        if s.get("fuente"):
            reg["fuente"] = s["fuente"]
        try:
            filas = bajar(s["id"])
            df = pd.DataFrame(filas, columns=["fecha", "valor"])
            df["fecha"] = pd.to_datetime(df["fecha"]).dt.date
            df = df.dropna(subset=["valor"])
            reg.update(ok=True, error=None)
        except Exception as e:  # noqa: BLE001
            reg.update(ok=False, error=" ".join(str(e).split())[:200])
            df = previo[previo["clave"] == s["clave"]][["fecha", "valor"]] if len(previo) else pd.DataFrame(columns=["fecha", "valor"])
        if len(df):
            for k in ("clave", "id", "grupo", "nombre", "unidad", "frecuencia"):
                df[k] = s[k]
            partes.append(df)
            ultimo = min(max(df["fecha"]), HOY)  # el SMVM publica montos ya fijados para meses futuros
            dias = (HOY - ultimo).days
            reg.update(ultimo=ultimo.isoformat(), filas=int(len(df)), dias=dias,
                       atrasada=dias > s.get("max_dias", MAX_DIAS.get(s["frecuencia"], 135)))
        else:
            reg.update(ultimo=None, filas=0, dias=None, atrasada=True)
        estado.append(reg)
        marca = "OK" if reg["ok"] else "FALLÓ"
        print(f"{marca:5} {s['clave']:<18} último {reg.get('ultimo')}{'  (ATRASADA)' if reg.get('atrasada') else ''}", flush=True)
        time.sleep(0.3)

    if partes:
        todo = pd.concat(partes, ignore_index=True)
        todo["fecha"] = pd.to_datetime(todo["fecha"])
        todo["anio"] = todo["fecha"].dt.year.astype("int32")
        todo["mes"] = todo["fecha"].dt.month.astype("int32")
        todo.to_parquet(ARCHIVO, index=False)

    ESTADO.write_text(json.dumps({
        "generado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fuente": "API de Series de Tiempo de datos.gob.ar (datos del INDEC)",
        "series_ok": sum(1 for r in estado if r["ok"]),
        "series_total": len(estado),
        "atrasadas": sum(1 for r in estado if r["atrasada"]),
        "series": estado,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nSeries OK: {sum(r['ok'] for r in estado)} de {len(estado)} · atrasadas: {sum(r['atrasada'] for r in estado)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:  # noqa: BLE001  # nunca cortar la corrida principal
        print(f"ERROR inesperado en series_tiempo: {e}")
        raise SystemExit(0)
