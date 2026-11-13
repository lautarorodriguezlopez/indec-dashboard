"""Imprime la estructura de cada tabla de data/parquet: columnas, rango de
períodos y valores distintos de las columnas de texto. Sirve para diseñar
los tableros sin tener que bajar los datos."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

DIR = Path(__file__).resolve().parent.parent / "data" / "parquet"
MAX = 45
salida = {}
for f in sorted(DIR.glob("*.parquet")):
    df = pd.read_parquet(f)
    info = {"filas": len(df), "columnas": {}}
    for c in df.columns:
        s = df[c]
        if pd.api.types.is_numeric_dtype(s):
            info["columnas"][c] = {"min": None if s.dropna().empty else float(s.min()),
                                   "max": None if s.dropna().empty else float(s.max())}
        else:
            v = s.dropna().astype(str).unique().tolist()
            info["columnas"][c] = {"n": len(v), "valores": sorted(v)[:MAX]}
    salida[f.stem] = info
print(json.dumps(salida, ensure_ascii=False))
