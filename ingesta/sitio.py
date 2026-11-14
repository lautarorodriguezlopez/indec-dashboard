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
    (SALIDA / "explorador.json").write_text(json.dumps({"tablas": tablas}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"explorador.json: {len(tablas)} tablas")


def main() -> None:
    SALIDA.mkdir(parents=True, exist_ok=True)
    estado = json.loads((DIR / "estado.json").read_text(encoding="utf-8"))

    pr, bo, pu = precios(), bolsillo(), pulso()
    tableros = {
        "generado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ingesta": estado["generado"],
        "precios": pr,
        "bolsillo": bo,
        "pulso": pu,
        "semaforo": semaforo(pr, bo, pu),
    }
    (SALIDA / "tableros.json").write_text(json.dumps(tableros, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    catalogo = {k: v for k, v in estado.items() if k != "servicios"}
    catalogo["servicios"] = [
        {k: s.get(k) for k in ("tabla", "endpoint", "descripcion", "ok", "error", "filas", "ultimo_periodo",
                                "ultima_ingesta_ok", "dato_nuevo")}
        for s in estado["servicios"]
    ]
    (SALIDA / "catalogo.json").write_text(json.dumps(catalogo, ensure_ascii=False, indent=1), encoding="utf-8")

    # Parquet descargables desde el sitio (no se suben al repo, solo al deploy)
    descargas = SITIO / "datos"
    descargas.mkdir(exist_ok=True)
    for f in DIR.glob("*.parquet"):
        shutil.copy2(f, descargas / f.name)
    explorador(estado)

    tam = (SALIDA / "tableros.json").stat().st_size
    print(f"tableros.json {tam/1024:.0f} KB · semáforo: {len(tableros['semaforo'])} indicadores")


if __name__ == "__main__":
    main()
