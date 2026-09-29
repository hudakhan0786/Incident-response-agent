"use strict";

/* ==========================================================================
   Incident Response Agent — frontend
   Vanilla JS, hash-based router, no build step: `uvicorn app.main:app`
   serves this directly. Kept dependency-free so the demo never depends on
   a CDN being reachable.
   ========================================================================== */

const API = "/api";
const root = document.getElementById("view-root");
const toastEl = document.getElementById("toast");

// cache of runbooks, refreshed lazily, used to populate <select> pickers
let runbookCache = null;

/* ------------------------------- api client ------------------------------ */

async function api(path, opts = {}) {
  const res = await fetch(API + path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  if (res.status === 204) return null;
  return res.json();
}
const get = (path) => api(path);
const post = (path, body) => api(path, { method: "POST", body: JSON.stringify(body || {}) });

async function getRunbooks(force = false) {
  if (runbookCache && !force) return runbookCache;
  runbookCache = await get("/runbooks");
  return runbookCache;
}

/* --------------------------------- toast ---------------------------------- */

let toastTimer = null;
function toast(msg, isErr = false) {
  clearTimeout(toastTimer);
  toastEl.textContent = msg;
  toastEl.classList.toggle("err", isErr);
  toastEl.classList.add("show");
  toastTimer = setTimeout(() => toastEl.classList.remove("show"), 3800);
}

/* -------------------------------- helpers --------------------------------- */

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" }) +
    " " + d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

function daysAgo(iso) {
  if (!iso) return null;
  return (Date.now() - new Date(iso).getTime()) / 86400000;
}

function relTime(iso) {
  const d = daysAgo(iso);
  if (d === null) return "never";
  if (d < 1 / 24) return "moments ago";
  if (d < 1) return `${Math.round(d * 24)}h ago`;
  if (d < 30) return `${Math.round(d)}d ago`;
  return `${Math.round(d / 30)}mo ago`;
}

function sevBadge(sev) {
  return `<span class="badge sev-${sev}">${sev}</span>`;
}
function statusBadge(status) {
  return `<span class="badge status-${status}">${status}</span>`;
}
function trustBadge(label) {
  return `<span class="badge trust-${label}">${esc(label)}</span>`;
}

/** Smoothly tween the text content of an element between two numbers. */
function tweenNumber(el, from, to, decimals = 0, duration = 650) {
  const start = performance.now();
  const ease = (t) => 1 - Math.pow(1 - t, 3); // easeOutCubic
  function frame(now) {
    const t = Math.min(1, (now - start) / duration);
    const val = from + (to - from) * ease(t);
    el.textContent = val.toFixed(decimals);
    if (t < 1) requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}

/* ------------------------------- SVG: gauge -------------------------------- */

const GAUGE_MIN = 600, GAUGE_MAX = 2400, GAUGE_R = 40, GAUGE_C = 2 * Math.PI * GAUGE_R;
const GAUGE_ARC = 0.75 * GAUGE_C; // 270 degree sweep, gap at bottom

function gaugeFrac(rating) {
  return Math.max(0, Math.min(1, (rating - GAUGE_MIN) / (GAUGE_MAX - GAUGE_MIN)));
}

function gaugeColor(rating) {
  if (rating >= 1700) return "var(--teal)";
  if (rating >= 1400) return "var(--teal)";
  if (rating >= 900) return "var(--amber)";
  return "var(--red)";
}

/** Returns markup for a self-contained Elo gauge. Pass a unique `uid`. */
function gaugeSvg(uid, rating) {
  const frac = gaugeFrac(rating);
  const dash = frac * GAUGE_ARC;
  return `
    <div class="gauge-wrap">
      <svg width="100" height="86" viewBox="0 0 100 100" data-gauge="${uid}">
        <circle class="gauge-arc-bg" cx="50" cy="50" r="${GAUGE_R}"
          stroke-dasharray="${GAUGE_ARC} ${GAUGE_C}" transform="rotate(135 50 50)"/>
        <circle class="gauge-arc-fg" cx="50" cy="50" r="${GAUGE_R}"
          stroke="${gaugeColor(rating)}"
          stroke-dasharray="${dash} ${GAUGE_C}" transform="rotate(135 50 50)"/>
      </svg>
      <div class="gauge-num" data-gauge-num="${uid}">${rating.toFixed(0)}</div>
    </div>`;
}

/** Animate an existing gauge (by uid) to a new rating value. */
function updateGauge(uid, fromRating, toRating) {
  const svg = document.querySelector(`[data-gauge="${uid}"] .gauge-arc-fg`);
  const numEl = document.querySelector(`[data-gauge-num="${uid}"]`);
  if (!svg || !numEl) return;
  const dash = gaugeFrac(toRating) * GAUGE_ARC;
  svg.setAttribute("stroke", gaugeColor(toRating));
  // force reflow so the dasharray change transitions rather than jumping
  // eslint-disable-next-line no-unused-expressions
  svg.getBoundingClientRect();
  svg.setAttribute("stroke-dasharray", `${dash} ${GAUGE_C}`);
  tweenNumber(numEl, fromRating, toRating, 0, 700);
}

/* ------------------------------- SVG: radar --------------------------------- */

const FP_AXES = [
  ["text_similarity", "Text"],
  ["service_match", "Service"],
  ["error_signature_match", "Error"],
  ["severity_match", "Severity"],
  ["recency", "Recency"],
];

function radarSvg(fingerprint) {
  const cx = 65, cy = 62, rMax = 44;
  const n = FP_AXES.length;
  const angleFor = (i) => -Math.PI / 2 + (i * 2 * Math.PI) / n;

  const rings = [0.33, 0.66, 1.0].map((frac) => {
    const pts = FP_AXES.map((_, i) => {
      const a = angleFor(i);
      return `${cx + Math.cos(a) * rMax * frac},${cy + Math.sin(a) * rMax * frac}`;
    }).join(" ");
    return `<polygon class="fingerprint-grid" points="${pts}"/>`;
  }).join("");

  const axes = FP_AXES.map((_, i) => {
    const a = angleFor(i);
    return `<line class="fingerprint-axis" x1="${cx}" y1="${cy}"
      x2="${cx + Math.cos(a) * rMax}" y2="${cy + Math.sin(a) * rMax}"/>`;
  }).join("");

  const labels = FP_AXES.map(([, label], i) => {
    const a = angleFor(i);
    const lx = cx + Math.cos(a) * (rMax + 12);
    const ly = cy + Math.sin(a) * (rMax + 12);
    const anchor = Math.cos(a) > 0.3 ? "start" : Math.cos(a) < -0.3 ? "end" : "middle";
    return `<text class="fingerprint-label" x="${lx}" y="${ly}" text-anchor="${anchor}" dominant-baseline="middle">${label}</text>`;
  }).join("");

  const poly = FP_AXES.map(([key], i) => {
    const a = angleFor(i);
    const val = fingerprint[key] ?? 0;
    return `${cx + Math.cos(a) * rMax * val},${cy + Math.sin(a) * rMax * val}`;
  }).join(" ");

  return `<svg width="140" height="124" viewBox="0 0 130 120">
    ${rings}${axes}<polygon class="fingerprint-poly" points="${poly}"/>${labels}
  </svg>`;
}

/* -------------------------------- router ----------------------------------- */

const ROUTES = [
  { tag: "warroom", label: "War Room", path: "#/warroom" },
  { tag: "new", label: "New Incident", path: "#/new" },
  { tag: "runbooks", label: "Runbooks", path: "#/runbooks" },
  { tag: "postmortems", label: "Postmortems", path: "#/postmortems" },
];

function renderNav(activeTag) {
  const tabs = ROUTES.map(
    (r) => `<a class="nav-tab ${r.tag === activeTag ? "active" : ""}" href="${r.path}">
      <span>${r.label}</span></a>`
  ).join("");
  document.getElementById("nav-index").innerHTML = tabs;
}

async function refreshNavStatus() {
  try {
    const s = await get("/dashboard/stats");
    const el = document.getElementById("nav-status");
    el.innerHTML = `
      <div class="row"><span>Open now</span><span class="v ${s.open_incidents ? "warn" : ""}">${s.open_incidents}</span></div>
      <div class="row"><span>Avg MTTR</span><span class="v">${s.avg_mttr_minutes ?? "—"}m</span></div>
      <div class="row"><span>Needs revalidation</span><span class="v ${s.decaying_runbooks.length ? "warn" : ""}">${s.decaying_runbooks.length}</span></div>`;
  } catch (_) { /* non-fatal */ }
}

async function router() {
  const hash = location.hash || "#/warroom";
  const parts = hash.replace(/^#\//, "").split("/");
  const [seg, id] = parts;

  try {
    if (seg === "warroom" || !seg) { renderNav("warroom"); await viewWarRoom(); }
    else if (seg === "new") { renderNav("new"); await viewNewIncident(); }
    else if (seg === "runbooks") { renderNav("runbooks"); await viewRunbooks(); }
    else if (seg === "postmortems") { renderNav("postmortems"); await viewPostmortems(); }
    else if (seg === "incident" && id) { renderNav(""); await viewIncidentDetail(Number(id)); }
    else { renderNav("warroom"); await viewWarRoom(); }
  } catch (err) {
    root.innerHTML = `<div class="panel"><h2>Something went wrong</h2><p class="empty-note">${esc(err.message)}</p></div>`;
  }
  refreshNavStatus();
  window.scrollTo(0, 0);
}
window.addEventListener("hashchange", router);

/* ================================ VIEWS ================================== */

async function viewWarRoom() {
  root.innerHTML = `<div class="loading">Loading war room…</div>`;
  const s = await get("/dashboard/stats");
  const open = await get("/incidents?status=open");

  const activeRows = open.length
    ? open.map((i) => incidentRow(i)).join("")
    : `<div class="empty-note">Nothing on fire. All incidents resolved.</div>`;

  const trend = s.mttr_trend;
  const trendMax = Math.max(10, ...trend.map((t) => t.mttr_minutes));
  const sparkline = trend.length ? `
    <svg width="100%" height="90" viewBox="0 0 ${Math.max(trend.length * 46, 200)} 90" preserveAspectRatio="none" style="overflow:visible">
      <polyline fill="none" stroke="var(--amber)" stroke-width="2" points="${trend.map((t, i) =>
        `${i * 46 + 10},${80 - (t.mttr_minutes / trendMax) * 70}`).join(" ")}"/>
      ${trend.map((t, i) => `<circle cx="${i * 46 + 10}" cy="${80 - (t.mttr_minutes / trendMax) * 70}" r="3" fill="var(--amber)">
        <title>${esc(t.title)} — ${t.mttr_minutes}m</title></circle>`).join("")}
    </svg>` : `<div class="empty-note">No resolved incidents yet.</div>`;

  const topRunbooks = s.top_runbooks.map((rb) => `
    <div class="incident-row" style="border-left-color:var(--teal)" data-action="go-runbooks">
      <div class="title"><div class="t">${esc(rb.title)}</div>
        <div class="m">${esc(rb.service)} · used ${rb.times_used}×</div></div>
      <div class="meta">${trustBadge(rb.trust_label)}<span class="mono" style="color:var(--ink-dim)">${rb.elo_rating.toFixed(0)}</span></div>
    </div>`).join("") || `<div class="empty-note">No runbooks proven yet.</div>`;

  const decaying = s.decaying_runbooks.map((rb) => `
    <div class="incident-row" style="border-left-color:var(--amber)" data-action="go-runbooks">
      <div class="title"><div class="t">${esc(rb.title)}</div>
        <div class="m">${esc(rb.service)} · last used ${relTime(rb.last_used_at)}</div></div>
      <div class="meta">${trustBadge(rb.trust_label)}</div>
    </div>`).join("") || `<div class="empty-note">Everything's been exercised recently.</div>`;

  root.innerHTML = `
    <div class="view-header">
      <div><h1>War room</h1><div class="desc">Live status across every service this tool has seen an incident on.</div></div>
    </div>

    <div class="readout-strip">
      <div class="readout"><div class="num ${s.open_incidents ? "amber" : ""}">${s.open_incidents}</div><div class="lbl">Open right now</div></div>
      <div class="readout"><div class="num">${s.avg_mttr_minutes ?? "—"}</div><div class="lbl">Average minutes to resolve</div></div>
      <div class="readout"><div class="num teal">${s.resolved_incidents}</div><div class="lbl">Resolved, all time</div></div>
      <div class="readout"><div class="num">${s.incidents_by_service.length}</div><div class="lbl">Services with history</div></div>
    </div>

    <div class="two-col">
      <div>
        <div class="panel">
          <h2>Active incidents</h2>
          ${activeRows}
        </div>
        <div class="panel">
          <h2>Time-to-resolve, most recent</h2>
          ${sparkline}
        </div>
      </div>
      <div>
        <div class="panel">
          <h2>Most-trusted runbooks</h2>
          ${topRunbooks}
        </div>
        <div class="panel">
          <h2>Needs re-validation</h2>
          ${decaying}
        </div>
      </div>
    </div>`;
}

function incidentRow(i) {
  return `<div class="incident-row ${i.severity}" data-action="open-incident" data-id="${i.id}">
    <div class="title"><div class="t">${esc(i.title)}</div>
      <div class="m">${esc(i.service)} · started ${relTime(i.started_at)}</div></div>
    <div class="meta">${sevBadge(i.severity)}${statusBadge(i.status)}</div>
  </div>`;
}

/* ------------------------------ new incident -------------------------------- */

async function viewNewIncident() {
  root.innerHTML = `
    <div class="view-header">
      <div><h1>Log a new incident</h1>
        <div class="desc">Describe what's happening. The fingerprint engine checks it against every resolved incident on record before you write a single line of mitigation.</div></div>
    </div>

    <div class="panel">
      <form id="new-incident-form">
        <div class="form-grid">
          <div class="field span-2">
            <label for="f-title">Title</label>
            <input id="f-title" required placeholder="e.g. Checkout API 502s during traffic spike">
          </div>
          <div class="field span-2">
            <label for="f-desc">What's happening</label>
            <textarea id="f-desc" required placeholder="Symptoms, what you've ruled out, anything odd about timing…"></textarea>
          </div>
          <div class="field">
            <label for="f-service">Service</label>
            <input id="f-service" placeholder="e.g. payments-api" list="service-list">
            <datalist id="service-list"></datalist>
          </div>
          <div class="field">
            <label for="f-errsig">Error signature</label>
            <input id="f-errsig" placeholder="e.g. 502-upstream-timeout">
          </div>
          <div class="field span-2">
            <label>Severity</label>
            <div class="severity-select-row" id="sev-picker">
              ${["SEV1", "SEV2", "SEV3", "SEV4"].map((s, i) =>
                `<button type="button" class="sev-pick ${i === 2 ? "selected " + s : ""}" data-sev="${s}">${s}</button>`).join("")}
            </div>
          </div>
        </div>
        <button type="submit" class="primary">Log incident and find matches</button>
      </form>
    </div>

    <div id="suggest-results"></div>
  `;

  // service autocomplete
  get("/runbooks").then((rbs) => {
    const services = [...new Set(rbs.map((r) => r.service))];
    document.getElementById("service-list").innerHTML =
      services.map((s) => `<option value="${esc(s)}">`).join("");
  }).catch(() => {});

  let selectedSeverity = "SEV3";
  document.getElementById("sev-picker").addEventListener("click", (e) => {
    const btn = e.target.closest(".sev-pick");
    if (!btn) return;
    selectedSeverity = btn.dataset.sev;
    document.querySelectorAll(".sev-pick").forEach((b) => b.className = "sev-pick");
    btn.classList.add("selected", selectedSeverity);
  });

  document.getElementById("new-incident-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const submitBtn = e.target.querySelector("button[type=submit]");
    submitBtn.disabled = true;
    submitBtn.textContent = "Searching history…";

    const payload = {
      title: document.getElementById("f-title").value,
      description: document.getElementById("f-desc").value,
      service: document.getElementById("f-service").value || "unknown",
      error_signature: document.getElementById("f-errsig").value,
      severity: selectedSeverity,
    };

    try {
      const incident = await post("/incidents", payload);
      const suggestions = await post("/search/suggest", { ...payload, top_k: 4 });
      renderSuggestResults(incident, suggestions);
      toast(`Incident #${incident.id} logged.`);
    } catch (err) {
      toast("Could not log incident: " + err.message, true);
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = "Log incident and find matches";
    }
  });
}

function renderSuggestResults(incident, suggestions) {
  const box = document.getElementById("suggest-results");
  const hindsightPanel = suggestions.hindsight_memories?.length ? `
    <div class="panel" style="border-color:var(--teal)">
      <h2>Hindsight memory</h2>
      <p class="empty-note">Relevant incident knowledge recalled from the Hindsight memory bank.</p>
      ${suggestions.hindsight_memories.map((memory) => `
        <div class="mini-runbook"><div class="n"><div class="why">${esc(memory.text)}</div></div></div>
      `).join("")}
    </div>` : "";
  if (!suggestions.matches.length) {
    box.innerHTML = `
      ${hindsightPanel}
      <div class="panel">
        <h2>No close precedent found</h2>
        <p class="empty-note">Nothing in history closely matches this fingerprint yet — you're likely first to see this one.
          <a href="#/incident/${incident.id}" style="color:var(--amber)">Open incident #${incident.id}</a> to start logging your response.</p>
      </div>`;
    return;
  }

  box.innerHTML = `
    ${hindsightPanel}
    <div class="panel" style="border-color:var(--amber-dim)">
      <h2>Closest precedents, ranked</h2>
      ${suggestions.matches.map((m) => matchCard(m)).join("")}
      <hr class="hairline">
      <p class="empty-note">Logged as incident #${incident.id}.
        <a href="#/incident/${incident.id}" style="color:var(--amber)">Open it</a> to record which runbook you actually used and mark it resolved.</p>
    </div>`;
}

function matchCard(m) {
  const runbooks = m.recommended_runbooks.length
    ? m.recommended_runbooks.map((r) => `
        <div class="mini-runbook">
          <div class="n"><div class="t">${esc(r.runbook.title)}</div><div class="why">${esc(r.why)}</div></div>
          ${trustBadge(r.runbook.trust_label)}
          <div class="elo">${r.runbook.elo_rating.toFixed(0)}</div>
        </div>`).join("")
    : `<div class="empty-note" style="padding:4px 0">No runbook was linked to this incident's resolution.</div>`;

  return `
    <div class="match-card">
      <div>
        ${radarSvg(m.fingerprint)}
        <div class="score"><b>${Math.round(m.score * 100)}%</b>fingerprint match</div>
      </div>
      <div class="body">
        <div class="title-row">
          <span class="t" data-action="open-incident" data-id="${m.incident.id}">${esc(m.incident.title)}</span>
          ${sevBadge(m.incident.severity)}
          <span class="mono" style="color:var(--ink-faint);font-size:11.5px">MTTR ${m.incident.mttr_minutes ?? "—"}m · ${relTime(m.incident.started_at)}</span>
        </div>
        <div class="desc">${esc(m.incident.description)}</div>
        <div class="recs">${runbooks}</div>
      </div>
    </div>`;
}

/* -------------------------------- runbooks ----------------------------------- */

async function viewRunbooks() {
  root.innerHTML = `<div class="loading">Loading runbook library…</div>`;
  const runbooks = await getRunbooks(true);

  root.innerHTML = `
    <div class="view-header">
      <div><h1>Runbook library</h1>
        <div class="desc">Every rating below comes from real usage on real incidents — an Elo match against the incident's severity, not a star rating anyone typed in. Use "Calibrate" to see it move.</div></div>
    </div>
    <div class="runbook-grid">${runbooks.map(runbookCard).join("")}</div>`;
}

function runbookCard(rb) {
  const uid = "rb" + rb.id;
  const freshPct = Math.round((rb.freshness ?? 0) * 100);
  return `
    <div class="runbook-card" data-runbook-card="${rb.id}">
      <div class="head">
        ${gaugeSvg(uid, rb.elo_rating)}
        <div class="info">
          <div class="t">${esc(rb.title)}</div>
          <div class="svc">${esc(rb.service)}${rb.tags ? " · " + esc(rb.tags) : ""}</div>
          <div style="margin-top:8px">${trustBadge(rb.trust_label)}</div>
        </div>
      </div>
      <div class="stats">
        <span>Used <b>${rb.times_used}</b>×</span>
        <span>Worked <b>${rb.times_worked}</b>×</span>
        <span>Last used <b style="font-weight:600">${relTime(rb.last_used_at)}</b></span>
      </div>
      <div class="freshness-bar"><i style="width:${freshPct}%; background:${freshPct < 25 ? "var(--red)" : freshPct < 60 ? "var(--amber)" : "var(--teal)"}"></i></div>

      <details class="runbook-content">
        <summary style="cursor:pointer;font-size:12.5px;color:var(--ink-dim)">Steps</summary>
        <pre>${esc(rb.content)}</pre>
      </details>

      <div class="calibrate">
        <div class="row">
          <select class="cal-sev" aria-label="Severity to simulate">
            <option value="SEV1">vs SEV1</option>
            <option value="SEV2">vs SEV2</option>
            <option value="SEV3" selected>vs SEV3</option>
            <option value="SEV4">vs SEV4</option>
          </select>
          <div class="outcome-btns">
            <button type="button" class="worked" data-action="calibrate" data-id="${rb.id}" data-uid="${uid}" data-outcome="worked">Worked</button>
            <button type="button" class="partial" data-action="calibrate" data-id="${rb.id}" data-uid="${uid}" data-outcome="partial">Partial</button>
            <button type="button" class="failed" data-action="calibrate" data-id="${rb.id}" data-uid="${uid}" data-outcome="failed">Failed</button>
          </div>
        </div>
        <div class="note">Simulates giving feedback after using this runbook on an incident of the chosen severity.</div>
        <div class="delta-flash" data-delta="${uid}"></div>
      </div>
    </div>`;
}

async function calibrateRunbook(runbookId, uid, outcome, cardEl) {
  const sev = cardEl.querySelector(".cal-sev").value;
  const btns = cardEl.querySelectorAll(".calibrate button");
  btns.forEach((b) => (b.disabled = true));
  try {
    const rb = runbookCache.find((r) => r.id === runbookId);
    const incident = await post("/incidents", {
      title: "Manual trust calibration",
      description: `Synthetic calibration incident for runbook #${runbookId}.`,
      service: rb ? rb.service : "unknown",
      severity: sev,
      error_signature: "manual-calibration",
    });
    await post(`/incidents/${incident.id}/resolve`);
    const result = await post(`/runbooks/${runbookId}/feedback`, {
      incident_id: incident.id,
      outcome,
    });

    updateGauge(uid, result.elo_before, result.elo_after);

    const flash = cardEl.querySelector(`[data-delta="${uid}"]`);
    const sign = result.delta >= 0 ? "+" : "";
    flash.textContent = `${sign}${result.delta.toFixed(1)} → ${result.elo_after.toFixed(1)} (${result.trust_label})`;
    flash.className = "delta-flash show " + (result.delta >= 0 ? "up" : "down");

    const badge = cardEl.querySelector(".badge[class*='trust-']");
    if (badge) {
      badge.className = `badge trust-${result.trust_label}`;
      badge.textContent = result.trust_label;
    }
    const usedEl = cardEl.querySelector(".stats b");
    if (usedEl) usedEl.textContent = String(parseInt(usedEl.textContent, 10) + 1);
    const bar = cardEl.querySelector(".freshness-bar > i");
    if (bar) { bar.style.width = "100%"; bar.style.background = "var(--teal)"; }

    // keep local cache roughly in sync for subsequent calibrations
    if (rb) { rb.elo_rating = result.elo_after; rb.times_used += 1; rb.last_used_at = new Date().toISOString(); }

    toast(`Rated "${outcome}" — Elo ${result.elo_before.toFixed(0)} → ${result.elo_after.toFixed(0)}`);
  } catch (err) {
    toast("Calibration failed: " + err.message, true);
  } finally {
    btns.forEach((b) => (b.disabled = false));
  }
}

/* ------------------------------- postmortems ---------------------------------- */

async function viewPostmortems() {
  root.innerHTML = `<div class="loading">Loading postmortems…</div>`;
  const pms = await get("/postmortems");

  if (!pms.length) {
    root.innerHTML = `
      <div class="view-header"><div><h1>Postmortems</h1></div></div>
      <div class="panel"><p class="empty-note">None generated yet. Open a resolved incident and click "Generate postmortem".</p></div>`;
    return;
  }

  root.innerHTML = `
    <div class="view-header">
      <div><h1>Postmortems</h1>
        <div class="desc">Drafted straight from each incident's own timeline and root causes — a starting point, not a final blameless writeup.</div></div>
    </div>
    ${pms.map((pm) => `
      <div class="pm-card" data-action="open-incident" data-id="${pm.incident_id}">
        <div class="top">
          <span class="t">${esc(pm.incident_title)}</span>
          <span>${sevBadge(pm.incident_severity)}</span>
        </div>
        <div style="color:var(--ink-dim);font-size:12px">${esc(pm.incident_service)} · ${fmtDate(pm.created_at)}</div>
        <div class="pm-section"><h4>Summary</h4><p>${esc(pm.summary)}</p></div>
        <div class="pm-section"><h4>Contributing factors</h4><p>${esc(pm.contributing_factors)}</p></div>
        <div class="pm-section"><h4>Action items</h4>
          <ul class="action-items">${pm.action_items.map((a) => `<li>${esc(a)}</li>`).join("")}</ul>
        </div>
      </div>`).join("")}`;
}

/* ------------------------------ incident detail ------------------------------- */

let playbackTimer = null;

async function viewIncidentDetail(id) {
  root.innerHTML = `<div class="loading">Loading incident…</div>`;
  if (playbackTimer) { clearInterval(playbackTimer); playbackTimer = null; }

  const incident = await get(`/incidents/${id}`);
  const rbs = await getRunbooks();

  const maxMinute = Math.max(1, ...incident.steps.map((s) => s.minute_offset), incident.mttr_minutes || 0);
  const ticks = incident.steps.map((s) =>
    `<div class="tick" style="left:${(s.minute_offset / maxMinute) * 100}%" data-tick="${s.id}"></div>`).join("");

  const stepItems = incident.steps.map((s) => {
    const rb = s.runbook_id ? rbs.find((r) => r.id === s.runbook_id) : null;
    return `
      <div class="step-item" data-step="${s.id}">
        <div class="t-offset">T+${s.minute_offset}m</div>
        <div class="type-chip">${esc(s.step_type)}</div>
        <div class="body">
          <div class="actor">${esc(s.actor)}</div>
          <div class="txt">${esc(s.action_text)}</div>
          ${rb ? `
            <div class="runbook-tag" data-action="go-runbooks">→ ${esc(rb.title)} · ${trustBadge(rb.trust_label)}</div>
            <div class="feedback-inline">
              <button class="worked" data-action="step-feedback" data-runbook="${rb.id}" data-incident="${incident.id}" data-outcome="worked">This worked</button>
              <button class="partial" data-action="step-feedback" data-runbook="${rb.id}" data-incident="${incident.id}" data-outcome="partial">Partially</button>
              <button class="failed" data-action="step-feedback" data-runbook="${rb.id}" data-incident="${incident.id}" data-outcome="failed">Didn't work</button>
            </div>` : ""}
        </div>
      </div>`;
  }).join("") || `<div class="empty-note">No steps logged yet.</div>`;

  const rootCauses = incident.root_causes.length
    ? incident.root_causes.map((rc) => `<li><b>${esc(rc.category)}</b> — ${esc(rc.summary)}</li>`).join("")
    : `<li class="empty-note" style="list-style:none;margin-left:-18px">None recorded yet.</li>`;

  const pmBlock = incident.postmortem ? `
    <div class="panel">
      <h2>Postmortem</h2>
      <div class="pm-section"><h4>Summary</h4><p>${esc(incident.postmortem.summary)}</p></div>
      <div class="pm-section"><h4>Contributing factors</h4><p>${esc(incident.postmortem.contributing_factors)}</p></div>
      <div class="pm-section"><h4>Lessons learned</h4><p>${esc(incident.postmortem.lessons_learned)}</p></div>
      <div class="pm-section"><h4>Action items</h4><ul class="action-items">${incident.postmortem.action_items.map((a) => `<li>${esc(a)}</li>`).join("")}</ul></div>
    </div>` : (incident.status === "resolved" ? `
    <div class="panel">
      <h2>Postmortem</h2>
      <p class="empty-note">Not generated yet.</p>
      <button class="primary" data-action="gen-pm" data-id="${incident.id}">Generate postmortem</button>
    </div>` : "");

  const rbOptions = rbs.map((r) => `<option value="${r.id}">${esc(r.title)}</option>`).join("");

  root.innerHTML = `
    <div class="crumb" data-action="go-warroom">← Back to war room</div>
    <div class="view-header">
      <div>
        <h1>${esc(incident.title)}</h1>
        <div class="desc">${esc(incident.service)} ${incident.error_signature ? " · <span class='mono'>" + esc(incident.error_signature) + "</span>" : ""}</div>
      </div>
      <div style="display:flex;gap:8px;align-items:center">
        ${sevBadge(incident.severity)}${statusBadge(incident.status)}
        ${incident.status !== "resolved" ? `<button class="primary" data-action="resolve" data-id="${incident.id}">Mark resolved</button>` : ""}
      </div>
    </div>

    <div class="panel">
      <p>${esc(incident.description)}</p>
      <hr class="hairline">
      <h2 style="margin-bottom:8px">Root causes</h2>
      <ul style="margin:0;padding-left:18px;font-size:13.5px">${rootCauses}</ul>
    </div>

    <div class="panel">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <h2 style="margin:0">Black-box replay</h2>
        <button data-action="play-timeline">▶ Play</button>
      </div>
      <div class="tape" id="tape">
        <div class="track"></div>
        ${ticks}
        <div class="playhead" id="playhead" style="left:0%"></div>
      </div>
      <div class="step-list">${stepItems}</div>

      <hr class="hairline">
      <h2 style="margin-bottom:10px">Log a step</h2>
      <form id="step-form" class="form-grid">
        <div class="field"><label>Minutes since start</label><input type="number" id="s-min" value="0" min="0"></div>
        <div class="field"><label>Actor</label><input id="s-actor" value="on-call"></div>
        <div class="field"><label>Type</label>
          <select id="s-type">
            <option value="diagnosis">diagnosis</option>
            <option value="mitigation">mitigation</option>
            <option value="fix">fix</option>
            <option value="communication">communication</option>
            <option value="resolution">resolution</option>
          </select>
        </div>
        <div class="field"><label>Runbook used (optional)</label>
          <select id="s-runbook"><option value="">— none —</option>${rbOptions}</select>
        </div>
        <div class="field span-2"><label>What happened</label><textarea id="s-text" required placeholder="e.g. Restarted payment worker pool per runbook"></textarea></div>
        <div class="field span-2"><button type="submit" class="primary">Add step</button></div>
      </form>
    </div>

    ${pmBlock}
  `;

  document.getElementById("step-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await post(`/incidents/${incident.id}/steps`, {
        minute_offset: Number(document.getElementById("s-min").value || 0),
        actor: document.getElementById("s-actor").value || "on-call",
        step_type: document.getElementById("s-type").value,
        action_text: document.getElementById("s-text").value,
        runbook_id: document.getElementById("s-runbook").value ? Number(document.getElementById("s-runbook").value) : null,
      });
      toast("Step logged.");
      viewIncidentDetail(incident.id);
    } catch (err) {
      toast("Couldn't log step: " + err.message, true);
    }
  });
}

function playTimeline() {
  const steps = [...document.querySelectorAll(".step-item")];
  const ticks = [...document.querySelectorAll(".tick")];
  const playhead = document.getElementById("playhead");
  const tape = document.getElementById("tape");
  if (!steps.length) return;

  let i = 0;
  const tapeWidth = 100;
  clearInterval(playbackTimer);

  function step() {
    steps.forEach((s) => s.classList.remove("playing"));
    ticks.forEach((t) => t.classList.remove("active"));
    if (i >= steps.length) { clearInterval(playbackTimer); playbackTimer = null; return; }
    steps[i].classList.add("playing");
    steps[i].scrollIntoView({ block: "nearest", behavior: "smooth" });
    const tick = document.querySelector(`.tick[data-tick="${steps[i].dataset.step}"]`);
    if (tick) { tick.classList.add("active"); playhead.style.left = tick.style.left; }
    i += 1;
  }
  step();
  playbackTimer = setInterval(step, 1100);
}

/* ------------------------------- event delegation ----------------------------- */

document.addEventListener("click", async (e) => {
  const el = e.target.closest("[data-action]");
  if (!el) return;
  const action = el.dataset.action;

  if (action === "open-incident") { location.hash = `#/incident/${el.dataset.id}`; }
  else if (action === "go-warroom") { location.hash = "#/warroom"; }
  else if (action === "go-runbooks") { location.hash = "#/runbooks"; }
  else if (action === "play-timeline") { playTimeline(); }
  else if (action === "resolve") {
    try {
      await post(`/incidents/${el.dataset.id}/resolve`);
      toast("Incident marked resolved.");
      viewIncidentDetail(Number(el.dataset.id));
    } catch (err) { toast("Couldn't resolve: " + err.message, true); }
  }
  else if (action === "gen-pm") {
    el.disabled = true; el.textContent = "Drafting…";
    try {
      await post(`/incidents/${el.dataset.id}/postmortem/generate`);
      toast("Postmortem drafted.");
      viewIncidentDetail(Number(el.dataset.id));
    } catch (err) { toast("Couldn't generate: " + err.message, true); }
  }
  else if (action === "step-feedback") {
    try {
      const result = await post(`/runbooks/${el.dataset.runbook}/feedback`, {
        incident_id: Number(el.dataset.incident),
        outcome: el.dataset.outcome,
      });
      toast(`Rated "${el.dataset.outcome}" — Elo ${result.elo_before.toFixed(0)} → ${result.elo_after.toFixed(0)} (${result.trust_label})`);
    } catch (err) { toast("Couldn't submit feedback: " + err.message, true); }
  }
  else if (action === "calibrate") {
    const card = el.closest("[data-runbook-card]");
    await calibrateRunbook(Number(el.dataset.id), el.dataset.uid, el.dataset.outcome, card);
  }
});

/* --------------------------------- boot ---------------------------------------- */

router();
