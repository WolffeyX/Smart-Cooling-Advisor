// Interactive 3D plant view: toggle, live state from app.js events, labels, tooltip.
// All plant numbers come from the API response delivered via sca:hour; nothing is computed here
// except display scaling (particle speed, water-cylinder height as a fraction).
(() => {
  const $ = (id) => document.getElementById(id);
  const btn3 = $("view-3d");
  const btn2 = $("view-2d");
  const note = $("view-note");
  const box = $("plant-3d");
  if (!btn3 || !box) return;

  const fmt = (n) => Math.round(n).toLocaleString("en-US");
  const NAMES = { academic: "Academic", evening: "Library & evening classes", base: "Data centre & labs" };

  function webglAvailable() {
    try {
      const c = document.createElement("canvas");
      return !!(c.getContext("webgl2") || c.getContext("webgl"));
    } catch (e) {
      return false;
    }
  }

  function unavailable(why) {
    btn3.disabled = true;
    btn3.title = why;
    note.textContent = why;
    note.hidden = false;
  }

  const hook = { ready: false, idx: 0, flows: {}, waterFraction: 0, labels: {}, rendering: false };
  window.__plant3d = hook;

  if (!webglAvailable()) {
    unavailable("3D view unavailable: WebGL is not supported in this browser. The 2D view is shown.");
    return;
  }

  let api = null; // scene API
  let last = null; // {idx, row, data}
  let visible = false;
  let raf = 0;
  let prev = 0;
  const labelEls = {};

  function makeLabel(id) {
    const d = document.createElement("div");
    d.className = "plant3d-label";
    const t = document.createElement("span");
    const s = document.createElement("small");
    d.append(t, s);
    box.appendChild(d);
    labelEls[id] = { d, t, s };
  }

  function setLabel(id, title, sub) {
    labelEls[id].t.textContent = title;
    labelEls[id].s.textContent = sub;
  }

  function maxLoad(data) {
    return Math.max(1, ...data.hourly.map((r) => r.campus_load_rt));
  }

  function applyState() {
    if (!api || !last) return;
    const { idx, row, data } = last;
    const plant = data.plant;
    const flows = {
      sac_campus: row.sac_rt,
      ec_tank: row.charge_rt,
      ec_campus: row.ec_load_rt,
      tank_campus: row.tank_out_rt,
      return: row.campus_load_rt,
    };
    const frac = row.tank_level_rth / plant.tank_capacity_rth;
    api.update({ ecCount: row.ec_count, frac, flows, max: maxLoad(data) });
    hook.idx = idx;
    hook.flows = flows;
    hook.waterFraction = frac;
    hook.labels = { academic: row.academic_rt, evening: row.evening_rt, base: row.base_rt };
    setLabel("sac", "Absorption chillers", `${fmt(row.sac_rt)} RT`);
    setLabel("ec", "Electric chillers", `${row.ec_count} of ${plant.n_ec} on`);
    setLabel("tank", "Cold-storage tank", `${fmt(row.tank_level_rth)} of ${fmt(plant.tank_capacity_rth)} RTh`);
    for (const k of Object.keys(NAMES)) setLabel(k, NAMES[k], `${fmt(row[`${k}_rt`])} RT`);
    setLabel("campus", `≈ ${fmt(plant.room_equivalents)} room-equivalents (SIMULATED)`, "");
    hook.ready = true;
    if (visible) api.render();
  }

  // ---------- tooltip ----------
  const tip = $("plant-tooltip");
  function tipText(t) {
    if (!t || !last) return "";
    const { row, data } = last;
    const p = data.plant;
    switch (t.id) {
      case "sac": return `Absorption chillers: ${fmt(row.sac_rt)} RT`;
      case "ec":
        return `Electric chiller ${t.index + 1}: ${t.index < row.ec_count ? "on" : "off"} (${row.ec_count} of ${p.n_ec} on · charging tank ${fmt(row.charge_rt)} RT · to campus ${fmt(row.ec_load_rt)} RT)`;
      case "tank": return `Cold-storage tank: ${fmt(row.tank_level_rth)} of ${fmt(p.tank_capacity_rth)} RTh`;
      case "academic": case "evening": case "base":
        return `${NAMES[t.id]}: ${fmt(row[`${t.id}_rt`])} RT`;
      case "seg": {
        const names = {
          sac_campus: ["Absorption chillers to campus", row.sac_rt],
          ec_tank: ["Electric chillers to tank (charging)", row.charge_rt],
          ec_campus: ["Electric chillers to campus", row.ec_load_rt],
          tank_campus: ["Tank to campus (discharge)", row.tank_out_rt],
          return: ["Warm return to plant", row.campus_load_rt],
        };
        const [n, v] = names[t.key];
        return `${n}: ${fmt(v)} RT`;
      }
      default: return "";
    }
  }

  function showTip(t, x, y) {
    const text = tipText(t);
    if (!text) { tip.hidden = true; return false; }
    tip.textContent = text;
    tip.hidden = false;
    tip.style.left = `${Math.min(x + 12, box.clientWidth - 200)}px`;
    tip.style.top = `${Math.max(y - 28, 4)}px`;
    return true;
  }

  box.addEventListener("pointermove", (e) => {
    if (!api || e.target.tagName !== "CANVAS") return;
    const r = e.target.getBoundingClientRect();
    const x = e.clientX - r.left, y = e.clientY - r.top;
    showTip(api.pick((x / r.width) * 2 - 1, -(y / r.height) * 2 + 1), x, y);
  });
  box.addEventListener("pointerleave", () => { tip.hidden = true; });
  hook.hoverProbe = (id) => showTip({ id, index: 0 }, box.clientWidth / 2, box.clientHeight / 2);

  // ---------- render loop (runs only while visible) ----------
  function size() {
    const w = box.clientWidth, h = box.clientHeight;
    if (api && w > 0 && h > 0) api.resize(w, h);
  }
  function frame(t) {
    if (!visible) { hook.rendering = false; return; }
    const dt = prev ? Math.min((t - prev) / 1000, 0.1) : 0;
    prev = t;
    api.advance(dt);
    api.render();
    const w = box.clientWidth, h = box.clientHeight;
    for (const [id, l] of Object.entries(labelEls)) {
      const p = api.project(id, w, h);
      l.d.style.display = p.on ? "" : "none";
      l.d.style.left = `${p.x}px`;
      l.d.style.top = `${p.y}px`;
    }
    raf = requestAnimationFrame(frame);
  }
  function startLoop() {
    visible = true;
    hook.rendering = true;
    prev = 0;
    size();
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(frame);
  }
  function stopLoop() {
    visible = false;
    hook.rendering = false;
    cancelAnimationFrame(raf);
  }

  // ---------- toggle ----------
  function setMode(three) {
    $("plant-svg").toggleAttribute("hidden", three);
    box.hidden = !three;
    btn3.classList.toggle("on", three);
    btn2.classList.toggle("on", !three);
    btn3.setAttribute("aria-pressed", String(three));
    btn2.setAttribute("aria-pressed", String(!three));
    if (three && api) startLoop();
    else stopLoop();
  }
  btn2.addEventListener("click", () => setMode(false));
  btn3.addEventListener("click", () => setMode(true));
  $("reset-view").addEventListener("click", () => api && api.resetView());
  window.addEventListener("resize", () => visible && size());

  document.addEventListener("sca:hour", (e) => {
    last = e.detail;
    applyState();
  });

  // The scene code (and Three.js) is only imported once WebGL is known to exist.
  import("./plant3d-scene.js")
    .then((m) => {
      api = m.createScene(box);
      for (const id of ["sac", "ec", "tank", "academic", "evening", "base", "campus"]) makeLabel(id);
      hook.camera = null;
      Object.defineProperty(hook, "camera", { get: () => api.getCamera(), enumerable: true });
      hook.setCamera = (p) => api.setCamera(p);
      // sca:hour may have fired before this module finished loading
      const data = window.SCA && window.SCA.getData();
      if (data && !last) {
        const idx = Number($("scrubber").value);
        last = { idx, row: data.hourly[idx], data };
      }
      applyState();
      if (!box.hidden) startLoop();
    })
    .catch(() => unavailable("3D view unavailable: the 3D scene could not be loaded. The 2D view is shown."));
})();
