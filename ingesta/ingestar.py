"""Ingesta de los 19 servicios del Catálogo API-INDEC (T-004).

- Incremental: si ya hay datos de una corrida anterior, vuelve a bajar solo
  desde el año anterior al último disponible (así toma datos nuevos y las
  revisiones recientes) y conserva el resto.
- Pasada completa: la primera vez, con --completa, o el primer lunes de cada
  mes (lo decide el workflow).
- Tolerante a fallos: si un servicio falla, se conserva su versión anterior,
  se marca en estado.json y los demás siguen.

Los datos quedan en data/parquet/<tabla>.parquet y el estado en
data/parquet/estado.json. El token se lee de INDEC_API_TOKEN y nunca se imprime.

Uso:
    python ingesta/ingestar.py              # incremental
    python ingesta/ingestar.py --completa   # baja todo de nuevo
    python ingesta/ingestar.py --solo ipc emae
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from pyindec import ENDPOINTS, F, IndecAuthError, IndecClient, IndecRateLimitError

RAIZ = Path(__file__).resolve().parent.parent
DIR = RAIZ / "data" / "parquet"
ESTADO = DIR / "estado.json"

# tabla -> endpoint oficial
SERVICIOS = {
    "ipc": "ipc_nacional",
    "canastas": "valorizacion_canastas_cba_cbt",
    "canasta_crianza": "canasta-crianza",
    "salarios": "indice_salarios",
    "icc": "icc_precios_construccion",
    "obras_publicas": "redeterminacion_precios_contratos_obras_publicas",
    "sipm": "sipm_precios_mayoristas",
    "emae": "estimador-mensual-de-actividad-economica-nivel-general",
    "emae_sectores": "estimador-mensual-de-actividad-economica-sectores",
    "ipi_manufacturero": "ipi_manufacturero",
    "ipi_minero": "ipi_minero",
    "pobreza": "pobreza_eph",
    "mercado_trabajo": "mercado_trabajo_eph",
    "exportaciones": "comercio_exterior_exportacion_bienes",
    "importaciones": "comercio_exterior_importacion_bienes",
    "comex_nomenclaturas": "comercio_exterior_nomenclaturas",
    "poblacion_nacional": "proyecciones_poblacion_nacional_2022_2040",
    "poblacion_jurisdiccion": "proyecciones_poblacion_jurisdiccion_2022_2040",
    "poblacion_departamento": "estimaciones_poblacion_departamento_2022_2035",
}

AHORA = datetime.now(timezone.utc)


def ahora_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def tiene_anio(endpoint: str) -> bool:
    return any(c.lower() == "anio" for c in ENDPOINTS[endpoint].column_names)


def bajar(cliente: IndecClient, endpoint: str, desde_anio: int | None) -> pd.DataFrame:
    filtros = {"anio": F.gte(desde_anio)} if desde_anio is not None else {}
    for intento in range(5):
        try:
            df = cliente.get(endpoint, fetch_all=True, **filtros)
            df.columns = [c.lower() for c in df.columns]
            return df
        except IndecRateLimitError:
            espera = 30 * (intento + 1)
            print(f"    429: límite de consultas, espero {espera}s", flush=True)
            time.sleep(espera)
    raise RuntimeError("se agotaron los reintentos por límite de consultas (429)")


def ultimo_periodo(df: pd.DataFrame) -> str | None:
    if df.empty:
        return None
    cols = set(df.columns)
    for sub in ("mes", "trimestre", "semestre"):
        if {"anio", sub}.issubset(cols):
            d = df.dropna(subset=["anio", sub])
            if d.empty:
                continue
            f = d.sort_values(["anio", sub]).iloc[-1]
            letra = {"mes": "", "trimestre": "T", "semestre": "S"}[sub]
            num = f"{int(f[sub]):02d}" if sub == "mes" else f"{letra}{int(f[sub])}"
            return f"{int(f['anio'])}-{num}"
    for c in ("periodo", "fecha"):
        if c in cols:
            return str(df[c].dropna().astype(str).max())
    return None


def token_vence() -> tuple[str | None, int | None]:
    """Lee la fecha de vencimiento del JWT sin validarlo ni mostrarlo."""
    tok = os.environ.get("INDEC_API_TOKEN", "")
    try:
        payload = tok.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        exp = json.loads(base64.urlsafe_b64decode(payload)).get("exp")
        if not exp:
            return None, None
        vence = datetime.fromtimestamp(int(exp), tz=timezone.utc)
        return vence.date().isoformat(), (vence - AHORA).days
    except Exception:
        return None, None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--completa", action="store_true", help="bajar todo de nuevo")
    ap.add_argument("--solo", nargs="*", help="tablas a procesar (por defecto, todas)")
    args = ap.parse_args()

    if not os.environ.get("INDEC_API_TOKEN") and not (RAIZ / ".env").exists():
        print("ERROR: no hay token (INDEC_API_TOKEN o archivo .env).")
        return 1

    DIR.mkdir(parents=True, exist_ok=True)
    previo = json.loads(ESTADO.read_text(encoding="utf-8")) if ESTADO.exists() else {}
    previo_ds = {d["tabla"]: d for d in previo.get("servicios", [])}

    cliente = IndecClient(max_retries=3, timeout=60)
    tablas = args.solo or list(SERVICIOS)
    resultados = []
    auth_error = False

    for tabla in SERVICIOS:
        endpoint = SERVICIOS[tabla]
        archivo = DIR / f"{tabla}.parquet"
        anterior = previo_ds.get(tabla, {})

        if tabla not in tablas:
            if anterior:
                resultados.append(anterior)
            continue

        reg = {
            "tabla": tabla,
            "endpoint": endpoint,
            "descripcion": ENDPOINTS[endpoint].summary,
            "ultima_ingesta_ok": anterior.get("ultima_ingesta_ok"),
        }
        t0 = time.time()
        try:
            if auth_error:
                raise IndecAuthError("token inválido o vencido (401)")

            viejo = pd.read_parquet(archivo) if archivo.exists() else None
            incremental = (
                not args.completa
                and viejo is not None
                and tiene_anio(endpoint)
                and "anio" in viejo.columns
                and len(viejo) > 0
            )
            if incremental:
                desde = int(viejo["anio"].max()) - 1
                print(f"→ {tabla}: incremental desde {desde}", flush=True)
                nuevo = bajar(cliente, endpoint, desde)
                df = pd.concat([viejo[viejo["anio"] < desde], nuevo], ignore_index=True)
                reg["modo"] = f"incremental desde {desde}"
            else:
                print(f"→ {tabla}: completa", flush=True)
                df = bajar(cliente, endpoint, None)
                reg["modo"] = "completa"

            if df.empty:
                raise RuntimeError("la API devolvió 0 filas")

            ult_prev = anterior.get("ultimo_periodo")
            ult = ultimo_periodo(df)
            df.to_parquet(archivo, index=False)

            reg.update(
                ok=True,
                error=None,
                filas=int(len(df)),
                filas_previas=anterior.get("filas"),
                ultimo_periodo=ult,
                dato_nuevo=bool(ult_prev and ult and ult != ult_prev),
                ultima_ingesta_ok=ahora_iso(),
                segundos=round(time.time() - t0, 1),
            )
            print(f"   {len(df):,} filas · último período {ult} · {reg['segundos']}s", flush=True)
        except IndecAuthError as ex:
            auth_error = True
            reg.update(ok=False, error=f"401: {ex}", filas=anterior.get("filas"),
                       ultimo_periodo=anterior.get("ultimo_periodo"), dato_nuevo=False)
            print(f"   ERROR {reg['error']}", flush=True)
        except Exception as ex:
            reg.update(ok=False, error=" ".join(f"{type(ex).__name__}: {ex}".split())[:300], filas=anterior.get("filas"),
                       ultimo_periodo=anterior.get("ultimo_periodo"), dato_nuevo=False)
            print(f"   ERROR {reg['error']}", flush=True)
            traceback.print_exc(limit=1)
        resultados.append(reg)

    vence, dias = token_vence()
    estado = {
        "generado": ahora_iso(),
        "modo": "completa" if args.completa else "incremental",
        "token_vence": vence,
        "token_dias_restantes": dias,
        "servicios_ok": sum(1 for r in resultados if r.get("ok")),
        "servicios_total": len(SERVICIOS),
        "servicios": resultados,
    }
    ESTADO.write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")

    # Resumen legible (también va al resumen de la corrida en GitHub)
    lineas = [
        f"## Ingesta INDEC · {estado['generado']} · {estado['modo']}",
        "",
        f"Servicios OK: **{estado['servicios_ok']} de {estado['servicios_total']}**"
        + (f" · Token vence el {vence} ({dias} días)" if vence else ""),
        "",
        "| Tabla | Estado | Filas | Último período | Dato nuevo |",
        "|---|---|---|---|---|",
    ]
    for r in resultados:
        est = "OK" if r.get("ok") else f"FALLÓ: {r.get('error')}"
        filas = f"{r['filas']:,}" if r.get("filas") is not None else "—"
        lineas.append(
            f"| {r['tabla']} | {est} | {filas} | {r.get('ultimo_periodo') or '—'} | {'sí' if r.get('dato_nuevo') else ''} |"
        )
    md = "\n".join(lineas) + "\n"
    print("\n" + md)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
