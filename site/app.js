/* Termómetro económico — gráficos hechos a mano en SVG, sin dependencias.
 * Seguridad: todo texto que viene de los datos pasa por esc() antes de ir a innerHTML;
 * sin estilos en línea (CSP style-src 'self'); solo se piden archivos del mismo sitio. */
(() => {
  "use strict";

  const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
  const COL = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)"];
  const NS = "http://www.w3.org/2000/svg";
  const tip = document.getElementById("tooltip");
  const BUILD = document.querySelector('meta[name="build"]')?.content || "";
  const Q = /^\d{8,14}$/.test(BUILD) ? `?v=${BUILD}` : ""; // misma versión para código y datos
  const TABS = ["portada", "precios", "ingresos", "actividad", "dinero", "cuentas", "datos"];
  // Enlaces viejos (compartidos antes de la reorganización) siguen funcionando
  const ALIAS = { bolsillo: "ingresos", mas: "actividad", explorador: "datos", catalogo: "datos" };
  const estado = { tab: "portada", region: "Nacional", rango: { precios: "3", ingresos: "3", actividad: "3", dinero: "3", cuentas: "3" } };

  // ---------------------------------------------------------------- datos (carga diferida, una vez)
  const DATA = {};
  const pedidos = {};
  const cargar = (n) => (pedidos[n] ||= fetch(`data/${n}.json${Q}`)
    .then((r) => { if (!r.ok) throw new Error(`${n}: ${r.status}`); return r.json(); })
    .then((d) => (DATA[n] = d))
    .catch((e) => { delete pedidos[n]; throw e; }));
  const NECESITA = {
    portada: ["tableros", "catalogo"], precios: ["tableros"], ingresos: ["tableros", "mas"],
    actividad: ["tableros", "mas"], dinero: ["bcra"], cuentas: ["tableros", "mas"], datos: ["catalogo"],
  };

  // ---------------------------------------------------------------- formato
  const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const num = (v, d = 1) =>
    v == null || Number.isNaN(v) ? "—" : v.toLocaleString("es-AR", { minimumFractionDigits: d, maximumFractionDigits: d });
  const signo = (v, d = 1) => (v == null ? "—" : (v > 0 ? "+" : v < 0 ? "−" : "") + num(Math.abs(v), d));
  const ejePesos = (t) => (t === 0 ? "0" : t >= 1e6 ? num(t / 1e6, 1) + " M" : num(t / 1e3, 0) + " mil");
  const pesos = (v) => (v == null ? "—" : "$ " + Math.round(v).toLocaleString("es-AR"));
  const pct = (v) => num(v) + " %";
  const $ = (id) => document.getElementById(id);

  function fmtP(p, corto = false) {
    if (!p) return "—";
    const m = /^(\d{4})-(\d{2})$/.exec(p);
    if (m) return corto ? `${MESES[+m[2] - 1]}-${m[1].slice(2)}` : `${MESES[+m[2] - 1]} ${m[1]}`;
    const f = /^(\d{4})-(\d{2})-(\d{2})$/.exec(p);
    if (f) return corto ? `${MESES[+f[2] - 1]}-${f[1].slice(2)}` : `${+f[3]} ${MESES[+f[2] - 1]} ${f[1]}`;
    const q = /^(\d{4})-([TS])(\d)$/.exec(p);
    if (q && corto) return `${q[2]}${q[3]}-${q[1].slice(2)}`;
    if (q) return q[2] === "T" ? `${q[3]}.º trim. ${q[1]}` : `${q[3]}.º sem. ${q[1]}`;
    return p;
  }
  function ordinal(p) {
    let m = /^(\d{4})-(\d{2})(?:-(\d{2}))?$/.exec(p);
    if (m) return +m[1] * 12 + +m[2] + (m[3] ? (+m[3] - 1) / 31 : 0);
    m = /^(\d{4})-([TS])(\d)$/.exec(p);
    if (m) return +m[1] * 12 + +m[3] * (m[2] === "T" ? 3 : 6);
    return +p.slice(0, 4) * 12;
  }

  // Recorta períodos y series al rango elegido ("1", "3" años o "todo")
  function recortar(p, series, rango) {
    if (rango === "todo" || !p.length) return { p, series };
    const ult = ordinal(p[p.length - 1]);
    const desde = ult - 12 * +rango;
    const idx = p.map((x, i) => (ordinal(x) > desde ? i : -1)).filter((i) => i >= 0);
    return { p: idx.map((i) => p[i]), series: series.map((s) => ({ ...s, valores: idx.map((i) => s.valores[i]) })) };
  }

  // ---------------------------------------------------------------- utilidades SVG
  function el(tag, attrs = {}, parent) {
    const n = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    if (parent) parent.appendChild(n);
    return n;
  }
  function escalaNice(min, max, n = 5) {
    if (min === max) { min -= 1; max += 1; }
    const paso0 = (max - min) / n;
    const mag = Math.pow(10, Math.floor(Math.log10(paso0)));
    const paso = [1, 2, 2.5, 5, 10].map((f) => f * mag).find((s) => s >= paso0) || 10 * mag;
    const lo = Math.floor(min / paso) * paso;
    const hi = Math.ceil(max / paso) * paso;
    const ticks = [];
    for (let v = lo; v <= hi + paso / 2; v += paso) ticks.push(+v.toFixed(10));
    return { lo, hi, ticks, paso };
  }
  const ancho = (fig) => Math.max(260, Math.round(fig.clientWidth - 32));

  function mostrarTip(html, ev) {
    tip.innerHTML = html;
    tip.hidden = false;
    const r = tip.getBoundingClientRect();
    let x = ev.clientX + 14;
    let y = ev.clientY + 14;
    if (x + r.width > window.innerWidth - 8) x = Math.max(8, ev.clientX - r.width - 14);
    if (y + r.height > window.innerHeight - 8) y = Math.max(8, ev.clientY - r.height - 14);
    tip.style.left = x + "px";
    tip.style.top = y + "px";
  }
  const ocultarTip = () => { tip.hidden = true; };

  function cabecera(fig, titulo, desc) {
    fig.replaceChildren();
    const h = document.createElement("h3");
    h.textContent = titulo;
    fig.appendChild(h);
    if (desc) {
      const d = document.createElement("p");
      d.className = "desc";
      d.textContent = desc;
      fig.appendChild(d);
    }
  }
  function leyenda(fig, series) {
    if (series.length < 2) return;
    const l = document.createElement("div");
    l.className = "leyenda";
    l.innerHTML = series.map((s) => `<span><i class="sw${s.k ?? 0}"></i>${esc(s.nombre)}</span>`).join("");
    fig.appendChild(l);
  }
  // Las tablas abiertas siguen abiertas al redibujar (cambio de rango, giro del celular)
  const abiertas = new Set();
  function tablaDatos(fig, p, series, fmt, max = 24) {
    const det = document.createElement("details");
    det.className = "tabla-datos";
    const desde = Math.max(0, p.length - max);
    const filas = p.slice(desde).map((x, j) => {
      const i = desde + j;
      return `<tr><td>${esc(fmtP(x))}</td>${series.map((s) => `<td>${esc(fmt(s.valores[i]))}</td>`).join("")}</tr>`;
    }).reverse();
    det.innerHTML = `<summary>Ver tabla${p.length > max ? ` (últimos ${max} períodos)` : ""}</summary>
      <div class="tabla-wrap"><table class="tabla"><thead><tr><th>Período</th>${series
        .map((s) => `<th>${esc(s.nombre)}</th>`).join("")}</tr></thead><tbody>${filas.join("")}</tbody></table></div>`;
    const clave = fig.id;
    det.open = abiertas.has(clave);
    det.addEventListener("toggle", () => (det.open ? abiertas.add(clave) : abiertas.delete(clave)));
    fig.appendChild(det);
  }
  function nota(fig, texto) {
    if (!texto) return;
    const n = document.createElement("p");
    n.className = "nota";
    n.textContent = texto;
    fig.appendChild(n);
  }
  function sinDatos(fig, titulo) {
    if (!fig) return;
    cabecera(fig, titulo);
    nota(fig, "Este dato no está disponible ahora. Volvé a intentar más tarde.");
  }

  // ---------------------------------------------------------------- gráfico de líneas
  function lineas(fig, cfg) {
    if (!fig) return;
    const { titulo, desc, rango = "todo", fmt = (v) => num(v), cero = false } = cfg;
    if (!cfg.p || !cfg.series) return sinDatos(fig, titulo);
    const recorte = recortar(cfg.p, cfg.series.map((s, i) => ({ color: COL[i], k: i, ...s })), rango);
    const p = recorte.p;
    const series = recorte.series;
    cabecera(fig, titulo, desc);
    leyenda(fig, series);

    const W = ancho(fig), H = cfg.alto || 240;
    const m = { l: 48, r: 14, t: 10, b: 26 };
    const vals = series.flatMap((s) => s.valores).filter((v) => v != null);
    if (!vals.length) { nota(fig, "Sin datos para este período."); return; }
    let mn = Math.min(...vals), mx = Math.max(...vals);
    if (cero || (mn < 0 && mx > 0)) { mn = Math.min(mn, 0); mx = Math.max(mx, 0); }
    const pad = (mx - mn) * 0.04;
    const bajo = mn >= 0 ? Math.max(0, mn - pad) : mn - pad;
    let es = escalaNice(bajo, mx + pad);
    if (mn >= 0 && es.lo < 0) es = escalaNice(0, mx + pad);
    const x = (i) => m.l + (p.length === 1 ? 0 : (i / (p.length - 1)) * (W - m.l - m.r));
    const y = (v) => m.t + (1 - (v - es.lo) / (es.hi - es.lo)) * (H - m.t - m.b);

    const svg = el("svg", { class: "chart", viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": titulo });
    const g = el("g", { class: "grid" }, svg);
    for (const t of es.ticks) {
      el("line", { x1: m.l, x2: W - m.r, y1: y(t), y2: y(t) }, g);
      const tx = el("text", { x: m.l - 6, y: y(t) + 4, "text-anchor": "end" }, svg);
      tx.textContent = cfg.fmtEje ? cfg.fmtEje(t) : num(t, es.paso < 1 ? 1 : 0);
    }
    if (es.lo < 0 && es.hi > 0) el("line", { class: "zero", x1: m.l, x2: W - m.r, y1: y(0), y2: y(0) }, svg);

    // Etiquetas del eje x: hasta ~7, en enero si la serie es larga
    const nEt = Math.max(2, Math.floor((W - m.l - m.r) / 90));
    const largo = p.length > 30;
    let cand = p.map((_, i) => i);
    const diaria = /^\d{4}-\d{2}-\d{2}$/.test(p[0] || "");
    const corteD = p.length > 120 ? 4 : 7;
    if (diaria) cand = cand.filter((i) => i > 0 && p[i].slice(0, corteD) !== p[i - 1].slice(0, corteD));
    else if (largo) cand = cand.filter((i) => /-(01|T1|S1)$/.test(p[i]));
    const paso = Math.max(1, Math.ceil(cand.length / nEt));
    cand.filter((_, k) => k % paso === 0).forEach((i) => {
      const t = el("text", { x: x(i), y: H - 6, "text-anchor": "middle" }, svg);
      t.textContent = diaria ? (corteD === 4 ? p[i].slice(0, 4) : fmtP(p[i].slice(0, 7), true)) : largo ? p[i].slice(0, 4) : fmtP(p[i], true);
    });

    series.forEach((s) => {
      let d = "", abierto = false;
      s.valores.forEach((v, i) => {
        if (v == null) { abierto = false; return; }
        d += `${abierto ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
        abierto = true;
      });
      el("path", { d, fill: "none", stroke: s.color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }, svg);
      for (let i = s.valores.length - 1; i >= 0; i--) {
        if (s.valores[i] != null) {
          el("circle", { cx: x(i), cy: y(s.valores[i]), r: 4, fill: s.color, stroke: "var(--surface-1)", "stroke-width": 2 }, svg);
          if (series.length === 1) {
            const t = el("text", { class: "val", x: Math.min(x(i), W - m.r) - 6, y: y(s.valores[i]) - 10, "text-anchor": "end" }, svg);
            t.textContent = fmt(s.valores[i]);
          }
          break;
        }
      }
    });

    // Capa de interacción: cruz + tooltip
    const cruz = el("line", { class: "cross", y1: m.t, y2: H - m.b, visibility: "hidden" }, svg);
    const puntos = series.map((s) => el("circle", { r: 5, fill: s.color, stroke: "var(--surface-1)", "stroke-width": 2, visibility: "hidden" }, svg));
    const capa = el("rect", { class: "capa", x: m.l, y: 0, width: W - m.l - m.r, height: H, fill: "transparent" }, svg);
    const apagar = () => { cruz.setAttribute("visibility", "hidden"); puntos.forEach((c) => c.setAttribute("visibility", "hidden")); ocultarTip(); };
    const mover = (ev) => {
      const r = svg.getBoundingClientRect();
      const px = ((ev.clientX - r.left) / r.width) * W;
      const i = Math.max(0, Math.min(p.length - 1, Math.round(((px - m.l) / (W - m.l - m.r)) * (p.length - 1))));
      cruz.setAttribute("x1", x(i)); cruz.setAttribute("x2", x(i)); cruz.setAttribute("visibility", "visible");
      series.forEach((s, k) => {
        const v = s.valores[i];
        if (v == null) { puntos[k].setAttribute("visibility", "hidden"); return; }
        puntos[k].setAttribute("cx", x(i)); puntos[k].setAttribute("cy", y(v)); puntos[k].setAttribute("visibility", "visible");
      });
      mostrarTip(`<div class="tt-t">${esc(fmtP(p[i]))}</div>` + series.map((s) =>
        `<div class="tt-r"><span><i class="sw${s.k ?? 0}"></i>${esc(s.nombre)}</span><b>${esc(fmt(s.valores[i]))}</b></div>`).join(""), ev);
      apagarActual = apagar;
    };
    capa.addEventListener("pointermove", mover);
    capa.addEventListener("pointerdown", mover);
    capa.addEventListener("pointerleave", (ev) => { if (ev.pointerType === "mouse") apagar(); });
    fig.appendChild(svg);
    tablaDatos(fig, p, series, fmt);
    nota(fig, cfg.nota);
  }
  // En pantallas táctiles el tooltip se cierra al desplazar o al tocar fuera del gráfico
  let apagarActual = null;
  const cerrarTip = () => { if (apagarActual) { apagarActual(); apagarActual = null; } else ocultarTip(); };
  window.addEventListener("scroll", () => { if (!tip.hidden) cerrarTip(); }, { passive: true });
  document.addEventListener("pointerdown", (ev) => { if (!tip.hidden && !ev.target.closest?.("svg.chart")) cerrarTip(); }, { passive: true });

  // ---------------------------------------------------------------- barras horizontales
  function barras(fig, cfg) {
    if (!fig) return;
    const { titulo, desc, items, fmt = (v) => signo(v) + " %" } = cfg;
    if (!items || !items.length) return sinDatos(fig, titulo);
    cabecera(fig, titulo, desc);
    const W = ancho(fig);
    const fila = 26;
    const H = items.length * fila + 8;
    const lw = Math.min(260, Math.round(W * 0.44));
    const vals = items.map((d) => d.valor).filter((v) => v != null);
    const mn = Math.min(0, ...vals), mx = Math.max(0, ...vals);
    const m = { l: lw + (mn < 0 ? 58 : 0), r: mx > 0 ? 64 : 12 };
    const xs = (v) => m.l + ((v - mn) / (mx - mn || 1)) * (W - m.l - m.r);
    const svg = el("svg", { class: "chart", viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": titulo });
    el("line", { class: "zero", x1: xs(0), x2: xs(0), y1: 0, y2: H }, svg);
    items.forEach((d, i) => {
      const yc = 4 + i * fila + fila / 2;
      const lbl = el("text", { class: "lbl", x: lw - 8, y: yc + 4, "text-anchor": "end" }, svg);
      const corto = d.etiqueta.length > lw / 6.4 ? d.etiqueta.slice(0, Math.floor(lw / 6.4) - 1) + "…" : d.etiqueta;
      lbl.textContent = corto;
      if (d.valor == null) return;
      const x0 = xs(Math.min(0, d.valor)), x1 = xs(Math.max(0, d.valor));
      const w = Math.max(2, x1 - x0);
      el("rect", { x: x0, y: yc - 8, width: w, height: 16, rx: 3, fill: d.color || COL[0] }, svg);
      const v = el("text", { class: "val", x: d.valor >= 0 ? x1 + 6 : x0 - 6, y: yc + 4, "text-anchor": d.valor >= 0 ? "start" : "end" }, svg);
      v.textContent = fmt(d.valor);
      const hit = el("rect", { x: 0, y: yc - fila / 2, width: W, height: fila, fill: "transparent" }, svg);
      const ver = (ev) => {
        mostrarTip(`<div class="tt-t">${esc(d.etiqueta)}</div><div class="tt-r"><span>${esc(cfg.serie || "Valor")}</span><b>${esc(fmt(d.valor))}</b></div>`
          + (d.extra ? `<div class="tt-r"><span>${esc(d.extra[0])}</span><b>${esc(d.extra[1])}</b></div>` : ""), ev);
        apagarActual = ocultarTip;
      };
      hit.addEventListener("pointermove", ver);
      hit.addEventListener("pointerdown", ver);
      hit.addEventListener("pointerleave", (ev) => { if (ev.pointerType === "mouse") ocultarTip(); });
    });
    fig.appendChild(svg);
    nota(fig, cfg.nota);
  }

  // ---------------------------------------------------------------- mini-línea (portada)
  function sparkline(valores) {
    const v = valores.filter((x) => x != null);
    if (v.length < 2) return "";
    const W = 120, H = 34, mn = Math.min(...v), mx = Math.max(...v), r = mx - mn || 1;
    const pts = v.map((x, i) => `${((i / (v.length - 1)) * (W - 4) + 2).toFixed(1)},${(H - 3 - ((x - mn) / r) * (H - 6)).toFixed(1)}`);
    const [ux, uy] = pts[pts.length - 1].split(",");
    return `<svg class="spark" viewBox="0 0 ${W} ${H}" aria-hidden="true" preserveAspectRatio="none"><polyline points="${pts.join(" ")}"/><circle cx="${ux}" cy="${uy}" r="2.6"/></svg>`;
  }

  // ---------------------------------------------------------------- KPIs
  function kpis(cont, lista) {
    if (!cont) return;
    cont.innerHTML = lista.filter(Boolean).map((k) =>
      `<div class="kpi"><div class="t">${esc(k.t)}</div><div class="v">${esc(k.v)}</div><div class="d">${esc(k.d || "")}</div></div>`).join("");
  }
  const ultimo = (p, v) => {
    for (let i = (v || []).length - 1; i >= 0; i--) if (v[i] != null) return { p: p[i], v: v[i], i };
    return { p: null, v: null, i: -1 };
  };
  const ser = (b) => Object.keys(b.series).map((n) => ({ nombre: n, valores: b.series[n] }));

  // ================================================================ RESUMEN
  function renderPortada() {
    const T = DATA.tableros, C = DATA.catalogo;
    // Datos del encabezado
    const totales = [
      [C.servicios_total, C.servicios_ok],
      [C.series_extra?.series_total, C.series_extra?.series_ok],
      [C.bcra?.series_total, C.bcra?.series_ok],
    ].filter(([t]) => t);
    const total = totales.reduce((a, [t]) => a + t, 0), ok = totales.reduce((a, [, o]) => a + (o || 0), 0);
    $("hero-datos").innerHTML = [
      [String(total), "series y datasets"],
      ["5", "organismos oficiales"],
      [`${ok}/${total}`, "al día en la última actualización"],
      ["17:13", "se actualiza cada día hábil"],
    ].map(([v, t]) => `<li><b>${esc(v)}</b><span>${esc(t)}</span></li>`).join("");

    const FMT = {
      "%": (v) => num(v) + " %", "% i.a.": (v) => signo(v) + " %", "% 12m": (v) => signo(v) + " %",
      "$": (v) => pesos(v), "USD mil M": (v) => "USD " + num(v, 1) + " mil M",
    };
    $("destacados").innerHTML = (T.destacados || []).map((d) => `
      <button type="button" class="dest" data-ir="${esc(d.tab)}">
        <span class="t">${esc(d.titulo)}</span>
        <span class="v">${esc((FMT[d.unidad] || ((v) => num(v)))(d.valor))}</span>
        <span class="d">${esc(d.detalle)}</span>
        ${sparkline(d.spark)}
        <span class="p">${esc(fmtP(d.periodo))}</span>
      </button>`).join("");

    const ETQ = { bien: ["▲", "Mejora"], templado: ["■", "Estable"], mal: ["▼", "Empeora"] };
    $("semaforo").innerHTML = T.semaforo.map((s) => {
      let valor, delta;
      if (s.unidad === "%") { valor = num(s.valor) + " %"; delta = `${signo(s.delta, 1)} pp`; }
      else if (s.unidad === "millones de USD") { valor = "US$ " + num(s.valor, 0) + " M"; delta = `${signo(s.delta, 0)} M`; }
      else { valor = num(s.valor, 1); delta = `${signo(s.delta, 1)} %`; }
      const [ic, tx] = ETQ[s.estado] || ["", ""];
      return `<article class="sem ${ETQ[s.estado] ? s.estado : ""}">
        <div class="t">${esc(s.indicador)}</div>
        <div class="v">${esc(valor)}</div>
        <div class="estado">${ic} ${tx} · ${esc(delta)}</div>
        <div class="r">${esc(fmtP(s.periodo))} · ${esc(s.texto_referencia)}</div>
      </article>`;
    }).join("");
  }

  // ================================================================ PRECIOS
  function renderPrecios() {
    const P = DATA.tableros.precios, reg = estado.region, rango = estado.rango.precios;
    const ng = P.nivel_general[reg];
    const vm = ultimo(ng.p, ng.series.v_m), via = ultimo(ng.p, ng.series.v_ia), vac = ultimo(ng.p, ng.series.v_acum);
    kpis($("kpi-precios"), [
      { t: `Inflación mensual · ${reg}`, v: num(vm.v) + " %", d: fmtP(vm.p) },
      { t: "Interanual", v: num(via.v) + " %", d: "frente al mismo mes del año anterior" },
      { t: "Acumulada en el año", v: num(vac.v) + " %", d: `desde diciembre de ${+String(vac.p).slice(0, 4) - 1}` },
    ]);
    lineas($("c-ipc"), {
      titulo: `Inflación mensual · ${reg}`, desc: "Variación % del IPC respecto del mes anterior.",
      p: ng.p, series: [{ nombre: "IPC mensual", valores: ng.series.v_m }], rango, cero: true, fmt: pct,
    });
    const cnr = P.nucleo_regulados[reg].v_m;
    lineas($("c-cnr"), {
      titulo: "Núcleo, regulados y estacionales", desc: "Variación % mensual. La núcleo es la inflación sin precios regulados ni estacionales.",
      p: cnr.p, series: ["Núcleo", "Regulados", "Estacional"].map((n) => ({ nombre: n, valores: cnr.series[n] })),
      rango, cero: true, fmt: pct,
    });
    const rub = [...P.rubros[reg]].sort((a, b) => (b.v_ia ?? -1e9) - (a.v_ia ?? -1e9));
    barras($("c-rubros"), {
      titulo: `Inflación por rubro · ${fmtP(P.rubros_periodo)}`, desc: "Variación % interanual de cada división del IPC.",
      serie: "Interanual", items: rub.map((r) => ({ etiqueta: r.rubro, valor: r.v_ia, extra: ["Mensual", signo(r.v_m) + " %"] })),
      fmt: pct,
    });
    const tp = P.tipos_de_precio;
    lineas($("c-tipos"), {
      titulo: "Consumidor, mayorista y construcción", desc: "Variación % interanual de cada índice de precios (nacional; ICC en GBA).",
      p: tp.p, series: ser(tp), rango, fmt: pct,
      nota: "El IPC mide lo que pagan los hogares; el IPIM, los precios mayoristas de productos nacionales e importados; el ICC, el costo de construir una vivienda.",
    });
  }

  // ================================================================ INGRESOS Y EMPLEO
  function renderIngresos() {
    const B = DATA.tableros.bolsillo, A = DATA.tableros.pulso, M = DATA.mas || {}, rango = estado.rango.ingresos;
    const sr = B.salario_real;
    const reg = ultimo(sr.p, sr.series["Total registrado"]);
    const regAnt = sr.series["Total registrado"][reg.i - 12];
    const cbt = ultimo(B.canastas.p, B.canastas.series["CBT H2"]);
    const pob = ultimo(B.pobreza.p, B.pobreza.series["Pobreza (personas)"]);
    const deso = ultimo(A.trabajo.p, A.trabajo.series["Desocupación"]);
    const em = M.empleo, ig = M.ingresos;
    kpis($("kpi-ingresos"), [
      { t: "Salario real registrado", v: signo(regAnt ? (reg.v / regAnt - 1) * 100 : null) + " %", d: `en 12 meses, a ${fmtP(reg.p)}` },
      ig?.kpi?.RIPTE && { t: "Salario promedio real (RIPTE)", v: signo(ig.kpi.RIPTE.v_ia) + " %", d: `en 12 meses · ${fmtP(ig.kpi.RIPTE.p)}` },
      em && { t: "Trabajadores registrados", v: num(em.kpi.v / 1000, 2) + " M", d: `${signo(em.kpi.dif_ia, 0)} mil en 12 meses · ${fmtP(em.kpi.p)}` },
      { t: "Desocupación", v: num(deso.v) + " %", d: fmtP(deso.p) },
      { t: "Canasta básica total · familia de 4", v: pesos(cbt.v), d: `${fmtP(cbt.p)} · GBA` },
      { t: "Pobreza (personas)", v: num(pob.v) + " %", d: fmtP(pob.p) + " · 31 aglomerados" },
    ]);
    const base = fmtP(sr.base);
    lineas($("c-salario"), {
      titulo: "Salario real", desc: `Índice de salarios deflactado por el IPC nacional. ${base} = 100: por encima de 100, el salario compra más que en ${base}.`,
      p: sr.p, series: ["Total registrado", "Sector privado registrado", "Sector público"].map((n) => ({ nombre: n, valores: sr.series[n] })),
      rango, fmt: (v) => num(v),
      nota: "El salario no registrado no se grafica: el INDEC lo publica con 5 meses de rezago y no es comparable mes a mes con el IPC.",
    });
    if (ig) lineas($("c-ingresos-reales"), {
      titulo: "Salario promedio, salario mínimo y jubilación mínima, en términos reales",
      desc: `Montos en pesos deflactados por el IPC nacional, ${fmtP(ig.base)} = 100. Por debajo de 100 compran menos que entonces.`,
      p: ig.reales.p, series: ser(ig.reales), rango, fmt: (v) => num(v),
      nota: "RIPTE: remuneración promedio de los trabajadores registrados estables. La jubilación mínima no incluye bonos extraordinarios.",
    }); else sinDatos($("c-ingresos-reales"), "Salarios y jubilación en términos reales");
    lineas($("c-canasta"), {
      titulo: "Canasta básica total · familia de 4", desc: "En pesos por mes (GBA): la línea de pobreza de un hogar de dos adultos y dos chicos.",
      p: B.canastas.p, series: [{ nombre: "CBT hogar de 4", valores: B.canastas.series["CBT H2"] }], rango, fmt: pesos, fmtEje: ejePesos,
    });
    lineas($("c-pobreza"), {
      titulo: "Pobreza e indigencia", desc: "% de personas, por semestre (31 aglomerados urbanos).",
      p: B.pobreza.p, series: ser(B.pobreza), rango: "todo", cero: true, fmt: pct,
    });
    lineas($("c-crianza"), {
      titulo: "Canasta de crianza", desc: "Costo mensual de criar a un chico, en pesos (bienes, servicios y cuidado).",
      p: B.crianza.p, series: ser(B.crianza), rango, fmt: pesos, fmtEje: ejePesos,
    });
    if (M.macro) lineas($("c-gini"), {
      titulo: "Desigualdad (coeficiente de Gini)", desc: "Ingreso per cápita familiar. 0 = igualdad total; 1 = máxima desigualdad.",
      p: M.macro.gini.p, series: [{ nombre: "Gini", valores: M.macro.gini.v }], rango: "todo", fmt: (v) => num(v, 3), fmtEje: (v) => num(v, 2),
    });
    if (em) {
      lineas($("c-sipa"), {
        titulo: "Trabajadores registrados", desc: "Miles de personas con empleo registrado (asalariados, monotributistas, autónomos y casas particulares), desestacionalizado.",
        p: em.total.p, series: ser(em.total), rango, fmt: (v) => num(v, 0) + " mil", fmtEje: (v) => num(v, 0),
      });
      lineas($("c-sipa-comp"), {
        titulo: "Por tipo de trabajo", desc: "Miles de personas. Asalariados privados y monotributistas con estacionalidad; públicos desestacionalizados.",
        p: em.composicion.p, series: ser(em.composicion), rango, cero: true, fmt: (v) => num(v, 0) + " mil", fmtEje: (v) => num(v, 0),
        nota: "El total también incluye autónomos, monotributo social y trabajadoras de casas particulares.",
      });
    }
    lineas($("c-trabajo"), {
      titulo: "Desocupación y subocupación", desc: "% de la población económicamente activa, por trimestre (31 aglomerados).",
      p: A.trabajo.p, series: ser(A.trabajo), rango: "todo", cero: true, fmt: pct,
    });
    $("ingresos-nota").textContent = "Fuentes: INDEC (índice de salarios, IPC, canastas, EPH), Secretaría de Trabajo (SIPA, RIPTE, salario mínimo) y Secretaría de Seguridad Social (jubilación mínima)."
      + atrasoTexto([em, ig, M.macro]);
  }

  // ================================================================ ACTIVIDAD
  function renderActividad() {
    const A = DATA.tableros.pulso, M = DATA.mas || {}, rango = estado.rango.actividad;
    const co = M.consumo, cn = M.construccion, ind = M.industria, tu = M.turismo, ma = M.macro, sv = M.servicios, xp = M.expectativas;
    const em = A.emae;
    const des = ultimo(em.p, em.series["Var % mensual serie desestacionalizada"]);
    const via = ultimo(em.p, em.series["Var % interanual serie original"]);
    const pibU = ma ? ultimo(ma.pib_ia.p, ma.pib_ia.v) : null;
    kpis($("kpi-actividad"), [
      { t: "Actividad (EMAE) mensual", v: signo(des.v) + " %", d: `${fmtP(des.p)} · desestacionalizado` },
      { t: "Actividad interanual", v: signo(via.v) + " %", d: fmtP(via.p) },
      pibU && { t: "PIB", v: signo(pibU.v) + " %", d: `interanual · ${fmtP(pibU.p)}` },
      ind && { t: "Capacidad instalada industrial", v: pct(ind.kpi.v), d: `${signo(ind.kpi.pp_ia)} pp en 12 meses · ${fmtP(ind.kpi.p)}` },
      cn && { t: "Construcción (ISAC)", v: signo(cn.kpi_isac_v_ia.v) + " %", d: `interanual · ${fmtP(cn.kpi_isac_v_ia.p)}` },
      co && { t: "Ventas en supermercados", v: signo(co.kpi_super_v_ia.v) + " %", d: `interanual, a precios constantes · ${fmtP(co.kpi_super_v_ia.p)}` },
    ]);
    lineas($("c-emae"), {
      titulo: "Actividad económica (EMAE)", desc: "Índice desestacionalizado, base 2004 = 100.",
      p: em.p, series: [{ nombre: "EMAE desestacionalizado", valores: em.series["Índice serie desestacionalizada"] }], rango,
    });
    barras($("c-sectores"), {
      titulo: `Actividad por sector · ${fmtP(A.sectores_periodo)}`, desc: "Variación % interanual de cada sector del EMAE.",
      serie: "Interanual", items: A.sectores.map((s) => ({ etiqueta: s.sector, valor: s.v_ia })),
    });
    if (ma) lineas($("c-pib"), {
      titulo: "PIB", desc: "Variación % interanual del PIB a precios constantes, por trimestre.",
      p: ma.pib_ia.p, series: [{ nombre: "PIB interanual", valores: ma.pib_ia.v }], rango: "todo", fmt: (v) => signo(v) + " %",
    });
    const mi = A.ipi_manufacturero.indice_desest, mn = A.ipi_minero.indice_desest;
    const per = [...new Set([...mi.p, ...mn.p])].sort();
    const idx = (s) => { const m = new Map(s.p.map((p, i) => [p, s.v[i]])); return per.map((p) => m.get(p) ?? null); };
    lineas($("c-ipi"), {
      titulo: "Industria y minería", desc: "Índices de producción (IPI), series desestacionalizadas.",
      p: per, series: [{ nombre: "Industria manufacturera", valores: idx(mi) }, { nombre: "Minería", valores: idx(mn) }], rango,
    });
    if (ind) lineas($("c-ucii"), {
      titulo: "Uso de la capacidad instalada", desc: "% de la capacidad de las fábricas que se está usando, por sector.",
      p: ind.ucii.p, series: ser(ind.ucii), rango, fmt: pct,
      nota: "La serie de sustancias y productos químicos está en el Explorador.",
    });
    if (cn) {
      lineas($("c-isac"), {
        titulo: "Actividad de la construcción (ISAC)", desc: "Índice 2004 = 100, desestacionalizado.",
        p: cn.isac.p, series: ser(cn.isac), rango,
      });
      barras($("c-insumos"), {
        titulo: `Insumos de la construcción · ${fmtP(cn.insumos_periodo)}`, desc: "Variación % interanual de la demanda de cada insumo.",
        serie: "Interanual", items: cn.insumos.map((x) => ({ etiqueta: x.insumo, valor: x.v_ia })),
      });
      if (cn.permisos) lineas($("c-permisos"), {
        titulo: "Permisos de edificación", desc: "Miles de m² autorizados por mes para obras privadas en 246 municipios. Anticipa la construcción de los próximos meses.",
        p: cn.permisos.p, series: [{ nombre: "Superficie autorizada", valores: cn.permisos.v }], rango, cero: true, fmt: (v) => num(v, 0) + " mil m²",
      });
    }
    if (co) {
      lineas($("c-consumo"), {
        titulo: "Ventas a precios constantes", desc: "Índice 2017 = 100, series desestacionalizadas. Por debajo de 100 se vende menos que en 2017.",
        p: co.real.p, series: ser(co.real), rango,
      });
      lineas($("c-pagos"), {
        titulo: "Cómo se paga en el súper", desc: "% de las ventas de supermercados por medio de pago.",
        p: co.pagos.p, series: ser(co.pagos), rango, cero: true, fmt: pct,
      });
      lineas($("c-online"), {
        titulo: "Ventas online en supermercados", desc: "% de las ventas que se hacen por canales online.",
        p: co.online.p, series: [{ nombre: "Online", valores: co.online.v }], rango, cero: true, fmt: pct,
      });
    }
    if (tu) {
      lineas($("c-turismo"), {
        titulo: "Turismo internacional", desc: "Miles de pasajeros por mes en Ezeiza y Aeroparque: los que llegan y los residentes que viajan al exterior.",
        p: tu.flujos.p, series: ser(tu.flujos), rango, cero: true, fmt: (v) => num(v, 0) + " mil",
      });
      if (tu.hoteles) lineas($("c-hoteles"), {
        titulo: "Ocupación hotelera", desc: "Noches en hoteles de todo el país, por residencia del viajero (desestacionalizada).",
        p: tu.hoteles.p, series: ser(tu.hoteles), rango, cero: true, fmt: (v) => (v >= 1e6 ? num(v / 1e6, 2) + " M" : num(v / 1e3, 0) + " mil"),
        fmtEje: (v) => (v === 0 ? "0" : v >= 1e6 ? num(v / 1e6, 1) + " M" : num(v / 1e3, 0) + " mil"),
        nota: "El INDEC dejó de publicar la Encuesta de Ocupación Hotelera después de noviembre de 2025: la serie termina ahí.",
      });
    }
    if (sv) lineas($("c-issp"), {
      titulo: "Servicios públicos", desc: "Índice de servicios públicos (transporte, peajes, telefonía, residuos y otros), tendencia-ciclo, 2004 = 100.",
      p: sv.issp.p, series: ser(sv.issp), rango,
    });
    if (xp) lineas($("c-ice"), {
      titulo: "Confianza empresarial", desc: "Saldo entre empresarios optimistas y pesimistas sobre los próximos 3 meses. Por debajo de 0 predominan los pesimistas.",
      p: xp.ice.p, series: ser(xp.ice), rango, cero: true, fmt: (v) => signo(v) + " %",
      nota: "La encuesta a la industria manufacturera empezó en enero de 2025.",
    });
    $("actividad-nota").textContent = "Fuentes: INDEC (EMAE, PIB, IPI, ISAC, encuestas de supermercados, turismo, servicios públicos y tendencia de negocios, y planillas de permisos y hoteles), vía su API, datos.gob.ar y sus planillas."
      + atrasoTexto([co, cn, ind, tu, ma, sv, xp]);
  }

  // ================================================================ DÓLAR Y TASAS
  const fecha = (p) => (p ? fmtP(p) : "—");
  function renderDinero() {
    const D = DATA.bcra, rango = estado.rango.dinero, K = D.kpi;
    const varPct = (k) => (k.v != null && k.v_comp ? signo((k.v / k.v_comp - 1) * 100) + " % en 12 meses" : "");
    const brecha = K.tc_minorista.v && K.tc_mayorista.v ? (K.tc_minorista.v / K.tc_mayorista.v - 1) * 100 : null;
    const aTecho = K.banda_techo.v && K.tc_mayorista.v ? (K.banda_techo.v / K.tc_mayorista.v - 1) * 100 : null;
    kpis($("kpi-dinero"), [
      { t: "Dólar mayorista", v: pesos(K.tc_mayorista.v), d: `${varPct(K.tc_mayorista)} · ${fecha(K.tc_mayorista.p)}` },
      { t: "Dólar minorista", v: pesos(K.tc_minorista.v), d: `${brecha != null ? signo(brecha) + " % sobre el mayorista" : ""} · ${fecha(K.tc_minorista.p)}` },
      aTecho != null && { t: "Distancia al techo de la banda", v: num(aTecho) + " %", d: `techo ${pesos(K.banda_techo.v)} · ${fecha(K.banda_techo.p)}` },
      { t: "Reservas internacionales", v: "USD " + num(K.reservas.v / 1000, 1) + " mil M", d: `${K.reservas.v_comp ? signo((K.reservas.v - K.reservas.v_comp) / 1000) + " mil M en 12 meses" : ""} · ${fecha(K.reservas.p)}` },
      { t: "Plazo fijo a 30 días", v: num(K.tasa_plazo_fijo.v) + " %", d: `nominal anual · ${fecha(K.tasa_plazo_fijo.p)}` },
      { t: "Inflación esperada", v: num(K.inflacion_esperada.v) + " %", d: `próximos 12 meses (REM) · ${fmtP((K.inflacion_esperada.p || "").slice(0, 7))}` },
    ]);
    lineas($("c-dolar"), {
      titulo: "Dólar oficial y bandas cambiarias", desc: "Pesos por dólar, último dato de cada semana. Las bandas son el piso y el techo dentro de los que el BCRA deja flotar el mayorista.",
      p: D.dolar.p, series: ser(D.dolar), rango, fmt: pesos, fmtEje: (v) => num(v, 0),
      nota: "Las bandas rigen desde abril de 2025: antes no hay datos de piso y techo.",
    });
    lineas($("c-reservas"), {
      titulo: "Reservas internacionales del BCRA", desc: "Miles de millones de USD, último dato de cada semana (reservas brutas).",
      p: D.reservas.p, series: [{ nombre: "Reservas", valores: D.reservas.series.Reservas.map((v) => (v == null ? null : v / 1000)) }],
      rango, fmt: (v) => "USD " + num(v, 1) + " mil M", fmtEje: (v) => num(v, 0),
    });
    lineas($("c-tasas"), {
      titulo: "Tasas de interés", desc: "% nominal anual. BADLAR y TAMAR: lo que pagan los bancos privados por depósitos grandes; plazo fijo: lo que recibe un ahorrista; personales: lo que cobra un banco por prestar.",
      p: D.tasas.p, series: ser(D.tasas), rango, cero: true, fmt: pct,
      nota: "Para comparar con la inflación, una tasa nominal anual de 30 % equivale a un 2,5 % mensual.",
    });
    lineas($("c-expectativas"), {
      titulo: "Inflación esperada", desc: "Mediana del Relevamiento de Expectativas de Mercado (REM): % de inflación que esperan los analistas para los próximos 12 meses.",
      p: D.expectativas.p, series: ser(D.expectativas), rango, cero: true, fmt: pct,
    });
    lineas($("c-m2"), {
      titulo: "Cantidad de dinero (M2 privado)", desc: "Variación % interanual del promedio de 30 días: efectivo más cuentas a la vista del sector privado.",
      p: D.m2.p, series: ser(D.m2), rango, cero: true, fmt: (v) => signo(v) + " %",
    });
    if (D.credito) lineas($("c-credito"), {
      titulo: "Préstamos y depósitos en términos reales", desc: `Saldos en pesos deflactados por el IPC nacional, ${fmtP(D.credito.base)} = 100. Por encima de 100 hay más crédito (o depósitos) que entonces, a valores de hoy.`,
      p: D.credito.p, series: ser(D.credito), rango,
    });
    lineas($("c-indices"), {
      titulo: "UVA e ICL", desc: "Índices con los que se ajustan créditos hipotecarios (UVA, en pesos) y alquileres firmados con la ley anterior (ICL). Último dato de cada semana.",
      p: D.indices.p, series: [{ nombre: "UVA (pesos)", valores: D.indices.series.UVA }, { nombre: "ICL × 50", valores: (D.indices.series.ICL || []).map((v) => (v == null ? null : v * 50)) }],
      rango, fmt: (v) => num(v, 2), fmtEje: (v) => num(v, 0),
      nota: "El ICL se multiplica por 50 solo para verlo en la misma escala que la UVA; el valor original está en el Explorador.",
    });
    const atr = D.fuentes.filter((f) => f.atrasada);
    $("dinero-nota").textContent = "Fuente: BCRA, API pública de Estadísticas Monetarias (v4). Los préstamos y depósitos reales usan el IPC del INDEC." +
      (atr.length ? ` Atención: ${atr.length} variable(s) sin dato nuevo hace varios días (${atr.map((f) => f.nombre).join(", ")}).` : "");
  }

  // ================================================================ FISCAL Y EXTERNO
  function renderCuentas() {
    const A = DATA.tableros.pulso, M = DATA.mas || {}, rango = estado.rango.cuentas;
    const fi = M.fiscal, ex = M.externo;
    const cx = A.comex, saldo = ultimo(cx.p, cx.series.Saldo);
    kpis($("kpi-cuentas"), [
      fi?.kpi_prim?.v != null && { t: "Resultado primario del mes", v: (fi.kpi_prim.v < 0 ? "−" : "") + "$ " + num(Math.abs(fi.kpi_prim.v) / 1000, 2) + " billones", d: `Sector Público Nacional · ${fmtP(fi.kpi_prim.p)}` },
      fi?.kpi_rec?.v != null && { t: "Recaudación real", v: signo(fi.kpi_rec.v) + " %", d: `interanual, descontada la inflación · ${fmtP(fi.kpi_rec.p)}` },
      { t: "Saldo comercial", v: "US$ " + num(saldo.v, 0) + " M", d: fmtP(saldo.p) },
      ex && { t: "Deuda externa bruta", v: "USD " + num(ex.kpi_deuda.v, 1) + " mil M", d: `${signo(ex.kpi_deuda.v_ia)} mil M en 12 meses · ${fmtP(ex.kpi_deuda.p)}` },
    ]);
    if (fi) {
      if (fi.primario_12m) lineas($("c-primario"), {
        titulo: "Resultado primario del Sector Público Nacional", desc: "Acumulado de los últimos 12 meses, en billones de pesos de hoy (deflactado por IPC). Positivo: superávit antes de pagar intereses de la deuda.",
        p: fi.primario_12m.p, series: [{ nombre: "Resultado primario (12 meses)", valores: fi.primario_12m.v }], rango, cero: true,
        fmt: (v) => "$ " + num(v, 1) + " billones", fmtEje: (v) => num(v, 0),
      });
      lineas($("c-recaudacion"), {
        titulo: "Recaudación tributaria real", desc: "Variación % interanual de la recaudación total, descontada la inflación del IPC nacional.",
        p: fi.recaudacion.p, series: [{ nombre: "Recaudación real", valores: fi.recaudacion.series["Real (descontada la inflación)"] }], rango, cero: true, fmt: (v) => signo(v) + " %",
        nota: (() => { const n = ultimo(fi.recaudacion.p, fi.recaudacion.series.Nominal); return n.v != null ? `En pesos corrientes, la recaudación de ${fmtP(n.p)} creció ${signo(n.v)} % interanual.` : ""; })(),
      });
    }
    lineas($("c-comex"), {
      titulo: "Exportaciones e importaciones", desc: "Millones de dólares por mes (FOB y CIF).",
      p: cx.p, series: [{ nombre: "Exportaciones", valores: cx.series.Exportaciones }, { nombre: "Importaciones", valores: cx.series.Importaciones }],
      rango, cero: true, fmt: (v) => "US$ " + num(v, 0) + " M", fmtEje: (t) => num(t, 0),
    });
    if (ex) {
      lineas($("c-cuenta"), {
        titulo: "Balanza de pagos: cuenta corriente", desc: "Millones de USD por trimestre. Positivo: entran más dólares por comercio, turismo, intereses y utilidades de los que salen.",
        p: ex.cuenta.p, series: ser(ex.cuenta), rango, cero: true, fmt: (v) => "USD " + num(v, 0) + " M",
      });
      lineas($("c-deuda"), {
        titulo: "Deuda externa bruta, por deudor", desc: "Miles de millones de USD al cierre de cada trimestre, a valor nominal.",
        p: ex.deuda.p, series: ser(ex.deuda), rango, cero: true, fmt: (v) => "USD " + num(v, 1) + " mil M", fmtEje: (v) => num(v, 0),
      });
    }
    $("cuentas-nota").textContent = "Fuentes: Ministerio de Economía (resultado fiscal y recaudación, con datos de ARCA) e INDEC (intercambio comercial, balanza de pagos y deuda externa)."
      + atrasoTexto([fi, ex]);
  }

  function atrasoTexto(bloques) {
    const atr = bloques.filter(Boolean).flatMap((b) => b.fuentes || []).filter((f) => f.atrasada);
    return atr.length ? ` Atención: ${atr.length} serie(s) atrasada(s) (${atr.map((f) => f.nombre).join(", ")}).` : "";
  }

  // ================================================================ DATOS
  function estadoCelda(x) {
    if (!x.ok) return '<span class="falla">✕ Falló</span>';
    if (x.discontinuada) return '<span class="nota">Discontinuada</span>';
    if (x.atrasada) return '<span class="atraso">● Atrasada</span>';
    return '<span class="ok">✓ Al día</span>';
  }
  function renderDatos() {
    const C = DATA.catalogo;
    const X = C.series_extra, B = C.bcra;
    const fuentes = [
      ["INDEC · API", C.servicios_ok, C.servicios_total],
      X && ["datos.gob.ar y planillas", X.series_ok, X.series_total],
      B && ["BCRA", B.series_ok, B.series_total],
    ].filter(Boolean);
    $("fuentes-resumen").innerHTML = fuentes.map(([n, ok, t]) =>
      `<div class="fuente ${ok === t ? "todo-ok" : "con-fallas"}"><span>${esc(n)}</span><b>${esc(ok)}/${esc(t)}</b><small>${ok === t ? "al día" : "con fallas"}</small></div>`).join("");
    $("cat-lead").textContent =
      `${C.servicios_ok} de ${C.servicios_total} datasets actualizados en la última ingesta (${new Date(C.generado).toLocaleString("es-AR", { dateStyle: "long", timeStyle: "short", timeZone: "America/Argentina/Buenos_Aires" })}).`;
    $("tabla-catalogo").innerHTML = `<thead><tr><th>Dataset</th><th>Último dato</th><th>Filas</th><th>Estado</th><th>Descargar</th></tr></thead><tbody>` +
      C.servicios.map((s) => `<tr>
        <td class="wrap"><b>${esc(s.descripcion)}</b><br><span class="nota">${esc(s.endpoint)}</span></td>
        <td>${esc(fmtP(s.ultimo_periodo))}</td>
        <td>${s.filas != null ? esc(s.filas.toLocaleString("es-AR")) : "—"}</td>
        <td>${s.ok ? '<span class="ok">✓ OK</span>' : `<span class="falla" title="${esc(s.error)}">✕ Falló</span>`}</td>
        <td><a href="datos/${encodeURIComponent(s.tabla)}.parquet" download>${esc(s.tabla)}.parquet</a></td></tr>`).join("") + "</tbody>";
    if (X) {
      $("cat-extra-lead").textContent = `${X.series_ok} de ${X.series_total} series actualizadas${X.atrasadas ? ` · ${X.atrasadas} atrasada(s)` : ""}. Se filtran y bajan desde el Explorador.`;
      $("tabla-extra").innerHTML = `<thead><tr><th>Serie</th><th>Grupo</th><th>Último dato</th><th>Estado</th><th>Fuente</th></tr></thead><tbody>` +
        X.series.map((x) => `<tr>
          <td class="wrap"><b>${esc(x.nombre)}</b><br><span class="nota">${esc(x.unidad)}</span></td>
          <td>${esc(x.grupo)}</td>
          <td>${esc(x.ultimo ? fmtP(String(x.ultimo)) : "—")}</td>
          <td>${estadoCelda(x)}</td>
          <td>${x.fuente === "planilla INDEC"
            ? `<a href="https://www.indec.gob.ar/ftp/cuadros/economia/${encodeURIComponent(x.id)}" rel="noopener noreferrer">Planilla</a>`
            : `<a href="https://apis.datos.gob.ar/series/api/series/?ids=${encodeURIComponent(x.id)}&amp;format=csv" rel="noopener noreferrer">CSV</a>`}</td></tr>`).join("") + "</tbody>";
    }
    if (B) {
      $("cat-bcra-lead").textContent = `${B.series_ok} de ${B.series_total} variables actualizadas${B.atrasadas ? ` · ${B.atrasadas} sin dato nuevo hace varios días` : ""}. Se filtran y bajan desde el Explorador.`;
      $("tabla-bcra").innerHTML = `<thead><tr><th>Variable</th><th>Grupo</th><th>Último dato</th><th>Estado</th><th>Fuente</th></tr></thead><tbody>` +
        B.series.map((x) => `<tr>
          <td class="wrap"><b>${esc(x.nombre)}</b><br><span class="nota">${esc(x.unidad)}</span></td>
          <td>${esc(x.grupo)}</td>
          <td>${esc(x.ultimo ? fmtP(String(x.ultimo)) : "—")}</td>
          <td>${estadoCelda(x)}</td>
          <td><a href="https://api.bcra.gob.ar/estadisticas/v4.0/monetarias/${encodeURIComponent(x.id)}" rel="noopener noreferrer">JSON</a></td></tr>`).join("") + "</tbody>";
    }
  }

  // El explorador (motor DuckDB-WASM) se baja solo si la persona lo pide
  let explorador = null;
  function abrirExplorador() {
    if (explorador) return;
    $("ex-arranque").hidden = true;
    $("ex-app").hidden = false;
    $("ex-estado").textContent = "Cargando el motor de consultas…";
    explorador = import(`./vendor/explorador.js${Q}`)
      .then((m) => m.iniciar())
      .catch((e) => {
        console.error(e);
        explorador = null;
        $("ex-estado").textContent = "No se pudo cargar el explorador. Revisá la conexión y volvé a intentar.";
        $("ex-arranque").hidden = false;
      });
  }

  // ---------------------------------------------------------------- render
  const RENDER = { portada: renderPortada, precios: renderPrecios, ingresos: renderIngresos, actividad: renderActividad,
    dinero: renderDinero, cuentas: renderCuentas, datos: renderDatos };
  let turno = 0;
  async function render() {
    cerrarTip();
    const tab = estado.tab, yo = ++turno;
    const panel = $(tab);
    panel.setAttribute("aria-busy", "true");
    try {
      // Datos obligatorios del panel; "mas" es opcional: si falla, se muestra lo demás
      const req = NECESITA[tab];
      await Promise.all(req.map((n) => (n === "mas" ? cargar(n).catch(() => null) : cargar(n))));
    } catch (e) {
      if (yo === turno) avisar(panel, `No se pudieron cargar los datos (${e.message}). Revisá la conexión y recargá la página.`);
      panel.removeAttribute("aria-busy");
      return;
    }
    if (yo !== turno) return; // se cambió de pestaña mientras cargaba
    panel.removeAttribute("aria-busy");
    try { RENDER[tab](); } catch (e) { console.error(e); avisar(panel, "Algo falló al dibujar esta sección. Recargá la página."); }
  }
  function avisar(panel, texto) {
    let n = panel.querySelector(":scope > .aviso");
    if (!n) { n = document.createElement("p"); n.className = "aviso"; panel.prepend(n); }
    n.textContent = texto;
  }

  // ---------------------------------------------------------------- navegación
  const tabsNav = document.querySelector(".tabs");
  function irA(tab, desdeClic = true) {
    tab = ALIAS[tab] || tab;
    if (!TABS.includes(tab)) tab = "portada";
    const cambio = tab !== estado.tab;
    estado.tab = tab;
    document.querySelectorAll(".tabs button").forEach((x) => x.setAttribute("aria-selected", x.dataset.tab === tab));
    document.querySelectorAll(".panel").forEach((p) => (p.hidden = p.id !== tab));
    history.replaceState(null, "", "#" + tab);
    // La pestaña elegida queda visible en la barra (sin mover la página)
    const b = tabsNav.querySelector(`[data-tab="${tab}"]`);
    if (b) tabsNav.scrollTo({ left: b.offsetLeft - (tabsNav.clientWidth - b.offsetWidth) / 2, behavior: "auto" });
    // Si se estaba más abajo, la sección nueva arranca desde arriba
    if (desdeClic && cambio) {
      const top = $("portada").parentElement.getBoundingClientRect().top + window.scrollY - tabsNav.offsetHeight - 16;
      if (window.scrollY > top) window.scrollTo({ top: Math.max(0, top), behavior: "auto" });
    }
    render();
  }

  function iniciarControles() {
    document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => irA(b.dataset.tab)));
    document.addEventListener("click", (ev) => {
      const ir = ev.target.closest("[data-ir]");
      if (ir) { ev.preventDefault(); irA(ir.dataset.ir); return; }
      const salto = ev.target.closest(".saltos a");
      if (salto) {
        ev.preventDefault();
        const destino = document.querySelector(salto.getAttribute("href"));
        if (destino) destino.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
      }
    });
    const sel = $("region");
    sel.innerHTML = DATA.tableros.precios.regiones.map((r) => `<option>${esc(r)}</option>`).join("");
    sel.addEventListener("change", () => { estado.region = sel.value; render(); });
    document.querySelectorAll(".rango").forEach((g) => {
      const grupo = g.dataset.rangoGrupo;
      g.innerHTML = [["1", "1 año"], ["3", "3 años"], ["todo", "Todo"]]
        .map(([v, t]) => `<button type="button" data-v="${v}" aria-pressed="${estado.rango[grupo] === v}">${t}</button>`).join("");
      g.addEventListener("click", (ev) => {
        const b = ev.target.closest("button");
        if (!b) return;
        estado.rango[grupo] = b.dataset.v;
        g.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", x === b));
        render();
      });
    });
    $("tema").addEventListener("click", () => {
      const raiz = document.documentElement;
      raiz.dataset.theme = raiz.dataset.theme === "light" ? "dark" : "light";
      try { localStorage.setItem("tema", raiz.dataset.theme); } catch (e) { /* sin almacenamiento */ }
    });
    $("ex-abrir").addEventListener("click", abrirExplorador);
    // Solo se redibuja si cambia el ANCHO: en el celular, la barra del navegador que aparece
    // y desaparece al desplazar cambia solo el alto y antes cerraba las tablas y hacía saltar la página.
    let anchoPrevio = document.documentElement.clientWidth, t;
    window.addEventListener("resize", () => {
      clearTimeout(t);
      t = setTimeout(() => {
        const a = document.documentElement.clientWidth;
        if (a === anchoPrevio) return;
        anchoPrevio = a;
        if (estado.tab !== "datos") render();
      }, 200);
    });
    window.addEventListener("hashchange", () => irA(location.hash.slice(1), false));
  }

  try { const tm = localStorage.getItem("tema"); if (tm === "light" || tm === "dark") document.documentElement.dataset.theme = tm; } catch (e) { /* nada */ }

  // Helpers que usa el explorador (módulo aparte)
  window.Tablero = Object.freeze({ lineas, esc, num, fmtP, q: Q });

  Promise.all([cargar("tableros"), cargar("catalogo")])
    .then(([, c]) => {
      const f = new Date(c.generado);
      const dia = f.toLocaleDateString("es-AR", { day: "numeric", month: "long", timeZone: "America/Argentina/Buenos_Aires" });
      const hora = f.toLocaleTimeString("es-AR", { hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone: "America/Argentina/Buenos_Aires" });
      $("actualizado").textContent = `Actualizado el ${dia}, ${hora} h`;
      iniciarControles();
      irA(location.hash.slice(1) || "portada", false);
    })
    .catch((e) => {
      document.querySelector("main").innerHTML = `<p class="aviso">No se pudieron cargar los datos (${esc(e.message)}). Revisá la conexión y recargá la página.</p>`;
    });
})();
