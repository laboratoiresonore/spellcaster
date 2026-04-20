/*
 * Spellcaster Insights — standalone dashboard wired to /api/speedcoach/*.
 *
 * Fetches the composite `/api/speedcoach/insights` bundle in one round
 * trip and renders eight cards: speed leaderboard, cost vs. quality
 * scatter, per-LoRA impact, queue heatmap, arch speed chart, faceswap
 * reliability sparkline, mailbox SLA, and the last-run warnings list.
 *
 * Design choices:
 *  - One endpoint instead of eight — saves N round-trips, makes a
 *    single empty-state cheap to handle.
 *  - Every card degrades gracefully when its data source is empty
 *    (new installs look like "no data yet" not broken).
 *  - Pure DOM, no framework — the Guild frontend is vanilla JS.
 */

(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);

  async function fetchInsights() {
    try {
      const r = await fetch("/api/speedcoach/insights");
      if (!r.ok) return null;
      return await r.json();
    } catch (e) {
      return null;
    }
  }

  function fmtSeconds(v) {
    if (!v || v <= 0) return "—";
    if (v < 1) return (v * 1000).toFixed(0) + "ms";
    if (v < 60) return v.toFixed(1) + "s";
    const m = Math.floor(v / 60);
    const s = Math.round(v - m * 60);
    return `${m}m ${s}s`;
  }

  function emptyNote(msg) {
    const el = document.createElement("div");
    el.className = "empty";
    el.textContent = msg || "No data yet.";
    return el;
  }

  function renderSpeedLeaderboard(rows) {
    const host = $("speed-leaderboard");
    host.innerHTML = "";
    if (!rows || !rows.length) {
      host.appendChild(emptyNote("Dispatch the same handler ≥3 times to show here."));
      return;
    }
    rows.forEach((r) => {
      const row = document.createElement("div");
      row.className = "row";
      const k = document.createElement("span"); k.className = "k";
      k.textContent = r.handler;
      const v = document.createElement("span"); v.className = "v";
      v.textContent = fmtSeconds(r.median);
      const n = document.createElement("span"); n.className = "n";
      n.textContent = `n=${r.sample_size}`;
      row.appendChild(k); row.appendChild(v); row.appendChild(n);
      host.appendChild(row);
    });
  }

  function renderCostVsQuality(rows) {
    const host = $("cost-vs-quality");
    host.innerHTML = "";
    if (!rows || !rows.length) {
      host.appendChild(emptyNote("Rate a few generations (thumbs) to populate."));
      return;
    }
    const maxE = Math.max(1, ...rows.map(r => r.elapsed));
    const svgNS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(svgNS, "svg");
    svg.setAttribute("viewBox", "0 0 300 220");
    // axes
    const axY = document.createElementNS(svgNS, "line");
    axY.setAttribute("x1", 40); axY.setAttribute("y1", 10);
    axY.setAttribute("x2", 40); axY.setAttribute("y2", 190);
    axY.setAttribute("stroke", "rgba(180,160,110,0.4)");
    svg.appendChild(axY);
    const axX = document.createElementNS(svgNS, "line");
    axX.setAttribute("x1", 40); axX.setAttribute("y1", 190);
    axX.setAttribute("x2", 290); axX.setAttribute("y2", 190);
    axX.setAttribute("stroke", "rgba(180,160,110,0.4)");
    svg.appendChild(axX);
    // labels
    const yL = document.createElementNS(svgNS, "text");
    yL.textContent = "thumbs %"; yL.setAttribute("x", 4); yL.setAttribute("y", 18);
    yL.setAttribute("fill", "#8a8778"); yL.setAttribute("font-size", "10");
    svg.appendChild(yL);
    const xL = document.createElementNS(svgNS, "text");
    xL.textContent = "elapsed (s)"; xL.setAttribute("x", 230); xL.setAttribute("y", 212);
    xL.setAttribute("fill", "#8a8778"); xL.setAttribute("font-size", "10");
    svg.appendChild(xL);
    // points
    rows.forEach((r) => {
      const cx = 40 + (r.elapsed / maxE) * 240;
      const pct = r.thumbs_pct === null || r.thumbs_pct === undefined ? 50 : r.thumbs_pct;
      const cy = 190 - (pct / 100) * 180;
      const c = document.createElementNS(svgNS, "circle");
      c.setAttribute("cx", cx); c.setAttribute("cy", cy);
      c.setAttribute("r", Math.min(9, Math.max(3, Math.log2(r.sample_size + 1) * 2)));
      c.setAttribute("fill", "rgba(240,216,154,0.6)");
      c.setAttribute("stroke", "rgba(200,170,90,0.9)");
      c.setAttribute("stroke-width", "1");
      const title = document.createElementNS(svgNS, "title");
      title.textContent = `${r.handler}\nmedian ${r.elapsed}s · thumbs ${pct}% · n=${r.sample_size}`;
      c.appendChild(title);
      svg.appendChild(c);
    });
    host.appendChild(svg);
  }

  function renderLoraImpact(rows) {
    const host = $("lora-impact");
    host.innerHTML = "";
    if (!rows || !rows.length) {
      host.appendChild(emptyNote("Use a LoRA ≥3 times for impact data."));
      return;
    }
    rows.forEach((r) => {
      const row = document.createElement("div");
      row.className = "row";
      const k = document.createElement("span"); k.className = "k";
      k.textContent = r.lora;
      const v = document.createElement("span"); v.className = "v";
      const sign = r.delta_t >= 0 ? "+" : "";
      v.textContent = `${sign}${r.delta_t}s`;
      const n = document.createElement("span"); n.className = "n";
      const ppSign = r.delta_thumbs_pp >= 0 ? "+" : "";
      n.textContent = `${ppSign}${r.delta_thumbs_pp}pp · n=${r.sample_size}`;
      row.appendChild(k); row.appendChild(v); row.appendChild(n);
      host.appendChild(row);
    });
  }

  function renderQueueHeatmap(matrix) {
    const host = $("queue-heatmap");
    host.innerHTML = "";
    if (!matrix || !matrix.length) {
      host.appendChild(emptyNote("Dispatch history is empty."));
      return;
    }
    let max = 0;
    matrix.forEach((row) => row.forEach((v) => { if (v > max) max = v; }));
    if (max === 0) {
      host.appendChild(emptyNote("Dispatch history is empty."));
      return;
    }
    const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
    const table = document.createElement("table");
    table.className = "heatmap-table";
    for (let d = 0; d < 7; d++) {
      const tr = document.createElement("tr");
      const lbl = document.createElement("td");
      lbl.textContent = days[d];
      lbl.style.color = "#a09a86"; lbl.style.textAlign = "left";
      tr.appendChild(lbl);
      for (let h = 0; h < 24; h++) {
        const td = document.createElement("td");
        const v = matrix[d][h] || 0;
        if (v > 0) {
          td.className = "has";
          td.textContent = v >= 10 ? "█" : v >= 5 ? "▓" : v >= 2 ? "▒" : "░";
          td.title = `${days[d]} ${h}:00 — ${v} dispatches`;
        } else {
          td.textContent = "·";
        }
        tr.appendChild(td);
      }
      table.appendChild(tr);
    }
    host.appendChild(table);
  }

  function renderArchSpeeds(rows) {
    const host = $("arch-speeds");
    host.innerHTML = "";
    if (!rows || !rows.length) {
      host.appendChild(emptyNote("Run preflight to populate."));
      return;
    }
    const max = Math.max(1, ...rows.map(r => r.elapsed_ms || 0));
    rows.forEach((r) => {
      const row = document.createElement("div");
      row.className = "row";
      const k = document.createElement("span"); k.className = "k";
      k.textContent = r.arch;
      const bar = document.createElement("span"); bar.className = "bar-cell";
      const width = Math.max(1, Math.round(20 * (r.elapsed_ms || 0) / max));
      bar.textContent = "█".repeat(width) + "░".repeat(20 - width);
      const v = document.createElement("span"); v.className = "v";
      v.textContent = r.elapsed_ms ? (r.elapsed_ms / 1000).toFixed(1) + "s" : "—";
      const n = document.createElement("span"); n.className = "n";
      const ageHr = Math.round((r.age_s || 0) / 3600);
      n.textContent = r.stale ? "stale" : r.ok ? (ageHr + "h ago") : "failed";
      if (r.stale) n.style.color = "#b08844";
      if (!r.ok) { n.style.color = "#d08080"; }
      row.appendChild(k); row.appendChild(bar); row.appendChild(v); row.appendChild(n);
      host.appendChild(row);
    });
  }

  function renderFaceswap(data) {
    const host = $("faceswap");
    host.innerHTML = "";
    if (!data) {
      host.appendChild(emptyNote("Faceswap state unavailable."));
      return;
    }
    const spark = document.createElement("div");
    spark.className = "bar-cell";
    spark.style.fontSize = "16px";
    spark.textContent = data.spark || "▁".repeat(20);
    host.appendChild(spark);
    const info = document.createElement("div");
    info.className = "row";
    info.innerHTML =
      `<span class="k">Crash history</span>` +
      `<span class="v">${data.crash_pct}% crash (last 20)</span>` +
      `<span class="n">auto-disables: ${data.auto_disable_count}</span>`;
    host.appendChild(info);
    if (data.escalated) {
      const p = document.createElement("div");
      p.innerHTML = '<span class="pill red">ESCALATED — manual reset required</span>';
      p.style.marginTop = "6px";
      host.appendChild(p);
    } else if (data.auto_disabled) {
      const p = document.createElement("div");
      p.innerHTML = '<span class="pill amber">auto-disabled</span> ' +
                    `<span style="color:#8a8778;font-size:12px;">${data.state_reason || ""}</span>`;
      p.style.marginTop = "6px";
      host.appendChild(p);
    }
  }

  function renderMailbox(data) {
    const host = $("mailbox");
    host.innerHTML = "";
    if (!data || !Object.keys(data).length) {
      host.appendChild(emptyNote("Mailbox SLA not available from this client."));
      return;
    }
    const strip = document.createElement("div");
    strip.className = "mailbox-strip";
    const cells = [
      ["pending",     data.pending],
      ["oldest",      data.oldest_s ? (data.oldest_s + "s") : "0s"],
      ["delivered",   data.delivered],
      ["dropped",     data.dropped],
    ];
    cells.forEach(([k, v]) => {
      const c = document.createElement("div");
      c.className = "mbox-cell";
      c.innerHTML = `<div class="v">${v ?? 0}</div><div class="k">${k}</div>`;
      strip.appendChild(c);
    });
    host.appendChild(strip);
    if (data.per_interface) {
      const tbl = document.createElement("div");
      tbl.style.marginTop = "12px";
      Object.entries(data.per_interface).forEach(([iface, s]) => {
        const r = document.createElement("div");
        r.className = "row";
        r.innerHTML =
          `<span class="k">${iface}</span>` +
          `<span class="v">${s.pending || 0} pending</span>` +
          `<span class="n">delivered ${s.delivered || 0} · dropped ${s.dropped || 0}</span>`;
        tbl.appendChild(r);
      });
      host.appendChild(tbl);
    }
  }

  function renderWarningsLast(data) {
    const host = $("warnings-last");
    host.innerHTML = "";
    if (!data) {
      host.appendChild(emptyNote("No dispatch records yet."));
      return;
    }
    const head = document.createElement("div");
    head.className = "row";
    const pillCls = data.outcome === "failed" ? "red" :
                    data.outcome === "warnings" ? "amber" : "green";
    head.innerHTML =
      `<span class="k">Last run outcome</span>` +
      `<span class="v"><span class="pill ${pillCls}">${(data.outcome || "ok").toUpperCase()}</span></span>` +
      `<span class="n">elapsed ${fmtSeconds(data.elapsed)}` +
      (data.predicted ? ` · predicted ${fmtSeconds(data.predicted)}` : "") +
      `</span>`;
    host.appendChild(head);
    const ws = data.warnings || [];
    if (!ws.length) {
      const e = document.createElement("div");
      e.className = "empty"; e.style.marginTop = "6px";
      e.textContent = "No warnings from the last run.";
      host.appendChild(e);
      return;
    }
    ws.forEach((w) => {
      const r = document.createElement("div");
      r.className = "row";
      r.innerHTML = `<span class="k">• ${String(w).replace(/</g, '&lt;')}</span>`;
      host.appendChild(r);
    });
  }

  function renderDriftHero(data) {
    const hero = $("drift-hero");
    const details = $("drift-hero-details");
    if (!data || !data.has_drift) {
      hero.classList.remove("show");
      return;
    }
    const a = (data.added || []).length;
    const r = (data.removed || []).length;
    const c = (data.changed || []).length;
    details.innerHTML =
      `+${a} added · −${r} removed · ~${c} signatures changed. ` +
      `Calibrations tuned against the previous catalogue may silently break.`;
    hero.classList.add("show");
  }

  async function render() {
    $("freshness").textContent = "loading...";
    const data = await fetchInsights();
    if (!data) {
      $("freshness").textContent = "Guild unreachable.";
      return;
    }
    renderDriftHero(data.drift);
    renderSpeedLeaderboard(data.speed_leaderboard);
    renderCostVsQuality(data.cost_vs_quality);
    renderLoraImpact(data.lora_impact);
    renderQueueHeatmap(data.queue_heatmap);
    renderArchSpeeds(data.arch_speeds);
    renderFaceswap(data.faceswap);
    renderMailbox(data.mailbox);
    renderWarningsLast(data.warnings_last);
    const when = new Date();
    $("freshness").textContent = "updated " + when.toLocaleTimeString();
  }

  window.SpellcasterInsights = { refresh: render };
  render();
})();
