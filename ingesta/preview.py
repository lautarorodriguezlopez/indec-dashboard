"""Arma salida/preview.json con las series clave a partir de data/indec.duckdb.

Se corre después de prueba_ingesta.py. Solo lee la base local, no consulta la API.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

RAIZ = Path(__file__).resolve().parent.parent
con = duckdb.connect(str(RAIZ / "data" / "indec.duckdb"), read_only=True)


def filas(sql: str) -> list[dict]:
    cur = con.execute(sql)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def distintos(tabla: str, columnas: list[str]) -> dict:
    return {
        c: [r[0] for r in con.execute(f"SELECT DISTINCT {c} FROM {tabla} ORDER BY 1").fetchall()][:60]
        for c in columnas
    }


ult_ipc = con.execute("SELECT max(periodo) FROM ipc").fetchone()[0]
ult_sal = con.execute("SELECT max(periodo) FROM salarios").fetchone()[0]

preview = {
    "valores": {
        "ipc": distintos("ipc", ["clasificador", "nivel", "tipo_de_indicador", "region", "indicador"]),
        "emae": distintos("emae", ["tipo_de_indicador_descripcion", "tipo_de_indicador"]),
        "salarios": distintos("salarios", ["clasificador", "nivel", "descripcion", "tipo_de_indicador"]),
    },
    # IPC nivel general, región Nacional, todos los tipos de indicador por mes
    "ipc_nivel_general": filas(
        """
        SELECT periodo, tipo_de_indicador, valor FROM ipc
        WHERE region = 'Nacional' AND lower(descripcion) = 'nivel general'
        ORDER BY periodo, tipo_de_indicador
        """
    ),
    # IPC del último mes, región Nacional, todas las aperturas
    "ipc_ultimo_mes": filas(
        f"""
        SELECT clasificador, nivel, codigo, descripcion, tipo_de_indicador, valor FROM ipc
        WHERE region = 'Nacional' AND periodo = '{ult_ipc}'
        ORDER BY clasificador, codigo, tipo_de_indicador
        """
    ),
    "emae": filas(
        "SELECT periodo, tipo_de_indicador_descripcion AS serie, valor FROM emae ORDER BY periodo, serie"
    ),
    "salarios_nivel_general": filas(
        """
        SELECT periodo, tipo_de_indicador, valor FROM salarios
        WHERE lower(descripcion) = 'nivel general'
        ORDER BY periodo, tipo_de_indicador
        """
    ),
    "salarios_ultimo_mes": filas(
        f"""
        SELECT codigo, descripcion, tipo_de_indicador, valor FROM salarios
        WHERE periodo = '{ult_sal}' ORDER BY codigo, tipo_de_indicador
        """
    ),
}

salida = RAIZ / "salida" / "preview.json"
salida.write_text(json.dumps(preview, ensure_ascii=False, default=str), encoding="utf-8")
print(f"preview.json: {salida.stat().st_size:,} bytes")
