"use strict";
(() => {
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const NS = "http://www.w3.org/2000/svg";
  const nf0 = new Intl.NumberFormat("en-MY", { maximumFractionDigits: 0 });
  const nf1 = new Intl.NumberFormat("en-MY", { maximumFractionDigits: 1 });
  const nf2 = new Intl.NumberFormat("en-MY", { maximumFractionDigits: 2 });
  const $ = (id) => document.getElementById(id);
  const monthList = (ms) => ms.map((m) => MONTHS[m - 1]).join(", ");
  const PROVENANCE = {
    observed_lag1: "observed yesterday",
    observed_lag7: "observed 7 days ago",
    calendar: "calendar",
    simulated_dayahead: "simulated day-ahead forecast",
  };

  const cache = new Map();
  let shownDate = null;
  let wantedDate = null;
  let seq = 0;
  let applied = 0;
  let modelForecast = null;

  function svgEl(name, attrs, text) {
    const e = document.createElementNS(NS, name);
    for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, String(v));
    if (text !== undefined) e.textContent = text;
    return e;
  }
  function el(name, text) {
    const e = document.createElement(name);
    if (text !== undefined) e.textContent = text;
    return e;
  }

  // Horizontal bar chart. rows: [{label, value, text}]; negative values extend left of the zero line.
  function barChart(svg, rows, colour) {
    svg.textContent = "";
    const rowH = 22, labelW = 190, valueW = 120, areaW = 330, top = 4;
    const W = labelW + areaW + valueW;
    svg.setAttribute("viewBox", `0 0 ${W} ${rows.length * rowH + top * 2}`);
    const vals = rows.map((r) => r.value);
    const lo = Math.min(0, ...vals), hi = Math.max(0, ...vals);
    const span = hi - lo || 1;
    const x = (v) => labelW + ((v - lo) / span) * areaW;
    rows.forEach((r, i) => {
      const y = top + i * rowH;
      svg.appendChild(svgEl("text", { x: labelW - 6, y: y + 15, "text-anchor": "end", "font-size": 12, fill: "#1B2430" }, r.label));
      const x0 = x(0), x1 = x(r.value);
      svg.appendChild(svgEl("rect", {
        class: "bar", x: Math.min(x0, x1), y: y + 3, width: Math.max(Math.abs(x1 - x0), 1), height: rowH - 8, rx: 2, fill: colour,
      }));
      svg.appendChild(svgEl("text", { x: Math.max(x0, x1) + 6, y: y + 15, "font-size": 11, fill: "#566273" }, r.text));
    });
    svg.appendChild(svgEl("line", { x1: x(0), x2: x(0), y1: top, y2: top + rows.length * rowH, stroke: "#8A94A3" }));
  }

  function renderFeatures(ex) {
    const body = document.querySelector("#explain-features tbody");
    body.textContent = "";
    for (const f of ex.features) {
      const tr = el("tr");
      tr.appendChild(el("td", f.label));
      tr.appendChild(el("td", `${nf2.format(f.value)}${f.unit ? " " + f.unit : ""}`));
      tr.appendChild(el("td", PROVENANCE[f.provenance] || f.provenance));
      body.appendChild(tr);
    }
  }

  function renderImportance(ex) {
    const label = new Map(ex.features.map((f) => [f.name, f.label]));
    const permOf = (r) => r.permutation_mae_increase_rth;
    const meanOf = (r) => (typeof permOf(r) === "object" ? permOf(r).mean : permOf(r));
    const stdOf = (r) => (typeof permOf(r) === "object" ? permOf(r).std : null);
    const order = [...ex.importance].sort((a, b) => meanOf(b) - meanOf(a));
    barChart($("explain-perm"), order.map((r) => ({
      label: label.get(r.name) || r.name,
      value: meanOf(r),
      text: `${nf0.format(meanOf(r))}${stdOf(r) === null ? "" : " ± " + nf0.format(stdOf(r))} RTh`,
    })), "#0E6F6A");
    barChart($("explain-impurity"), order.map((r) => ({
      label: label.get(r.name) || r.name,
      value: r.impurity,
      text: `${nf1.format(r.impurity * 100)}% share`,
    })), "#B8C2CC");
  }

  function renderHist(ex) {
    const svg = $("explain-hist");
    svg.textContent = "";
    const { edges, counts } = ex.trees.histogram;
    const W = 640, H = 220, padL = 36, padR = 12, padT = 26, padB = 34;
    const plotW = W - padL - padR, plotH = H - padT - padB;
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    const e0 = edges[0], e1 = edges[edges.length - 1];
    const x = (v) => padL + ((v - e0) / (e1 - e0 || 1)) * plotW;
    const maxC = Math.max(...counts, 1);
    counts.forEach((c, i) => {
      const h = (c / maxC) * plotH;
      svg.appendChild(svgEl("rect", {
        class: "bar", x: x(edges[i]) + 1, y: padT + plotH - h, width: Math.max(x(edges[i + 1]) - x(edges[i]) - 2, 1), height: h, fill: "#2F80ED",
      }));
    });
    svg.appendChild(svgEl("line", { x1: padL, x2: W - padR, y1: padT + plotH, y2: padT + plotH, stroke: "#8A94A3" }));
    for (const [v, anchor] of [[e0, "start"], [ex.trees.median, "middle"], [e1, "end"]]) {
      svg.appendChild(svgEl("text", { x: x(v), y: H - 12, "text-anchor": anchor, "font-size": 11, fill: "#566273" }, nf0.format(v)));
    }
    const mx = x(ex.trees.mean);
    svg.appendChild(svgEl("line", { class: "mean-line", x1: mx, x2: mx, y1: padT - 6, y2: padT + plotH, stroke: "#C0392B", "stroke-width": 2 }));
    const anchor = mx > W * 0.7 ? "end" : "start";
    svg.appendChild(svgEl("text", { x: mx + (anchor === "end" ? -6 : 6), y: 14, "text-anchor": anchor, "font-size": 12, "font-weight": 600, fill: "#C0392B" },
      `mean ${nf0.format(ex.trees.mean)} RTh`));
    $("explain-hist-note").textContent =
      `${ex.n_trees} trees each predict tomorrow's tank need (RTh). Their mean is the forecast: ${nf0.format(ex.trees.mean)} RTh. ` +
      `Range ${nf0.format(ex.trees.min)}–${nf0.format(ex.trees.max)}, middle 80% of trees ${nf0.format(ex.trees.p10)}–${nf0.format(ex.trees.p90)}.`;
  }

  function renderPath(ex) {
    const ol = $("explain-path");
    ol.textContent = "";
    for (const s of ex.path.splits) {
      const li = el("li");
      li.appendChild(el("strong", `${s.label}: ${nf2.format(s.value)} ${s.direction} ${nf2.format(s.threshold)}`));
      li.appendChild(el("span", `${nf0.format(s.samples)} distinct training days reaching this split; their mean tank need ${nf0.format(s.node_mean_rth)} RTh`));
      ol.appendChild(li);
    }
    const more = $("explain-path-more");
    more.textContent = ex.path.hidden_splits > 0 ? `… ${ex.path.hidden_splits} more splits not shown` : "";
    more.hidden = !(ex.path.hidden_splits > 0);
    $("explain-path-end").textContent =
      `Tree ${ex.path.tree_index + 1} of ${ex.n_trees} (depth ${ex.path.depth}) ends at ${nf0.format(ex.path.tree_prediction_rth)} RTh. ` +
      `One tree is a rough guess; the forecast averages all ${ex.n_trees}.`;
  }

  function renderTraining(ex) {
    const c = ex.classifier;
    $("explain-training").textContent =
      `Trained on ${monthList(ex.training_months)} (${ex.n_training_days} days, ${ex.n_trees} trees, min ${ex.min_samples_leaf} days per leaf), ` +
      `then tested on the held-out months ${monthList(ex.held_out_months)}. On those months the random forest's mean absolute error was ` +
      `${nf0.format(ex.held_out_mae_ai_rth)} RTh against ${nf0.format(ex.held_out_mae_rule_rth)} RTh for the weekday/weekend rule (SIMULATED data). ` +
      `The step-1 day-type classifier scored ${nf1.format(c.accuracy * 100)}% accuracy on ${monthList(c.test_months)} after training on ${monthList(c.train_months)} (${c.label}).`;
  }

  function renderForecastNote() {
    $("explain-forecast").textContent = modelForecast === null ? "" :
      `The recommendation starts from the model forecast of ${nf0.format(modelForecast)} RTh.`;
  }

  function render(ex) {
    $("explain-status").hidden = true;
    $("explain-body").hidden = false;
    renderFeatures(ex);
    renderImportance(ex);
    renderHist(ex);
    renderPath(ex);
    renderTraining(ex);
    shownDate = ex.source_date;
    $("explain-date").textContent = ex.source_date;
  }

  function status(msg) {
    const s = $("explain-status");
    s.textContent = msg;
    s.hidden = false;
  }

  async function load(date) {
    wantedDate = date;
    if (cache.has(date)) {
      seq++;
      applied = seq;
      render(cache.get(date));
      return;
    }
    const mySeq = ++seq;
    try {
      const res = await fetch(`/explain?source_date=${encodeURIComponent(date)}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const ex = await res.json();
      cache.set(date, ex);
      if (mySeq < applied || mySeq < seq) return; // a newer request exists: drop this one
      applied = mySeq;
      render(ex);
    } catch (err) {
      if (mySeq === seq) status(`Could not load the explanation (${err.message}).`);
    }
  }

  document.addEventListener("sca:data", (e) => {
    const d = e.detail;
    if (!d || !d.scenario) return;
    modelForecast = d.recommendation ? d.recommendation.ai_forecast_model_rth : null;
    renderForecastNote();
    if (d.scenario.source_date !== wantedDate) load(d.scenario.source_date);
  });
})();
