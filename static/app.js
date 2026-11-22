"use strict";
(() => {
  const NS = "http://www.w3.org/2000/svg";
  const nf = new Intl.NumberFormat("en-MY", { maximumFractionDigits: 0 });
  const nf1 = new Intl.NumberFormat("en-MY", { maximumFractionDigits: 1 });
  const $ = (id) => document.getElementById(id);
  const fmt = (v, f = nf) => f.format(v).replace("-", "−");
  const STRATEGY = {
    always_full: "Always fill the tank",
    calendar_rule: "Weekday/weekend rule",
    ai_forecast: "AI forecast",
  };
  const COLORS = { sac: "#0E6F6A", tank: "#2F80ED", ec: "#D98E04", chg: "#B8C2CC" };
  const NOON = 14; // index of 12:00 in the 22:00-first hour order

  let data = null;
  let reqBody = null; // request body that produced `data`
  let dayType = "weekday";
  let seq = 0;
  let applied = 0;
  let timer = null;
  let playTimer = null;
  let toastTimer = null;
  let idx = NOON;
  let override = null; // operator charge target (RTh) being previewed, else null

  function el(name, attrs = {}, parent = null, text = null) {
    const e = document.createElementNS(NS, name);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    if (text !== null) e.textContent = text;
    if (parent) parent.appendChild(e);
    return e;
  }

  // ---------- inputs ----------
  function readInputs() {
    const cap = Number($("capacity").value);
    $("level").max = cap;
    if (Number($("level").value) > cap) $("level").value = cap;
    return {
      day_type: dayType,
      forecast_max_temp_c: Number($("temp").value),
      forecast_error_pct: Number($("error").value),
      safety_margin_pct: Number($("margin").value),
      tank_capacity_rth: cap,
      tank_level_22_rth: Number($("level").value),
    };
  }

  function showInputs() {
    const b = readInputs();
    $("temp-out").textContent = `${fmt(b.forecast_max_temp_c, nf1)} °C`;
    $("error-out").textContent = `${b.forecast_error_pct > 0 ? "+" : ""}${fmt(b.forecast_error_pct)} %`;
    $("margin-out").textContent = `${fmt(b.safety_margin_pct)} %`;
    $("capacity-out").textContent = `${fmt(b.tank_capacity_rth)} RTh`;
    $("level-out").textContent = `${fmt(b.tank_level_22_rth)} RTh`;
  }

  function clearOverride() {
    override = null;
    seq++; // drop any in-flight response that was requested with the old override
    $("adjust-box").hidden = true;
    $("adjust").setAttribute("aria-expanded", "false");
    $("operator-note").hidden = true;
    $("override-confirm").disabled = true;
    $("approve").disabled = false; // the plan on screen is the AI plan again
  }

  function schedule() {
    clearOverride(); // any input change makes a previewed override stale
    showInputs();
    clearTimeout(timer);
    timer = setTimeout(fetchRecommendation, 300);
  }

  async function fetchRecommendation() {
    const mySeq = ++seq;
    const body = readInputs();
    if (override !== null) body.charge_target_override_rth = override;
    document.body.classList.add("loading");
    try {
      const res = await fetch("/recommend", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(`The advisor returned an error (HTTP ${res.status}).`);
      const json = await res.json();
      if (mySeq < applied || mySeq < seq) return; // a newer request exists: drop this one
      applied = mySeq;
      data = json;
      reqBody = body;
      $("api-error").hidden = true;
      render();
    } catch (err) {
      if (mySeq === seq) {
        $("api-error").textContent = `Could not update the plan: ${err.message}`;
        $("api-error").hidden = false;
      }
    } finally {
      if (mySeq === seq) document.body.classList.remove("loading");
    }
  }

  // ---------- render ----------
  function render() {
    const r = data.recommendation;
    const sc = data.scenario;
    const d = new Date(`${sc.source_date}T00:00:00Z`);
    const dateText = d.toLocaleDateString("en-GB", {
      weekday: "short", day: "numeric", month: "short", year: "numeric", timeZone: "UTC",
    });
    const sd = $("scenario-date");
    sd.textContent = `${dateText} (2024 replay, max ${fmt(sc.source_tmax_c, nf1)} °C)`;
    sd.dataset.date = sc.source_date;

    $("hero-target").textContent = `${fmt(r.charge_target_rth)} RTh`;
    $("capped-chip").hidden = !r.capped;
    const ec = r.electric_chillers;
    $("chiller-plan").textContent = ec.count
      ? `Run ${fmt(ec.count)} electric chillers from ${ec.start} to ${ec.end}`
      : "No overnight charging needed";
    $("ai-need").textContent = `${fmt(r.ai_forecast_need_rth)} RTh`;
    $("actual-need").textContent = `${fmt(r.actual_need_rth)} RTh`;
    $("daytime-ec").textContent = r.daytime_ec_hours ? `${fmt(r.daytime_ec_hours)} h` : "none";
    $("shortfall").textContent = r.shortfall_rth > 0 ? `${fmt(r.shortfall_rth)} RTh` : "none";
    $("shortfall").classList.toggle("good", !(r.shortfall_rth > 0));

    const note = $("status-note");
    note.textContent = "";
    let cls = "ok";
    if (r.shortfall_rth > 0 || r.status === "shortfall") cls = "bad";
    else if (r.capped || r.over_charged || r.daytime_ec_hours > 0) cls = "warn";
    note.className = `status ${cls}`;
    if (cls === "bad") {
      const icon = document.createElement("span");
      icon.setAttribute("aria-hidden", "true");
      icon.textContent = "⚠ ";
      note.appendChild(icon);
    }
    note.appendChild(document.createTextNode(r.message));

    renderImpact();

    const p = data.plant;
    $("plant-text").textContent =
      `Fixed plant: 2 × 1,250 RT absorption chillers (≈${fmt(p.sac_available_rt)} RT ` +
      `available), ${fmt(p.n_ec)} × ${fmt(p.ec_unit_rt)} RT electric chillers, ` +
      `overnight charging ${p.charge_window.replace("-", "–")}.`;

    renderTable();
    const ul = document.querySelector("#assumptions ul");
    ul.textContent = "";
    for (const a of data.assumptions) {
      const li = document.createElement("li");
      li.textContent = a;
      ul.appendChild(li);
    }
    $("scrubber").max = data.hourly.length - 1;
    renderOperator();
    renderTime();
    document.dispatchEvent(new CustomEvent("sca:data", { detail: data }));
  }

  function impactText(prefix, line) {
    const less = line.kwh_saved >= 0;
    const pct = line.pct_saved === null ? "" : ` (${fmt(Math.abs(line.pct_saved), nf1)} %)`;
    const dir = less ? "less" : "more";
    return (
      `${prefix}: ${fmt(Math.abs(line.kwh_saved), nf1)} kWh ${dir} electric-chiller energy${pct}` +
      ` · ≈ ${fmt(Math.abs(line.co2_kg_saved), nf1)} kg CO₂ ${dir}`
    );
  }

  function renderImpact() {
    const im = data.impact;
    $("impact-full").textContent = impactText("vs always filling the tank", im.vs_always_full);
    $("impact-rule").textContent = impactText("vs weekday/weekend rule", im.vs_calendar_rule);
    $("impact-factor").textContent =
      `Grid factor ${im.grid_kg_per_kwh.toFixed(3)} kg CO₂/kWh, ${im.grid_source} · ` +
      "electricity only · ASSUMPTION";
    $("impact-caveat").textContent =
      "One day overstates the saving: cold left in the tank at 21:00 counts as spent. " +
      "Over Oct–Dec the AI saves about 9 % against always filling (SIMULATED).";
  }

  function renderOperator() {
    const op = data.operator_plan;
    const note = $("operator-note");
    note.hidden = !op;
    $("override-confirm").disabled = !(
      override !== null && op && op.charge_target_rth === override &&
      Number($("override-input").value) === override
    );
    if (op) {
      note.textContent =
        `Operator plan: ${fmt(op.charge_target_rth)} RTh · ` +
        `AI recommended ${fmt(data.recommendation.charge_target_rth)} RTh. ${op.message}`;
    }
  }

  function renderTable() {
    const body = document.querySelector("#comparison tbody");
    body.textContent = "";
    for (const c of data.comparison) {
      const tr = document.createElement("tr");
      if (c.strategy === "ai_forecast") tr.className = "ai";
      const cells = [
        STRATEGY[c.strategy] || c.strategy,
        `${fmt(c.charge_target_rth)} RTh`,
        `${fmt(c.ec_energy_kwh)} kWh`,
        c.vs_always_full_pct === null ? "—" : `${fmt(c.vs_always_full_pct, nf1)} %`,
        `${fmt(c.daytime_ec_hours)} h`,
        c.shortfall_rth > 0 ? `${fmt(c.shortfall_rth)} RTh` : "none",
        `${fmt(c.tank_level_21_rth)} RTh`,
      ];
      for (const t of cells) {
        const td = document.createElement("td");
        td.textContent = t;
        tr.appendChild(td);
      }
      body.appendChild(tr);
    }
  }

  // time-dependent parts: tiles, plant view, chart highlights
  function renderTime() {
    if (!data) return;
    const h = data.hourly[idx];
    $("scrubber").value = idx;
    const when = `${h.hour} ${idx < 2 ? "tonight" : "tomorrow"}`;
    $("clock").textContent = when;
    $("t-plant").textContent = `Plant view · ${when}`;
    const night = idx < 10; // 22:00-07:00
    let cap;
    if (h.charge_rt > 0) cap = "Night: charging the tank";
    else if (!night && h.ec_load_rt > 0) cap = "Electric chillers covering the gap";
    else if (h.tank_out_rt > 0) cap = "Day: tank is covering the peak";
    else cap = night ? "Night: absorption chillers only" : "Day: absorption chillers only";
    $("plant-caption").textContent = cap;
    $("tile-load").textContent = `${fmt(h.campus_load_rt)} RT`;
    $("tile-sac").textContent = `${fmt(h.sac_rt)} RT`;
    $("tile-tank").textContent =
      h.charge_rt > 0
        ? `+${fmt(h.charge_rt * 0.95)} RT`
        : h.tank_out_rt > 0 ? `−${fmt(h.tank_out_rt)} RT` : "idle";
    $("tile-ec").textContent = h.ec_count ? `${fmt(h.ec_count)} on` : "all off";
    drawPlant(h);
    drawSupply();
    drawTank();
    document.dispatchEvent(new CustomEvent("sca:hour", { detail: { idx, row: h, data } }));
  }

  // ---------- plant view ----------
  function box(svg, x, y, w, hgt, depth, color, topColor) {
    el("rect", { x, y, width: w, height: hgt, fill: color }, svg);
    el("polygon", {
      points: `${x},${y} ${x + depth},${y - depth / 2} ${x + w + depth},${y - depth / 2} ${x + w},${y}`,
      fill: topColor,
    }, svg);
    el("polygon", {
      points: `${x + w},${y} ${x + w + depth},${y - depth / 2} ${x + w + depth},${y + hgt - depth / 2} ${x + w},${y + hgt}`,
      fill: "#000", opacity: 0.25,
    }, svg);
  }

  function drawPlant(h) {
    const svg = $("plant-svg");
    svg.textContent = "";
    const cap = reqBody.tank_capacity_rth;
    const fill = Math.max(0, Math.min(1, h.tank_level_rth / cap));
    const flow = (x1, y1, x2, y2, on, color) => {
      const l = el("path", {
        d: `M${x1},${y1} L${x2},${y2}`, stroke: color, "stroke-width": 4, fill: "none",
        opacity: on ? 1 : 0.18,
      }, svg);
      if (on) l.setAttribute("stroke-dasharray", "8 6");
    };
    const label = (x, y, t, extra = {}) =>
      el("text", { x, y, fill: "#E8EDF4", "font-size": 13, "font-weight": 600, ...extra }, svg, t);

    // flows first so boxes sit on top
    flow(180, 110, 455, 190, h.sac_rt > 0, "#2BB5AC");
    flow(410, 165, 455, 205, h.tank_out_rt > 0, "#5AA0FF");
    flow(140, 236, 290, 236, h.charge_rt > 0, "#B8C2CC");
    flow(140, 250, 455, 250, h.ec_load_rt > 0, "#F2B73A");

    box(svg, 30, 70, 130, 60, 22, COLORS.sac, "#16918B");
    label(30, 58, "Absorption chillers");
    el("text", { x: 40, y: 106, fill: "#fff", "font-size": 13 }, svg, `${fmt(h.sac_rt)} RT`);

    label(30, 196, "Electric chillers");
    const n = Math.max(data.plant.n_ec, h.ec_count);
    for (let i = 0; i < n; i++) {
      const on = i < h.ec_count;
      const g = el("g", { class: on ? "ec on" : "ec" }, svg);
      box(g, 30 + i * 38, 215, 28, 44, 10, on ? COLORS.ec : "#3A4A63", on ? "#F2B73A" : "#4A5A74");
      el("text", {
        x: 33 + i * 38, y: 280, fill: on ? "#F3D98B" : "#B9C5D6", "font-size": 11,
      }, g, `EC${i + 1}`);
    }

    const tx = 290, ty = 70, tw = 120, th = 190;
    label(tx, 58, "Cold-storage tank");
    el("rect", {
      x: tx, y: ty, width: tw, height: th, rx: 10, fill: "#17263D", stroke: "#4A5A74",
      "stroke-width": 2,
    }, svg);
    const fh = Math.max(0, (th - 6) * fill);
    el("rect", {
      x: tx + 3, y: ty + th - 3 - fh, width: tw - 6, height: fh, rx: 7, fill: COLORS.tank,
      class: "tank-fill",
    }, svg);
    el("text", {
      x: tx + tw / 2, y: ty + th / 2, fill: "#fff", "font-size": 14, "font-weight": 700,
      "text-anchor": "middle",
    }, svg, `${fmt(h.tank_level_rth)} RTh`);
    el("text", {
      x: tx + tw / 2, y: ty + th + 18, fill: "#B9C5D6", "font-size": 12, "text-anchor": "middle",
    }, svg, `of ${fmt(cap)} RTh`);

    label(470, 58, "Campus buildings");
    [[470, 150, 40, 110], [520, 110, 44, 150], [574, 170, 40, 90]].forEach(([x, y, w, hh]) => {
      box(svg, x, y, w, hh, 10, "#5B6F8F", "#7C90B0");
      for (let wy = y + 12; wy < y + hh - 8; wy += 22) {
        el("rect", { x: x + 8, y: wy, width: w - 16, height: 8, fill: "#C9D6EA", opacity: 0.7 }, svg);
      }
    });
    el("text", { x: 470, y: 292, fill: "#fff", "font-size": 13 }, svg, `Load ${fmt(h.campus_load_rt)} RT`);
  }

  // ---------- charts ----------
  function axisGrid(svg, W, H, m, maxV, unit) {
    const steps = 4;
    for (let i = 0; i <= steps; i++) {
      const v = (maxV * i) / steps;
      const y = H - m.b - ((H - m.t - m.b) * i) / steps;
      el("line", { x1: m.l, x2: W - m.r, y1: y, y2: y, stroke: "#E3E6EB" }, svg);
      el("text", { x: m.l - 6, y: y + 4, "text-anchor": "end", "font-size": 11, fill: "#566273" }, svg, fmt(v));
    }
    el("text", { x: 4, y: 12, "font-size": 11, fill: "#566273" }, svg, unit);
  }

  function drawSupply() {
    const svg = $("chart-supply");
    svg.textContent = "";
    const W = 640, H = 240, m = { l: 48, r: 8, t: 20, b: 26 };
    const rows = data.hourly;
    const tot = rows.map((r) => r.sac_rt + r.tank_out_rt + r.ec_load_rt + r.charge_rt + r.unmet_rt);
    const maxV = Math.max(1, ...tot) * 1.05;
    axisGrid(svg, W, H, m, maxV, "RT");
    const bw = (W - m.l - m.r) / rows.length;
    const sy = (v) => ((H - m.t - m.b) * v) / maxV;
    rows.forEach((r, i) => {
      const g = el("g", { class: i === idx ? "bar sel" : "bar", "data-i": i, style: "cursor:pointer" }, svg);
      let y = H - m.b;
      for (const [k, c] of [["sac_rt", COLORS.sac], ["tank_out_rt", COLORS.tank], ["ec_load_rt", COLORS.ec], ["charge_rt", COLORS.chg]]) {
        const hh = sy(r[k]);
        if (hh > 0) el("rect", { x: m.l + i * bw + 2, y: y - hh, width: bw - 4, height: hh, fill: c }, g);
        y -= hh;
      }
      el("rect", {
        x: m.l + i * bw, y: m.t, width: bw, height: H - m.t - m.b, fill: "#000", opacity: 0,
        "pointer-events": "all",
      }, g);
      if (i === idx) {
        el("rect", {
          x: m.l + i * bw, y: m.t, width: bw, height: H - m.t - m.b, fill: "none",
          stroke: "#1B2430", "stroke-width": 2,
        }, g);
      }
      if (r.unmet_rt > 0) {
        const uh = Math.max(3, sy(r.unmet_rt));
        el("rect", { x: m.l + i * bw + 2, y: y - uh, width: bw - 4, height: uh, fill: "#C0392B" }, g);
      }
      el("text", {
        x: m.l + i * bw + bw / 2, y: H - 8, "text-anchor": "middle", "font-size": 10, fill: "#566273",
      }, svg, r.hour.slice(0, 2));
      g.addEventListener("click", () => { idx = i; stopPlay(); renderTime(); });
    });
  }

  function drawTank() {
    const svg = $("chart-tank");
    svg.textContent = "";
    const W = 440, H = 240, m = { l: 48, r: 8, t: 20, b: 26 };
    const rows = data.hourly;
    const cap = reqBody.tank_capacity_rth;
    const maxV = Math.max(cap, ...rows.map((r) => r.tank_level_rth)) * 1.05;
    axisGrid(svg, W, H, m, maxV, "RTh");
    const bw = (W - m.l - m.r) / rows.length;
    const py = (v) => H - m.b - ((H - m.t - m.b) * v) / maxV;
    rows.forEach((r, i) => {
      const y = py(r.tank_level_rth);
      el("rect", {
        x: m.l + i * bw + 2, y, width: bw - 4, height: H - m.b - y,
        fill: i === idx ? "#1B2430" : COLORS.tank, class: i === idx ? "tbar sel" : "tbar",
      }, svg);
      if (i % 2 === 0) el("text", {
        x: m.l + i * bw + bw / 2, y: H - 8, "text-anchor": "middle", "font-size": 11, fill: "#566273",
      }, svg, r.hour.slice(0, 2));
    });
    el("line", { x1: m.l, x2: W - m.r, y1: py(cap), y2: py(cap), stroke: "#C0392B", "stroke-dasharray": "5 4" }, svg);
    el("text", { x: W - m.r, y: py(cap) - 4, "text-anchor": "end", "font-size": 11, fill: "#C0392B" }, svg, "capacity");
  }

  // ---------- playback ----------
  function stopPlay() {
    clearInterval(playTimer);
    playTimer = null;
    $("play").textContent = "Play 24 h";
  }

  function togglePlay() {
    if (playTimer) return stopPlay();
    if (!data) return;
    if (idx >= data.hourly.length - 1) idx = 0;
    $("play").textContent = "Pause";
    renderTime();
    playTimer = setInterval(() => {
      idx = Math.min(idx + 1, data.hourly.length - 1);
      renderTime();
      if (idx >= data.hourly.length - 1) stopPlay();
    }, 700);
  }

  // ---------- decisions ----------
  function openAdjust() {
    if (!data) return;
    const inp = $("override-input");
    inp.max = reqBody.tank_capacity_rth;
    inp.min = 0;
    inp.value = Math.round(data.recommendation.charge_target_rth);
    $("override-confirm").disabled = true;
    $("approve").disabled = true; // approving would log the AI plan, not the previewed one
    $("adjust-box").hidden = false;
    $("adjust").setAttribute("aria-expanded", "true");
    inp.focus();
  }

  function previewOverride() {
    const inp = $("override-input");
    if (inp.value === "" || !inp.checkValidity()) {
      inp.reportValidity();
      return;
    }
    override = Number(inp.value);
    clearTimeout(timer);
    fetchRecommendation();
  }

  async function postDecision(button, action) {
    if (!data || button.disabled) return;
    const body = { ...reqBody, action };
    if (action === "approved") delete body.charge_target_override_rth;
    button.disabled = true;
    try {
      const res = await fetch("/decisions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await res.json();
      if (action === "adjusted") {
        clearOverride();
        fetchRecommendation(); // back to the AI plan view
      }
      if (window.SCADecisions) await window.SCADecisions.refresh();
      toast("Logged · SIMULATED");
    } catch (err) {
      toast(`Could not log the decision (${err.message})`);
    } finally {
      button.disabled = action === "adjusted" && override === null;
    }
  }

  function toast(msg) {
    const t = $("toast");
    t.textContent = msg;
    t.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove("show"), 3000);
  }

  // ---------- wiring ----------
  for (const id of ["temp", "error", "margin", "capacity", "level"]) {
    $(id).addEventListener("input", schedule);
  }
  document.querySelectorAll("#day-type button").forEach((b) => {
    b.addEventListener("click", () => {
      dayType = b.dataset.value;
      document.querySelectorAll("#day-type button").forEach((o) => {
        o.classList.toggle("on", o === b);
        o.setAttribute("aria-pressed", String(o === b));
      });
      schedule();
    });
  });
  $("scrubber").addEventListener("input", (e) => {
    idx = Number(e.target.value);
    stopPlay();
    renderTime();
  });
  $("play").addEventListener("click", togglePlay);
  $("reset").addEventListener("click", () => {
    stopPlay();
    idx = NOON;
    $("scrubber").value = NOON;
    renderTime();
  });
  $("approve").addEventListener("click", () => postDecision($("approve"), "approved"));
  $("adjust").addEventListener("click", openAdjust);
  $("override-preview").addEventListener("click", previewOverride);
  $("override-input").addEventListener("input", () => { $("override-confirm").disabled = true; });
  $("override-confirm").addEventListener("click", () => postDecision($("override-confirm"), "adjusted"));
  $("override-cancel").addEventListener("click", () => {
    const had = override !== null;
    clearOverride();
    if (had) fetchRecommendation();
  });
  document.querySelectorAll("[data-toast]").forEach((b) => {
    b.addEventListener("click", () => toast("Demo only, nothing is sent"));
  });

  window.SCA = {
    getData: () => data,
    setHour(i) {
      if (!data) return;
      idx = Math.max(0, Math.min(data.hourly.length - 1, Number(i)));
      stopPlay();
      renderTime();
    },
  };

  showInputs();
  fetchRecommendation();
})();
