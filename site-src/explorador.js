/*
 * Explorador de los 19 servicios del INDEC.
 *
 * Seguridad (ver SECURITY.md):
 * - Sin backend: las consultas corren en el navegador con DuckDB-WASM, servido
 *   desde el propio sitio. No hay servidor ni API propia que atacar.
 * - Lista blanca: tablas y columnas salen de data/explorador.json y además se
 *   validan con una expresión regular antes de entrar en el SQL.
 * - Consultas parametrizadas: todo valor elegido por el usuario va como
 *   parámetro (?) de una sentencia preparada, nunca concatenado al SQL.
 * - Límites de consumo: tabla paginada de a 100 filas, descarga de hasta
 *   200.000 filas y una sola consulta a la vez.
 * - Salida segura: el texto se inserta con textContent o con esc(); el CSV
 *   neutraliza fórmulas (inyección CSV).
 */
import * as duckdb from "@duckdb/duckdb-wasm";

const T = window.Tablero; // helpers de gráficos del panel (app.js)
const ID = /^[a-z][a-z0-9_]{0,62}$/;
const POR_PAGINA = 100;
const MAX_DESCARGA = 200000;
const MAX_SERIES = 4;
const RAIZ = new URL(".", document.baseURI);

let meta = null;
let db = null;
let conn = null;
let ocupado = false;
const st = { tabla: null, filtros: {}, desde: null, hasta: null, medida: null, comparar: "", series: [], pagina: 0, total: 0 };

const $ = (sel) => document.querySelector(sel);
const esc = T.esc;

function ident(c) {
  if (!ID.test(c)) throw new Error(`Identificador no permitido: ${c}`);
  return `"${c}"`;
}
function tablaMeta(nombre) {
  const t = meta.tablas.find((x) => x.tabla === nombre);
  if (!t) throw new Error("Tabla desconocida");
  return t;
}

// ------------------------------------------------------------------ motor
async function motor() {
  if (conn) return conn;
  estado("Cargando el motor de consultas (unos 8 MB, solo la primera vez)…");
  const worker = new Worker(new URL("vendor/duckdb/duckdb-browser-eh.worker.js", RAIZ));
  db = new duckdb.AsyncDuckDB(new duckdb.VoidLogger(), worker);
  await db.instantiate(new URL("vendor/duckdb/duckdb-eh.wasm", RAIZ).href);
  await db.registerFileURL("explorador.duckdb", new URL("datos/explorador.duckdb", RAIZ).href, duckdb.DuckDBDataProtocol.HTTP, false);
  conn = await db.connect();
  // Base de solo lectura y configuración bloqueada: aunque alguien lograra
  // inyectar SQL, no podría instalar extensiones, leer otros archivos ni
  // cambiar estos ajustes.
  await conn.query("SET autoinstall_known_extensions = false");
  await conn.query("SET autoload_known_extensions = false");
  await conn.query("ATTACH 'explorador.duckdb' AS ex (READ_ONLY)");
  await conn.query("USE ex");
  await conn.query("SET enable_external_access = false");
  await conn.query("SET lock_configuration = true");
  return conn;
}

// Arma WHERE con parámetros a partir del estado
function where(t, { sinComparar = false } = {}) {
  const partes = [];
  const params = [];
  for (const d of t.dims) {
    if (d.col === st.comparar && !sinComparar) {
      const vals = st.series.filter((v) => v !== "");
      if (vals.length) {
        partes.push(`CAST(${ident(d.col)} AS VARCHAR) IN (${vals.map(() => "?").join(", ")})`);
        params.push(...vals);
      }
      continue;
    }
    const v = st.filtros[d.col];
    if (v !== undefined && v !== "") {
      partes.push(`CAST(${ident(d.col)} AS VARCHAR) = ?`);
      params.push(v);
    }
  }
  if (t.tiempo && st.desde != null && st.hasta != null) {
    partes.push(`_anio BETWEEN ? AND ?`);
    params.push(st.desde, st.hasta);
  }
  return { sql: partes.length ? ` WHERE ${partes.join(" AND ")}` : "", params };
}

async function consulta(sql, params) {
  const stmt = await conn.prepare(sql);
  try {
    return await stmt.query(...params);
  } finally {
    await stmt.close();
  }
}

// ------------------------------------------------------------------ interfaz
function estado(msg, error = false) {
  const e = $("#ex-estado");
  e.textContent = msg || "";
  e.className = error ? "nota falla" : "nota";
}

function opcion(sel, valor, texto) {
  const o = document.createElement("option");
  o.value = valor;
  o.textContent = texto;
  sel.appendChild(o);
}

function campo(etq, control) {
  const l = document.createElement("label");
  l.className = "ex-campo";
  const s = document.createElement("span");
  s.textContent = etq;
  l.append(s, control);
  return l;
}

function selectValores(d, valorActual, conTodos = true, textoTodos = "Todos") {
  const s = document.createElement("select");
  if (conTodos) opcion(s, "", textoTodos);
  for (const v of d.valores) opcion(s, v, v);
  s.value = valorActual ?? "";
  return s;
}

function armarControles() {
  const t = tablaMeta(st.tabla);
  $("#ex-desc").textContent = `${t.filas.toLocaleString("es-AR")} filas · último dato: ${T.fmtP(t.ultimo_periodo)}`;
  const cont = $("#ex-filtros");
  cont.replaceChildren();

  for (const d of t.dims) {
    if (d.col === st.comparar) continue;
    const s = selectValores(d, st.filtros[d.col], true, d.valores.length > 1 ? "Todos" : d.valores[0]);
    s.addEventListener("change", () => { st.filtros[d.col] = s.value; st.pagina = 0; correr(); });
    cont.appendChild(campo(d.label, s));
  }

  if (t.tiempo && t.anios) {
    const anios = [];
    for (let a = t.anios[0]; a <= t.anios[1]; a++) anios.push(a);
    const mk = (valor, cb) => {
      const s = document.createElement("select");
      anios.forEach((a) => opcion(s, String(a), String(a)));
      s.value = String(valor);
      s.addEventListener("change", () => { cb(+s.value); st.pagina = 0; correr(); });
      return s;
    };
    cont.appendChild(campo("Desde", mk(st.desde, (v) => { st.desde = Math.min(v, st.hasta); })));
    cont.appendChild(campo("Hasta", mk(st.hasta, (v) => { st.hasta = Math.max(v, st.desde); })));
  }

  // Medida y comparación (para el gráfico)
  const g = $("#ex-grafico-ctrl");
  g.replaceChildren();
  if (t.medidas.length) {
    const sm = document.createElement("select");
    t.medidas.forEach((m) => opcion(sm, m.col, m.label));
    sm.value = st.medida;
    sm.addEventListener("change", () => { st.medida = sm.value; correr(); });
    g.appendChild(campo("Medida a graficar", sm));
  }
  if (t.tiempo && t.dims.length) {
    const sc = document.createElement("select");
    opcion(sc, "", "Nada (una sola serie)");
    t.dims.forEach((d) => opcion(sc, d.col, d.label));
    sc.value = st.comparar;
    sc.addEventListener("change", () => {
      st.comparar = sc.value;
      const d = t.dims.find((x) => x.col === st.comparar);
      st.series = d ? d.valores.slice(0, 2) : [];
      armarControles();
      correr();
    });
    g.appendChild(campo("Comparar por", sc));
    const d = t.dims.find((x) => x.col === st.comparar);
    if (d) {
      for (let i = 0; i < MAX_SERIES; i++) {
        const s = selectValores(d, st.series[i] ?? "", true, "—");
        s.addEventListener("change", () => { st.series[i] = s.value; correr(); });
        g.appendChild(campo(`Serie ${i + 1}`, s));
      }
    }
  }
}

function elegirTabla(nombre) {
  const t = tablaMeta(nombre);
  st.tabla = t.tabla;
  st.filtros = {};
  // Valores iniciales razonables (solo si hay exactamente una coincidencia)
  const PREF = {
    region: /^(nacional|total del país)$/i,
    nivel: /^nivel general$/i,
    tipo_de_indicador: /^v_m$/,
    tipo_de_indicador_descripcion: /^índice serie desestacionalizada$/i,
    serie: /^serie desestacionalizada$/i,
  };
  for (const d of t.dims) {
    const re = PREF[d.col];
    const hits = re ? d.valores.filter((v) => re.test(v)) : [];
    if (hits.length === 1) st.filtros[d.col] = hits[0];
  }
  st.desde = t.anios ? Math.max(t.anios[0], t.anios[1] - 4) : null;
  st.hasta = t.anios ? t.anios[1] : null;
  st.medida = t.medidas[0]?.col ?? null;
  st.comparar = "";
  st.series = [];
  st.pagina = 0;
  armarControles();
  correr();
}

// ------------------------------------------------------------------ consultas
let pendiente = false;
async function correr() {
  if (ocupado) { pendiente = true; return; }
  ocupado = true;
  bloquear(true);
  try {
    await motor();
    const t = tablaMeta(st.tabla);
    estado("Consultando…");
    const w = where(t);
    const tab = ident(t.tabla);
    const total = await consulta(`SELECT count(*)::INTEGER AS n FROM ${tab}${w.sql}`, w.params);
    st.total = total.toArray()[0].n;
    await tabla(t, w);
    await grafico(t, w);
    estado(`${st.total.toLocaleString("es-AR")} filas con estos filtros.`);
  } catch (e) {
    console.error(e);
    estado("No se pudo hacer la consulta. Probá con otros filtros o recargá la página.", true);
  } finally {
    ocupado = false;
    bloquear(false);
    if (pendiente) { pendiente = false; correr(); }
  }
}

function bloquear(si) {
  document.querySelectorAll("#explorador select, #explorador button").forEach((x) => { x.disabled = si; });
}

function ordenTiempo(t) {
  return t.tiempo ? ` ORDER BY _periodo DESC` : "";
}

async function tabla(t, w) {
  const cols = t.columnas.map((c) => ident(c.col)).join(", ");
  const per = t.tiempo ? "_periodo, " : "";
  const res = await consulta(
    // OFFSET: entero calculado acá (no viene de texto del usuario) y acotado
    `SELECT ${per}${cols} FROM ${ident(t.tabla)}${w.sql}${ordenTiempo(t)} LIMIT ${POR_PAGINA} OFFSET ${Math.max(0, Math.trunc(st.pagina)) * POR_PAGINA}`,
    w.params,
  );
  const filas = res.toArray().map((r) => r.toJSON());
  const thead = document.createElement("thead");
  const trh = document.createElement("tr");
  const encabezados = (t.tiempo ? [{ col: "_periodo", label: "Período" }] : []).concat(t.columnas);
  for (const c of encabezados) { const th = document.createElement("th"); th.textContent = c.label; trh.appendChild(th); }
  thead.appendChild(trh);
  const tbody = document.createElement("tbody");
  for (const f of filas) {
    const tr = document.createElement("tr");
    for (const c of encabezados) {
      const td = document.createElement("td");
      const v = f[c.col];
      td.textContent = c.col === "_periodo" ? T.fmtP(v) : formato(v);
      if (typeof v === "string" && v.length > 40) td.className = "wrap";
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
  $("#ex-tabla").replaceChildren(thead, tbody);
  const paginas = Math.max(1, Math.ceil(st.total / POR_PAGINA));
  $("#ex-pag-txt").textContent = `Página ${st.pagina + 1} de ${paginas.toLocaleString("es-AR")}`;
  $("#ex-prev").dataset.off = st.pagina <= 0 ? "1" : "";
  $("#ex-next").dataset.off = st.pagina >= paginas - 1 ? "1" : "";
}

// Eje compacto para números grandes: 9.000 M, 350 mil
function compacto(v) {
  const a = Math.abs(v);
  if (a >= 1e9) return T.num(v / 1e9, a % 1e9 ? 1 : 0) + " mil M";
  if (a >= 1e6) return T.num(v / 1e6, 0) + " M";
  if (a >= 1e4) return T.num(v / 1e3, 0) + " mil";
  return T.num(v, Number.isInteger(v) ? 0 : 1);
}

function formato(v) {
  if (v == null) return "—";
  if (typeof v === "bigint") v = Number(v);
  if (typeof v === "number") return Number.isInteger(v) ? v.toLocaleString("es-AR") : v.toLocaleString("es-AR", { maximumFractionDigits: 4 });
  return String(v);
}

async function grafico(t, w) {
  const fig = $("#ex-grafico");
  const m = t.medidas.find((x) => x.col === st.medida);
  if (!t.tiempo || !m) { fig.hidden = true; return; }
  fig.hidden = false;
  const comparar = t.dims.find((d) => d.col === st.comparar);
  const serieExpr = comparar ? `CAST(${ident(comparar.col)} AS VARCHAR)` : `'${"Serie"}'`;
  // ¿Hay más de una fila por período y serie? Entonces hace falta fijar filtros (salvo medidas sumables)
  const chequeo = await consulta(
    `SELECT max(n)::INTEGER AS m FROM (SELECT count(*) AS n FROM ${ident(t.tabla)}${w.sql} GROUP BY _periodo, ${serieExpr})`,
    w.params,
  );
  const repetidas = (chequeo.toArray()[0]?.m ?? 0) > 1;
  if (repetidas && !m.sumable) {
    fig.replaceChildren();
    const h = document.createElement("h3"); h.textContent = "Gráfico";
    const p = document.createElement("p"); p.className = "desc";
    p.textContent = "Para graficar, elegí un valor en los filtros hasta que quede una sola serie por período (por ejemplo, una región y un tipo de indicador).";
    fig.append(h, p);
    return;
  }
  const agg = m.sumable ? `sum(${ident(m.col)})` : `any_value(${ident(m.col)})`;
  const res = await consulta(
    `SELECT _periodo AS p, ${serieExpr} AS s, ${agg}::DOUBLE AS v FROM ${ident(t.tabla)}${w.sql} GROUP BY 1, 2 ORDER BY 1`,
    w.params,
  );
  const filas = res.toArray().map((r) => r.toJSON());
  const per = [...new Set(filas.map((f) => f.p))].sort();
  const nombres = comparar ? st.series.filter((v) => v !== "") : ["Serie"];
  const idx = new Map(per.map((p, i) => [p, i]));
  const series = nombres.slice(0, MAX_SERIES).map((n) => {
    const vals = new Array(per.length).fill(null);
    filas.filter((f) => f.s === n).forEach((f) => { vals[idx.get(f.p)] = f.v; });
    return { nombre: comparar ? n : m.label, valores: vals };
  });
  if (!per.length) { fig.hidden = true; return; }
  T.lineas(fig, {
    titulo: `${m.label}${m.sumable && repetidas ? " (suma)" : ""}`,
    desc: t.titulo,
    p: per,
    series,
    rango: "todo",
    fmt: (v) => T.num(v, Math.abs(v) >= 1000 ? 0 : 2),
    fmtEje: compacto,
  });
}

// ------------------------------------------------------------------ descarga CSV
function celdaCSV(v) {
  if (v == null) return "";
  if (typeof v === "bigint") v = Number(v);
  if (typeof v === "number") return String(v);
  let s = String(v);
  // Inyección CSV (OWASP): un texto que empieza con = + - @ tab o CR se toma como fórmula
  if (/^[=+\-@\t\r]/.test(s)) s = "'" + s;
  return /[",;\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

async function descargar() {
  if (ocupado) return;
  ocupado = true;
  bloquear(true);
  try {
    const t = tablaMeta(st.tabla);
    if (st.total > MAX_DESCARGA) {
      estado(`Son ${st.total.toLocaleString("es-AR")} filas: el máximo para descargar es ${MAX_DESCARGA.toLocaleString("es-AR")}. Achicá los filtros o bajá el archivo completo en la sección Datos.`, true);
      return;
    }
    estado("Preparando el CSV…");
    const w = where(t);
    const cols = (t.tiempo ? [{ col: "_periodo", label: "Período" }] : []).concat(t.columnas);
    const res = await consulta(
      `SELECT ${cols.map((c) => ident(c.col)).join(", ")} FROM ${ident(t.tabla)}${w.sql}${ordenTiempo(t)} LIMIT ${MAX_DESCARGA}`,
      w.params,
    );
    const lineas = [cols.map((c) => celdaCSV(c.label)).join(",")];
    for (const r of res.toArray()) {
      const f = r.toJSON();
      lineas.push(cols.map((c) => celdaCSV(f[c.col])).join(","));
    }
    const blob = new Blob(["﻿" + lineas.join("\r\n")], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `indec_${t.tabla}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    estado(`Descargadas ${(lineas.length - 1).toLocaleString("es-AR")} filas. Fuente: INDEC.`);
  } catch (e) {
    console.error(e);
    estado("No se pudo preparar la descarga.", true);
  } finally {
    ocupado = false;
    bloquear(false);
  }
}

// ------------------------------------------------------------------ inicio
export async function iniciar() {
  const r = await fetch("data/explorador.json");
  if (!r.ok) throw new Error("No se pudo cargar el catálogo del explorador");
  meta = await r.json();
  meta.tablas = meta.tablas.filter((t) => ID.test(t.tabla));
  const sel = $("#ex-tabla-sel");
  meta.tablas.forEach((t) => opcion(sel, t.tabla, t.titulo));
  sel.addEventListener("change", () => elegirTabla(sel.value));
  $("#ex-prev").addEventListener("click", () => { if (st.pagina > 0 && !ocupado) { st.pagina--; correr(); } });
  $("#ex-next").addEventListener("click", () => {
    if (!ocupado && (st.pagina + 1) * POR_PAGINA < st.total) { st.pagina++; correr(); }
  });
  $("#ex-csv").addEventListener("click", descargar);
  sel.value = meta.tablas.some((t) => t.tabla === "ipc") ? "ipc" : meta.tablas[0].tabla;
  elegirTabla(sel.value);
}
