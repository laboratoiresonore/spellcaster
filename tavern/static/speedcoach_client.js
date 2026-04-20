/*
 * SpeedCoach Guild-chat-side client.
 *
 * Does one thing in the main chat UI: polls /api/speedcoach/drift on
 * load + every 5 min, and toggles the drift banner when ComfyUI's
 * /object_info catalogue has changed since the last session.
 *
 * The heavy Insights dashboard lives in insights.html + insights.js;
 * this file stays deliberately small so it can ride along on every
 * chat page load without ballooning the bundle.
 */

(function () {
  "use strict";

  const BANNER_ID  = "speedcoach-drift-banner";
  const TEXT_ID    = "speedcoach-drift-text";
  const DISMISS_ID = "speedcoach-drift-dismiss";
  const LS_KEY     = "speedcoach.drift.ack.session";

  async function fetchDrift() {
    try {
      const r = await fetch("/api/speedcoach/drift");
      if (!r.ok) return null;
      return await r.json();
    } catch {
      return null;
    }
  }

  function getSessionAck() {
    try {
      return sessionStorage.getItem(LS_KEY) || "";
    } catch {
      return "";
    }
  }

  function setSessionAck(hash) {
    try {
      sessionStorage.setItem(LS_KEY, hash);
    } catch { /* sessionStorage disabled */ }
  }

  async function refresh() {
    const banner = document.getElementById(BANNER_ID);
    if (!banner) return;
    const data = await fetchDrift();
    if (!data || !data.has_drift) {
      banner.style.display = "none";
      return;
    }
    // Skip if the user already dismissed this drift hash in this session.
    if (getSessionAck() === data.current_hash) {
      banner.style.display = "none";
      return;
    }
    const a = (data.added || []).length;
    const r = (data.removed || []).length;
    const c = (data.changed || []).length;
    const text = document.getElementById(TEXT_ID);
    if (text) {
      text.textContent = `⚠ ComfyUI node catalogue changed — ${a} added, ${r} removed, ${c} signatures changed. Calibrations may silently regress.`;
    }
    banner.style.display = "flex";
    const dismiss = document.getElementById(DISMISS_ID);
    if (dismiss && !dismiss.dataset.wired) {
      dismiss.addEventListener("click", () => {
        setSessionAck(data.current_hash);
        banner.style.display = "none";
      });
      dismiss.dataset.wired = "1";
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", refresh);
  } else {
    refresh();
  }
  // Re-check every 5 minutes so long-running sessions still pick up drift.
  setInterval(refresh, 5 * 60 * 1000);

  window.SpeedCoachClient = { refresh };
})();
