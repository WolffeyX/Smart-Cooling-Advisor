"use strict";
(() => {
  const nf = new Intl.NumberFormat("en-MY", { maximumFractionDigits: 0 });
  const num = (v) => (v === "" || v === null || v === undefined || Number.isNaN(Number(v)) ? "—" : nf.format(Number(v)));

  async function refresh() {
    const body = document.querySelector("#decision-log tbody");
    if (!body) return;
    try {
      const res = await fetch("/decisions");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const { rows } = await res.json();
      body.textContent = "";
      for (const r of rows.slice(0, 20)) {
        const tr = document.createElement("tr");
        const cells = [
          String(r.timestamp).replace("T", " "),
          r.action,
          r.day_type,
          `${num(r.ai_target_rth)} RTh`,
          `${num(r.operator_target_rth)} RTh`,
          r.chosen_status,
          `${num(r.chosen_ec_kwh)} kWh`,
        ];
        for (const t of cells) {
          const td = document.createElement("td");
          td.textContent = t;
          tr.appendChild(td);
        }
        body.appendChild(tr);
      }
      document.getElementById("decision-empty").hidden = rows.length > 0;
    } catch (err) {
      document.getElementById("decision-empty").textContent = `Could not load the decision log (${err.message}).`;
      document.getElementById("decision-empty").hidden = false;
    }
  }

  window.SCADecisions = { refresh };
  refresh();
})();
