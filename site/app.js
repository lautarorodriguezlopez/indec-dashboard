/* Tablero INDEC — gráficos hechos a mano en SVG, sin dependencias. */
(() => {
  "use strict";

  const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
  const COL = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)"];
  const NS = "http://www.w3.org/2000/svg";
  const tip = document.getElementById("tooltip");
  const estado = { tab: "portada", region: "Nacional", rango: { precios: "3", bolsillo: "todo", actividad: "3" } };
  let T = null; // tableros.json
  let C = null; // catalogo.json

  // ---------------------------------------------------------------- formato
  // Todo texto que viene de los datos pasa por esc() antes de ir a innerHTML.
  const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const num = (v, d = 1) =>
    v == null || Number.isNaN(v) ? "—" : v.toLocaleString("es-AR", { minimumFractionDigits: d, maximumFractionDigits: d });
  const signo = (v, d = 1) => (v == null ? "—" : (v > 0 ? "+" : v < 0 ? "−" : "") + num(Math.abs(v), d));
  const ejePesos = (t) => (t === 0 ? "0" : t >= 1e6 ? num(t / 1e6, 1) + " M" : num(t / 1e3, 0) + " mil");
  const pesos = (v) => (v == null ? "—" : "$ " + Math.round(v).toLocaleString("es-AR"));

  function fmtP(p, corto = false) {
    if (!p) return "—";
    const m = /^(\d{4})-(\d{2})$/.exec(p);
    if (m) return corto ? `${MESES[+m[2] - 1]}-${m[1].slice(2)}` : `${MESES[+m[2] - 1]} ${m[1]}`;
    const q = /^(\d{4})-([TS])(\d)$/.exec(p);
    if (q) return q[2] === "T" ? `${q[3]}.º trim. ${q[1]}` : `${q[3]}.º sem. ${q[1]}`;
    return p;
  }
  function ordinal(p) {
    let m = /^(\d{4})-(\d{2})$/.exec(p);
    if (m) return +m[1] * 12 + +m[2];
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
  function ancho(fig) {
    return Math.max(280, Math.round(fig.clientWidth - 32));
  }

  function mostrarTip(html, ev) {
    tip.innerHTML = html;
    tip.hidden = false;
    const r = tip.getBoundingClientRect();
    let x = ev.clientX + 14;
    let y = ev.clientY + 14;
    if (x + r.width > window.innerWidth - 8) x = ev.clientX - r.width - 14;
    if (y + r.height > window.innerHeight - 8) y = ev.clientY - r.height - 14;
    tip.style.left = x + "px";
    tip.style.top = y + "px";
  }
  const ocultarTip = () => { tip.hidden = true; };

  function cabecera(fig, titulo, desc) {
    fig.innerHTML = "";
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
  function tablaDatos(fig, p, series, fmt, max = 24) {
    const det = document.createElement("details");
    det.className = "tabla-datos";
    const desde = Math.max(0, p.length - max);
    const filas = p.slice(desde).map((x, j) => {
      const i = desde + j;
      return `<tr><td>${esc(fmtP(x))}</td>${series.map((s) => `<td>${fmt(s.valores[i])}</td>`).join("")}</tr>`;
    }).reverse();
    det.innerHTML = `<summary>Ver tabla${p.length > max ? ` (últimos ${max} períodos)` : ""}</summary>
      <div class="tabla-wrap"><table class="tabla"><thead><tr><th>Período</th>${series
        .map((s) => `<th>${esc(s.nombre)}</th>`).join("")}</tr></thead><tbody>${filas.join("")}</tbody></table></div>`;
    fig.appendChild(det);
  }
  function nota(fig, texto) {
    if (!texto) return;
    const n = document.createElement("p");
    n.className = "nota";
    n.textContent = texto;
    fig.appendChild(n);
  }

  // ---------------------------------------------------------------- gráfico de líneas
  function lineas(fig, cfg) {
    const { titulo, desc, rango = "todo", fmt = (v) => num(v), cero = false } = cfg;
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
    let esc = escalaNice(bajo, mx + pad);
    if (mn >= 0 && esc.lo < 0) esc = escalaNice(0, mx + pad);
    const x = (i) => m.l + (p.length === 1 ? 0 : (i / (p.length - 1)) * (W - m.l - m.r));
    const y = (v) => m.t + (1 - (v - esc.lo) / (esc.hi - esc.lo)) * (H - m.t - m.b);

    const svg = el("svg", { class: "chart", viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": titulo });
    const g = el("g", { class: "grid" }, svg);
    for (const t of esc.ticks) {
      el("line", { x1: m.l, x2: W - m.r, y1: y(t), y2: y(t) }, g);
      const tx = el("text", { x: m.l - 6, y: y(t) + 4, "text-anchor": "end" }, svg);
      tx.textContent = cfg.fmtEje ? cfg.fmtEje(t) : num(t, esc.paso < 1 ? 1 : 0);
    }
    if (esc.lo < 0 && esc.hi > 0) el("line", { class: "zero", x1: m.l, x2: W - m.r, y1: y(0), y2: y(0) }, svg);

    // Etiquetas del eje x: hasta ~7, en enero si la serie es larga
    const nEt = Math.max(2, Math.floor((W - m.l - m.r) / 90));
    const largo = p.length > 30;
    let cand = p.map((_, i) => i);
    if (largo) cand = cand.filter((i) => /-(01|T1|S1)$/.test(p[i]));
    const paso = Math.max(1, Math.ceil(cand.length / nEt));
    cand.filter((_, k) => k % paso === 0).forEach((i) => {
      const t = el("text", { x: x(i), y: H - 6, "text-anchor": "middle" }, svg);
      t.textContent = largo ? p[i].slice(0, 4) : fmtP(p[i], true);
    });

    series.forEach((s) => {
      let d = "", abierto = false;
      s.valores.forEach((v, i) => {
        if (v == null) { abierto = false; return; }
        d += `${abierto ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
        abierto = true;
      });
      el("path", { d, fill: "none", stroke: s.color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }, svg);
      // último punto
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
    const capa = el("rect", { x: m.l, y: 0, width: W - m.l - m.r, height: H, fill: "transparent" }, svg);
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
    };
    capa.addEventListener("pointermove", mover);
    capa.addEventListener("pointerdown", mover);
    capa.addEventListener("pointerleave", () => {
      cruz.setAttribute("visibility", "hidden"); puntos.forEach((c) => c.setAttribute("visibility", "hidden")); ocultarTip();
    });
    fig.appendChild(svg);
    tablaDatos(fig, p, series, fmt);
    nota(fig, cfg.nota);
  }

  // ---------------------------------------------------------------- barras horizontales
  function barras(fig, cfg) {
    const { titulo, desc, items, fmt = (v) => signo(v) + " %" } = cfg;
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
      const ver = (ev) => mostrarTip(`<div class="tt-t">${esc(d.etiqueta)}</div><div class="tt-r"><span>${esc(cfg.serie || "Valor")}</span><b>${fmt(d.valor)}</b></div>`
        + (d.extra ? `<div class="tt-r"><span>${esc(d.extra[0])}</span><b>${esc(d.extra[1])}</b></div>` : ""), ev);
      hit.addEventListener("pointermove", ver);
      hit.addEventListener("pointerdown", ver);
      hit.addEventListener("pointerleave", ocultarTip);
    });
    fig.appendChild(svg);
    nota(fig, cfg.nota);
  }

  // ---------------------------------------------------------------- KPIs
  function kpis(cont, lista) {
    cont.innerHTML = lista.map((k) =>
      `<div class="kpi"><div class="t">${esc(k.t)}</div><div class="v">${k.v}</div><div class="d">${k.d || ""}</div></div>`).join("");
  }
  const ultimo = (p, v) => {
    for (let i = v.length - 1; i >= 0; i--) if (v[i] != null) return { p: p[i], v: v[i], i };
    return { p: null, v: null, i: -1 };
  };

  // ---------------------------------------------------------------- secciones
  function renderPortada() {
    const cont = document.getElementById("semaforo");
    const ETQ = { bien: ["▲", "Mejora"], templado: ["■", "Estable"], mal: ["▼", "Empeora"] };
    cont.innerHTML = T.semaforo.map((s) => {
      let valor, delta;
      if (s.unidad === "%") { valor = num(s.valor) + " %"; delta = `${signo(s.delta, 1)} pp`; }
      else if (s.unidad === "millones de USD") { valor = "US$ " + num(s.valor, 0) + " M"; delta = `${signo(s.delta, 0)} M`; }
      else { valor = num(s.valor, 1); delta = `${signo(s.delta, 1)} %`; }
      const [ic, tx] = ETQ[s.estado] || ["", ""];
      return `<article class="sem ${ETQ[s.estado] ? s.estado : ""}">
        <div class="t">${esc(s.indicador)}</div>
        <div class="v">${valor}</div>
        <div class="estado">${ic} ${tx} · ${delta}</div>
        <div class="r">${esc(fmtP(s.periodo))} · ${esc(s.texto_referencia)}</div>
      </article>`;
    }).join("");
  }

  function renderPrecios() {
    const P = T.precios, reg = estado.region, rango = estado.rango.precios;
    const ng = P.nivel_general[reg];
    const vm = ultimo(ng.p, ng.series.v_m), via = ultimo(ng.p, ng.series.v_ia), vac = ultimo(ng.p, ng.series.v_acum);
    kpis(document.getElementById("kpi-precios"), [
      { t: `Inflación mensual · ${reg}`, v: num(vm.v) + " %", d: fmtP(vm.p) },
      { t: "Interanual", v: num(via.v) + " %", d: "frente al mismo mes del año anterior" },
      { t: "Acumulada en el año", v: num(vac.v) + " %", d: `desde diciembre de ${+String(vac.p).slice(0, 4) - 1}` },
    ]);
    lineas(document.getElementById("c-ipc"), {
      titulo: `Inflación mensual · ${reg}`, desc: "Variación % del IPC respecto del mes anterior.",
      p: ng.p, series: [{ nombre: "IPC mensual", valores: ng.series.v_m }], rango, cero: true, fmt: (v) => num(v) + " %",
    });
    const cnr = P.nucleo_regulados[reg].v_m;
    lineas(document.getElementById("c-cnr"), {
      titulo: "Núcleo, regulados y estacionales", desc: "Variación % mensual. La núcleo es la inflación sin precios regulados ni estacionales.",
      p: cnr.p, series: ["Núcleo", "Regulados", "Estacional"].map((n) => ({ nombre: n, valores: cnr.series[n] })),
      rango, cero: true, fmt: (v) => num(v) + " %",
    });
    const rub = [...P.rubros[reg]].sort((a, b) => (b.v_ia ?? -1e9) - (a.v_ia ?? -1e9));
    barras(document.getElementById("c-rubros"), {
      titulo: `Inflación por rubro · ${fmtP(P.rubros_periodo)}`, desc: "Variación % interanual de cada división del IPC.",
      serie: "Interanual", items: rub.map((r) => ({ etiqueta: r.rubro, valor: r.v_ia, extra: ["Mensual", signo(r.v_m) + " %"] })),
      fmt: (v) => num(v) + " %",
    });
    const tp = P.tipos_de_precio;
    lineas(document.getElementById("c-tipos"), {
      titulo: "Consumidor, mayorista y construcción", desc: "Variación % interanual de cada índice de precios (nacional; ICC en GBA).",
      p: tp.p, series: Object.keys(tp.series).map((n) => ({ nombre: n, valores: tp.series[n] })), rango, fmt: (v) => num(v) + " %",
      nota: "El IPC mide lo que pagan los hogares; el IPIM, los precios mayoristas de productos nacionales e importados; el ICC, el costo de construir una vivienda.",
    });
  }

  function renderBolsillo() {
    const B = T.bolsillo, rango = estado.rango.bolsillo;
    const sr = B.salario_real;
    const reg = ultimo(sr.p, sr.series["Total registrado"]);
    const cbt = ultimo(B.canastas.p, B.canastas.series["CBT H2"]);
    const pob = ultimo(B.pobreza.p, B.pobreza.series["Pobreza (personas)"]);
    const regAnt = sr.series["Total registrado"][reg.i - 12];
    kpis(document.getElementById("kpi-bolsillo"), [
      { t: "Salario real registrado", v: signo(regAnt ? (reg.v / regAnt - 1) * 100 : null) + " %", d: `en 12 meses, a ${fmtP(reg.p)}` },
      { t: "Canasta básica total · familia de 4", v: pesos(cbt.v), d: `${fmtP(cbt.p)} · GBA` },
      { t: "Pobreza (personas)", v: num(pob.v) + " %", d: fmtP(pob.p) + " · 31 aglomerados" },
    ]);
    const base = fmtP(sr.base);
    lineas(document.getElementById("c-salario"), {
      titulo: "Salario real", desc: `Índice de salarios deflactado por el IPC nacional. ${base} = 100: por encima de 100, el salario compra más que en ${base}.`,
      p: sr.p, series: ["Total registrado", "Sector privado registrado", "Sector público"].map((n) => ({ nombre: n, valores: sr.series[n] })),
      rango, fmt: (v) => num(v),
      nota: "El salario no registrado no se grafica: el INDEC lo publica con 5 meses de rezago y no es comparable mes a mes con el IPC.",
    });
    lineas(document.getElementById("c-canasta"), {
      titulo: "Canasta básica total · familia de 4", desc: "En pesos por mes (GBA): la línea de pobreza de un hogar de dos adultos y dos chicos.",
      p: B.canastas.p, series: [{ nombre: "CBT hogar de 4", valores: B.canastas.series["CBT H2"] }], rango, fmt: pesos,
      fmtEje: ejePesos,
    });
    lineas(document.getElementById("c-pobreza"), {
      titulo: "Pobreza e indigencia", desc: "% de personas, por semestre (31 aglomerados urbanos).",
      p: B.pobreza.p, series: Object.keys(B.pobreza.series).map((n) => ({ nombre: n, valores: B.pobreza.series[n] })),
      rango: "todo", cero: true, fmt: (v) => num(v) + " %",
    });
    const cr = B.crianza;
    lineas(document.getElementById("c-crianza"), {
      titulo: "Canasta de crianza", desc: "Costo mensual de criar a un chico, en pesos (bienes, servicios y cuidado).",
      p: cr.p, series: Object.keys(cr.series).map((n) => ({ nombre: n, valores: cr.series[n] })), rango, fmt: pesos,
      fmtEje: ejePesos,
    });
  }

  function renderActividad() {
    const A = T.pulso, rango = estado.rango.actividad;
    const em = A.emae;
    const des = ultimo(em.p, em.series["Var % mensual serie desestacionalizada"]);
    const via = ultimo(em.p, em.series["Var % interanual serie original"]);
    const tr = A.trabajo;
    const deso = ultimo(tr.p, tr.series["Desocupación"]);
    const cx = A.comex;
    const saldo = ultimo(cx.p, cx.series.Saldo);
    kpis(document.getElementById("kpi-actividad"), [
      { t: "Actividad (EMAE) mensual", v: signo(des.v) + " %", d: `${fmtP(des.p)} · desestacionalizado` },
      { t: "Actividad interanual", v: signo(via.v) + " %", d: fmtP(via.p) },
      { t: "Desocupación", v: num(deso.v) + " %", d: fmtP(deso.p) },
      { t: "Saldo comercial", v: "US$ " + num(saldo.v, 0) + " M", d: fmtP(saldo.p) },
    ]);
    lineas(document.getElementById("c-emae"), {
      titulo: "Actividad económica (EMAE)", desc: "Índice desestacionalizado, base 2004 = 100.",
      p: em.p, series: [{ nombre: "EMAE desestacionalizado", valores: em.series["Índice serie desestacionalizada"] }], rango,
    });
    barras(document.getElementById("c-sectores"), {
      titulo: `Actividad por sector · ${fmtP(A.sectores_periodo)}`, desc: "Variación % interanual de cada sector del EMAE.",
      serie: "Interanual", items: A.sectores.map((s) => ({ etiqueta: s.sector, valor: s.v_ia })),
      fmt: (v) => signo(v) + " %",
    });
    const mi = A.ipi_manufacturero.indice_desest, mn = A.ipi_minero.indice_desest;
    // Alinear las dos series por período
    const per = [...new Set([...mi.p, ...mn.p])].sort();
    const idx = (s) => { const m = new Map(s.p.map((p, i) => [p, s.v[i]])); return per.map((p) => m.get(p) ?? null); };
    lineas(document.getElementById("c-ipi"), {
      titulo: "Industria y minería", desc: "Índices de producción (IPI), series desestacionalizadas.",
      p: per, series: [{ nombre: "Industria manufacturera", valores: idx(mi) }, { nombre: "Minería", valores: idx(mn) }], rango,
    });
    lineas(document.getElementById("c-trabajo"), {
      titulo: "Desocupación y subocupación", desc: "% de la población económicamente activa, por trimestre (31 aglomerados).",
      p: tr.p, series: Object.keys(tr.series).map((n) => ({ nombre: n, valores: tr.series[n] })), rango: "todo", cero: true,
      fmt: (v) => num(v) + " %",
    });
    lineas(document.getElementById("c-comex"), {
      titulo: "Exportaciones e importaciones", desc: "Millones de dólares por mes (FOB y CIF).",
      p: cx.p, series: [{ nombre: "Exportaciones", valores: cx.series.Exportaciones }, { nombre: "Importaciones", valores: cx.series.Importaciones }],
      rango, cero: true, fmt: (v) => "US$ " + num(v, 0) + " M", fmtEje: (t) => num(t, 0),
    });
  }

  function renderCatalogo() {
    document.getElementById("cat-lead").textContent =
      `${C.servicios_ok} de ${C.servicios_total} servicios actualizados en la última ingesta (${new Date(C.generado).toLocaleString("es-AR", { dateStyle: "long", timeStyle: "short" })}).`;
    const t = document.getElementById("tabla-catalogo");
    t.innerHTML = `<thead><tr><th>Dataset</th><th>Último dato</th><th>Filas</th><th>Estado</th><th>Descargar</th></tr></thead><tbody>` +
      C.servicios.map((s) => `<tr>
        <td class="wrap"><b>${esc(s.descripcion)}</b><br><span class="nota">${esc(s.endpoint)}</span></td>
        <td>${esc(fmtP(s.ultimo_periodo))}</td>
        <td>${s.filas != null ? s.filas.toLocaleString("es-AR") : "—"}</td>
        <td>${s.ok ? '<span class="ok">✓ OK</span>' : `<span class="falla" title="${esc(s.error)}">✕ Falló</span>`}</td>
        <td><a href="datos/${encodeURIComponent(s.tabla)}.parquet" download>${esc(s.tabla)}.parquet</a></td></tr>`).join("") + "</tbody>";
  }

  // El explorador se carga recién cuando se abre (trae el motor DuckDB-WASM)
  let explorador = null;
  function renderExplorador() {
    if (explorador) return;
    explorador = import("./vendor/explorador.js")
      .then((m) => m.iniciar())
      .catch((e) => {
        console.error(e);
        explorador = null;
        document.getElementById("ex-estado").textContent = "No se pudo cargar el explorador. Recargá la página.";
      });
  }

  const RENDER = { portada: renderPortada, precios: renderPrecios, bolsillo: renderBolsillo, actividad: renderActividad, explorador: renderExplorador, catalogo: renderCatalogo };
  const render = () => { ocultarTip(); RENDER[estado.tab](); };

  // Helpers que usa el explorador (módulo aparte)
  window.Tablero = Object.freeze({ lineas, esc, num, fmtP });

  // ---------------------------------------------------------------- controles
  function iniciarControles() {
    document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => {
      estado.tab = b.dataset.tab;
      document.querySelectorAll(".tabs button").forEach((x) => x.setAttribute("aria-selected", x === b));
      document.querySelectorAll(".panel").forEach((p) => (p.hidden = p.id !== estado.tab));
      history.replaceState(null, "", "#" + estado.tab);
      render();
    }));
    const sel = document.getElementById("region");
    sel.innerHTML = T.precios.regiones.map((r) => `<option>${esc(r)}</option>`).join("");
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
    document.getElementById("tema").addEventListener("click", () => {
      const raiz = document.documentElement;
      const oscuro = raiz.dataset.theme ? raiz.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
      raiz.dataset.theme = oscuro ? "light" : "dark";
      try { localStorage.setItem("tema", raiz.dataset.theme); } catch (e) { /* sin almacenamiento */ }
    });
    let t;
    window.addEventListener("resize", () => { clearTimeout(t); t = setTimeout(() => { if (estado.tab !== "explorador") render(); }, 150); });
    const h = location.hash.slice(1);
    if (RENDER[h]) document.querySelector(`.tabs button[data-tab="${h}"]`).click();
  }

  try { const tm = localStorage.getItem("tema"); if (tm) document.documentElement.dataset.theme = tm; } catch (e) { /* nada */ }

  Promise.all([fetch("data/tableros.json").then((r) => r.json()), fetch("data/catalogo.json").then((r) => r.json())])
    .then(([t, c]) => {
      T = t; C = c;
      document.getElementById("actualizado").textContent =
        "Última actualización: " + new Date(c.generado).toLocaleString("es-AR", { day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "America/Argentina/Buenos_Aires" }) + " (hora argentina).";
      iniciarControles();
      render();
    })
    .catch((e) => {
      document.querySelector("main").innerHTML = `<p class="lead">No se pudieron cargar los datos (${esc(e.message)}).</p>`;
    });
})();
