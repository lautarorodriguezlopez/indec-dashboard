"""Ingesta de series del INDEC que solo se publican en planillas (xls/xlsx) del
sitio oficial: ocupación hotelera, permisos de edificación, confianza empresarial
(Encuesta de Tendencia de Negocios), balanza de pagos y deuda externa.

Seguridad (OWASP A08/A10, API10 "consumo inseguro de APIs"):
- Lista blanca fija de archivos: no sigue links ni rastrea páginas.
- Solo https://www.indec.gob.ar/ftp/cuadros/economia/ ; si una redirección
  saca del dominio, se descarta.
- Tope de tamaño (15 MB) y verificación de firma del archivo (xlsx = ZIP,
  xls = OLE2). Si el INDEC devuelve una página HTML en lugar de la planilla,
  se descarta.
- Las planillas se leen como datos (pandas). No se ejecutan macros ni fórmulas.
- Las filas se buscan por su etiqueta, no por número de fila; si el INDEC cambia
  la planilla y una etiqueta no aparece, esa serie falla sola y conserva sus
  datos anteriores.
- Nunca corta la corrida: los problemas quedan en estado_planillas.json y los
  revisa ingesta/alertas.py.

Salida: data/parquet/planillas.parquet y data/parquet/estado_planillas.json
(mismo esquema que series_extra.parquet).
"""

from __future__ import annotations

import io
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
DIR = RAIZ / "data" / "parquet"
ARCHIVO = DIR / "planillas.parquet"
ESTADO = DIR / "estado_planillas.json"
BASE = "https://www.indec.gob.ar/ftp/cuadros/economia/"
HEADERS = {"User-Agent": "indec-dashboard/1.0 (+https://github.com/lautarorodriguezlopez/indec-dashboard)"}
MAX_BYTES = 15 * 1024 * 1024
FIRMAS = {".xlsx": b"PK\x03\x04", ".xls": b"\xd0\xcf\x11\xe0"}
MAX_DIAS = {"M": 135, "T": 280}
HOY = date.today()
MESES = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6, "jul": 7, "ago": 8,
         "sep": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12}
ARCHIVO_OK = re.compile(r"^[a-z0-9_]{1,60}\.xlsx?$", re.I)


def bajar(nombre: str) -> bytes:
    if not ARCHIVO_OK.match(nombre):
        raise ValueError(f"nombre de archivo no permitido: {nombre!r}")
    url = BASE + nombre
    error = None
    for intento in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=60) as r:
                final = urllib.parse.urlparse(r.geturl())
                if final.scheme != "https" or final.hostname != "www.indec.gob.ar":
                    raise RuntimeError(f"redirección fuera del INDEC: {final.hostname}")
                datos = r.read(MAX_BYTES + 1)
            if len(datos) > MAX_BYTES:
                raise RuntimeError("archivo más grande que el tope permitido")
            firma = FIRMAS[Path(nombre).suffix.lower()]
            if not datos.startswith(firma):
                raise RuntimeError("la respuesta no es una planilla (¿el INDEC movió el archivo?)")
            return datos
        except Exception as e:  # noqa: BLE001
            error = e
            if "no es una planilla" in str(e) or "no permitido" in str(e):
                break
            time.sleep(4 * (intento + 1))
    raise RuntimeError(f"{type(error).__name__}: {error}")


def hoja(datos: bytes, nombre: str) -> pd.DataFrame:
    return pd.read_excel(io.BytesIO(datos), sheet_name=nombre, header=None)


def num(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(x) else x


def col_fecha(df: pd.DataFrame, col: int, valor: int) -> pd.Series:
    """Filas con una fecha en `col` y un número en `valor`."""
    out = {}
    for _, r in df.iterrows():
        f, v = r.iloc[col], num(r.iloc[valor])
        if isinstance(f, (datetime, pd.Timestamp)) and v is not None:
            out[pd.Timestamp(f).normalize().replace(day=1)] = v
    return pd.Series(out, dtype="float64").sort_index()


def col_anio_mes(df: pd.DataFrame, valor: int) -> pd.Series:
    """Año en la columna 0 (solo en enero) y mes abreviado en la 1."""
    out, anio = {}, None
    for _, r in df.iterrows():
        a = num(r.iloc[0])
        if a is not None and 1990 < a < 2100:
            anio = int(a)
        m = str(r.iloc[1]).strip().lower().rstrip("*")[:3]
        v = num(r.iloc[valor])
        if anio and m in MESES and v is not None:
            out[pd.Timestamp(anio, MESES[m], 1)] = v
    return pd.Series(out, dtype="float64").sort_index()


def fila_trimestral(df: pd.DataFrame, etiqueta: str) -> pd.Series:
    """Serie trimestral de una fila con etiqueta en la columna 0 y encabezados tipo 2026T2*."""
    patron = re.compile(r"^(\d{4})T([1-4])\*?$")
    enc = None
    for i in range(min(12, len(df))):
        if sum(bool(patron.match(str(v).strip())) for v in df.iloc[i]) >= 4:
            enc = i
            break
    if enc is None:
        raise RuntimeError("no encontré la fila de trimestres")
    filas = [i for i, v in df.iloc[:, 0].items() if str(v).strip().lower().startswith(etiqueta.lower())]
    if not filas:
        raise RuntimeError(f"no encontré la fila «{etiqueta}»")
    fila = df.iloc[filas[0]]
    out = {}
    for j, h in enumerate(df.iloc[enc]):
        m = patron.match(str(h).strip())
        v = num(fila.iloc[j])
        if m and v is not None:
            out[pd.Timestamp(int(m.group(1)), (int(m.group(2)) - 1) * 3 + 1, 1)] = v
    return pd.Series(out, dtype="float64").sort_index()


def archivo_bdp() -> str:
    """El informe de balanza de pagos cambia de nombre cada trimestre (cin_II_2026.xls)."""
    romanos = ["I", "II", "III", "IV"]
    a, t = HOY.year, (HOY.month - 1) // 3
    for _ in range(6):
        nombre = f"cin_{romanos[t]}_{a}.xls"
        try:
            req = urllib.request.Request(BASE + nombre, headers={**HEADERS, "Range": "bytes=0-7"})
            with urllib.request.urlopen(req, timeout=30) as r:
                if r.read(8).startswith(FIRMAS[".xls"]):
                    return nombre
        except Exception:  # noqa: BLE001
            pass
        t -= 1
        if t < 0:
            a, t = a - 1, 3
    raise RuntimeError("no encontré el informe de balanza de pagos de los últimos 6 trimestres")


# Cada planilla: archivo y lista de (clave, grupo, nombre, unidad, frecuencia, extractor)
PLANILLAS = [
    {"archivo": "serie_eoh_pernoctaciones.xlsx", "series": [
        ("eoh_total", "Turismo", "Pernoctaciones en hoteles (desestacionalizada)", "Noches", "M",
         lambda d: col_fecha(hoja(d, "Pernoctaciones totales"), 0, 2)),
        ("eoh_residentes", "Turismo", "Pernoctaciones de residentes (desestacionalizada)", "Noches", "M",
         lambda d: col_fecha(hoja(d, "Pernotaciones residentes"), 0, 2)),
        ("eoh_no_residentes", "Turismo", "Pernoctaciones de no residentes (desestacionalizada)", "Noches", "M",
         lambda d: col_fecha(hoja(d, "Pernoctaciones no residentes"), 0, 2)),
    ], "discontinuada": True},
    {"archivo": "permisos_edificacion_246_municipios.xlsx", "series": [
        ("permisos_m2", "Construcción", "Superficie autorizada por permisos de edificación (246 municipios)", "m²", "M",
         lambda d: col_anio_mes(hoja(d, "Permisos de Edificación"), 4)),
        ("permisos_n", "Construcción", "Permisos de edificación otorgados (246 municipios)", "Permisos", "M",
         lambda d: col_anio_mes(hoja(d, "Permisos de Edificación"), 2)),
    ]},
    {"archivo": "serie_etn_sam.xlsx", "series": [
        ("ice_super", "Expectativas", "Confianza empresarial: supermercados y mayoristas", "Saldo %", "M",
         lambda d: col_fecha(hoja(d, "Cuadro 1."), 0, 1)),
    ]},
    {"archivo": "serie_etn_im.xlsx", "series": [
        ("ice_industria", "Expectativas", "Confianza empresarial: industria manufacturera", "Saldo %", "M",
         lambda d: col_fecha(hoja(d, "Cuadro 1."), 0, 1)),
    ]},
    {"archivo": archivo_bdp, "series": [
        ("bdp_cc", "Sector externo", "Cuenta corriente", "Millones de USD", "T",
         lambda d: fila_trimestral(hoja(d, "Cuadro 1"), "1. Cuenta corriente")),
        ("bdp_bienes", "Sector externo", "Balance de bienes", "Millones de USD", "T",
         lambda d: fila_trimestral(hoja(d, "Cuadro 1"), "1.A.a Bienes")),
        ("bdp_servicios", "Sector externo", "Balance de servicios", "Millones de USD", "T",
         lambda d: fila_trimestral(hoja(d, "Cuadro 1"), "1.A.b Servicios")),
        ("bdp_ingreso_primario", "Sector externo", "Ingreso primario (intereses y utilidades)", "Millones de USD", "T",
         lambda d: fila_trimestral(hoja(d, "Cuadro 1"), "1.B Ingreso primario")),
        ("bdp_reservas", "Sector externo", "Variación de reservas por transacciones", "Millones de USD", "T",
         lambda d: fila_trimestral(hoja(d, "Cuadro 1"), "3.5 Activos de reserva")),
        ("deuda_total", "Sector externo", "Deuda externa bruta total", "Millones de USD", "T",
         lambda d: fila_trimestral(hoja(d, "Cuadro 23"), "Saldo deuda ext")),
        ("deuda_gobierno", "Sector externo", "Deuda externa del gobierno general", "Millones de USD", "T",
         lambda d: fila_trimestral(hoja(d, "Cuadro 23"), "Gobierno general")),
        ("deuda_bcra", "Sector externo", "Deuda externa del Banco Central", "Millones de USD", "T",
         lambda d: fila_trimestral(hoja(d, "Cuadro 23"), "Banco central")),
    ]},
]


def main() -> int:
    DIR.mkdir(parents=True, exist_ok=True)
    previo = pd.read_parquet(ARCHIVO) if ARCHIVO.exists() else pd.DataFrame()
    partes, estado = [], []
    for pl in PLANILLAS:
        datos, nombre, err_archivo = None, None, None
        try:
            nombre = pl["archivo"]() if callable(pl["archivo"]) else pl["archivo"]
            datos = bajar(nombre)
        except Exception as e:  # noqa: BLE001
            err_archivo = str(e)[:200]
        for clave, grupo, titulo, unidad, frec, extraer in pl["series"]:
            info = {"clave": clave, "id": nombre or "?", "grupo": grupo, "nombre": titulo, "unidad": unidad,
                    "frecuencia": frec, "fuente": "planilla INDEC", "ok": False, "error": None,
                    "ultimo": None, "atrasada": False, "discontinuada": bool(pl.get("discontinuada"))}
            try:
                if err_archivo:
                    raise RuntimeError(err_archivo)
                s = extraer(datos).dropna()
                if len(s) < 4:
                    raise RuntimeError(f"solo {len(s)} datos")
                df = pd.DataFrame({"fecha": s.index, "valor": s.values})
                info.update(ok=True, filas=len(df))
            except Exception as e:  # noqa: BLE001
                info["error"] = str(e)[:200]
                df = previo[previo["clave"] == clave][["fecha", "valor"]] if not previo.empty else pd.DataFrame()
            if not df.empty:
                df = df.assign(clave=clave, id=info["id"], grupo=grupo, nombre=titulo, unidad=unidad, frecuencia=frec)
                f = pd.to_datetime(df["fecha"])
                df["anio"], df["mes"] = f.dt.year.astype("int32"), f.dt.month.astype("int32")
                partes.append(df)
                ult = f.max().date()
                info["ultimo"] = f.max().strftime("%Y-%m") if frec == "M" else f"{ult.year}-T{(ult.month - 1) // 3 + 1}"
                info["atrasada"] = (not info["discontinuada"]) and (HOY - ult).days > MAX_DIAS[frec]
            estado.append(info)
            marca = "ok" if info["ok"] else "FALLÓ"
            print(f"{marca:5} {clave:22} {info['ultimo']}  {info['error'] or ''}")

    if partes:
        pd.concat(partes, ignore_index=True).to_parquet(ARCHIVO, index=False)
    ESTADO.write_text(json.dumps({
        "generado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fuente": "Planillas del INDEC (www.indec.gob.ar/ftp/cuadros/economia)",
        "series_ok": sum(s["ok"] for s in estado),
        "series_total": len(estado),
        "atrasadas": sum(s["atrasada"] for s in estado),
        "series": estado,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
