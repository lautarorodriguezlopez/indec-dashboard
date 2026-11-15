"""Arma los datos del sitio (site/data/*.json) a partir de data/parquet.

Genera:
- tableros.json: series de los tres tableros destacados (Precios, Bolsillo,
  Pulso de actividad) y el semáforo.
- catalogo.json: estado de los 19 servicios (filas, último período, última
  ingesta) para la página de catálogo.

No consulta la API: solo lee los Parquet que deja ingestar.py.
"""

from __future__ import annotations

import json
import math
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
DIR = RAIZ / "data" / "parquet"
SITIO = RAIZ / "site"
SALIDA = SITIO / "data"


def leer(tabla: str) -> pd.DataFrame:
    return pd.read_parquet(DIR / f"{tabla}.parquet")


def limpio(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else round(f, 4)


def periodo_mes(df: pd.DataFrame) -> pd.Series:
    return df["anio"].astype(int).astype(str) + "-" + df["mes"].astype(int).map("{:02d}".format)


def serie(df: pd.DataFrame, clave: str = "p", valor: str = "valor") -> dict:
    d = df.dropna(subset=[valor]).sort_values(clave).drop_duplicates(clave, keep="last")
    return {"p": d[clave].tolist(), "v": [limpio(x) for x in d[valor]]}


def tabla_series(df: pd.DataFrame, columna: str, nombres: list[str] | None = None) -> dict:
    """Pivot: períodos alineados y una lista de valores por cada valor de `columna`."""
    d = df.dropna(subset=["valor"]).drop_duplicates(["p", columna], keep="last")
    piv = d.pivot(index="p", columns=columna, values="valor").sort_index()
    cols = nombres or list(piv.columns)
    return {
        "p": piv.index.tolist(),
        "series": {c: [limpio(x) for x in piv[c]] if c in piv.columns else [] for c in cols},
    }


def var_vs_prom(valores: list, n: int = 12) -> tuple[float | None, float | None]:
    vals = [v for v in valores if v is not None]
    if len(vals) < n + 1:
        return None, None
    ult, prev = vals[-1], vals[-1 - n : -1]
    return ult, sum(prev) / len(prev)


# --------------------------------------------------------------------- precios
def precios() -> dict:
    ipc = leer("ipc")
    ipc["p"] = periodo_mes(ipc)

    ng = ipc[ipc["nivel"] == "Nivel General"]
    por_region = {}
    for reg, g in ng.groupby("region"):
        por_region[reg] = tabla_series(g, "tipo_de_indicador", ["v_m", "v_ia", "v_acum", "Indice"])

    cnr = ipc[ipc["descripcion"].isin(["Estacional", "Núcleo", "Regulados"])]
    cnr = cnr[cnr["tipo_de_indicador"].isin(["v_m", "v_ia"])].dropna(subset=["valor"])
    cnr_region = {}
    for reg, g in cnr.groupby("region"):
        cnr_region[reg] = {
            t: tabla_series(gt, "descripcion", ["Núcleo", "Regulados", "Estacional"])
            for t, gt in g.groupby("tipo_de_indicador")
        }

    div = ipc[(ipc["nivel"] == "División") & ipc["clasificador"].str.startswith("COICOP")]
    div = div[div["tipo_de_indicador"].isin(["v_m", "v_ia"])].dropna(subset=["valor"])
    ult = div["p"].max()
    rubros = {}
    for reg, g in div[div["p"] == ult].groupby("region"):
        piv = g.pivot_table(index=["codigo", "descripcion"], columns="tipo_de_indicador", values="valor")
        rubros[reg] = [
            {"codigo": c, "rubro": d, "v_m": limpio(r.get("v_m")), "v_ia": limpio(r.get("v_ia"))}
            for (c, d), r in piv.iterrows()
        ]

    # Inflación por tipo de precio: consumidor (IPC), mayorista (IPIM) y construcción (ICC)
    sipm = leer("sipm")
    sipm = sipm[(sipm["indicador"] == "IPIM") & (sipm["nivel"] == "Nivel general") & (sipm["tipo_de_indicador"] == "v_ia")]
    sipm["p"] = periodo_mes(sipm)
    icc = leer("icc")
    icc = icc[(icc["nivel"] == "Nivel general") & (icc["tipo_de_indicador"] == "v_ia")]
    icc["p"] = periodo_mes(icc)
    nac = ng[(ng["region"] == "Nacional") & (ng["tipo_de_indicador"] == "v_ia")]
    tipos = pd.concat(
        [
            nac.assign(s="Consumidor (IPC)")[["p", "s", "valor"]],
            sipm.assign(s="Mayorista (IPIM)")[["p", "s", "valor"]],
            icc.assign(s="Construcción (ICC)")[["p", "s", "valor"]],
        ]
    )
    return {
        "regiones": ["Nacional", "GBA", "Pampeana", "Noreste", "Noroeste", "Cuyo", "Patagonia"],
        "nivel_general": por_region,
        "nucleo_regulados": cnr_region,
        "rubros_periodo": ult,
        "rubros": rubros,
        "tipos_de_precio": tabla_series(tipos, "s", ["Consumidor (IPC)", "Mayorista (IPIM)", "Construcción (ICC)"]),
    }


# -------------------------------------------------------------------- bolsillo
def bolsillo() -> dict:
    ipc = leer("ipc")
    ipc["p"] = periodo_mes(ipc)
    ipc_idx = ipc[(ipc["nivel"] == "Nivel General") & (ipc["region"] == "Nacional") & (ipc["tipo_de_indicador"] == "Indice")]
    ipc_idx = ipc_idx.dropna(subset=["valor"]).drop_duplicates("p").set_index("p")["valor"].sort_index()

    sal = leer("salarios")
    sal["p"] = periodo_mes(sal)
    sal = sal[sal["tipo_de_indicador"] == "Indice"].dropna(subset=["valor"])
    grupos = ["Total registrado", "Sector privado registrado", "Sector público", "Total no registrado"]
    piv = sal.pivot_table(index="p", columns="descripcion", values="valor").sort_index()
    comunes = piv.index.intersection(ipc_idx.index)
    base = "2023-12" if "2023-12" in comunes else comunes[0]
    real = {}
    for g in grupos:
        if g in piv.columns:
            s = (piv[g] / piv.loc[base, g]) / (ipc_idx / ipc_idx.loc[base]) * 100
            real[g] = [limpio(s.get(p)) for p in comunes]

    can = leer("canastas")
    can["p"] = periodo_mes(can)
    pesos = can[can["unidad_de_medida"] == "Pesos argentinos"].dropna(subset=["valor"])
    etiquetas = {}
    for cod in ["CBA", "CBT", "CBT H1", "CBT H2", "CBT H3"]:
        fila = pesos[pesos["codigo"] == cod]
        if len(fila):
            etiquetas[cod] = fila["tipo_de_indicador_descripcion"].iloc[-1]
    can_series = tabla_series(pesos[pesos["codigo"].isin(etiquetas)], "codigo", list(etiquetas))
    via = can[(can["tipo_de_indicador"] == "v_ia")].dropna(subset=["valor"])
    can_via = tabla_series(via[via["codigo"].isin(["CBA", "CBT"])], "codigo", ["CBA", "CBT"])

    pob = leer("pobreza").sort_values(["anio", "semestre"])
    pob["p"] = pob["anio"].astype(int).astype(str) + "-S" + pob["semestre"].astype(int).astype(str)
    pobreza = {
        "p": pob["p"].tolist(),
        "series": {
            "Pobreza (personas)": [limpio(x) for x in pob["tasa_pobreza_personas"]],
            "Indigencia (personas)": [limpio(x) for x in pob["tasa_indigencia_personas"]],
        },
    }

    cri = leer("canasta_crianza").sort_values(["anio", "mes"])
    cri["p"] = periodo_mes(cri)
    crianza = {
        "p": cri["p"].tolist(),
        "series": {
            "Menos de 1 año": [limpio(x) for x in cri["tot_men1"]],
            "1 a 3 años": [limpio(x) for x in cri["tot_1a3"]],
            "4 a 5 años": [limpio(x) for x in cri["tot_4a5"]],
            "6 a 12 años": [limpio(x) for x in cri["tot_6a12"]],
        },
    }

    return {
        "salario_real": {"p": list(comunes), "base": base, "series": real},
        "canastas": {**can_series, "etiquetas": etiquetas},
        "canastas_v_ia": can_via,
        "pobreza": pobreza,
        "crianza": crianza,
    }


# ----------------------------------------------------------------------- pulso
def pulso() -> dict:
    emae = leer("emae")
    emae["p"] = periodo_mes(emae)
    em = tabla_series(
        emae,
        "tipo_de_indicador_descripcion",
        ["Índice serie desestacionalizada", "Var % mensual serie desestacionalizada", "Var % interanual serie original"],
    )

    sec = leer("emae_sectores")
    sec["p"] = periodo_mes(sec)
    sec = sec[sec["tipo_de_indicador"] == "Variación porcentual interanual"].dropna(subset=["valor"])
    ult_sec = sec["p"].max()
    sectores = [
        {"sector": r["descripcion"], "v_ia": limpio(r["valor"])}
        for _, r in sec[sec["p"] == ult_sec].sort_values("valor", ascending=False).iterrows()
    ]

    def ipi(tabla: str, desc: str, serie_des: str, serie_orig: str) -> dict:
        d = leer(tabla)
        d["p"] = periodo_mes(d)
        d = d[d["descripcion"] == desc]
        des = d[(d["serie"] == serie_des) & (d["tipo_de_indicador"] == "Índice")]
        via = d[(d["serie"] == serie_orig) & (d["tipo_de_indicador"] == "Variación interanual")]
        return {"indice_desest": serie(des), "v_ia": serie(via)}

    manuf = ipi("ipi_manufacturero", "IPI Manufacturero - Nivel general", "Serie desestacionalizada", "Serie original")
    miner = ipi("ipi_minero", "Nivel General - IPI Minero", "Serie Desestacionalizada", "Serie Original")

    tra = leer("mercado_trabajo").sort_values(["anio", "trimestre"])
    tra["p"] = tra["anio"].astype(int).astype(str) + "-T" + tra["trimestre"].astype(int).astype(str)
    trabajo = {
        "p": tra["p"].tolist(),
        "series": {
            "Desocupación": [limpio(x) for x in tra["tasa_de_desocupacion"]],
            "Subocupación": [limpio(x) for x in tra["tasa_de_subocupacion"]],
        },
        "actividad": [limpio(x) for x in tra["tasa_de_actividad"]],
        "empleo": [limpio(x) for x in tra["tasa_de_empleo"]],
    }

    ex = leer("exportaciones")
    im = leer("importaciones")
    ex["p"] = periodo_mes(ex)
    im["p"] = periodo_mes(im)
    exp_m = ex.groupby("p")["valor_fob"].sum() / 1e6
    imp_m = im.groupby("p")["valor_cif"].sum() / 1e6
    meses = sorted(set(exp_m.index) & set(imp_m.index))
    meses = [m for m in meses if m >= "2017-01"]
    comex = {
        "p": meses,
        "series": {
            "Exportaciones": [limpio(exp_m[m]) for m in meses],
            "Importaciones": [limpio(imp_m[m]) for m in meses],
            "Saldo": [limpio(exp_m[m] - imp_m[m]) for m in meses],
        },
    }
    return {
        "emae": em,
        "sectores_periodo": ult_sec,
        "sectores": sectores,
        "ipi_manufacturero": manuf,
        "ipi_minero": miner,
        "trabajo": trabajo,
        "comex": comex,
    }


# -------------------------------------------------------------------- semáforo
def semaforo(pr: dict, bo: dict, pu: dict) -> list[dict]:
    """Compara el último dato con su historia reciente. Reglas simples y explícitas."""
    out = []

    def item(nombre, periodo, valor, ref, texto_ref, delta, mejor_si_sube, umbral, unidad):
        if valor is None or ref is None:
            return
        d = delta
        if abs(d) < umbral:
            estado = "templado"
        elif (d > 0) == mejor_si_sube:
            estado = "bien"
        else:
            estado = "mal"
        out.append(
            {"indicador": nombre, "periodo": periodo, "valor": round(valor, 2), "unidad": unidad,
             "referencia": round(ref, 2), "texto_referencia": texto_ref, "delta": round(d, 2), "estado": estado}
        )

    s = pu["emae"]["series"]["Índice serie desestacionalizada"]
    ult, prom = var_vs_prom(s)
    if ult is not None:
        item("Actividad (EMAE)", pu["emae"]["p"][-1], ult, prom, "frente al promedio de los 12 meses previos",
             (ult / prom - 1) * 100, True, 0.5, "índice")

    for clave, nombre in (("ipi_manufacturero", "Industria (IPI)"), ("ipi_minero", "Minería (IPI)")):
        s = pu[clave]["indice_desest"]
        ult, prom = var_vs_prom(s["v"])
        if ult is not None:
            item(nombre, s["p"][-1], ult, prom, "frente al promedio de los 12 meses previos",
                 (ult / prom - 1) * 100, True, 1.0, "índice")

    ng = pr["nivel_general"]["Nacional"]
    ult, prom = var_vs_prom(ng["series"]["v_m"])
    if ult is not None:
        item("Inflación mensual (IPC)", ng["p"][-1], ult, prom, "frente al promedio de los 12 meses previos",
             ult - prom, False, 0.2, "%")

    t = pu["trabajo"]
    des = t["series"]["Desocupación"]
    if len(des) >= 5 and des[-1] is not None and des[-5] is not None:
        item("Desocupación (EPH)", t["p"][-1], des[-1], des[-5], "frente al mismo trimestre del año anterior",
             des[-1] - des[-5], False, 0.3, "%")

    sr = bo["salario_real"]["series"].get("Total registrado", [])
    if len(sr) >= 13 and sr[-1] and sr[-13]:
        item("Salario real registrado", bo["salario_real"]["p"][-1], sr[-1], sr[-13], "frente a 12 meses antes",
             (sr[-1] / sr[-13] - 1) * 100, True, 1.0, "índice")

    saldo = [v for v in pu["comex"]["series"]["Saldo"] if v is not None]
    if len(saldo) >= 15:
        ult3 = sum(saldo[-3:]) / 3
        prev12 = sum(saldo[-15:-3]) / 12
        item("Saldo comercial (promedio 3 meses)", pu["comex"]["p"][-1], ult3, prev12,
             "frente al promedio mensual de los 12 meses previos",
             ult3 - prev12, True, 100, "millones de USD")
    return out


# ------------------------------------------------------------------ explorador
# Metadatos para el explorador del sitio. El navegador solo arma consultas
# con las tablas y columnas que figuran acá (lista blanca).

ETIQUETAS = {
    "region": "Región", "descripcion": "Descripción", "codigo": "Código", "nivel": "Nivel",
    "clasificador": "Clasificador", "tipo_de_indicador": "Tipo de indicador",
    "tipo_de_indicador_descripcion": "Indicador", "unidad_de_medida": "Unidad", "valor": "Valor",
    "serie": "Serie", "indicador": "Índice", "operativo": "Operativo", "origen": "Origen",
    "inciso": "Inciso", "descripcion_inciso": "Inciso (descripción)", "codigo_apertura": "Código de apertura",
    "area_geografica_nom": "Área geográfica", "sexo_nom": "Sexo", "edad": "Edad", "edad_nom": "Edad",
    "jurisdiccion_nom": "Provincia", "departamento_nom": "Departamento", "rmba": "Región Metropolitana (1 = sí)",
    "poblacion": "Población", "pais": "País", "rubro": "Rubro", "subrubro": "Subrubro",
    "uso_economico": "Uso económico", "gce": "Grandes categorías económicas",
    "valor_fob": "Valor FOB (US$)", "valor_cif": "Valor CIF (US$)", "peso_neto": "Peso neto (kg)",
    "observaciones": "Observaciones", "nombre_columna": "Columna", "codigo_descripcion": "Descripción del código",
    "tasa_pobreza_hogares": "Pobreza (% hogares)", "tasa_pobreza_personas": "Pobreza (% personas)",
    "tasa_indigencia_hogares": "Indigencia (% hogares)", "tasa_indigencia_personas": "Indigencia (% personas)",
    "tasa_de_actividad": "Tasa de actividad", "tasa_de_empleo": "Tasa de empleo",
    "tasa_de_empleo_formal": "Empleo formal", "tasa_de_empleo_informal": "Empleo informal",
    "tasa_de_desocupacion": "Desocupación", "tasa_de_ocupacion_demandante": "Ocupados demandantes",
    "tasa_de_subocupacion": "Subocupación", "tasa_de_subocupacion_demandante": "Subocupación demandante",
    "tasa_de_subocupacion_no_demandante": "Subocupación no demandante",
}
EDADES = {"men1": "menos de 1 año", "1a3": "1 a 3 años", "4a5": "4 a 5 años", "6a12": "6 a 12 años"}
PARTES = {"bys": "Bienes y servicios", "cuid": "Cuidado", "tot": "Total"}
OCULTAS = {"periodo", "cuadro_web", "anio", "mes", "trimestre", "semestre", "fecha", "area_geografica_cod",
           "sexo_cod", "edad_cod", "jurisdiccion_cod", "departamento_cod", "rubro_cod", "subrubro_cod",
           "pais_cod", "uso_economico_cod", "gce_cod"}
SUMABLES = {"valor_fob", "valor_cif", "peso_neto", "poblacion"}
COMEX_NOMBRES = {
    "exportaciones": {"rubro_cod": "rubro", "subrubro_cod": "subrubro", "pais_cod": "pais"},
    "importaciones": {"uso_economico_cod": "uso_economico", "gce_cod": "gce", "pais_cod": "pais"},
}


def etiqueta(col: str) -> str:
    if col in ETIQUETAS:
        return ETIQUETAS[col]
    parte, _, edad = col.partition("_")
    if parte in PARTES and edad in EDADES:
        return f"{PARTES[parte]} · {EDADES[edad]}"
    return col.replace("_", " ").capitalize()


def con_tiempo(df: pd.DataFrame, tiempo: str | None) -> pd.DataFrame:
    df = df.copy()
    if tiempo == "fecha":
        anio = pd.to_numeric(df["fecha"], errors="coerce").astype("Int64")
        df["_anio"], df["_periodo"] = anio, anio.astype(str)
    elif tiempo:
        sub = {"mes": "mes", "trimestre": "trimestre", "semestre": "semestre"}[tiempo]
        anio = df["anio"].astype("Int64")
        n = df[sub].astype("Int64")
        pref = {"mes": "", "trimestre": "T", "semestre": "S"}[tiempo]
        txt = n.map(lambda x: f"{x:02d}" if tiempo == "mes" else f"{pref}{x}", na_action="ignore")
        df["_anio"], df["_periodo"] = anio, anio.astype(str) + "-" + txt
    return df


def escribir_base(descargas: Path, tablas: list[dict]) -> None:
    import duckdb

    destino = descargas / "explorador.duckdb"
    destino.unlink(missing_ok=True)
    con = duckdb.connect()
    con.execute(f"ATTACH '{destino.as_posix()}' AS ex (STORAGE_VERSION 'v1.2.0')")
    for t in tablas:
        archivo = descargas / f"{t['tabla']}.parquet"
        df = con_tiempo(pd.read_parquet(archivo), t["tiempo"])
        con.register("df_tmp", df)
        con.execute(f'CREATE TABLE ex."{t["tabla"]}" AS SELECT * FROM df_tmp')
        con.unregister("df_tmp")
    con.execute("DETACH ex")
    con.close()
    print(f"explorador.duckdb: {destino.stat().st_size / 1e6:.1f} MB")


def explorador(estado: dict) -> None:
    descargas = SITIO / "datos"
    nom = leer("comex_nomenclaturas")
    tablas = []
    for s in estado["servicios"]:
        tabla = s["tabla"]
        if not (DIR / f"{tabla}.parquet").exists():
            continue
        df = leer(tabla)
        # Comercio exterior: agrega nombres legibles a los códigos
        if tabla in COMEX_NOMBRES:
            for cod, nombre in COMEX_NOMBRES[tabla].items():
                m = nom[nom["nombre_columna"] == cod].drop_duplicates("codigo").set_index("codigo")["codigo_descripcion"]
                df[nombre] = df[cod].map(m).fillna(df[cod])
            df.to_parquet(descargas / f"{tabla}.parquet", index=False)

        cols = set(df.columns)
        if {"anio", "mes"} <= cols:
            tiempo = "mes"
        elif {"anio", "trimestre"} <= cols:
            tiempo = "trimestre"
        elif {"anio", "semestre"} <= cols:
            tiempo = "semestre"
        elif "fecha" in cols:
            tiempo = "fecha"
        else:
            tiempo = None
        anios = None
        if tiempo == "fecha":
            f = pd.to_numeric(df["fecha"], errors="coerce").dropna()
            anios = [int(f.min()), int(f.max())]
        elif tiempo:
            anios = [int(df["anio"].min()), int(df["anio"].max())]

        dims, medidas, visibles = [], [], []
        for c in df.columns:
            if c.endswith("_null") or c in OCULTAS:
                continue
            visibles.append(c)
            s_ = df[c]
            if c == "edad" or not pd.api.types.is_numeric_dtype(s_):
                if c == "observaciones":
                    continue
                vals = sorted(s_.dropna().astype(str).unique().tolist(), key=lambda v: (len(v) if c == "edad" else 0, v))
                if 2 <= len(vals) <= 600:
                    dims.append({"col": c, "label": etiqueta(c), "valores": vals, "numerica": c == "edad"})
            else:
                medidas.append({"col": c, "label": etiqueta(c), "sumable": c in SUMABLES})
        tablas.append({
            "tabla": tabla,
            "titulo": s.get("descripcion") or tabla,
            "filas": int(len(df)),
            "ultimo_periodo": s.get("ultimo_periodo"),
            "tiempo": tiempo,
            "anios": anios,
            "dims": dims,
            "medidas": medidas,
            "columnas": [{"col": c, "label": etiqueta(c)} for c in visibles],
        })
    explorador_extra(tablas)
    # Base DuckDB nativa para el explorador: el navegador la lee por rangos HTTP
    # sin extensiones ni descargas de terceros. Formato compatible con DuckDB-WASM.
    escribir_base(descargas, tablas)
    (SALIDA / "explorador.json").write_text(json.dumps({"tablas": tablas}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"explorador.json: {len(tablas)} tablas")


# ----------------------------------------------------------- más indicadores
# Series de datos.gob.ar (ingesta/series_tiempo.py). Si no están, la sección no se arma.

def _extra() -> pd.DataFrame | None:
    """series_extra (datos.gob.ar) + planillas del INDEC, en un solo DataFrame."""
    partes = [pd.read_parquet(DIR / f) for f in ("series_extra.parquet", "planillas.parquet") if (DIR / f).exists()]
    if not partes:
        return None
    df = pd.concat(partes, ignore_index=True)
    df["fecha"] = pd.to_datetime(df["fecha"])
    trimestral = df["frecuencia"] == "T"
    df["p"] = df["fecha"].dt.strftime("%Y-%m")
    df.loc[trimestral, "p"] = df.loc[trimestral, "fecha"].dt.year.astype(str) + "-T" + ((df.loc[trimestral, "fecha"].dt.month - 1) // 3 + 1).astype(str)
    return df


def _serie(df: pd.DataFrame, clave: str) -> pd.Series:
    d = df[df["clave"] == clave].sort_values("fecha")
    return pd.Series(d["valor"].values, index=d["p"].values)


def _alinear(df: pd.DataFrame, claves: dict[str, str], desde: str | None = None) -> dict:
    piv = pd.DataFrame({nombre: _serie(df, clave) for clave, nombre in claves.items()}).sort_index()
    if desde:
        piv = piv[piv.index >= desde]
    return {"p": piv.index.tolist(), "series": {c: [limpio(x) for x in piv[c]] for c in piv.columns}}


def _var(s: pd.Series, n: int) -> tuple[str | None, float | None]:
    s = s.dropna()
    if len(s) <= n:
        return None, None
    return s.index[-1], limpio((s.iloc[-1] / s.iloc[-1 - n] - 1) * 100)


def mas(estado_series: dict | None) -> dict | None:
    df = _extra()
    if df is None or df.empty:
        return None
    est = {s["clave"]: s for s in (estado_series or {}).get("series", [])}

    def info(*claves):
        return [{"clave": c, "nombre": est.get(c, {}).get("nombre", c), "ultimo": est.get(c, {}).get("ultimo"),
                 "atrasada": bool(est.get(c, {}).get("atrasada"))} for c in claves]

    # Consumo
    pagos = {"pago_efectivo": "Efectivo", "pago_debito": "Débito", "pago_credito": "Crédito", "pago_otros": "Otros medios"}
    piv = pd.DataFrame({n: _serie(df, c) for c, n in pagos.items()}).dropna().sort_index()
    piv = piv[piv.index >= "2017-01"]
    cuotas = piv.div(piv.sum(axis=1), axis=0) * 100
    online = (_serie(df, "canal_online") / (_serie(df, "canal_online") + _serie(df, "canal_salon")) * 100).dropna().sort_index()
    p_sup, v_sup = _var(_serie(df, "super"), 12)
    consumo = {
        "real": _alinear(df, {"super_desest": "Supermercados", "mayoristas_desest": "Mayoristas", "shoppings_desest": "Shoppings"}),
        "pagos": {"p": cuotas.index.tolist(), "series": {c: [limpio(x) for x in cuotas[c]] for c in cuotas.columns}},
        "online": {"p": online.index.tolist(), "v": [limpio(x) for x in online.values]},
        "kpi_super_v_ia": {"p": p_sup, "v": v_sup},
        "fuentes": info("super_desest", "mayoristas_desest", "shoppings_desest", "pago_efectivo"),
    }

    # Construcción
    insumos = {"ins_cemento": "Cemento", "ins_hierro": "Hierro y acero", "ins_ladrillos": "Ladrillos huecos",
               "ins_pinturas": "Pinturas", "ins_asfalto": "Asfalto", "ins_hormigon": "Hormigón"}
    barras = []
    for c, n in insumos.items():
        p, v = _var(_serie(df, c), 12)
        if v is not None:
            barras.append({"insumo": n, "v_ia": v, "p": p})
    p_isac, v_isac = _var(_serie(df, "isac"), 12)
    construccion = {
        "isac": _alinear(df, {"isac_desest": "ISAC desestacionalizado"}),
        "insumos": sorted(barras, key=lambda x: -x["v_ia"]),
        "insumos_periodo": max((b["p"] for b in barras), default=None),
        "kpi_isac_v_ia": {"p": p_isac, "v": v_isac},
        "fuentes": info("isac_desest", "isac", *insumos),
    }

    # Industria (capacidad instalada)
    ucii = _serie(df, "ucii").dropna()
    industria = {
        "ucii": _alinear(df, {"ucii": "Nivel general", "ucii_autos": "Automotores", "ucii_metales": "Metales básicos",
                              "ucii_textil": "Textiles"}, desde="2016-01"),
        "kpi": {"p": ucii.index[-1] if len(ucii) else None, "v": limpio(ucii.iloc[-1]) if len(ucii) else None,
                "pp_ia": limpio(ucii.iloc[-1] - ucii.iloc[-13]) if len(ucii) > 12 else None},
        "fuentes": info("ucii", "ucii_autos", "ucii_metales", "ucii_textil", "ucii_quimicos"),
    }

    # Turismo
    rec, emi = _serie(df, "tur_receptivo"), _serie(df, "tur_emisivo")
    comun = rec.index.intersection(emi.index)
    turismo = {
        "flujos": _alinear(df, {"tur_receptivo": "Llegan al país", "tur_emisivo": "Viajan al exterior"}, desde="2016-01"),
        "kpi": {"p": comun[-1] if len(comun) else None,
                "llegan": limpio(rec[comun[-1]]) if len(comun) else None,
                "viajan": limpio(emi[comun[-1]]) if len(comun) else None},
        "fuentes": info("tur_receptivo", "tur_emisivo"),
    }

    # Macro
    pib = _serie(df, "pib").dropna()
    pib_ia = ((pib / pib.shift(4) - 1) * 100).dropna()
    pib_ia = pib_ia[pib_ia.index >= "2010"]
    gini = _serie(df, "gini").dropna()
    gini = gini[gini.index >= "2016"]
    macro = {
        "pib_ia": {"p": pib_ia.index.tolist(), "v": [limpio(x) for x in pib_ia.values]},
        "gini": {"p": gini.index.tolist(), "v": [limpio(x) for x in gini.values]},
        "fuentes": info("pib", "gini"),
    }

    # Servicios públicos
    issp = _serie(df, "issp").dropna()
    p_issp, v_issp = _var(issp, 12)
    servicios = {
        "issp": _alinear(df, {"issp": "Servicios públicos (tendencia-ciclo)"}, desde="2016-01"),
        "kpi_v_ia": {"p": p_issp, "v": v_issp},
        "fuentes": info("issp"),
    }
    # Fase 2: planillas del INDEC
    pm2 = _serie(df, "permisos_m2").dropna() / 1000
    p_pm, v_pm = _var(pm2, 12)
    construccion["permisos"] = {"p": pm2.index.tolist(), "v": [limpio(x) for x in pm2.values]}
    construccion["kpi_permisos_v_ia"] = {"p": p_pm, "v": v_pm}
    construccion["fuentes"] += info("permisos_m2", "permisos_n")

    turismo["hoteles"] = _alinear(df, {"eoh_residentes": "Residentes", "eoh_no_residentes": "No residentes"}, desde="2016-01")
    turismo["fuentes"] += info("eoh_total", "eoh_residentes", "eoh_no_residentes")

    expectativas = {
        "ice": _alinear(df, {"ice_super": "Supermercados y mayoristas", "ice_industria": "Industria manufacturera"}),
        "fuentes": info("ice_super", "ice_industria"),
    }

    dt, dg, db = _serie(df, "deuda_total"), _serie(df, "deuda_gobierno"), _serie(df, "deuda_bcra")
    priv = (dt - dg - db).dropna()
    deuda = pd.DataFrame({"Gobierno general": dg, "Banco Central": db, "Sector privado y bancos": priv}).dropna().sort_index()
    deuda = deuda[deuda.index >= "2016"] / 1000
    dt16 = dt.dropna().sort_index()
    externo = {
        "cuenta": _alinear(df, {"bdp_cc": "Cuenta corriente", "bdp_bienes": "Bienes", "bdp_servicios": "Servicios",
                                "bdp_ingreso_primario": "Ingreso primario"}, desde="2016"),
        "deuda": {"p": deuda.index.tolist(), "series": {c: [limpio(x) for x in deuda[c]] for c in deuda.columns}},
        "kpi_deuda": {"p": dt16.index[-1] if len(dt16) else None, "v": limpio(dt16.iloc[-1] / 1000) if len(dt16) else None,
                      "v_ia": limpio(dt16.iloc[-1] / 1000 - dt16.iloc[-5] / 1000) if len(dt16) > 4 else None},
        "fuentes": info("bdp_cc", "bdp_bienes", "bdp_servicios", "bdp_ingreso_primario", "deuda_total"),
    }
    # Fase 3: empleo registrado, ingresos en términos reales y cuentas públicas
    empleo = ingresos = fiscal = None
    sipa = _serie(df, "sipa_total_desest").dropna()
    if len(sipa):
        p_s, v_s = _var(sipa, 12)
        empleo = {
            "total": _alinear(df, {"sipa_total_desest": "Total registrados"}, desde="2016-01"),
            "composicion": _alinear(df, {"sipa_privados": "Asalariados privados", "sipa_monotributo": "Monotributistas",
                                         "sipa_publicos_desest": "Asalariados públicos"}, desde="2016-01"),
            "kpi": {"p": p_s, "v": limpio(sipa.iloc[-1]), "dif_ia": limpio(sipa.iloc[-1] - sipa.iloc[-13]) if len(sipa) > 12 else None,
                    "v_ia": v_s},
            "fuentes": info("sipa_total_desest", "sipa_privados", "sipa_monotributo", "sipa_publicos_desest"),
        }
    ipc = _ipc_nacional()
    if ipc is not None:
        hasta = ipc.index.max()
        reales = {}
        for c, n in (("ripte", "RIPTE"), ("smvm", "Salario mínimo"), ("haber_minimo", "Jubilación mínima")):
            s = _serie(df, c).dropna()
            s = s[(s.index >= "2017-01") & (s.index <= hasta)]
            r = (s / ipc.reindex(s.index)).dropna()
            if len(r):
                reales[n] = r
        if reales:
            piv = pd.DataFrame(reales).sort_index()
            base = "2017-11" if "2017-11" in piv.index else piv.index[0]
            piv = piv / piv.loc[base] * 100
            kpis = {}
            for n in piv.columns:
                s = piv[n].dropna()
                kpis[n] = {"p": s.index[-1], "v_ia": limpio((s.iloc[-1] / s.iloc[-13] - 1) * 100) if len(s) > 12 else None,
                           "nominal": limpio(_serie(df, {"RIPTE": "ripte", "Salario mínimo": "smvm",
                                                         "Jubilación mínima": "haber_minimo"}[n]).dropna().loc[:s.index[-1]].iloc[-1])}
            ingresos = {"reales": {"p": piv.index.tolist(), "series": {c: [limpio(x) for x in piv[c]] for c in piv.columns}},
                        "base": base, "kpi": kpis, "fuentes": info("ripte", "smvm", "haber_minimo")}
    rec = _serie(df, "recaudacion_ia").dropna()
    prim = _serie(df, "resultado_primario").dropna()
    if len(rec) or len(prim):
        # Resultado primario acumulado en 12 meses, en millones de pesos de hoy (deflactado por IPC)
        acum = None
        if len(prim) and ipc is not None:
            pr = prim[prim.index <= ipc.index.max()]
            real = (pr / ipc.reindex(pr.index) * ipc.iloc[-1]).dropna()
            acum = (real.rolling(12).sum() / 1e6).dropna()
            acum = acum[acum.index >= "2018-01"]
        fiscal = {
            "recaudacion_ia": {"p": rec[rec.index >= "2018-01"].index.tolist(), "v": [limpio(x) for x in rec[rec.index >= "2018-01"]]},
            "primario": {"p": prim[prim.index >= "2018-01"].index.tolist(), "v": [limpio(x / 1e3) for x in prim[prim.index >= "2018-01"]]},
            "primario_12m": {"p": acum.index.tolist(), "v": [limpio(x) for x in acum]} if acum is not None else None,
            "kpi_rec": {"p": rec.index[-1] if len(rec) else None, "v": limpio(rec.iloc[-1]) if len(rec) else None},
            "kpi_prim": {"p": prim.index[-1] if len(prim) else None, "v": limpio(prim.iloc[-1] / 1e3) if len(prim) else None},
            "fuentes": info("recaudacion", "recaudacion_ia", "resultado_primario"),
        }
    return {"consumo": consumo, "construccion": construccion, "industria": industria,
            "turismo": turismo, "macro": macro, "servicios": servicios,
            "expectativas": expectativas, "externo": externo,
            "empleo": empleo, "ingresos": ingresos, "fiscal": fiscal}


def _ipc_nacional() -> pd.Series | None:
    """Índice del IPC nacional, nivel general (base dic-16 = 100), indexado por 'YYYY-MM'."""
    try:
        ipc = leer("ipc")
    except Exception:  # noqa: BLE001
        return None
    d = ipc[(ipc["nivel"] == "Nivel General") & (ipc["region"] == "Nacional") & (ipc["tipo_de_indicador"] == "Indice")]
    if d.empty:
        return None
    d = d.assign(p=periodo_mes(d)).dropna(subset=["valor"]).drop_duplicates("p", keep="last").sort_values("p")
    return pd.Series(d["valor"].astype(float).values, index=d["p"].values)


# ------------------------------------------------------------------------ BCRA
def bcra() -> dict | None:
    """Variables del BCRA para la pestaña Dinero: semanales (último dato de cada semana)
    para los gráficos y el último dato diario para las tarjetas. Liviano a propósito."""
    archivo = DIR / "bcra.parquet"
    if not archivo.exists():
        return None
    df = pd.read_parquet(archivo)
    df["fecha"] = pd.to_datetime(df["fecha"])
    archivo_e = DIR / "estado_bcra.json"
    est = {s["clave"]: s for s in json.loads(archivo_e.read_text(encoding="utf-8"))["series"]} if archivo_e.exists() else {}

    def diaria(clave: str) -> pd.Series:
        d = df[df["clave"] == clave].sort_values("fecha").drop_duplicates("fecha", keep="last")
        return pd.Series(d["valor"].astype(float).values, index=d["fecha"].values)

    def semanal(claves: dict[str, str], desde: str = "2018-01-01") -> dict:
        cols = {}
        for c, n in claves.items():
            s = diaria(c)
            if len(s):
                cols[n] = s.resample("W-FRI").last()
        if not cols:
            return {"p": [], "series": {}}
        piv = pd.DataFrame(cols).sort_index()
        piv = piv[piv.index >= desde].dropna(how="all")
        return {"p": [x.strftime("%Y-%m-%d") for x in piv.index],
                "series": {c: [limpio(x) for x in piv[c]] for c in piv.columns}}

    def kpi(clave: str, dias_comp: int = 365) -> dict:
        s = diaria(clave).dropna()
        if not len(s):
            return {"p": None, "v": None, "v_comp": None}
        ref = s[s.index <= s.index[-1] - pd.Timedelta(days=dias_comp)]
        return {"p": s.index[-1].strftime("%Y-%m-%d"), "v": limpio(s.iloc[-1]),
                "v_comp": limpio(ref.iloc[-1]) if len(ref) else None}

    # Crecimiento real de préstamos y depósitos: nominal mensual deflactado por IPC
    credito = None
    ipc = _ipc_nacional()
    if ipc is not None:
        cols = {}
        for c, n in (("prestamos_privados", "Préstamos al sector privado"), ("depositos", "Depósitos")):
            s = diaria(c)
            if len(s):
                m = s.resample("MS").mean()
                m.index = m.index.strftime("%Y-%m")
                r = (m / ipc.reindex(m.index)).dropna()
                cols[n] = r
        if cols:
            piv = pd.DataFrame(cols).sort_index()
            piv = piv[piv.index >= "2018-01"]
            base = piv.index[0]
            piv = piv / piv.loc[base] * 100
            credito = {"p": piv.index.tolist(), "series": {c: [limpio(x) for x in piv[c]] for c in piv.columns}, "base": base}

    return {
        "dolar": semanal({"tc_mayorista": "Mayorista", "tc_minorista": "Minorista", "banda_piso": "Banda: piso",
                          "banda_techo": "Banda: techo"}),
        "reservas": semanal({"reservas": "Reservas"}),
        "tasas": semanal({"badlar": "BADLAR", "tamar": "TAMAR", "tasa_plazo_fijo": "Plazo fijo 30 días",
                          "tasa_personales": "Préstamos personales"}),
        "m2": semanal({"m2_privado_ia": "M2 privado"}),
        "credito": credito,
        "expectativas": semanal({"inflacion_esperada": "Inflación esperada a 12 meses"}, desde="2018-01-01"),
        "indices": semanal({"uva": "UVA", "icl": "ICL"}, desde="2020-07-01"),
        "kpi": {c: kpi(c) for c in ("tc_mayorista", "tc_minorista", "reservas", "badlar", "tasa_plazo_fijo",
                                    "inflacion_esperada", "banda_techo", "uva")},
        "fuentes": [{"clave": c, "nombre": s.get("nombre", c), "ultimo": s.get("ultimo"), "atrasada": bool(s.get("atrasada"))}
                    for c, s in est.items()],
    }


def semaforo_extra(m: dict | None) -> list[dict]:
    if not m:
        return []
    out = []

    def item(nombre, p, valor, ref, texto, delta, mejor_si_sube, umbral, unidad):
        if valor is None or ref is None or p is None:
            return
        estado = "templado" if abs(delta) < umbral else ("bien" if (delta > 0) == mejor_si_sube else "mal")
        out.append({"indicador": nombre, "periodo": p, "valor": round(valor, 2), "unidad": unidad,
                    "referencia": round(ref, 2), "texto_referencia": texto, "delta": round(delta, 2), "estado": estado})

    sup = m["consumo"]["real"]
    vals = sup["series"].get("Supermercados", [])
    ult, prom = var_vs_prom(vals)
    if ult is not None:
        p = [x for x, v in zip(sup["p"], vals) if v is not None][-1]
        item("Consumo en supermercados", p, ult, prom, "frente al promedio de los 12 meses previos",
             (ult / prom - 1) * 100, True, 1.0, "índice")
    isac = m["construccion"]["isac"]
    vals = isac["series"].get("ISAC desestacionalizado", [])
    ult, prom = var_vs_prom(vals)
    if ult is not None:
        p = [x for x, v in zip(isac["p"], vals) if v is not None][-1]
        item("Construcción (ISAC)", p, ult, prom, "frente al promedio de los 12 meses previos",
             (ult / prom - 1) * 100, True, 1.0, "índice")
    k = m["industria"]["kpi"]
    if k["v"] is not None and k["pp_ia"] is not None:
        item("Capacidad instalada industrial", k["p"], k["v"], k["v"] - k["pp_ia"], "frente al mismo mes del año anterior",
             k["pp_ia"], True, 1.0, "%")
    return out


def explorador_extra(tablas: list[dict]) -> None:
    """Agrega la tabla series_extra al explorador."""
    archivo = SITIO / "datos" / "series_extra.parquet"
    if not archivo.exists():
        return
    df = pd.read_parquet(archivo)
    dims = []
    for c, label in (("grupo", "Grupo"), ("nombre", "Serie"), ("unidad", "Unidad"), ("frecuencia", "Frecuencia")):
        vals = sorted(df[c].dropna().astype(str).unique().tolist())
        if len(vals) >= 2:
            dims.append({"col": c, "label": label, "valores": vals, "numerica": False})
    tablas.append({
        "tabla": "series_extra",
        "titulo": "Más indicadores (consumo, construcción, industria, turismo, macro, empleo, ingresos y cuentas públicas)",
        "filas": int(len(df)),
        "ultimo_periodo": pd.to_datetime(df["fecha"]).max().strftime("%Y-%m"),
        "tiempo": "mes",
        "anios": [int(df["anio"].min()), int(df["anio"].max())],
        "dims": dims,
        "medidas": [{"col": "valor", "label": "Valor", "sumable": False}],
        "columnas": [{"col": "grupo", "label": "Grupo"}, {"col": "nombre", "label": "Serie"},
                     {"col": "unidad", "label": "Unidad"}, {"col": "valor", "label": "Valor"}],
    })


    archivo = SITIO / "datos" / "bcra.parquet"
    if archivo.exists():
        df = pd.read_parquet(archivo)
        df["fecha"] = pd.to_datetime(df["fecha"])
        df["anio"] = df["fecha"].dt.year.astype("int32")
        df["mes"] = df["fecha"].dt.month.astype("int32")
        df.to_parquet(archivo, index=False)
        tablas.append({
            "tabla": "bcra",
            "titulo": "BCRA: dólar, reservas, tasas, dinero, crédito e índices (datos diarios)",
            "filas": int(len(df)),
            "ultimo_periodo": df["fecha"].max().strftime("%Y-%m"),
            "tiempo": "mes",
            "anios": [int(df["anio"].min()), int(df["anio"].max())],
            "dims": [{"col": c, "label": lb, "valores": sorted(df[c].dropna().astype(str).unique().tolist()), "numerica": False}
                     for c, lb in (("grupo", "Grupo"), ("nombre", "Variable"), ("unidad", "Unidad"))],
            "medidas": [{"col": "valor", "label": "Valor", "sumable": False}],
            "columnas": [{"col": "fecha", "label": "Fecha"}, {"col": "grupo", "label": "Grupo"}, {"col": "nombre", "label": "Variable"},
                         {"col": "unidad", "label": "Unidad"}, {"col": "valor", "label": "Valor"}],
        })


def _periodo(ultimo: str | None, frecuencia: str | None) -> str | None:
    """Normaliza el último período: '2026-04-01' trimestral -> '2026-T2'; mensual -> '2026-04'."""
    if not ultimo:
        return None
    u = str(ultimo)
    if "-T" in u:
        return u
    if frecuencia == "T" and len(u) >= 7:
        return f"{u[:4]}-T{(int(u[5:7]) - 1) // 3 + 1}"
    return u[:7]


def _n(x) -> int:
    return len(x) if isinstance(x, list) else int(x or 0)


def main() -> None:
    SALIDA.mkdir(parents=True, exist_ok=True)
    estado = json.loads((DIR / "estado.json").read_text(encoding="utf-8"))
    archivo_es = DIR / "estado_series.json"
    estado_series = json.loads(archivo_es.read_text(encoding="utf-8")) if archivo_es.exists() else None
    archivo_ep = DIR / "estado_planillas.json"
    if archivo_ep.exists():
        ep = json.loads(archivo_ep.read_text(encoding="utf-8"))
        if estado_series is None:
            estado_series = {"generado": ep["generado"], "fuente": ep["fuente"], "series_ok": 0, "series_total": 0,
                             "atrasadas": 0, "series": []}
        estado_series = {**estado_series,
                         "series_ok": estado_series["series_ok"] + ep["series_ok"],
                         "series_total": estado_series["series_total"] + ep["series_total"],
                         "atrasadas": _n(estado_series["atrasadas"]) + _n(ep["atrasadas"]),
                         "series": estado_series["series"] + ep["series"]}
    m = mas(estado_series)
    if m:
        (SALIDA / "mas.json").write_text(json.dumps(m, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"mas.json {(SALIDA / 'mas.json').stat().st_size / 1024:.0f} KB")

    b = bcra()
    if b:
        (SALIDA / "bcra.json").write_text(json.dumps(b, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"bcra.json {(SALIDA / 'bcra.json').stat().st_size / 1024:.0f} KB")

    pr, bo, pu = precios(), bolsillo(), pulso()
    tableros = {
        "generado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ingesta": estado["generado"],
        "precios": pr,
        "bolsillo": bo,
        "pulso": pu,
        "semaforo": semaforo(pr, bo, pu) + semaforo_extra(m),
    }
    (SALIDA / "tableros.json").write_text(json.dumps(tableros, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    catalogo = {k: v for k, v in estado.items() if k != "servicios"}
    catalogo["servicios"] = [
        {k: s.get(k) for k in ("tabla", "endpoint", "descripcion", "ok", "error", "filas", "ultimo_periodo",
                                "ultima_ingesta_ok", "dato_nuevo")}
        for s in estado["servicios"]
    ]
    if estado_series:
        catalogo["series_extra"] = {k: estado_series[k] for k in ("generado", "fuente", "series_ok", "series_total", "atrasadas")}
        catalogo["series_extra"]["series"] = [
            {**{k: x.get(k) for k in ("clave", "id", "grupo", "nombre", "unidad", "ok", "atrasada", "fuente", "discontinuada")},
             "ultimo": _periodo(x.get("ultimo"), x.get("frecuencia"))}
            for x in estado_series["series"]
        ]
    archivo_eb = DIR / "estado_bcra.json"
    if archivo_eb.exists():
        eb = json.loads(archivo_eb.read_text(encoding="utf-8"))
        catalogo["bcra"] = {k: eb[k] for k in ("generado", "fuente", "series_ok", "series_total", "atrasadas")}
        catalogo["bcra"]["series"] = [{k: x.get(k) for k in ("clave", "id", "grupo", "nombre", "unidad", "ok", "atrasada", "ultimo")}
                                      for x in eb["series"]]
    (SALIDA / "catalogo.json").write_text(json.dumps(catalogo, ensure_ascii=False, indent=1), encoding="utf-8")

    # Parquet descargables desde el sitio (no se suben al repo, solo al deploy)
    descargas = SITIO / "datos"
    descargas.mkdir(exist_ok=True)
    for f in DIR.glob("*.parquet"):
        if f.name != "planillas.parquet":
            shutil.copy2(f, descargas / f.name)
    extra = _extra()
    if extra is not None:
        extra.drop(columns=["p"]).to_parquet(descargas / "series_extra.parquet", index=False)
    explorador(estado)

    tam = (SALIDA / "tableros.json").stat().st_size
    print(f"tableros.json {tam/1024:.0f} KB · semáforo: {len(tableros['semaforo'])} indicadores")


if __name__ == "__main__":
    main()
