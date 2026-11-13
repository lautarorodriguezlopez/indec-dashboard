"""Prueba de ingesta del Catálogo API-INDEC (T-003).

Baja IPC, EMAE e índice de salarios desde 2023, los guarda en una base
DuckDB local y escribe un resumen para revisar qué columnas y valores
devuelve cada dataset.

Uso:
    python ingesta/prueba_ingesta.py

El token se lee de la variable de entorno INDEC_API_TOKEN (en tu compu,
desde el archivo .env; en GitHub Actions, desde el secreto). El script
nunca lo imprime.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd
from pyindec import F, IndecAuthError, IndecClient, IndecRateLimitError

RAIZ = Path(__file__).resolve().parent.parent
DIR_DATOS = RAIZ / "data"
DIR_SALIDA = RAIZ / "salida"
BASE = DIR_DATOS / "indec.duckdb"
DESDE_ANIO = 2023

# tabla en DuckDB -> endpoint de la API
DATASETS = {
    "ipc": "ipc_nacional",
    "emae": "estimador-mensual-de-actividad-economica-nivel-general",
    "salarios": "indice_salarios",
}

# columnas categóricas cuyos valores distintos conviene conocer
MAX_VALORES = 25


def bajar(cliente: IndecClient, endpoint: str) -> pd.DataFrame:
    """Baja todas las filas desde DESDE_ANIO, con reintento ante 429."""
    for intento in range(4):
        try:
            return cliente.get(endpoint, anio=F.gte(DESDE_ANIO), fetch_all=True)
        except IndecRateLimitError:
            espera = 15 * (intento + 1)
            print(f"  límite de consultas (429), espero {espera}s…")
            time.sleep(espera)
    raise RuntimeError(f"{endpoint}: se agotaron los reintentos por límite de consultas")


def perfil(nombre: str, endpoint: str, df: pd.DataFrame) -> dict:
    """Resumen de un dataset: filas, columnas, valores y último período."""
    categoricas = {}
    for col in df.columns:
        if df[col].dtype == object and col not in ("valor", "observaciones"):
            valores = sorted(df[col].dropna().astype(str).unique().tolist())
            categoricas[col] = {
                "cantidad": len(valores),
                "valores": valores[:MAX_VALORES],
            }
    ultimo = None
    if {"anio", "mes"}.issubset(df.columns) and len(df):
        fila = df.sort_values(["anio", "mes"]).iloc[-1]
        ultimo = f"{int(fila['anio'])}-{int(fila['mes']):02d}"
    return {
        "tabla": nombre,
        "endpoint": endpoint,
        "filas": int(len(df)),
        "columnas": list(df.columns),
        "ultimo_periodo": ultimo,
        "categoricas": categoricas,
    }


def main() -> int:
    if not os.environ.get("INDEC_API_TOKEN"):
        if not (RAIZ / ".env").exists():
            print(
                "ERROR: no hay token. Falta la variable INDEC_API_TOKEN "
                "(en GitHub: secreto del repo en Settings → Secrets and variables → Actions → Secrets; "
                "en tu compu: archivo .env)."
            )
            return 1
        print("Aviso: INDEC_API_TOKEN no está en el entorno, se busca en .env")

    DIR_DATOS.mkdir(exist_ok=True)
    DIR_SALIDA.mkdir(exist_ok=True)

    cliente = IndecClient()
    con = duckdb.connect(str(BASE))
    resumen = {
        "generado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "desde_anio": DESDE_ANIO,
        "datasets": [],
    }

    try:
        for nombre, endpoint in DATASETS.items():
            print(f"→ {nombre} ({endpoint})")
            t0 = time.time()
            df = bajar(cliente, endpoint)
            print(f"  {len(df):,} filas en {time.time() - t0:.1f}s")

            con.register("df_tmp", df)
            con.execute(f"CREATE OR REPLACE TABLE {nombre} AS SELECT * FROM df_tmp")
            con.unregister("df_tmp")
            df.to_csv(DIR_SALIDA / f"{nombre}.csv", index=False)

            resumen["datasets"].append(perfil(nombre, endpoint, df))
    except IndecAuthError:
        print("ERROR 401: el token es inválido o venció. Generá uno nuevo en api.indec.gob.ar.")
        return 1
    finally:
        con.close()

    (DIR_SALIDA / "resumen.json").write_text(
        json.dumps(resumen, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lineas = ["# Prueba de ingesta INDEC", "", f"Generado: {resumen['generado']} (desde {DESDE_ANIO})", ""]
    lineas += ["| Tabla | Filas | Último período |", "|---|---|---|"]
    for d in resumen["datasets"]:
        lineas.append(f"| {d['tabla']} | {d['filas']:,} | {d['ultimo_periodo']} |")
    md = "\n".join(lineas) + "\n"
    (DIR_SALIDA / "resumen.md").write_text(md, encoding="utf-8")

    resumen_gh = os.environ.get("GITHUB_STEP_SUMMARY")
    if resumen_gh:
        with open(resumen_gh, "a", encoding="utf-8") as f:
            f.write(md)

    print()
    print(md)
    print(f"Base: {BASE.relative_to(RAIZ)} · Resumen: salida/resumen.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
