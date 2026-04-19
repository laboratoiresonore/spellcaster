/**
 * VideoPanel — React component for the Guild's Video/Shotboard tab.
 *
 * Provides full CRUD for shots, backend/preset configuration,
 * reference image attachment, trajectory drawing (via TrajectoryCanvas),
 * render queueing, and status polling with SSE + fallback polling.
 *
 * Features:
 * - Full shot management (CRUD, reorder, duplicate, continuity)
 * - Bulk operations (select, delete, render)
 * - Template system (save/load/delete prompt templates)
 * - Override system (per-shot steps, guidance, frames, fps, resolution)
 * - Reference image upload with drag-drop
 * - Trajectory drawing (via TrajectoryCanvas)
 * - Auto-save with debounce
 * - SSE polling with fallback HTTP polling
 * - Keyboard shortcuts (N=add, Ctrl+Shift+R=render all)
 *
 * Depends on: TrajectoryCanvas (trajectory_canvas.js) being loaded first.
 * Uses the same design tokens as travelling_wizard.jsx (Tailwind + amber/slate).
 */

const {
  useState: _useState,
  useEffect: _useEffect,
  useCallback: _useCallback,
  useRef: _useRef,
  useMemo: _useMemo,
} = React;

// ── Status badge colours ──
const STATUS_STYLE = {
  draft:   { bg: "bg-slate-700",   text: "text-slate-300",  dot: "bg-slate-400"  },
  queued:  { bg: "bg-amber-900/40", text: "text-amber-300", dot: "bg-amber-400"  },
  running: { bg: "bg-blue-900/40",  text: "text-blue-300",  dot: "bg-blue-400 animate-pulse" },
  ready:   { bg: "bg-emerald-900/40", text: "text-emerald-300", dot: "bg-emerald-400" },
  failed:  { bg: "bg-red-900/40",  text: "text-red-300",    dot: "bg-red-400"    },
};

const BACKENDS = ["wangp", "comfyui", "hybrid"];

// ── Small helpers ──
function StatusBadge({ status }) {
  const s = STATUS_STYLE[status] || STATUS_STYLE.draft;
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium ${s.bg} ${s.text}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${s.dot}`} />
      {status}
    </span>
  );
}

// ── API helpers ──
const api = {
  get:  (url) => fetch(url).then(r => r.json()),
  post: (url, body) => fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then(r => r.json()),
};

// ════════════════════════════════════════════════════════════════════
// StatusSummary — shows shot count and status breakdown
// ════════════════════════════════════════════════════════════════════

function StatusSummary({ shots }) {
  const statusCounts = {
    draft: 0, queued: 0, running: 0, ready: 0, failed: 0
  };
  shots.forEach(s => {
    if (statusCounts.hasOwnProperty(s.status)) statusCounts[s.status]++;
  });

  const breakdown = Object.entries(statusCounts)
    .filter(([_, count]) => count > 0)
    .map(([status, count]) => `${count} ${status}`)
    .join(", ");

  return (
    <div className="text-sm text-slate-400">
      {shots.length} shot{shots.length !== 1 ? "s" : ""} · {breakdown || "empty"}
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════
// Shot Card — one row per shot with full editing
// ════════════════════════════════════════════════════════════════════

function ToastContainer({ toasts, onDismiss }) {
  if (!toasts || toasts.length === 0) return null;
  return (
    <div className="toast-container fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm">
      {toasts.map(t => (
        <div key={t.id} className={"toast-item flex items-center gap-2 px-4 py-3 rounded-lg shadow-lg text-sm transition-all " +
          (t.type === "success" ? "bg-emerald-800/90 text-emerald-100 border border-emerald-600/50" :
           t.type === "error" ? "bg-red-800/90 text-red-100 border border-red-600/50" :
           "bg-slate-800/90 text-slate-100 border border-slate-600/50")}>
          <span className="toast-icon">{t.type === "success" ? "OK" : t.type === "error" ? "ERR" : "i"}</span>
          <span className="toast-message flex-1">{t.message}</span>
          <button onClick={() => onDismiss(t.id)}
            className="toast-dismiss text-slate-400 hover:text-white ml-2">&times;</button>
        </div>
      ))}
    </div>
  );
}

function ShotCard({
  shot,
  presets,
  templates,
  onUpdate,
  onRemove,
  onRender,
  onRetry,
  onCancel,
  onOpenTrajectory,
  onUploadRef,
  onReorder,
  onContinuity,
  onDuplicate,
  onClone,
  onMove,
  onSaveTemplate,
  onDeleteTemplate,
  isSelected,
  onToggleSelect,
  isFirst,
  isLast,
  colorLabel,
  onColorLabel,
  estimateAvg,
  allShots,
  onAddDependency,
  onRemoveDependency,
  onToggleLock,
  onSaveSnapshot,
  onRestoreSnapshot,
  onDeleteSnapshot,
  onTogglePinSnapshot,
  focused = false,
}) {
  const [expanded, setExpanded] = _useState(shot.status === "draft");
  const [showHistory, setShowHistory] = _useState(false);
  const [showCompare, setShowCompare] = _useState(false);
  const [showSnapshots, setShowSnapshots] = _useState(false);
  const [snapLabel, setSnapLabel] = _useState("");
  const [snapCompare, setSnapCompare] = _useState([]);  // R46b: 0-2 snap ids selected for diff

  const isLocked = shot.locked || false;
  const [editTitle, setEditTitle] = _useState(shot.title);
  const [editPrompt, setEditPrompt] = _useState(shot.prompt);
  const [editNegative, setEditNegative] = _useState(shot.negative || "");
  const [editNotes, setEditNotes] = _useState(shot.notes || "");
  const [editSeed, setEditSeed] = _useState(shot.seed || "");
  const [editBackend, setEditBackend] = _useState(shot.backend);
  const [editPreset, setEditPreset] = _useState(shot.preset);
  const [uploading, setUploading] = _useState(false);
  const fileRef = _useRef(null);
  const [dragOver, setDragOver] = _useState(false);
  const [showAdvanced, setShowAdvanced] = _useState(false);
  const [editCarryFrame, setEditCarryFrame] = _useState(shot.carry_last_frame || false);
  const [editTransition, setEditTransition] = _useState(shot.transition || "cut");
  const [editTransitionMs, setEditTransitionMs] = _useState(shot.transition_ms ?? 500);
  const [editTargetDuration, setEditTargetDuration] = _useState(shot.target_duration_s ?? "");

  // Override state
  const [ovSteps, setOvSteps] = _useState(shot.overrides?.steps ?? "");
  const [ovGuidance, setOvGuidance] = _useState(shot.overrides?.guidance ?? "");
  const [ovFrames, setOvFrames] = _useState(shot.overrides?.frames ?? "");
  const [ovFps, setOvFps] = _useState(shot.overrides?.fps ?? "");
  const [ovResolution, setOvResolution] = _useState(shot.overrides?.resolution ?? "");

  const debounceRef = _useRef(null);
  const lastSavedRef = _useRef(null);

  // Sync from props when shot changes externally (e.g. poll refresh)
  _useEffect(() => {
    setEditTitle(shot.title);
    setEditPrompt(shot.prompt);
    setEditNegative(shot.negative || "");
    setEditNotes(shot.notes || "");
    setEditSeed(shot.seed || "");
    setEditBackend(shot.backend);
    setEditPreset(shot.preset);
    setEditCarryFrame(shot.carry_last_frame || false);
    setEditTransition(shot.transition || "cut");
    setEditTransitionMs(shot.transition_ms ?? 500);
    setOvSteps(shot.overrides?.steps ?? "");
    setOvGuidance(shot.overrides?.guidance ?? "");
    setOvFrames(shot.overrides?.frames ?? "");
    setOvFps(shot.overrides?.fps ?? "");
    setOvResolution(shot.overrides?.resolution ?? "");
  }, [shot.title, shot.prompt, shot.negative, shot.notes, shot.seed, shot.backend, shot.preset, shot.carry_last_frame, shot.transition, shot.transition_ms, JSON.stringify(shot.overrides)]);

  const buildOverrides = () => {
    const ov = {};
    if (ovSteps) ov.steps = parseInt(ovSteps, 10);
    if (ovGuidance) ov.guidance = parseFloat(ovGuidance);
    if (ovFrames) ov.frames = parseInt(ovFrames, 10);
    if (ovFps) ov.fps = parseInt(ovFps, 10);
    if (ovResolution) ov.resolution = ovResolution;
    return Object.keys(ov).length > 0 ? ov : null;
  };

  const calcDuration = () => {
    const preset = presets[editPreset] || {};
    const frames = parseInt(ovFrames || preset.frames || 16, 10);
    const fps = parseInt(ovFps || preset.fps || 8, 10);
    if (frames && fps) {
      return (frames / fps).toFixed(2) + "s";
    }
    return "—";
  };

  const doSave = () => {
    onUpdate(shot.id, {
      title: editTitle,
      prompt: editPrompt,
      negative: editNegative,
      notes: editNotes,
      seed: editSeed,
      backend: editBackend,
      preset: editPreset,
      carry_last_frame: editCarryFrame,
      transition: editTransition,
      transition_ms: parseInt(editTransitionMs, 10) || 500,
      overrides: buildOverrides(),
    });
    lastSavedRef.current = {
      title: editTitle,
      prompt: editPrompt,
      negative: editNegative,
      notes: editNotes,
      seed: editSeed,
      backend: editBackend,
      preset: editPreset,
      carry_last_frame: editCarryFrame,
      transition: editTransition,
      transition_ms: editTransitionMs,
      overrides: JSON.stringify(buildOverrides()),
    };
  };

  const dirty = () => {
    const current = {
      title: editTitle,
      prompt: editPrompt,
      negative: editNegative,
      notes: editNotes,
      seed: editSeed,
      backend: editBackend,
      preset: editPreset,
      carry_last_frame: editCarryFrame,
      transition: editTransition,
      transition_ms: editTransitionMs,
      overrides: JSON.stringify(buildOverrides()),
    };
    const last = lastSavedRef.current || {
      title: shot.title,
      prompt: shot.prompt,
      negative: shot.negative || "",
      notes: shot.notes || "",
      seed: shot.seed || "",
      backend: shot.backend,
      preset: shot.preset,
      carry_last_frame: shot.carry_last_frame || false,
      transition: shot.transition || "cut",
      transition_ms: shot.transition_ms ?? 500,
      overrides: JSON.stringify(shot.overrides || null),
    };
    return JSON.stringify(current) !== JSON.stringify(last);
  };

  // Debounced auto-save at 800ms
  _useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!dirty()) return;
    debounceRef.current = setTimeout(() => {
      doSave();
    }, 800);
    return () => clearTimeout(debounceRef.current);
  }, [editTitle, editPrompt, editNegative, editNotes, editSeed, editBackend, editPreset, editCarryFrame, editTransition, editTransitionMs, ovSteps, ovGuidance, ovFrames, ovFps, ovResolution]);

  const presetKeys = presets ? Object.keys(presets) : [];
  const currentPreset = presets[editPreset];

  return (
    <div data-shot-id={shot.id} className={`bg-slate-900 border rounded-xl overflow-hidden transition-all ${focused ? "shot-card-focused ring-2 ring-amber-400 border-amber-400" : ""} ${isSelected ? "shot-card-root border-amber-400 shadow-lg shadow-amber-600/30" : focused ? "" : "border-amber-600/20"}`}>
      {/* Collapsed header */}
      <div
        draggable
        onDragStart={e => { e.dataTransfer.setData("text/plain", shot.id); e.dataTransfer.effectAllowed = "move"; }}
        onDragOver={e => { e.preventDefault(); e.dataTransfer.dropEffect = "move"; setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={e => { e.preventDefault(); setDragOver(false); const from = e.dataTransfer.getData("text/plain"); if (from !== shot.id) onReorder(from, shot.id); }}
        className={`flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-purple-800/10 transition-colors reorder-arrows ${dragOver ? "border-t-2 border-amber-400" : ""}`}
        onClick={() => setExpanded(!expanded)}
      >
        <input
          type="checkbox"
          checked={isSelected}
          onChange={() => onToggleSelect(shot.id)}
          onClick={e => e.stopPropagation()}
          className="bulk-checkbox w-4 h-4 rounded accent-amber-500"
        />
        {/* Move arrows */}
        <div className="flex gap-0.5">
          <button
            disabled={isFirst}
            onClick={(e) => { e.stopPropagation(); onMove(shot.id, -1); }}
            className="p-0.5 text-slate-500 hover:text-amber-300 disabled:opacity-20 transition-colors"
            title="Move up"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 15l-6-6-6 6" /></svg>
          </button>
          <button
            disabled={isLast}
            onClick={(e) => { e.stopPropagation(); onMove(shot.id, 1); }}
            className="p-0.5 text-slate-500 hover:text-amber-300 disabled:opacity-20 transition-colors"
            title="Move down"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M6 9l6 6 6-6" /></svg>
          </button>
        </div>

        <span className="text-amber-600/60 text-xs font-mono w-6 text-center">{shot.index + 1}</span>
        <div className="w-12 h-8 rounded bg-slate-950 border border-amber-600/20 overflow-hidden flex-shrink-0">
          {shot.thumb ? (
            <img src={shot.thumb || `/api/video/shots/${shot.id}/thumbnail`} alt="thumb" className="w-full h-full object-cover" />
          ) : (
            <div className="w-full h-full flex items-center justify-center text-slate-600">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="8.5" cy="8.5" r="1.5" /><path d="M21 15l-5-5L5 21" /></svg>
            </div>
          )}
        </div>
        <span className="flex-1 text-amber-50 text-sm font-medium truncate">
          {editTitle || <span className="text-slate-500 italic">Untitled shot</span>}
        </span>
        <StatusBadge status={shot.status} />
        {shot.ref_image && (
          <span className="text-xs text-purple-400 font-medium" title="Has reference image">REF</span>
        )}
        {shot.trajectories && shot.trajectories.length > 0 && (
          <span className="text-xs text-teal-400 font-medium" title={`${shot.trajectories.length} trajectory(s)`}>
            {shot.trajectories.length}T
          </span>
        )}
        <div className="text-amber-600 text-xs font-mono tabular-nums w-12 text-right">
          {shot.status === "running" || shot.status === "queued" ? (
            <span>{shot.progress || 0}%</span>
          ) : (
            <span>{calcDuration()}</span>
          )}
        </div>
        <span className={`text-amber-600 transition-transform ${expanded ? "rotate-180" : ""}`}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M6 9l6 6 6-6" /></svg>
        </span>
      </div>

      {/* Error banner */}
      {shot.error && (
        <div className="error-banner bg-red-500/10 border-t border-red-500/30 px-4 py-2 text-sm text-red-400 flex items-center gap-2">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0zM12 9v4M12 17h.01" /></svg>
          {shot.error}
        </div>
      )}

      {/* Progress bar for running/queued */}
      {(shot.status === "running" || shot.status === "queued") && (
        <div className="h-1 bg-slate-800">
          <div
            className="h-full bg-gradient-to-r from-amber-500 to-amber-400 transition-all"
            style={{ width: `${Math.min(shot.progress || 0, 100)}%` }}
          />
        </div>
      )}

      {/* Inline video preview for ready shots */}
      {shot.video_path && shot.status === "ready" && (
        <div className="px-4 py-2 bg-slate-950">
          <video
            src={`/api/video/shots/${shot.id}/video`}
            controls
            autoPlay
            loop
            muted
            className="max-h-32 rounded"
          />
        </div>
      )}

      {/* Expanded editor */}
      {expanded && (
        <div className="px-4 pb-4 space-y-3 border-t border-amber-600/15">
          {/* Title */}
          <div className="pt-3">
            <label className="block text-xs font-medium text-amber-200 mb-1">Title</label>
            <input
              value={editTitle}
              onChange={e => setEditTitle(e.target.value)}
              placeholder="EXT. forest — day"
              className="w-full bg-slate-950 border border-amber-500/20 rounded-lg px-3 py-2 text-amber-50 placeholder-slate-500 focus:border-amber-500/60 outline-none text-sm"
            />
          </div>

          {/* Prompt */}
          <div>
            <label className="block text-xs font-medium text-amber-200 mb-1">Prompt</label>
            <textarea
              value={editPrompt}
              onChange={e => setEditPrompt(e.target.value)}
              placeholder="A gentle breeze through autumn trees, camera slowly panning right..."
              rows={3}
              className="w-full bg-slate-950 border border-amber-500/20 rounded-lg px-3 py-2 text-amber-50 placeholder-slate-500 focus:border-amber-500/60 outline-none text-sm resize-y"
            />
            {(() => {
              const currentPreset = presets.find(p => p.key === editPreset) || {};
              const limit = currentPreset.prompt_char_limit || 500;
              const len = editPrompt.length;
              const color = len > limit ? "text-red-400" : len > limit * 0.8 ? "text-amber-400" : "text-slate-500";
              return (
                <div className="prompt-char-count flex justify-end text-[10px] mt-0.5">
                  <span className={"prompt-char-current " + color}>{len}</span>
                  <span className="prompt-char-limit text-slate-600">/{limit}</span>
                  {len > limit && <span className="prompt-limit-warning text-red-400 ml-1">(over limit)</span>}
                </div>
              );
            })()}
          </div>

          {/* Negative prompt */}
          <div>
            <label className="block text-xs font-medium text-amber-200 mb-1">Negative Prompt</label>
            <textarea
              value={editNegative}
              onChange={e => setEditNegative(e.target.value)}
              placeholder="blurry, distorted, artifacts..."
              rows={2}
              className="w-full bg-slate-950 border border-amber-500/20 rounded-lg px-3 py-2 text-amber-50 placeholder-slate-500 focus:border-amber-500/60 outline-none text-sm resize-y"
            />
          </div>

          {/* Prompt templates */}
          {templates && templates.length > 0 && (
            <div>
              <label className="block text-xs font-medium text-amber-200 mb-2">Prompt Templates</label>
              <div className="prompt-templates flex flex-wrap gap-2">
                {templates.map((t, idx) => (
                  <div key={idx} className="flex items-center gap-1 bg-slate-950 border border-amber-500/20 rounded-lg px-2 py-1 text-xs">
                    <button
                      onClick={() => setEditPrompt(t.prompt)}
                      className="text-amber-400 hover:text-amber-300"
                      title="Load this template"
                    >
                      {t.name}
                    </button>
                    <button
                      onClick={() => onDeleteTemplate(t.id)}
                      className="text-slate-500 hover:text-red-400 text-lg leading-none"
                    >
                      &times;
                    </button>
                  </div>
                ))}
              </div>
              <button
                onClick={() => {
                  if (editPrompt.trim()) {
                    const name = prompt("Template name?");
                    if (name) onSaveTemplate({ name, prompt: editPrompt });
                  }
                }}
                className="save-template-btn mt-2 text-xs text-amber-400 hover:text-amber-300 font-medium underline"
              >
                + Save as template
              </button>
            </div>
          )}

          {/* Director's notes */}
          <div>
            <label className="block text-xs font-medium text-amber-200 mb-1">Director's Notes <span className="text-slate-500">(not sent to model)</span></label>
            <textarea
              value={editNotes}
              onChange={e => setEditNotes(e.target.value)}
              placeholder="Internal notes for you or your team..."
              rows={2}
              className="shot-notes w-full bg-slate-950 border border-amber-500/20 rounded-lg px-3 py-2 text-amber-50 placeholder-slate-500 focus:border-amber-500/60 outline-none text-sm resize-y"
            />
          </div>

          {/* Render history */}
          <div className="render-history-section">
            <button
              onClick={() => setShowHistory(!showHistory)}
              className="render-history-toggle text-xs text-slate-400 hover:text-amber-300 flex items-center gap-1"
            >
              <span>{showHistory ? "Hide" : "Show"} render history</span>
              <span className="render-history-count text-slate-500">({(shot.render_history || []).length})</span>
            </button>
            {showHistory && (shot.render_history || []).length > 0 && (
              <div className="render-history-list mt-2 space-y-1 max-h-32 overflow-y-auto">
                {(shot.render_history || []).slice().reverse().map((entry, i) => (
                  <div key={i} className={"render-history-entry text-[10px] px-2 py-1 rounded " +
                    (entry.status === "ready" ? "bg-emerald-900/30 text-emerald-300" :
                     entry.status === "failed" ? "bg-red-900/30 text-red-300" :
                     "bg-slate-800/50 text-slate-400")}>
                    <span className="render-history-time">{new Date(entry.timestamp * 1000).toLocaleString()}</span>
                    {" — "}
                    <span className="render-history-status font-medium">{entry.status}</span>
                    {entry.preset && <span className="render-history-preset"> ({entry.preset})</span>}
                    {entry.duration_s != null && <span className="render-history-duration"> {entry.duration_s.toFixed(1)}s</span>}
                    {entry.error && <span className="render-history-error text-red-400"> {entry.error}</span>}
                  </div>
                ))}
              </div>
            )}
            {showHistory && (shot.render_history || []).length === 0 && (
              <div className="text-[10px] text-slate-500 mt-1">No renders yet</div>
            )}
          </div>

          {/* R45a: Snapshots */}
          <div className="snapshots-section">
            <button
              onClick={() => setShowSnapshots(!showSnapshots)}
              className="snapshots-toggle text-xs text-slate-400 hover:text-cyan-300 flex items-center gap-1"
            >
              <span>{showSnapshots ? "Hide" : "Show"} snapshots</span>
              <span className="snapshots-count text-slate-500">({(shot.snapshots || []).length})</span>
            </button>
            {showSnapshots && (
              <div className="snapshots-panel mt-2 rounded bg-slate-900/60 border border-cyan-700/20 p-2 space-y-2">
                <div className="snapshots-save-row flex gap-2 items-center">
                  <input
                    type="text"
                    value={snapLabel}
                    onChange={(e) => setSnapLabel(e.target.value)}
                    placeholder="Snapshot label (optional)"
                    className="snapshot-label-input flex-1 bg-slate-800 border border-slate-600 rounded px-2 py-1 text-[11px] text-slate-200 placeholder-slate-500 focus:border-cyan-500 focus:outline-none"
                  />
                  <button
                    onClick={async () => {
                      await onSaveSnapshot(shot.id, snapLabel);
                      setSnapLabel("");
                    }}
                    disabled={isLocked}
                    className="snapshot-save-btn px-2 py-1 rounded bg-cyan-700/40 hover:bg-cyan-600/50 text-cyan-100 text-[11px] font-medium disabled:bg-slate-700 disabled:text-slate-500"
                    title={isLocked ? "Locked — unlock to snapshot" : "Save a restorable copy of current creative state"}
                  >Save snapshot</button>
                </div>
                {(shot.snapshots || []).length === 0 ? (
                  <div className="text-[10px] text-slate-500">No snapshots yet. Save one before risky edits — you can restore later.</div>
                ) : (
                  <div className="snapshots-list space-y-1 max-h-40 overflow-y-auto">
                    {(shot.snapshots || []).slice().reverse().map((snap) => {
                      const inCompare = snapCompare.includes(snap.id);
                      const isPinned = (shot.pinned_snapshots || []).includes(snap.id);
                      const toggleCompare = () => {
                        setSnapCompare(prev => {
                          if (prev.includes(snap.id)) return prev.filter(x => x !== snap.id);
                          if (prev.length >= 2) return [prev[1], snap.id];  // rolling 2-slot selection
                          return [...prev, snap.id];
                        });
                      };
                      return (
                        <div key={snap.id} className={`snapshot-entry flex items-center gap-2 text-[10px] px-2 py-1 rounded ${inCompare ? "bg-cyan-900/40 border border-cyan-600/40" : (isPinned ? "bg-amber-900/20 border border-amber-600/30" : "bg-slate-800/60")}`}>
                          <input
                            type="checkbox"
                            checked={inCompare}
                            onChange={toggleCompare}
                            className="snapshot-compare-check w-3 h-3 accent-cyan-500"
                            title="Select to compare (max 2)"
                          />
                          <button
                            onClick={() => onTogglePinSnapshot(shot.id, snap.id, isPinned)}
                            className={`snapshot-pin-btn text-sm leading-none ${isPinned ? "text-amber-400" : "text-slate-500 hover:text-amber-400"}`}
                            title={isPinned ? "Pinned — won't auto-prune. Click to unpin." : "Pin to protect from auto-pruning"}
                          >{isPinned ? "📌" : "📍"}</button>
                          <span className="snapshot-time text-slate-400">{new Date((snap.created_at || 0) * 1000).toLocaleString()}</span>
                          {snap.label && <span className="snapshot-label text-cyan-300 font-medium">— {snap.label}</span>}
                          <span className="snapshot-preset text-slate-500">({snap.preset || "?"})</span>
                          <button
                            onClick={() => onRestoreSnapshot(shot.id, snap.id)}
                            disabled={isLocked}
                            className="snapshot-restore-btn ml-auto px-2 py-0.5 rounded bg-cyan-700/40 hover:bg-cyan-600/50 text-cyan-100 font-medium disabled:bg-slate-700 disabled:text-slate-500"
                          >Restore</button>
                          <button
                            onClick={() => { if (confirm("Delete this snapshot?")) onDeleteSnapshot(shot.id, snap.id); }}
                            className="snapshot-delete-btn px-2 py-0.5 rounded bg-red-700/30 hover:bg-red-600/50 text-red-200 font-medium"
                          >×</button>
                        </div>
                      );
                    })}
                  </div>
                )}
                {/* R46b: snapshot diff viewer */}
                {snapCompare.length === 2 && (() => {
                  const snaps = shot.snapshots || [];
                  const a = snaps.find(s => s.id === snapCompare[0]);
                  const b = snaps.find(s => s.id === snapCompare[1]);
                  if (!a || !b) return null;
                  const fields = [
                    { key: "prompt", label: "Prompt" },
                    { key: "negative", label: "Negative" },
                    { key: "preset", label: "Preset" },
                    { key: "seed", label: "Seed" },
                    { key: "notes", label: "Notes" },
                    { key: "backend", label: "Backend" },
                    { key: "transition", label: "Transition" },
                  ];
                  const fmt = (v) => {
                    if (v === null || v === undefined || v === "") return <span className="text-slate-600 italic">empty</span>;
                    return String(v);
                  };
                  const ovA = JSON.stringify(a.overrides || {}, null, 1);
                  const ovB = JSON.stringify(b.overrides || {}, null, 1);
                  return (
                    <div className="snapshot-diff-panel mt-2 rounded bg-slate-900/80 border border-cyan-700/30 p-2 text-[10px]">
                      <div className="flex items-center justify-between mb-2">
                        <div className="snapshot-diff-title text-[11px] font-semibold text-cyan-200">
                          Comparing: <span className="text-cyan-400">{a.label || a.id.slice(0,6)}</span>
                          {" ↔ "}
                          <span className="text-cyan-400">{b.label || b.id.slice(0,6)}</span>
                        </div>
                        <button
                          onClick={() => setSnapCompare([])}
                          className="snapshot-diff-close text-slate-400 hover:text-slate-200 text-[10px] px-2"
                        >Clear</button>
                      </div>
                      <div className="space-y-1">
                        {fields.map(f => {
                          const va = a[f.key], vb = b[f.key];
                          const same = JSON.stringify(va) === JSON.stringify(vb);
                          if (same) return null;
                          return (
                            <div key={f.key} className="snapshot-diff-row">
                              <div className="text-slate-400 font-medium mb-0.5">{f.label}</div>
                              <div className="grid grid-cols-2 gap-2">
                                <div className="snapshot-diff-a rounded bg-red-950/30 border border-red-800/20 p-1.5 text-red-300 whitespace-pre-wrap break-words">{fmt(va)}</div>
                                <div className="snapshot-diff-b rounded bg-emerald-950/30 border border-emerald-800/20 p-1.5 text-emerald-300 whitespace-pre-wrap break-words">{fmt(vb)}</div>
                              </div>
                            </div>
                          );
                        })}
                        {ovA !== ovB && (
                          <div className="snapshot-diff-row">
                            <div className="text-slate-400 font-medium mb-0.5">Overrides</div>
                            <div className="grid grid-cols-2 gap-2">
                              <div className="snapshot-diff-a rounded bg-red-950/30 border border-red-800/20 p-1.5 text-red-300 font-mono whitespace-pre-wrap">{ovA}</div>
                              <div className="snapshot-diff-b rounded bg-emerald-950/30 border border-emerald-800/20 p-1.5 text-emerald-300 font-mono whitespace-pre-wrap">{ovB}</div>
                            </div>
                          </div>
                        )}
                        {fields.every(f => JSON.stringify(a[f.key]) === JSON.stringify(b[f.key])) && ovA === ovB && (
                          <div className="text-slate-500 italic text-center py-1">No differences in creative state.</div>
                        )}
                      </div>
                    </div>
                  );
                })()}
              </div>
            )}
          </div>

          {/* Modified since last render indicator + comparison */}
          {(() => {
            const hist = shot.render_history || [];
            const lastOk = hist.slice().reverse().find(e => e.status === "ready");
            if (!lastOk) return null;
            const diffs = [];
            if (shot.prompt !== (lastOk.prompt || "")) diffs.push("prompt");
            if ((shot.negative || "") !== (lastOk.negative || "")) diffs.push("negative");
            if (shot.preset !== (lastOk.preset || "")) diffs.push("preset");
            const oldOv = lastOk.overrides || {};
            const newOv = shot.overrides || {};
            if (JSON.stringify(oldOv) !== JSON.stringify(newOv)) diffs.push("overrides");
            if (diffs.length === 0) return null;
            return (
              <div className="shot-diff-section">
                <div className="shot-diff-badge flex items-center gap-2 px-2 py-1 rounded bg-amber-900/30 border border-amber-500/30 text-[11px] text-amber-300">
                  <span className="shot-diff-icon">⚠</span>
                  <span className="shot-diff-label">Modified since last render</span>
                  <span className="shot-diff-fields text-amber-400/70">({diffs.join(", ")})</span>
                  <button
                    onClick={() => setShowCompare(!showCompare)}
                    className="compare-toggle-btn px-2 py-0.5 rounded bg-slate-700/50 hover:bg-slate-600/60 text-slate-200 text-[10px] font-medium"
                  >{showCompare ? "Hide" : "Compare"}</button>
                  {!shot.locked && (
                    <button
                      onClick={() => revertShot(shot.id)}
                      className="revert-btn ml-auto px-2 py-0.5 rounded bg-amber-700/50 hover:bg-amber-600/60 text-amber-100 text-[10px] font-medium"
                    >Revert</button>
                  )}
                </div>
                {showCompare && (
                  <div className="shot-compare-panel mt-1 rounded bg-slate-900/60 border border-slate-700/40 p-2 text-[10px] space-y-2">
                    {diffs.includes("prompt") && (
                      <div className="compare-row-prompt">
                        <div className="compare-field-label text-slate-400 font-medium mb-0.5">Prompt</div>
                        <div className="grid grid-cols-2 gap-2">
                          <div className="compare-old rounded bg-red-950/30 border border-red-800/20 p-1.5 text-red-300 whitespace-pre-wrap break-words">{lastOk.prompt || ""}</div>
                          <div className="compare-new rounded bg-emerald-950/30 border border-emerald-800/20 p-1.5 text-emerald-300 whitespace-pre-wrap break-words">{shot.prompt}</div>
                        </div>
                      </div>
                    )}
                    {diffs.includes("negative") && (
                      <div className="compare-row-negative">
                        <div className="compare-field-label text-slate-400 font-medium mb-0.5">Negative</div>
                        <div className="grid grid-cols-2 gap-2">
                          <div className="compare-old rounded bg-red-950/30 border border-red-800/20 p-1.5 text-red-300 whitespace-pre-wrap break-words">{lastOk.negative || ""}</div>
                          <div className="compare-new rounded bg-emerald-950/30 border border-emerald-800/20 p-1.5 text-emerald-300 whitespace-pre-wrap break-words">{shot.negative || ""}</div>
                        </div>
                      </div>
                    )}
                    {diffs.includes("preset") && (
                      <div className="compare-row-preset">
                        <div className="compare-field-label text-slate-400 font-medium mb-0.5">Preset</div>
                        <div className="grid grid-cols-2 gap-2">
                          <div className="compare-old rounded bg-red-950/30 border border-red-800/20 p-1.5 text-red-300">{lastOk.preset || ""}</div>
                          <div className="compare-new rounded bg-emerald-950/30 border border-emerald-800/20 p-1.5 text-emerald-300">{shot.preset}</div>
                        </div>
                      </div>
                    )}
                    {diffs.includes("overrides") && (
                      <div className="compare-row-overrides">
                        <div className="compare-field-label text-slate-400 font-medium mb-0.5">Overrides</div>
                        <div className="grid grid-cols-2 gap-2">
                          <div className="compare-old rounded bg-red-950/30 border border-red-800/20 p-1.5 text-red-300 font-mono">{JSON.stringify(oldOv, null, 1)}</div>
                          <div className="compare-new rounded bg-emerald-950/30 border border-emerald-800/20 p-1.5 text-emerald-300 font-mono">{JSON.stringify(newOv, null, 1)}</div>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })()}

          {/* Seed + Backend row */}
          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="block text-xs font-medium text-amber-200 mb-1">Seed</label>
              <div className="flex gap-1">
                <input
                  value={editSeed}
                  onChange={e => setEditSeed(e.target.value)}
                  placeholder="Auto"
                  type="text"
                  className="flex-1 bg-slate-950 border border-amber-500/20 rounded-lg px-3 py-2 text-amber-50 placeholder-slate-500 focus:border-amber-500/60 outline-none text-sm"
                />
                <button
                  onClick={() => setEditSeed(Math.floor(Math.random() * 2147483647).toString())}
                  className="px-2 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs transition-colors"
                  title="Random seed"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 2.2" /></svg>
                </button>
              </div>
            </div>
            <div>
              <label className="block text-xs font-medium text-amber-200 mb-1">Backend</label>
              <select
                value={editBackend}
                onChange={e => setEditBackend(e.target.value)}
                className="w-full bg-slate-950 border border-amber-500/20 rounded-lg px-3 py-2 text-amber-50 focus:border-amber-500/60 outline-none text-sm"
              >
                {BACKENDS.map(b => (
                  <option key={b} value={b} className="bg-slate-950">{b}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-amber-200 mb-1">Preset</label>
              <select
                value={editPreset}
                onChange={e => setEditPreset(e.target.value)}
                className="w-full bg-slate-950 border border-amber-500/20 rounded-lg px-3 py-2 text-amber-50 focus:border-amber-500/60 outline-none text-sm"
              >
                {presetKeys.map(p => (
                  <option key={p} value={p} className="bg-slate-950">{p}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Preset parameter preview */}
          {currentPreset && (
            <>
              <div className="preset-params bg-slate-950 border border-amber-500/10 rounded-lg px-3 py-2 text-xs text-slate-400">
                {(() => {
                  const info = [];
                  if (currentPreset.steps) info.push(`${currentPreset.steps} steps`);
                  if (currentPreset.guidance) info.push(`${currentPreset.guidance} guidance`);
                  if (currentPreset.frames) info.push(`${currentPreset.frames} frames`);
                  if (currentPreset.fps) info.push(`${currentPreset.fps} fps`);
                  if (currentPreset.resolution) info.push(`${currentPreset.resolution} res`);
                  return info.join(" · ");
                })()}
              </div>
              {buildOverrides() && (
                <div className="text-xs text-orange-400 font-medium">⚠ Settings Overridden</div>
              )}
            </>
          )}

          {/* Advanced overrides toggle */}
          <button
            onClick={() => setShowAdvanced(!showAdvanced)}
            className="text-xs text-amber-400 hover:text-amber-300 font-medium underline"
          >
            {showAdvanced ? "▼" : "▶"} Advanced Overrides
          </button>

          {showAdvanced && (
            <div className="bg-slate-950 border border-amber-500/10 rounded-lg p-3 space-y-2">
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-xs text-amber-200 mb-0.5">Override Steps</label>
                  <input type="number" value={ovSteps} onChange={e => setOvSteps(e.target.value)} placeholder="(use preset)" className="w-full bg-slate-900 border border-amber-500/20 rounded px-2 py-1 text-xs text-amber-50" />
                </div>
                <div>
                  <label className="block text-xs text-amber-200 mb-0.5">Override Guidance</label>
                  <input type="number" step="0.1" value={ovGuidance} onChange={e => setOvGuidance(e.target.value)} placeholder="(use preset)" className="w-full bg-slate-900 border border-amber-500/20 rounded px-2 py-1 text-xs text-amber-50" />
                </div>
                <div>
                  <label className="block text-xs text-amber-200 mb-0.5">Override Frames</label>
                  <input type="number" value={ovFrames} onChange={e => setOvFrames(e.target.value)} placeholder="(use preset)" className="w-full bg-slate-900 border border-amber-500/20 rounded px-2 py-1 text-xs text-amber-50" />
                </div>
                <div>
                  <label className="block text-xs text-amber-200 mb-0.5">Override FPS</label>
                  <input type="number" value={ovFps} onChange={e => setOvFps(e.target.value)} placeholder="(use preset)" className="w-full bg-slate-900 border border-amber-500/20 rounded px-2 py-1 text-xs text-amber-50" />
                </div>
                <div className="col-span-2">
                  <label className="block text-xs text-amber-200 mb-0.5">Override Resolution</label>
                  <input type="text" value={ovResolution} onChange={e => setOvResolution(e.target.value)} placeholder="e.g. 1280x720" className="w-full bg-slate-900 border border-amber-500/20 rounded px-2 py-1 text-xs text-amber-50" />
                </div>
              </div>
            </div>
          )}

          {/* Reference image section */}
          <div className="bg-slate-950 border border-amber-500/10 rounded-lg p-3 space-y-2">
            <label className="block text-xs font-medium text-amber-200">Reference Image</label>
            <div
              onDragOver={e => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={async e => {
                e.preventDefault();
                setDragOver(false);
                const file = e.dataTransfer.files?.[0];
                if (file) {
                  setUploading(true);
                  try {
                    const reader = new FileReader();
                    reader.onload = async () => {
                      await onUploadRef(shot.id, reader.result, file.name);
                      setUploading(false);
                    };
                    reader.readAsDataURL(file);
                  } catch { setUploading(false); }
                }
              }}
              className={`border-2 border-dashed rounded-lg p-3 text-center transition-colors ${dragOver ? "border-amber-400 bg-amber-500/10" : "border-amber-500/20 hover:border-amber-400/30"}`}
            >
              {shot.ref_image ? (
                <img src={`/api/video/shots/${shot.id}/reference`} alt="ref" className="max-h-32 mx-auto rounded" />
              ) : (
                <p className="text-xs text-slate-500">Drag image here or click to upload</p>
              )}
            </div>
            <input
              ref={fileRef}
              type="file"
              accept="image/*"
              hidden
              onChange={async (e) => {
                const file = e.target.files?.[0];
                if (!file) return;
                setUploading(true);
                try {
                  const reader = new FileReader();
                  reader.onload = async () => {
                    await onUploadRef(shot.id, reader.result, file.name);
                    setUploading(false);
                  };
                  reader.readAsDataURL(file);
                } catch { setUploading(false); }
              }}
            />
            <button
              onClick={() => fileRef.current?.click()}
              disabled={uploading}
              className="w-full flex items-center justify-center gap-1.5 bg-purple-700/30 hover:bg-purple-700/50 text-purple-300 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors disabled:opacity-40"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12" /></svg>
              {uploading ? "Uploading..." : (shot.ref_image ? "Replace" : "Upload")}
            </button>
          </div>

          {/* Trajectory button */}
          {shot.ref_image && (
            <button
              onClick={() => onOpenTrajectory(shot)}
              className="w-full flex items-center justify-center gap-1.5 bg-teal-700/30 hover:bg-teal-700/50 text-teal-300 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M2 22l10-10M15 4V2M15 16v-2M8 9h2M20 9h2" /></svg>
              Edit Trajectories
            </button>
          )}

          {/* Carry last frame */}
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={editCarryFrame}
              onChange={e => setEditCarryFrame(e.target.checked)}
              className="w-4 h-4 rounded accent-amber-500"
            />
            <span className="text-xs text-amber-200">Carry last frame to next shot</span>
          </label>

          {/* Transition to next shot */}
          <div className="preset-quick-switch flex items-center gap-2 mb-2">
          <label className="text-xs text-amber-200/80">Preset:</label>
          <select value={shot.preset || ""} onChange={e => {
            if (onSave) onSave(shot.id, { preset: e.target.value });
          }} className="preset-quick-select bg-slate-800 border border-slate-600 rounded px-2 py-1 text-xs text-slate-200 flex-1">
            {(favPresets || []).length > 0 && React.createElement("optgroup", { label: "Favorites" },
              (favPresets || []).map(p => React.createElement("option", { key: "fav_" + p, value: p }, "\u2605 " + p))
            )}
            {Object.keys(window._videoPresets || {}).map(p =>
              React.createElement("option", { key: p, value: p }, p)
            )}
          </select>
          <button onClick={() => onToggleFavorite && onToggleFavorite(shot.preset)}
            className="favorite-preset-btn text-sm"
            title={(favPresets || []).includes(shot.preset) ? "Remove from favorites" : "Add to favorites"}>
            {(favPresets || []).includes(shot.preset) ? "\u2605" : "\u2606"}
          </button>
        </div>
        <div className="scene-assign-row flex items-center gap-3 mb-2">
          <label className="text-xs text-amber-200/80">Scene:</label>
          <select value={shot.scene_id || ""} onChange={e => {
            const val = e.target.value || null;
            if (onSceneAssign) onSceneAssign(shot.id, val);
          }} className="scene-assign-select bg-slate-800 border border-slate-600 rounded px-2 py-1 text-xs text-slate-200">
            <option value="">No scene</option>
            {(scenesList || []).map(sc =>
              React.createElement("option", { key: sc.id, value: sc.id }, sc.name || "Unnamed")
            )}
          </select>
        </div>
        <div className="dependency-row flex items-center gap-3 mb-2">
          <label className="text-xs text-amber-200/80">Depends on:</label>
          <select
            value=""
            onChange={e => {
              if (e.target.value && onAddDependency) {
                onAddDependency(shot.id, e.target.value);
              }
              e.target.value = "";
            }}
            className="dep-add-select bg-slate-800 border border-slate-600 rounded px-2 py-1 text-xs text-slate-200"
          >
            <option value="">+ Add dependency</option>
            {(allShots || []).filter(s => s.id !== shot.id && !(shot.depends_on || []).includes(s.id)).map(s =>
              React.createElement("option", { key: s.id, value: s.id }, s.title || s.id.slice(0,8))
            )}
          </select>
          {(shot.depends_on || []).length > 0 && (
            <div className="dep-badges flex flex-wrap gap-1">
              {(shot.depends_on || []).map(depId => {
                const depShot = (allShots || []).find(s => s.id === depId);
                return (
                  <span key={depId} className="dep-badge inline-flex items-center gap-1 bg-indigo-900/60 text-indigo-200 text-xs px-2 py-0.5 rounded">
                    {depShot ? (depShot.title || depShot.id.slice(0,8)) : depId.slice(0,8)}
                    <button onClick={() => onRemoveDependency && onRemoveDependency(shot.id, depId)}
                      className="dep-remove-btn text-indigo-400 hover:text-red-400 ml-0.5"
                      title="Remove dependency">&times;</button>
                  </span>
                );
              })}
            </div>
          )}
        </div>
        <div className="transition-picker flex items-center gap-3">
            <label className="text-xs text-amber-200/80">Transition:</label>
            <select
              value={editTransition}
              onChange={e => setEditTransition(e.target.value)}
              className="transition-type-select bg-slate-800 border border-slate-600 text-slate-300 text-xs rounded px-2 py-1"
            >
              <option value="cut">Cut</option>
              <option value="fade">Fade</option>
              <option value="crossfade">Crossfade</option>
              <option value="wipeleft">Wipe Left</option>
              <option value="wiperight">Wipe Right</option>
              <option value="wipeup">Wipe Up</option>
              <option value="wipedown">Wipe Down</option>
            </select>
            {editTransition !== "cut" && (
              <div className="flex items-center gap-1">
                <input
                  type="number"
                  min="100"
                  max="3000"
                  step="100"
                  value={editTransitionMs}
                  onChange={e => setEditTransitionMs(parseInt(e.target.value, 10) || 500)}
                  className="transition-duration-input bg-slate-800 border border-slate-600 text-slate-300 text-xs rounded px-2 py-1 w-20"
                />
                <span className="text-xs text-slate-500">ms</span>
              </div>
            )}
          </div>
        <div className="target-duration-row flex items-center gap-3 mt-2">
          <label className="text-xs text-amber-200/80">Target duration:</label>
          <input
            type="number"
            min="0.5"
            max="60"
            step="0.5"
            value={editTargetDuration}
            onChange={e => setEditTargetDuration(e.target.value === "" ? "" : parseFloat(e.target.value))}
            onBlur={() => {
              const val = editTargetDuration === "" ? null : parseFloat(editTargetDuration);
              if (onUpdate) onUpdate(shot.id, { target_duration_s: val });
            }}
            placeholder={shot.duration_s ? shot.duration_s + "s (preset)" : "auto"}
            className="target-duration-input bg-slate-800 border border-slate-600 text-slate-300 text-xs rounded px-2 py-1 w-24"
          />
          <span className="text-xs text-slate-500">seconds</span>
          {editTargetDuration && shot.duration_s && parseFloat(editTargetDuration) > shot.duration_s * 2 && (
            <span className="duration-warning text-xs text-amber-400">exceeds 2x preset</span>
          )}
        </div>

          {/* Action buttons */}
          <div className="flex gap-2 flex-wrap pt-1">
            {dirty() && (
              <button
                onClick={doSave}
                className="flex items-center gap-1.5 bg-amber-600 hover:bg-amber-500 text-white px-3 py-1.5 rounded-lg text-xs font-medium transition-colors"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z" /></svg>
                Save
              </button>
            )}
            <button
              onClick={() => onRender(shot.id)}
              disabled={shot.status === "running" || shot.status === "queued"}
              className="flex items-center gap-1.5 bg-emerald-700/30 hover:bg-emerald-700/50 text-emerald-300 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M5 3l14 9-14 9V3z" /></svg>
              Render
            </button>
            {(shot.status === "running" || shot.status === "queued") && (
              <button
                onClick={() => onCancel(shot.id)}
                className="cancel-render flex items-center gap-1.5 bg-red-700/30 hover:bg-red-700/50 text-red-300 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12" /></svg>
                Cancel
              </button>
            )}
            {shot.status === "failed" && (
              <button
                onClick={() => onRetry(shot.id)}
                className="flex items-center gap-1.5 bg-orange-700/30 hover:bg-orange-700/50 text-orange-300 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M1 4v6h6M23 20v-6h-6M20.49 9a9 9 0 0 0-14.85-3.36M3.51 15a9 9 0 0 0 14.85 3.36" /></svg>
                Retry
              </button>
            )}
            {/* Color label picker */}
            <div className="color-label-picker relative group">
              <button
                className="w-5 h-5 rounded-full border border-slate-600 hover:border-slate-400 transition-colors"
                style={{ backgroundColor: (COLOR_LABELS.find(c => c.key === (shot.color_label || "")) || {}).color || "transparent" }}
                title="Set color label"
              />
              <div className="color-label-menu hidden group-hover:flex absolute top-6 left-0 z-10 bg-slate-800 rounded-lg shadow-xl border border-slate-700 p-1.5 gap-1">
                {COLOR_LABELS.map(c => (
                  <button
                    key={c.key}
                    onClick={() => onColorLabel(shot.id, c.key)}
                    className="w-4 h-4 rounded-full border border-slate-600 hover:scale-125 transition-transform"
                    style={{ backgroundColor: c.color }}
                    title={c.label}
                  />
                ))}
              </div>
            </div>
            <button
              onClick={() => onDuplicate(shot.id)}
              className="flex items-center gap-1.5 bg-slate-700/30 hover:bg-slate-700/50 text-slate-300 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M8 16H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v2m-6 12h8a2 2 0 0 0 2-2v-8a2 2 0 0 0-2-2h-8a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2z" /></svg>
              Duplicate
            </button>
            <button
              onClick={() => {
                const variation = prompt("Variation description (leave empty for exact clone):", "");
                if (variation !== null) onClone(shot.id, variation);
              }}
              className="flex items-center gap-1.5 bg-indigo-700/30 hover:bg-indigo-700/50 text-indigo-300 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M8 16H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v2m-6 12h8a2 2 0 0 0 2-2v-8a2 2 0 0 0-2-2h-8a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2z" /><line x1="12" y1="18" x2="18" y2="18" /></svg>
              Clone Variation
            </button>
            {shot.ref_image && (
              <button
                onClick={() => onContinuity(shot.id)}
                className="flex items-center gap-1.5 bg-purple-700/30 hover:bg-purple-700/50 text-purple-300 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
                Use as next ref
              </button>
            )}
            <button
              onClick={() => { if (confirm(`Delete shot "${editTitle || 'Untitled'}"?`)) onRemove(shot.id); }}
              className="flex items-center gap-1.5 bg-red-600/20 hover:bg-red-600/40 text-red-400 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ml-auto"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /></svg>
              Delete
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════
// Trajectory Modal — overlay with TrajectoryCanvas
// ════════════════════════════════════════════════════════════════════

function TrajectoryModal({ shot, onClose, onSaved }) {
  const containerRef = _useRef(null);
  const canvasRef = _useRef(null);

  _useEffect(() => {
    if (!containerRef.current || !shot) return;

    containerRef.current.innerHTML = '';

    const tc = new TrajectoryCanvas({
      container: containerRef.current,
      imageUrl: `/api/video/shots/${shot.id}/reference`,
      onSave: (trajectories) => {
        onSaved(shot.id, trajectories);
      },
    });

    if (shot.trajectories && shot.trajectories.length > 0) {
      tc.setTrajectories(shot.trajectories);
    }

    canvasRef.current = tc;
    return () => tc.destroy();
  }, [shot]);

  if (!shot) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm"
         onClick={onClose}>
      <div className="bg-slate-900 border border-amber-600/30 rounded-2xl w-full max-w-3xl mx-4 overflow-hidden shadow-2xl"
           onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-3 border-b border-amber-600/20">
          <h3 className="text-amber-50 font-semibold">
            Trajectories — {shot.title || "Untitled"}
          </h3>
          <button onClick={onClose}
            className="text-slate-400 hover:text-amber-300 transition-colors text-xl leading-none">&times;</button>
        </div>
        <div className="p-4">
          <div ref={containerRef} className="w-full" style={{minHeight: "300px"}} />
          <p className="text-xs text-slate-500 mt-2">
            Draw motion paths on the reference image. Click Save when done.
          </p>
        </div>
      </div>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════
// Health Panel — backend status indicators
// ════════════════════════════════════════════════════════════════════

function HealthPanel({ health, maxConcurrent, onMaxConcurrentChange }) {
  if (!health) return null;

  const dot = (ok) => ok
    ? "w-2 h-2 rounded-full bg-emerald-400"
    : "w-2 h-2 rounded-full bg-red-400";

  return (
    <div className="flex gap-4 text-xs flex-wrap items-center">
      <span className="flex items-center gap-1.5 text-slate-300">
        <span className={dot(health.wangp?.available)} />
        WanGP {health.wangp?.available ? "online" : "offline"}
      </span>
      <span className="flex items-center gap-1.5 text-slate-300">
        <span className={dot(health.comfyui?.available)} />
        ComfyUI {health.comfyui?.available ? "online" : "offline"}
      </span>
      {health.shotboard && (
        <span className="text-slate-500">
          {health.shotboard.total_shots} shot(s) · {health.shotboard.ready_count} ready
        </span>
      )}
      <span className="concurrency-control flex items-center gap-1.5 text-slate-400 ml-auto">
        <label className="text-xs">Max parallel:</label>
        <select
          value={maxConcurrent || 2}
          onChange={e => onMaxConcurrentChange && onMaxConcurrentChange(parseInt(e.target.value, 10))}
          className="max-concurrent-select bg-slate-800 border border-slate-600 text-slate-300 text-xs rounded px-1.5 py-0.5"
        >
          {[1,2,3,4,5,6,7,8].map(n => (
            <option key={n} value={n}>{n}</option>
          ))}
        </select>
      </span>
    </div>
  );
}


// ════════════════════════════════════════════════════════════════════
// ShotSummary — summary statistics for a single shot
// ════════════════════════════════════════════════════════════════════

function ShotSummary({ shots, shot }) {
  if (shots && Array.isArray(shots)) {
    // Array version - show summary stats
    let totalDuration = 0;
    let draftCount = 0, readyCount = 0;
    shots.forEach(s => {
      if (s.render_duration_s) totalDuration += s.render_duration_s;
      if (s.status === 'draft') draftCount++;
      if (s.status === 'ready') readyCount++;
    });
    return (
      <div className="shot-summary text-xs text-slate-400">
        Draft: {draftCount} · Ready: {readyCount} · Total duration: {Math.floor(totalDuration)}s
      </div>
    );
  }
  // Single shot version
  return (
    <div className="shot-summary text-xs text-slate-400 space-y-1">
      {shot && shot.status && <div>Status: {shot.status}</div>}
      {shot && shot.progress !== undefined && <div>Progress: {Math.round(shot.progress)}%</div>}
      {shot && shot.render_duration_s !== undefined && <div>Render time: {Math.floor(shot.render_duration_s)}s</div>}
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════
// VideoPanel — main component for the "Video" tab
// ════════════════════════════════════════════════════════════════════


function TimelineStrip({ shots, selectedId, onSelect, onDrop }) {
  const statusColors = {
    draft: "bg-slate-600", queued: "bg-blue-600",
    running: "bg-amber-500 animate-pulse", ready: "bg-emerald-500", failed: "bg-red-500",
  };

  const handleDragStart = (e, id) => {
    e.dataTransfer.setData("text/plain", id);
    e.dataTransfer.effectAllowed = "move";
  };

  const handleDragOver = (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  };

  const handleDrop = (e, targetId) => {
    e.preventDefault();
    const draggedId = e.dataTransfer.getData("text/plain");
    if (draggedId && draggedId !== targetId && onDrop) {
      onDrop(draggedId, targetId);
    }
  };

  return (
    <div className="timeline-strip flex gap-2 overflow-x-auto pb-2 mb-4 scrollbar-thin scrollbar-thumb-slate-700" data-testid="timeline-strip">
      {shots.map((shot, i) => (
        <div
          key={shot.id}
          draggable
          onDragStart={(e) => handleDragStart(e, shot.id)}
          onDragOver={handleDragOver}
          onDrop={(e) => handleDrop(e, shot.id)}
          onClick={() => onSelect(shot.id)}
          className={`timeline-shot flex-shrink-0 cursor-pointer rounded-lg border-2 transition-all ${
            selectedId === shot.id
              ? "border-amber-500 shadow-lg shadow-amber-500/20"
              : "border-slate-700/50 hover:border-slate-600"
          } bg-slate-800/80 w-28 p-1.5`}
          title={shot.title || `Shot ${i + 1}`}
        >
          {/* Thumbnail or placeholder */}
          <div className="timeline-thumb w-full h-16 rounded bg-slate-900/50 mb-1 flex items-center justify-center overflow-hidden">
            {shot.ref_image ? (
              <img src={`/api/video/shots/${shot.id}/thumbnail`} alt="" className="w-full h-full object-cover rounded" />
            ) : (
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-slate-600">
                <rect x="2" y="2" width="20" height="20" rx="2" />
                <path d="M7 2v20M17 2v20M2 12h20M2 7h5M2 17h5M17 17h5M17 7h5" />
              </svg>
            )}
          </div>
          {/* Label + status */}
          <div className="flex items-center gap-1">
            {shot.color_label && (
              <span className="timeline-color-label w-2 h-2 rounded-full" style={{ backgroundColor: (COLOR_LABELS.find(c => c.key === shot.color_label) || {}).color }} />
            )}
            <span className={`timeline-status w-2 h-2 rounded-full ${statusColors[shot.status] || "bg-slate-600"}`} />
            <span className="text-[10px] text-slate-400 truncate flex-1">
              {shot.title || `#${i + 1}`}
            </span>
            {shot.duration_s && (
              <span className="text-[9px] text-slate-500 font-mono timeline-duration">
                {shot.duration_s.toFixed(1)}s
              </span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

function GridCard({ shot, presets, onRender, onRemove, isSelected, onToggleSelect }) {
  const STATUS_COLORS = {
    draft: "bg-slate-600", queued: "bg-blue-600", running: "bg-amber-600",
    ready: "bg-emerald-600", failed: "bg-red-600",
  };
  const presetLabel = presets[shot.preset]?.label || shot.preset;
  return (
    <div
      className={`grid-card relative rounded-xl border overflow-hidden cursor-pointer transition-all ${
        isSelected ? "border-amber-500 ring-1 ring-amber-500/30" : "border-slate-700/50 hover:border-slate-600"
      } bg-slate-800/60`}
      onClick={() => onToggleSelect(shot.id)}
    >
      {/* Thumbnail or placeholder */}
      <div className="aspect-video bg-slate-900 flex items-center justify-center">
        {shot.video_path ? (
          <video src={`/api/video/shots/${shot.id}/video`} className="w-full h-full object-cover" muted />
        ) : shot.ref_image ? (
          <img src={`/api/video/shots/${shot.id}/reference`} className="w-full h-full object-cover" alt="" />
        ) : (
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-slate-600">
            <rect x="2" y="2" width="20" height="20" rx="2.18" /><path d="m7 2 10 20M17 2 7 20" />
          </svg>
        )}
      </div>
      {/* Status badge */}
      <span className={`absolute top-2 right-2 text-[10px] font-bold uppercase px-1.5 py-0.5 rounded ${STATUS_COLORS[shot.status] || "bg-slate-600"} text-white`}>
        {shot.status}
      </span>
      {/* Info */}
      <div className="p-2 space-y-1">
        <div className="text-xs font-medium text-amber-50 truncate">
          {shot.title || `Shot ${shot.index + 1}`}
          {isLocked && <span className="lock-indicator text-amber-400 ml-1 text-[10px]">[locked]</span>}
          <button onClick={(e) => { e.stopPropagation(); onToggleLock && onToggleLock(shot.id, !isLocked); }}
            className="lock-toggle-btn text-slate-500 hover:text-amber-400 ml-1 text-[10px]"
            title={isLocked ? "Unlock shot" : "Lock shot"}>
            {isLocked ? "unlock" : "lock"}
          </button>
        </div>
        <div className="text-[10px] text-slate-400 truncate">{shot.prompt || "No prompt"}</div>
        <div className="text-[10px] text-slate-500">{presetLabel}</div>
        {shot.status === "draft" && (
          <button
            onClick={(e) => { e.stopPropagation(); onRender(shot.id); }}
            className="mt-1 w-full text-center text-[10px] bg-emerald-700/30 hover:bg-emerald-700/50 text-emerald-300 py-1 rounded font-medium"
          >Render</button>
        )}
      </div>
      {/* Color label stripe */}
      {shot.color_label && (
        <div className="absolute top-0 left-0 w-1 h-full" style={{ backgroundColor: shot.color_label }} />
      )}
    </div>
  );
}





// ── Render Queue Dashboard ──────────────────────────────────────────
function RenderQueuePanel({ shots, queueStatus, onCancel, onRetry }) {
  const queued = shots.filter(s => s.status === "queued");
  const running = shots.filter(s => s.status === "running");
  const failed = shots.filter(s => s.status === "failed");
  const ready = shots.filter(s => s.status === "ready");
  const totalRenderTime = ready.reduce((sum, s) => sum + (s.render_duration_s || 0), 0);
  const avgRenderTime = ready.length > 0 ? totalRenderTime / ready.length : 0;
  const eta = avgRenderTime * (queued.length + running.length);

  return (
    React.createElement("div", { className: "render-queue-panel bg-slate-800/80 border border-amber-700/30 rounded-lg p-4 mb-4" },
      React.createElement("h4", { className: "text-sm font-semibold text-amber-300 mb-3" }, "Render Queue"),
      React.createElement("div", { className: "queue-summary flex gap-4 mb-3 text-xs" },
        React.createElement("span", { className: "queue-stat-running text-blue-400" },
          "Running: ", running.length),
        React.createElement("span", { className: "queue-stat-queued text-amber-400" },
          "Queued: ", queued.length),
        React.createElement("span", { className: "queue-stat-ready text-emerald-400" },
          "Complete: ", ready.length),
        React.createElement("span", { className: "queue-stat-failed text-red-400" },
          "Failed: ", failed.length),
        eta > 0 && React.createElement("span", { className: "queue-eta text-slate-400" },
          "ETA: ", eta < 60 ? Math.round(eta) + "s" : Math.round(eta / 60) + "m")
      ),
      React.createElement("div", { className: "queue-items flex flex-col gap-2 max-h-64 overflow-y-auto" },
        running.map(s => React.createElement("div", {
          key: s.id, className: "queue-item queue-item-running flex items-center gap-2 bg-blue-900/30 rounded px-3 py-2"
        },
          React.createElement("div", { className: "w-2 h-2 rounded-full bg-blue-400 animate-pulse" }),
          React.createElement("span", { className: "text-xs text-slate-200 flex-1 truncate" }, s.title || s.prompt || "Untitled"),
          React.createElement("div", { className: "queue-progress-bar w-24 h-1.5 bg-slate-700 rounded overflow-hidden" },
            React.createElement("div", {
              className: "h-full bg-blue-400 transition-all",
              style: { width: (s.progress || 0) + "%" }
            })
          ),
          React.createElement("button", {
            onClick: () => onCancel(s.id),
            className: "queue-cancel-btn text-red-400 hover:text-red-300 text-xs ml-1",
            title: "Cancel"
          }, "Cancel")
        )),
        queued.map(s => React.createElement("div", {
          key: s.id, className: "queue-item queue-item-queued flex items-center gap-2 bg-amber-900/20 rounded px-3 py-2"
        },
          React.createElement("div", { className: "w-2 h-2 rounded-full bg-amber-400" }),
          React.createElement("span", { className: "text-xs text-slate-200 flex-1 truncate" }, s.title || s.prompt || "Untitled"),
          React.createElement("span", { className: "text-xs text-amber-400/60" }, "Waiting..."),
          React.createElement("button", {
            onClick: () => onCancel(s.id),
            className: "queue-cancel-btn text-red-400 hover:text-red-300 text-xs ml-1",
            title: "Cancel"
          }, "Cancel")
        )),
        failed.map(s => React.createElement("div", {
          key: s.id, className: "queue-item queue-item-failed flex items-center gap-2 bg-red-900/20 rounded px-3 py-2"
        },
          React.createElement("div", { className: "w-2 h-2 rounded-full bg-red-400" }),
          React.createElement("span", { className: "text-xs text-slate-200 flex-1 truncate" }, s.title || s.prompt || "Untitled"),
          React.createElement("span", { className: "text-xs text-red-400/70 truncate max-w-xs" }, s.error || "Failed"),
          React.createElement("button", {
            onClick: () => onRetry(s.id),
            className: "queue-retry-btn text-amber-400 hover:text-amber-300 text-xs ml-1",
            title: "Retry"
          }, "Retry")
        ))
      ),
      (queued.length === 0 && running.length === 0 && failed.length === 0) &&
        React.createElement("div", { className: "text-xs text-slate-500 italic" }, "No active renders")
    )
  );
}

// ── Undo/Redo Manager ──────────────────────────────────────────────
class UndoManager {
  constructor(maxHistory = 50) {
    this._stack = [];
    this._index = -1;
    this._max = maxHistory;
  }

  push(snapshot) {
    // Discard any redo history beyond current index
    this._stack = this._stack.slice(0, this._index + 1);
    this._stack.push(JSON.parse(JSON.stringify(snapshot)));
    if (this._stack.length > this._max) {
      this._stack.shift();
    }
    this._index = this._stack.length - 1;
  }

  undo() {
    if (this._index <= 0) return null;
    this._index--;
    return JSON.parse(JSON.stringify(this._stack[this._index]));
  }

  redo() {
    if (this._index >= this._stack.length - 1) return null;
    this._index++;
    return JSON.parse(JSON.stringify(this._stack[this._index]));
  }

  canUndo() { return this._index > 0; }
  canRedo() { return this._index < this._stack.length - 1; }
  size() { return this._stack.length; }
}

const _undoManager = new UndoManager();

function SceneManager({ scenes, onAdd, onUpdate, onRemove }) {
  const [newName, setNewName] = _useState("");
  return (
    React.createElement("div", { className: "scene-manager bg-slate-800/80 border border-amber-700/30 rounded-lg p-4 mb-4" },
      React.createElement("h4", { className: "text-sm font-semibold text-amber-300 mb-3" }, "Scene Manager"),
      React.createElement("div", { className: "scene-list flex flex-col gap-2 mb-3" },
        scenes.map(sc => React.createElement("div", {
          key: sc.id,
          className: "scene-item flex items-center gap-2 bg-slate-900/50 rounded px-3 py-2"
        },
          React.createElement("input", {
            type: "color", value: sc.color || "#4a9eff",
            onChange: e => onUpdate(sc.id, { color: e.target.value }),
            className: "scene-color-picker w-6 h-6 rounded cursor-pointer border-0"
          }),
          React.createElement("input", {
            type: "text", value: sc.name,
            onChange: e => onUpdate(sc.id, { name: e.target.value }),
            className: "scene-name-input bg-transparent border-b border-slate-600 text-sm text-slate-200 flex-1 px-1",
            placeholder: "Scene name"
          }),
          React.createElement("button", {
            onClick: () => onRemove(sc.id),
            className: "text-red-400 hover:text-red-300 text-xs",
            title: "Remove scene"
          }, "\u00d7")
        ))
      ),
      React.createElement("div", { className: "flex gap-2" },
        React.createElement("input", {
          type: "text", value: newName,
          onChange: e => setNewName(e.target.value),
          className: "scene-new-name bg-slate-900 border border-slate-600 rounded px-2 py-1 text-sm text-slate-200 flex-1",
          placeholder: "New scene name..."
        }),
        React.createElement("button", {
          onClick: () => { onAdd(newName); setNewName(""); },
          className: "add-scene-btn bg-amber-600 hover:bg-amber-500 text-white px-3 py-1 rounded text-xs font-medium"
        }, "+ Add")
      )
    )
  );
}

function ExportSettingsPanel({ settings, onChange }) {
  const resolutions = ["source", "1920x1080", "1280x720", "3840x2160", "1080x1920", "720x1280"];
  const codecs = ["h264", "h265", "vp9", "prores"];
  return (
    React.createElement("div", { className: "export-settings-panel bg-slate-800/80 border border-amber-700/30 rounded-lg p-4 mb-4" },
      React.createElement("h4", { className: "text-sm font-semibold text-amber-300 mb-3" }, "Export Settings"),
      React.createElement("div", { className: "grid grid-cols-2 gap-3" },
        React.createElement("div", { className: "flex flex-col gap-1" },
          React.createElement("label", { className: "text-xs text-amber-200/70" }, "Resolution"),
          React.createElement("select", {
            value: settings.resolution,
            onChange: e => onChange({ resolution: e.target.value }),
            className: "export-resolution-select bg-slate-900 border border-slate-600 rounded px-2 py-1 text-sm text-slate-200"
          }, resolutions.map(r => React.createElement("option", { key: r, value: r }, r === "source" ? "Source (no resize)" : r)))
        ),
        React.createElement("div", { className: "flex flex-col gap-1" },
          React.createElement("label", { className: "text-xs text-amber-200/70" }, "Codec"),
          React.createElement("select", {
            value: settings.codec,
            onChange: e => onChange({ codec: e.target.value }),
            className: "export-codec-select bg-slate-900 border border-slate-600 rounded px-2 py-1 text-sm text-slate-200"
          }, codecs.map(c => React.createElement("option", { key: c, value: c }, c.toUpperCase())))
        ),
        React.createElement("div", { className: "flex flex-col gap-1" },
          React.createElement("label", { className: "text-xs text-amber-200/70" }, "FPS (0 = source)"),
          React.createElement("input", {
            type: "number", min: 0, max: 120, step: 1,
            value: settings.fps,
            onChange: e => onChange({ fps: parseInt(e.target.value, 10) || 0 }),
            className: "export-fps-input bg-slate-900 border border-slate-600 rounded px-2 py-1 text-sm text-slate-200 w-full"
          })
        ),
        React.createElement("div", { className: "flex flex-col gap-1" },
          React.createElement("label", { className: "text-xs text-amber-200/70" }, "Quality (CRF: 0=best, 51=worst)"),
          React.createElement("input", {
            type: "number", min: 0, max: 51, step: 1,
            value: settings.crf,
            onChange: e => onChange({ crf: parseInt(e.target.value, 10) || 23 }),
            className: "export-crf-input bg-slate-900 border border-slate-600 rounded px-2 py-1 text-sm text-slate-200 w-full"
          })
        )
      ),
      React.createElement("div", { className: "flex items-center gap-2 mt-3" },
        React.createElement("input", {
          type: "checkbox", checked: settings.audio,
          onChange: e => onChange({ audio: e.target.checked }),
          className: "export-audio-checkbox"
        }),
        React.createElement("label", { className: "text-xs text-amber-200/70" }, "Include audio")
      )
    )
  );
}

function VideoPanel() {
  const [shots, setShots] = _useState([]);
  const [presets, setPresets] = _useState({});
  const [health, setHealth] = _useState(null);
  const [trajShot, setTrajShot] = _useState(null);
  const [queuePaused, setQueuePaused] = _useState(false);
  const [cycleWarning, setCycleWarning] = _useState(false);
  const [toasts, setToasts] = _useState([]);
  const prevShotsRef = React.useRef([]);
  const toastIdCounter = React.useRef(0);

  const addToast = (message, type) => {
    const id = ++toastIdCounter.current;
    setToasts(prev => [...prev, { id, message, type: type || "info" }]);
    setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id));
    }, 5000);
  };

  const dismissToast = (id) => {
    setToasts(prev => prev.filter(t => t.id !== id));
  };
  const [renderOrder, setRenderOrder] = _useState(null);
  const [showDepGraph, setShowDepGraph] = _useState(false);
  const totalTimelineDuration = shots.reduce((sum, s) => {
    const eff = s.target_duration_s != null && s.target_duration_s > 0 ? s.target_duration_s : (s.duration_s || 0);
    return sum + eff;
  }, 0);
  const [viewMode, setViewMode] = _useState("list");
  const [loading, setLoading] = _useState(true);
  const [selectedShotId, setSelectedShotId] = useState(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [assembling, setAssembling] = _useState(false);
  const [assembledPath, setAssembledPath] = _useState(null);
  const [error, setError] = _useState("");
  const [statusFilter, setStatusFilter] = _useState("all");
  const [templates, setTemplates] = _useState([]);
  const [autoScroll, setAutoScroll] = _useState(true);
  const [selected, setSelected] = _useState(new Set());
  const [maxConcurrent, setMaxConcurrent] = _useState(2);
  const [exportSettings, setExportSettings] = _useState({
    resolution: "source", codec: "h264", fps: 0, crf: 23, audio: true
  });
  const [showExportSettings, setShowExportSettings] = _useState(false);
  const [scenes, setScenes] = _useState([]);
  const [showSceneManager, setShowSceneManager] = _useState(false);
  const [favoritePresets, setFavoritePresets] = _useState([]);
  const [showRenderQueue, setShowRenderQueue] = _useState(false);
  const [canUndo, setCanUndo] = _useState(false);
  const [canRedo, setCanRedo] = _useState(false);
  // R44: batch prompt prefix/suffix edit UI
  const [showPromptEdit, setShowPromptEdit] = _useState(false);
  const [editPrefix, setEditPrefix] = _useState("");
  const [editSuffix, setEditSuffix] = _useState("");
  const [editMode, setEditMode] = _useState("add");
  // R44: keyboard navigation between shot cards
  const [focusedShotIndex, setFocusedShotIndex] = _useState(null);
  // R45b: batch duplicate controls
  const [showBatchDupe, setShowBatchDupe] = _useState(false);
  const [batchDupeCount, setBatchDupeCount] = _useState(1);
  const pollRef = _useRef(null);
  const sseRef = _useRef(null);
  const [sseConnected, setSseConnected] = _useState(false);

  // ── Filtered shots ──
  const filteredShots = _useMemo(() => {
    let result = statusFilter === "all" ? shots : shots.filter(s => s.status === statusFilter);
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      result = result.filter(s =>
        (s.prompt || "").toLowerCase().includes(q) ||
        (s.title || "").toLowerCase().includes(q) ||
        (s.notes || "").toLowerCase().includes(q)
      );
    }
    return result;
  }, [shots, statusFilter, searchQuery]);

  // R44: keyboard navigation — Arrow up/down moves focus between cards,
  // Escape clears it, Space toggles the focused card's selection.
  // Enter intentionally NOT handled here so it stays available for form
  // submission inside ShotCard (prompt editor, etc.).
  // Typing in an input/textarea bypasses this handler so users can
  // Arrow through text.
  _useEffect(() => {
    const onKeyDown = (e) => {
      // Skip when the user is typing in any editable control
      const tag = (e.target?.tagName || "").toUpperCase();
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT"
          || e.target?.isContentEditable) {
        return;
      }
      if (filteredShots.length === 0) return;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setFocusedShotIndex((i) => {
          const next = i === null ? 0 : Math.min(i + 1, filteredShots.length - 1);
          // Scroll the newly-focused card into view
          setTimeout(() => {
            const card = document.querySelector(`[data-shot-id="${filteredShots[next]?.id}"]`);
            if (card) card.scrollIntoView({ block: "nearest", behavior: "smooth" });
          }, 0);
          return next;
        });
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setFocusedShotIndex((i) => {
          const next = i === null ? 0 : Math.max(i - 1, 0);
          setTimeout(() => {
            const card = document.querySelector(`[data-shot-id="${filteredShots[next]?.id}"]`);
            if (card) card.scrollIntoView({ block: "nearest", behavior: "smooth" });
          }, 0);
          return next;
        });
      } else if (e.key === "Escape") {
        setFocusedShotIndex(null);
      } else if (e.key === " " && focusedShotIndex !== null) {
        // Space toggles selection of the focused card (no scroll)
        e.preventDefault();
        const focusedShot = filteredShots[focusedShotIndex];
        if (focusedShot) toggleSelect(focusedShot.id);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [filteredShots, focusedShotIndex]);

  // Clamp focusedShotIndex if filter shrinks the list below it
  _useEffect(() => {
    if (focusedShotIndex !== null && focusedShotIndex >= filteredShots.length) {
      setFocusedShotIndex(filteredShots.length > 0 ? filteredShots.length - 1 : null);
    }
  }, [filteredShots.length, focusedShotIndex]);

  // ── Bulk select helpers ──
  const toggleSelect = (id) => {
    const newSet = new Set(selected);
    if (newSet.has(id)) newSet.delete(id);
    else newSet.add(id);
    setSelected(newSet);
  };

  const selectAll = () => {
    setSelected(new Set(filteredShots.map(s => s.id)));
  };

  const selectNone = () => {
    setSelected(new Set());
  };

  const deleteSelected = async () => {
    if (!confirm(`Delete ${selected.size} shot(s)?`)) return;
    for (const id of selected) {
      try {
        await api.post(`/api/video/shots/${id}`, { _method: "DELETE" });
      } catch {}
    }
    setSelected(new Set());
    await refresh();
  };

  const scrollToShot = (shotId) => {
    const el = document.querySelector('[data-shot-id="' + shotId + '"]');
    if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
  };

    const renderSelected = async () => {
    for (const id of selected) {
      try {
        await api.post(`/api/video/shots/${id}/render`, {});
      } catch {}
    }
    await refresh();
  };

  // ── Initial load ──
  const refresh = _useCallback(async () => {
    try {
      const [shotsData, presetsData, healthData, templatesData, settingsData] = await Promise.all([
        api.get("/api/video/shots"),
        api.get("/api/video/presets"),
        api.get("/api/video/health"),
        api.get("/api/video/templates"),
        api.get("/api/video/settings").catch(() => null),
      ]);
      const newShots = (shotsData.shots || []).map((s, i) => ({ ...s, index: i }));
      const prev = prevShotsRef.current;
      if (prev.length > 0) {
        for (const ns of newShots) {
          const ps = prev.find(p => p.id === ns.id);
          if (ps && ps.status !== ns.status) {
            if (ns.status === "ready") {
              addToast((ns.title || "Shot") + " rendered successfully", "success");
            } else if (ns.status === "failed") {
              addToast((ns.title || "Shot") + " render failed", "error");
            }
          if ((ns.status === "running" || ns.status === "rendering") && autoScroll) {
            setTimeout(() => scrollToShot(ns.id), 300);
          }
          }
        }
      }
      prevShotsRef.current = newShots;
      setShots(newShots);
      setPresets(presetsData || {});
      setHealth(healthData || null);
      setTemplates(templatesData.templates || []);
      if (settingsData) setMaxConcurrent(settingsData.max_concurrent || 2);
      setError("");
    } catch (e) {
      setError("Video Bridge not available. Make sure the server is running with video support enabled.");
    } finally {
      setLoading(false);
    }
  }, []);

  _useEffect(() => {
    refresh();
    // SSE connection
    sseRef.current = new EventSource("/api/video/events");
    sseRef.current.addEventListener("shot-update", async () => {
      await refresh();
    });
    sseRef.current.addEventListener("open", () => setSseConnected(true));
    sseRef.current.addEventListener("error", () => setSseConnected(false));
    // Fallback polling every 3s
    pollRef.current = setInterval(async () => {
      try {
        const data = await api.get("/api/video/shots");
        setShots((data.shots || []).map((s, i) => ({ ...s, index: i })));
      } catch {}
    }, 3000);
    return () => {
      clearInterval(pollRef.current);
      sseRef.current?.close();
    };
  }, [refresh]);

  // ── Keyboard shortcuts ──
  _useEffect(() => {
    const handleKey = (e) => {
      if (e.target.tagName === "TEXTAREA" || e.target.tagName === "INPUT") return;
      if (e.key === "n" || e.key === "N") addShot();
      if (e.key === "z" && (e.ctrlKey || e.metaKey) && !e.shiftKey) { e.preventDefault(); doUndo(); }
      if ((e.key === "y" && (e.ctrlKey || e.metaKey)) || (e.key === "z" && (e.ctrlKey || e.metaKey) && e.shiftKey)) { e.preventDefault(); doRedo(); }
      if (e.ctrlKey && e.shiftKey && e.key === "R") {
        e.preventDefault();
        renderAll();
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, []);

  // ── CRUD ops ──
  const addShot = async () => {
    pushUndo();
    try {
      await api.post("/api/video/shots", {
        title: `Shot ${shots.length + 1}`,
        prompt: "",
        negative: "",
        notes: "",
        seed: "",
        backend: "wangp",
        preset: Object.keys(presets)[0] || "wan22_i2v_lightning",
      });
      await refresh();
    } catch (e) {
      setError("Failed to add shot");
    }
  };

  const updateShot = async (id, fields) => {
    try {
      await api.post(`/api/video/shots/${id}`, fields);
      await refresh();
    } catch (e) {
      setError("Failed to update shot");
    }
  };

  const setColorLabel = async (id, colorKey) => {
    try {
      await api.put(`/api/video/shots/${id}`, { color_label: colorKey });
      await refresh();
    } catch (e) {
      setError("Failed to set color label");
    }
  };

  const removeShot = async (id) => {
    if (!window.confirm("Delete this shot?")) return;
    pushUndo();
    try {
      await api.post(`/api/video/shots/${id}`, { _method: "DELETE" });
      await refresh();
    } catch (e) {
      setError("Failed to remove shot");
    }
  };

  const renderShot = async (id) => {
    try {
      await api.post(`/api/video/shots/${id}/render`, {});
      await refresh();
    } catch (e) {
      setError("Failed to queue render");
    }
  };

  const retryShot = async (id) => {
    try {
      await api.post(`/api/video/shots/${id}/retry`, {});
      await refresh();
    } catch (e) {
      setError("Failed to retry shot");
    }
  };

  const cancelShot = async (id) => {
    if (!window.confirm("Cancel this render?")) return;
    try {
      await api.post(`/api/video/shots/${id}/cancel`, {});
      await refresh();
    } catch (e) {
      setError("Failed to cancel render");
    }
  };

  const duplicateShot = async (id) => {
    try {
      await api.post(`/api/video/shots/${id}/duplicate`, {});
      await refresh();
    } catch (e) {
      setError("Failed to duplicate shot");
    }
  };

  const cloneShot = async (id, variation = "") => {
    try {
      await api.post(`/api/video/shots/${id}/clone`, { variation });
      await refresh();
    } catch (e) {
      setError("Failed to clone shot");
    }
  };

  // R45a: snapshots
  const saveSnapshot = async (id, label = "") => {
    try {
      const res = await api.post(`/api/video/shots/${id}/snapshot`, { label });
      addToast("Snapshot saved", "success");
      await refresh();
      return res;
    } catch (e) {
      addToast("Failed to save snapshot: " + (e.message || "unknown"), "error");
      return null;
    }
  };

  const listSnapshots = async (id) => {
    try {
      return await api.get(`/api/video/shots/${id}/snapshots`);
    } catch (e) {
      return { snapshots: [] };
    }
  };

  const restoreSnapshot = async (id, snapId) => {
    try {
      const res = await api.post(`/api/video/shots/${id}/snapshot/${snapId}/restore`, {});
      if (res && res.restored) {
        addToast("Snapshot restored", "success");
      } else {
        addToast(res && res.error ? res.error : "Could not restore (shot may be locked)", "error");
      }
      await refresh();
    } catch (e) {
      addToast("Restore failed: " + (e.message || "unknown"), "error");
    }
  };

  const deleteSnapshot = async (id, snapId) => {
    try {
      await api.post(`/api/video/shots/${id}/snapshot/${snapId}`, { _action: "delete" });
      addToast("Snapshot deleted", "success");
      await refresh();
    } catch (e) {
      addToast("Delete failed: " + (e.message || "unknown"), "error");
    }
  };

  // R48b: Send the current timeline directly to DaVinci Resolve via antenna.
  // Needs Resolve running on the antenna host and antenna_token in guild_config.
  const sendToResolve = async () => {
    const readyCount = shots.filter(s => s.status === "ready" && s.video_path).length;
    if (readyCount === 0) {
      addToast("No ready shots to send — render something first", "error");
      return;
    }
    addToast("Sending timeline to Resolve...", "info");
    try {
      const res = await api.post("/api/video/send-to-resolve",
                                 { format: "fcpxml", fps: 30, bin: "Spellcaster" });
      if (res && res.antenna_response && res.antenna_response.ok) {
        const name = res.antenna_response.timeline_name || "timeline";
        addToast(`Resolve: created "${name}" in project "${res.antenna_response.project}"`,
                 "success");
      } else if (res && res.error) {
        addToast(`Resolve: ${res.error}`, "error");
      } else if (res && res.antenna_response && res.antenna_response.error) {
        addToast(`Resolve: ${res.antenna_response.error}`, "error");
      } else {
        addToast("Resolve: unexpected response (check console)", "error");
        console.warn("[Resolve]", res);
      }
    } catch (e) {
      addToast(`Resolve send failed: ${e.message || "unknown"}`, "error");
    }
  };

  // R47b: pin/unpin a snapshot so it survives the 20-slot cap
  const togglePinSnapshot = async (id, snapId, isPinned) => {
    try {
      const res = await api.post(`/api/video/shots/${id}/snapshot/${snapId}/pin`,
                                 { _action: isPinned ? "unpin" : "pin" });
      if (res && res.ok) {
        addToast(isPinned ? "Snapshot unpinned" : "Snapshot pinned", "success");
      } else {
        addToast(res && res.error ? res.error : "Pin toggle failed", "error");
      }
      await refresh();
    } catch (e) {
      addToast("Pin failed: " + (e.message || "unknown"), "error");
    }
  };

  const exportShotboard = async () => {
    try {
      const resp = await api.post("/api/video/export", {});
      const blob = new Blob([JSON.stringify(resp, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "shotboard_backup.json";
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError("Failed to export shotboard");
    }
  };

  const importShotboard = async () => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".json";
    input.onchange = async (e) => {
      const file = e.target.files[0];
      if (!file) return;
      try {
        const text = await file.text();
        const data = JSON.parse(text);
        if (!window.confirm("Import will replace all current shots. Continue?")) return;
        await api.post("/api/video/import", data);
        await refresh();
      } catch (err) {
        setError("Failed to import shotboard");
      }
    };
    input.click();
  };

  const onTimelineDrop = async (draggedId, targetId) => {
    const dragIdx = shots.findIndex(s => s.id === draggedId);
    const targetIdx = shots.findIndex(s => s.id === targetId);
    if (dragIdx < 0 || targetIdx < 0) return;
    const reordered = [...shots];
    const [moved] = reordered.splice(dragIdx, 1);
    reordered.splice(targetIdx, 0, moved);
    try {
      await api.post("/api/video/reorder", { ordered_ids: reordered.map(s => s.id) });
      await refresh();
    } catch (e) {
      setError("Failed to reorder shots");
      await refresh();
    }
  };

  const batchPreset = async (preset) => {
    if (selected.size === 0) return;
    try {
      await api.post("/api/video/batch-preset", {
        shot_ids: Array.from(selected),
        preset,
      });
      await refresh();
    } catch (e) {
      setError("Failed to change preset for selected shots");
    }
  };

  const batchLock = async (lock) => {
    try {
      await api.post("/api/video/batch-lock", {
        shot_ids: Array.from(selected),
        lock: lock,
      });
      await refresh();
      addToast(lock ? "Locked " + selected.size + " shot(s)" : "Unlocked " + selected.size + " shot(s)", "success");
    } catch (e) {
      setError("Failed to batch lock/unlock");
    }
  };

  const revertShot = async (shotId) => {
    if (!confirm("Revert this shot to its last rendered settings?")) return;
    try {
      await api.post("/api/video/shots/" + shotId + "/revert", {});
      await refresh();
      addToast("Shot reverted to last render", "success");
    } catch (e) {
      addToast("Revert failed: " + (e.message || "unknown error"), "error");
    }
  };

  const batchRevert = async () => {
    if (!confirm("Revert " + selected.size + " shot(s) to their last rendered settings?")) return;
    try {
      await api.post("/api/video/batch-revert", {
        shot_ids: Array.from(selected),
      });
      await refresh();
      addToast("Batch revert complete", "success");
    } catch (e) {
      addToast("Batch revert failed", "error");
    }
  };

  const batchResetStatus = async () => {
    if (!confirm("Reset " + selected.size + " shot(s) to draft?")) return;
    try {
      await api.post("/api/video/batch-reset", {
        shot_ids: Array.from(selected),
      });
      setSelected(new Set());
      await refresh();
      addToast("Reset shots to draft", "success");
    } catch (e) {
      setError("Failed to batch reset");
    }
  };

  const batchColorLabel = async (colorKey) => {
    try {
      await api.post("/api/video/batch-color", {
        shot_ids: Array.from(selected),
        color_label: colorKey,
      });
      await refresh();
    } catch (e) {
      setError("Failed to batch color label");
    }
  };

  // R45b: clone each selected shot N times. Each copy gets a fresh id,
  // status='draft', empty render_history + snapshots, and a versioned
  // title ("Hero" → "Hero v2", "Hero v3", ...).
  const batchDuplicate = async () => {
    if (selected.size === 0) return;
    const count = Math.max(1, Math.min(50, parseInt(batchDupeCount) || 1));
    try {
      const res = await api.post("/api/video/batch-duplicate", {
        shot_ids: Array.from(selected),
        count: count,
        title_suffix_mode: "counter",
      });
      addToast(
        `Duplicated ${selected.size} shot(s) × ${count} = ${res.created} new`,
        res.created > 0 ? "success" : "error"
      );
      setShowBatchDupe(false);
      await refresh();
    } catch (e) {
      addToast("Batch duplicate failed: " + (e.message || "unknown"), "error");
    }
  };

  // R44: add/remove a common prefix/suffix across selected shots' prompts.
  // Calls into Shotboard.batch_prompt_edit which is idempotent — repeated
  // "add" with the same prefix is a no-op, safe to re-run.
  const batchPromptEdit = async () => {
    if (selected.size === 0) return;
    if (!editPrefix && !editSuffix) {
      addToast("Enter a prefix or suffix first", "error");
      return;
    }
    try {
      const res = await api.post("/api/video/batch-prompt-edit", {
        shot_ids: Array.from(selected),
        prefix: editPrefix,
        suffix: editSuffix,
        mode: editMode,
      });
      addToast(
        `Prompt ${editMode}: ${res.modified} modified, ${res.skipped} skipped`,
        res.modified > 0 ? "success" : "info"
      );
      setShowPromptEdit(false);
      setEditPrefix("");
      setEditSuffix("");
      await refresh();
    } catch (e) {
      addToast("Batch prompt edit failed: " + (e.message || "unknown"), "error");
    }
  };


  const moveShot = async (id, direction) => {
    const idx = shots.findIndex(s => s.id === id);
    if (idx < 0) return;
    const newIdx = idx + direction;
    if (newIdx < 0 || newIdx >= shots.length) return;
    const [moved] = shots.splice(idx, 1);
    shots.splice(newIdx, 0, moved);
    const ordered = shots.map(s => s.id);
    try {
      await api.post("/api/video/reorder", { ordered_ids: ordered });
      await refresh();
    } catch (e) {
      setError("Failed to move shot");
      await refresh();
    }
  };

  const reorderShot = async (fromId, toId) => {
    const ids = shots.map(s => s.id);
    const filtered = ids.filter(id => id !== fromId);
    const targetIdx = filtered.indexOf(toId);
    if (targetIdx < 0) return;
    filtered.splice(targetIdx, 0, fromId);
    try {
      await api.post("/api/video/reorder", { ordered_ids: filtered });
      await refresh();
    } catch (e) {
      setError("Failed to reorder shots");
      await refresh();
    }
  };

  const uploadReference = async (shotId, dataUrl, filename) => {
    try {
      await api.post(`/api/video/shots/${shotId}/reference`, {
        image_data: dataUrl,
        filename: filename,
      });
      await refresh();
    } catch (e) {
      setError("Failed to upload reference image");
    }
  };

  const continuityToNext = async (id) => {
    try {
      await api.post(`/api/video/shots/${id}/continuity`, {});
      await refresh();
    } catch (e) {
      setError("Failed to set continuity");
    }
  };

  const renderAll = async () => {
    try {
      const result = await api.post("/api/video/render-all", {});
      if (result && result.has_cycle) {
        setCycleWarning(true);
        setTimeout(() => setCycleWarning(false), 6000);
      }
    } catch (e) {
      console.error("renderAll error:", e);
      // Fallback: render individually
      const draftShots = shots.filter(s => s.status === "draft" || s.status === "failed");
      for (const s of draftShots) {
        try { await api.post(`/api/video/shots/${s.id}/render`, {}); } catch {}
      }
    }
    await refresh();
  };

  const togglePause = async () => {
    try {
      if (queuePaused) {
        await api.post("/api/video/queue/resume", {});
        setQueuePaused(false);
      } else {
        await api.post("/api/video/queue/pause", {});
        setQueuePaused(true);
      }
    } catch (e) {
      setError("Failed to toggle queue pause");
    }
  };

  const changeMaxConcurrent = async (n) => {
    try {
      const result = await api.post("/api/video/settings", { max_concurrent: n });
      setMaxConcurrent(result.max_concurrent || n);
    } catch (e) {
      setError("Failed to update concurrency limit");
    }
  };

  const addScene = async (name, color) => {
    try {
      const sc = await api.post("/api/video/scenes", { name: name || "New Scene", color: color || "#4a9eff" });
      setScenes(prev => [...prev, sc]);
    } catch (e) { setError("Failed to add scene"); }
  };

  const updateScene = async (sceneId, updates) => {
    try {
      await api.post("/api/video/scenes/" + sceneId, updates);
      setScenes(prev => prev.map(sc => sc.id === sceneId ? { ...sc, ...updates } : sc));
    } catch (e) { setError("Failed to update scene"); }
  };

  const removeScene = async (sceneId) => {
    try {
      await api.delete("/api/video/scenes/" + sceneId);
      setScenes(prev => prev.filter(sc => sc.id !== sceneId));
      setShots(prev => prev.map(s => s.scene_id === sceneId ? { ...s, scene_id: null } : s));
    } catch (e) { setError("Failed to remove scene"); }
  };

  const assignShotToScene = async (shotId, sceneId) => {
    try {
      await api.post("/api/video/scenes/" + sceneId + "/assign", { shot_id: shotId });
      setShots(prev => prev.map(s => s.id === shotId ? { ...s, scene_id: sceneId } : s));
    } catch (e) { setError("Failed to assign shot to scene"); }
  };

  const addDependency = async (shotId, dependsOnId) => {
    try {
      const resp = await fetch("/api/video/dependencies", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ shot_id: shotId, depends_on: dependsOnId }),
      });
      if (resp.ok) fetchShots();
    } catch (e) { console.error("addDependency error:", e); }
  };

  const removeDependency = async (shotId, dependsOnId) => {
    try {
      const resp = await fetch("/api/video/dependencies", {
        method: "DELETE",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ shot_id: shotId, depends_on: dependsOnId }),
      });
      if (resp.ok) fetchShots();
    } catch (e) { console.error("removeDependency error:", e); }
  };

  const toggleLock = async (shotId, lock) => {
    try {
      await fetch("/api/video/lock", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ shot_id: shotId, lock: lock }),
      });
      fetchShots();
    } catch (e) { console.error("toggleLock error:", e); }
  };

  const fetchRenderOrder = async () => {
    try {
      const resp = await fetch("/api/video/render-order");
      if (resp.ok) {
        const data = await resp.json();
        setRenderOrder(data);
      }
    } catch (e) { console.error("fetchRenderOrder error:", e); }
  };

  const toggleFavoritePreset = async (presetKey) => {
    try {
      const result = await api.post("/api/video/favorites", { preset: presetKey });
      setFavoritePresets(result.favorites || []);
    } catch (e) { setError("Failed to toggle favorite"); }
  };

  const cancelRender = async (shotId) => {
    try {
      await api.post("/api/video/shots/" + shotId + "/cancel", {});
      await refresh();
    } catch (e) { setError("Failed to cancel render"); }
  };

  const retryRender = async (shotId) => {
    try {
      await api.post("/api/video/shots/" + shotId + "/render", {});
      await refresh();
    } catch (e) { setError("Failed to retry render"); }
  };

  const pushUndo = () => {
    _undoManager.push({ shots, scenes });
    setCanUndo(_undoManager.canUndo());
    setCanRedo(_undoManager.canRedo());
  };

  const doUndo = async () => {
    const snapshot = _undoManager.undo();
    if (!snapshot) return;
    try {
      await api.post("/api/video/import", snapshot);
      await refresh();
    } catch (e) { setError("Undo failed"); }
    setCanUndo(_undoManager.canUndo());
    setCanRedo(_undoManager.canRedo());
  };

  const doRedo = async () => {
    const snapshot = _undoManager.redo();
    if (!snapshot) return;
    try {
      await api.post("/api/video/import", snapshot);
      await refresh();
    } catch (e) { setError("Redo failed"); }
    setCanUndo(_undoManager.canUndo());
    setCanRedo(_undoManager.canRedo());
  };

  const updateExportSettings = async (updates) => {
    const merged = { ...exportSettings, ...updates };
    setExportSettings(merged);
    try {
      const result = await api.post("/api/video/export-settings", merged);
      setExportSettings(result);
    } catch (e) {
      setError("Failed to update export settings");
    }
  };

  const assembleAll = async () => {
    setAssembling(true);
    try {
      const result = await api.post("/api/video/assemble", {});
      setAssembledPath(result.assembled_path || "assembled.mp4");
      setError("");
    } catch (e) {
      setError("Failed to assemble video");
    } finally {
      setAssembling(false);
    }
  }

  const assembleVideo = assembleAll;  // Alias for API consistency
;

  const resetFailed = async () => {
    if (!window.confirm("Reset all failed shots to draft?")) return;
    const failed = shots.filter(s => s.status === "failed");
    for (const s of failed) {
      try {
        await api.post(`/api/video/shots/${s.id}`, { status: "draft" });
      } catch {}
    }
    await refresh();
  };

  const saveTrajectories = async (shotId, trajectories) => {
    try {
      await api.post(`/api/video/shots/${shotId}/trajectories`, { trajectories });
      setTrajShot(null);
      await refresh();
    } catch (e) {
      setError("Failed to save trajectories");
    }
  };

  const saveTemplate = async (template) => {
    try {
      await api.post("/api/video/templates", template);
      await refresh();
    } catch (e) {
      setError("Failed to save template");
    }
  };

  const deleteTemplate = async (templateId) => {
    try {
      await api.post(`/api/video/templates/${templateId}`, { _method: "DELETE" });
      await refresh();
    } catch (e) {
      setError("Failed to delete template");
    }
  };

  // ── Render ──
  if (loading) {
    const queueEta = _useMemo(() => {
    const durations = shots.filter(s => s.render_duration_s > 0).map(s => s.render_duration_s);
    const avg = durations.length > 0 ? durations.reduce((a, b) => a + b, 0) / durations.length : 0;
    const pending = shots.filter(s => s.status === "queued" || s.status === "running").length;
    const eta = avg > 0 && pending > 0 ? avg * pending : 0;
    const mins = Math.floor(eta / 60);
    const secs = Math.round(eta % 60);
    const label = eta > 0 ? (mins > 0 ? mins + "m " + secs + "s" : secs + "s") + " remaining" : "";
    return { eta, pending, avg: Math.round(avg), label };
  }, [shots]);

  return (
      <div className="text-center py-12">
        <div className="inline-block w-8 h-8 border-2 border-amber-500 border-t-transparent rounded-full animate-spin" />
        <p className="text-slate-400 text-sm mt-3">Connecting to Video Bridge...</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Error banner */}
      {error && (
        <div className="error-banner bg-red-500/10 border border-red-500/30 rounded-xl px-4 py-3 text-sm text-red-400 flex items-center gap-2">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0zM12 9v4M12 17h.01" /></svg>
          {error}
          <button onClick={() => setError("")} className="ml-auto text-red-500 hover:text-red-300">&times;</button>
        </div>
      )}

      {/* Header with health + buttons */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-amber-50">Shotboard</h2>
          <HealthPanel health={health} maxConcurrent={maxConcurrent} onMaxConcurrentChange={changeMaxConcurrent} />
        </div>
        <div className="flex gap-2">
          <button onClick={refresh}
            className="flex items-center gap-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 px-3 py-2 rounded-lg text-xs font-medium transition-colors">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M23 4v6h-6M1 20v-6h6M3.51 9a9 9 0 0 1 14.85-3.36M20.49 15a9 9 0 0 1-14.85 3.36" /></svg>
            Refresh
          </button>
          {shots.some(s => s.status === "ready") && (
            <button onClick={assembleAll} disabled={assembling}
              className="flex items-center gap-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 px-3 py-2 rounded-lg text-xs font-medium transition-colors disabled:opacity-40">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 5v14M5 12h14" /></svg>
              {assembling ? "Assembling..." : "Export Video"}
            </button>
            <button onClick={() => setShowExportSettings(!showExportSettings)}
              className="render-queue-toggle bg-slate-700 hover:bg-slate-600 text-amber-200 px-3 py-1.5 rounded text-xs font-medium transition-colors"
              onClick={() => setShowRenderQueue(!showRenderQueue)} title="Render queue">
              {showRenderQueue ? "Hide Queue" : "Queue"}
            </button>
            <button
              className="undo-btn bg-slate-700 hover:bg-slate-600 text-amber-200 px-3 py-1.5 rounded text-xs font-medium transition-colors disabled:opacity-40"
              disabled={!canUndo} onClick={doUndo} title="Undo (Ctrl+Z)">
              Undo
            </button>
            <button
              className="redo-btn bg-slate-700 hover:bg-slate-600 text-amber-200 px-3 py-1.5 rounded text-xs font-medium transition-colors disabled:opacity-40"
              disabled={!canRedo} onClick={doRedo} title="Redo (Ctrl+Y)">
              Redo
            </button>
            <button
              className="scene-manager-toggle bg-slate-700 hover:bg-slate-600 text-amber-200 px-3 py-1.5 rounded text-xs font-medium transition-colors"
              title="Manage scenes"
              onClick={() => setShowSceneManager(!showSceneManager)}>
              {showSceneManager ? "Hide Scenes" : "Scenes"}
            </button>
            <button
              className="export-settings-toggle bg-slate-700 hover:bg-slate-600 text-amber-200 px-3 py-1.5 rounded text-xs font-medium transition-colors"
              title="Export settings">
              {showExportSettings ? "Hide Settings" : "Settings"}
            </button>
          )}
          {shots.some(s => s.status === "failed") && (
            <button data-endpoint="reset-failed" onClick={resetFailed}
              className="reset-failed flex items-center gap-1.5 bg-orange-700/30 hover:bg-orange-700/50 text-orange-300 px-3 py-2 rounded-lg text-xs font-medium transition-colors">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M1 4v6h6M23 20v-6h-6M20.49 9a9 9 0 0 0-14.85-3.36M3.51 15a9 9 0 0 0 14.85 3.36" /></svg>
              Reset Failed
            </button>
          )}
          {shots.some(s => s.status === "draft" || s.status === "failed") && (
            <button onClick={togglePause}
              className={`queue-pause-btn flex items-center gap-1 ${queuePaused ? 'bg-emerald-700/30 hover:bg-emerald-700/50 text-emerald-300' : 'bg-amber-700/30 hover:bg-amber-700/50 text-amber-300'} px-3 py-1.5 rounded-lg text-xs font-medium transition-colors`}
            >
              {queuePaused ? "▶ Resume" : "⏸ Pause"}
            </button>
            <button onClick={renderAll}
              className="flex items-center gap-1.5 bg-emerald-700/30 hover:bg-emerald-700/50 text-emerald-300 px-3 py-2 rounded-lg text-xs font-medium transition-colors">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M5 3l14 9-14 9V3z" /></svg>
              Render All
            </button>
          )}
          {cycleWarning && (
            <span className="cycle-warning text-xs text-red-400 bg-red-900/30 px-2 py-1 rounded">
              Warning: dependency cycle detected — some shots may render out of order
            </span>
          )}
          <button onClick={() => { setShowDepGraph(!showDepGraph); if (!showDepGraph) fetchRenderOrder(); }}
            className={"dep-graph-toggle flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium transition-colors " + (showDepGraph ? "bg-indigo-700/40 text-indigo-200" : "bg-slate-800 hover:bg-slate-700 text-slate-300")}
            title="Show dependency graph and render order">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="5" cy="6" r="3"/><circle cx="19" cy="6" r="3"/><circle cx="12" cy="18" r="3"/><line x1="7.5" y1="7.5" x2="10.5" y2="16.5"/><line x1="16.5" y1="7.5" x2="13.5" y2="16.5"/></svg>
            {showDepGraph ? "Hide Graph" : "Dep Graph"}
          </button>
          <button onClick={exportShotboard}
            className="export-json flex items-center gap-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 px-3 py-2 rounded-lg text-xs font-medium transition-colors">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3" /></svg>
            Export JSON
          </button>
          <button onClick={importShotboard}
            className="import-json flex items-center gap-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 px-3 py-2 rounded-lg text-xs font-medium transition-colors">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12" /></svg>
            Import JSON
          </button>
          <a href="/api/video/export/edl?fps=30" download
            className="export-edl flex items-center gap-1.5 bg-slate-800 hover:bg-emerald-700/50 text-slate-300 hover:text-emerald-100 px-3 py-2 rounded-lg text-xs font-medium transition-colors"
            title="Download EDL (CMX 3600) — import into DaVinci Resolve / Avid / Premiere">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
            EDL
          </a>
          <a href="/api/video/export/fcpxml?fps=30" download
            className="export-fcpxml flex items-center gap-1.5 bg-slate-800 hover:bg-emerald-700/50 text-slate-300 hover:text-emerald-100 px-3 py-2 rounded-lg text-xs font-medium transition-colors"
            title="Download FCPXML — preferred for DaVinci Resolve (preserves names + paths)">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="8" y1="13" x2="16" y2="13"/><line x1="8" y1="17" x2="16" y2="17"/></svg>
            FCPXML
          </a>
          <button onClick={sendToResolve}
            className="send-to-resolve flex items-center gap-1.5 bg-pink-900/40 hover:bg-pink-700/50 text-pink-200 hover:text-pink-100 px-3 py-2 rounded-lg text-xs font-medium transition-colors"
            title="Build timeline directly in DaVinci Resolve via antenna (needs Resolve running + antenna online)">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
            → Resolve
          </button>
          <button onClick={() => setViewMode(viewMode === "list" ? "grid" : "list")}
            className="view-toggle flex items-center gap-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 px-3 py-2 rounded-lg text-xs font-medium transition-colors"
            title={viewMode === "list" ? "Switch to grid view" : "Switch to list view"}
          >
            {viewMode === "list" ? (
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="7" height="7" /><rect x="14" y="3" width="7" height="7" /><rect x="3" y="14" width="7" height="7" /><rect x="14" y="14" width="7" height="7" /></svg>
            ) : (
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" /></svg>
            )}
            {viewMode === "list" ? "Grid" : "List"}
          </button>
          <button onClick={addShot}
            className="flex items-center gap-1.5 bg-amber-600 hover:bg-amber-500 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors shadow-lg shadow-amber-600/30">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 5v14M5 12h14" /></svg>
            New Shot
          </button>
        </div>
      </div>

      {showExportSettings && React.createElement(ExportSettingsPanel, {
        settings: exportSettings, onChange: updateExportSettings
      })}
      {showRenderQueue && React.createElement(RenderQueuePanel, {
        shots: shots, queueStatus: null, onCancel: cancelRender, onRetry: retryRender
      })}
      {showSceneManager && React.createElement(SceneManager, {
        scenes: scenes, onAdd: addScene, onUpdate: updateScene, onRemove: removeScene
      })}
      {/* Assembled video result */}
      {assembledPath && (
        <div className="bg-emerald-500/10 border border-emerald-500/30 rounded-xl px-4 py-3 text-sm text-emerald-300 flex items-center gap-2">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M10 19l-7-7m0 0l7-7m-7 7h18" /></svg>
          Video assembled: <code className="text-emerald-400 font-mono">{assembledPath}</code>
          <a href="/api/video/assembled" download className="ml-2 inline-block bg-emerald-600 hover:bg-emerald-500 text-white px-2 py-1 rounded text-xs font-medium transition-colors">
            Download
          </a>
          <button onClick={() => setAssembledPath(null)} className="ml-auto text-emerald-500 hover:text-emerald-300">&times;</button>
        </div>
      )}

      {/* Timeline strip */}
      {shots.length > 0 && (
        <TimelineStrip
          shots={shots}
          selectedId={selectedShotId}
          onSelect={setSelectedShotId}
          onDrop={onTimelineDrop}
        />
      )}

      {/* Status summary + filter */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <StatusSummary shots={shots} />
          <span className="total-duration text-xs text-slate-500 font-mono">
            {shots.length} shots &middot; ~{shots.reduce((sum, s) => sum + (s.duration_s || 0), 0).toFixed(1)}s total
          </span>
        </div>
        <ShotSummary shots={shots} />
        <div className="flex gap-1.5">
          {["all", "draft", "queued", "running", "ready", "failed"].map(status => (
            <button
              key={status}
              onClick={() => setStatusFilter(status)}
              className={`px-3 py-1 rounded-lg text-xs font-medium transition-colors ${
                statusFilter === status
                  ? "bg-amber-600 text-white"
                  : "bg-slate-800 hover:bg-slate-700 text-slate-300"
              }`}
            >
              {status}
            </button>
          ))}
        </div>
      </div>

      {/* Bulk action bar */}
      {selected.size > 0 && (
        <div className="bulk-actions bg-slate-900 border border-amber-600/20 rounded-xl px-4 py-3 flex items-center justify-between">
          <span className="text-sm text-amber-50">{selected.size} selected</span>
          <select
            className="batch-preset-select bg-slate-800 border border-slate-600 text-slate-300 text-xs rounded px-2 py-1"
            defaultValue=""
            onChange={(e) => { if (e.target.value) { batchPreset(e.target.value); e.target.value = ""; } }}
          >
            <option value="" disabled>Change preset...</option>
            {Object.entries(presets).map(([k, v]) => (
              <option key={k} value={k}>{v.label || k}</option>
            ))}
          </select>
          <div className="flex gap-2 flex-wrap items-center">
            <button onClick={selectNone} className="batch-deselect-btn text-xs text-slate-400 hover:text-slate-300">Deselect</button>
            <button onClick={() => batchLock(true)} className="batch-lock-btn flex items-center gap-1 bg-amber-700/30 hover:bg-amber-700/50 text-amber-300 px-3 py-1 rounded text-xs font-medium">
              Lock
            </button>
            <button onClick={() => batchLock(false)} className="batch-unlock-btn flex items-center gap-1 bg-slate-700/30 hover:bg-slate-700/50 text-slate-300 px-3 py-1 rounded text-xs font-medium">
              Unlock
            </button>
            <select
              className="batch-color-select bg-slate-800 border border-slate-600 text-slate-300 text-xs rounded px-2 py-1"
              defaultValue=""
              onChange={(e) => { if (e.target.value !== "") { batchColorLabel(e.target.value); e.target.value = ""; } }}
            >
              <option value="" disabled>Color label...</option>
              <option value="">None</option>
              {COLOR_LABELS.filter(c => c.key).map(c => (
                <option key={c.key} value={c.key}>{c.label}</option>
              ))}
            </select>
            <button onClick={batchRevert} className="batch-revert-btn px-3 py-1 rounded bg-amber-700/40 hover:bg-amber-600/50 text-amber-100 text-xs">Batch Revert</button>
            <button onClick={() => setShowPromptEdit(v => !v)} className="batch-prompt-edit-btn px-3 py-1 rounded bg-violet-700/40 hover:bg-violet-600/50 text-violet-100 text-xs">
              {showPromptEdit ? "Close Prompt Edit" : "Prompt ±"}
            </button>
            <button onClick={() => setShowBatchDupe(v => !v)} className="batch-duplicate-btn px-3 py-1 rounded bg-cyan-700/40 hover:bg-cyan-600/50 text-cyan-100 text-xs">
              {showBatchDupe ? "Close Duplicate" : "Duplicate ×N"}
            </button>
                <button onClick={batchResetStatus} className="batch-reset-btn flex items-center gap-1 bg-sky-700/30 hover:bg-sky-700/50 text-sky-300 px-3 py-1 rounded text-xs font-medium">
              Reset
            </button>
            <button onClick={renderSelected} className="batch-render-btn flex items-center gap-1 bg-emerald-700/30 hover:bg-emerald-700/50 text-emerald-300 px-3 py-1 rounded text-xs font-medium">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M5 3l14 9-14 9V3z" /></svg>
              Render
            </button>
            <button onClick={deleteSelected} className="batch-delete-btn flex items-center gap-1 bg-red-600/20 hover:bg-red-600/40 text-red-400 px-3 py-1 rounded text-xs font-medium">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /></svg>
              Delete
            </button>
          </div>
        </div>
      )}

      {/* R44: batch prompt prefix/suffix edit — expanding panel */}
      {selected.size > 0 && showPromptEdit && (
        <div className="batch-prompt-edit-panel bg-slate-900 border border-violet-600/30 rounded-xl px-4 py-3 flex flex-col gap-2">
          <div className="flex items-center gap-2 text-xs text-violet-200">
            <span className="font-semibold">Prompt editor</span>
            <span className="text-slate-400">— add or remove a common prefix/suffix on all {selected.size} selected shot(s)</span>
          </div>
          <div className="flex gap-2 items-center flex-wrap">
            <input
              type="text"
              value={editPrefix}
              onChange={(e) => setEditPrefix(e.target.value)}
              placeholder="prefix (e.g. 'cinematic, ')"
              className="batch-prompt-prefix bg-slate-800 border border-slate-600 rounded px-2 py-1 text-xs text-slate-200 placeholder-slate-500 focus:border-violet-500 focus:outline-none flex-1 min-w-[180px]"
            />
            <input
              type="text"
              value={editSuffix}
              onChange={(e) => setEditSuffix(e.target.value)}
              placeholder="suffix (e.g. ', 4k')"
              className="batch-prompt-suffix bg-slate-800 border border-slate-600 rounded px-2 py-1 text-xs text-slate-200 placeholder-slate-500 focus:border-violet-500 focus:outline-none flex-1 min-w-[180px]"
            />
            <div className="batch-prompt-mode inline-flex rounded overflow-hidden border border-slate-600">
              <button
                onClick={() => setEditMode("add")}
                className={`batch-prompt-mode-add px-3 py-1 text-xs ${editMode === "add" ? "bg-violet-600 text-white" : "bg-slate-800 text-slate-300 hover:bg-slate-700"}`}
              >Add</button>
              <button
                onClick={() => setEditMode("remove")}
                className={`batch-prompt-mode-remove px-3 py-1 text-xs ${editMode === "remove" ? "bg-violet-600 text-white" : "bg-slate-800 text-slate-300 hover:bg-slate-700"}`}
              >Remove</button>
            </div>
            <button
              onClick={batchPromptEdit}
              disabled={!editPrefix && !editSuffix}
              className="batch-prompt-apply px-3 py-1 rounded bg-violet-600 hover:bg-violet-500 text-white text-xs font-medium disabled:bg-slate-700 disabled:text-slate-500 disabled:cursor-not-allowed"
            >Apply</button>
          </div>
          <div className="text-xs text-slate-500">
            Idempotent — re-running with the same prefix won't double-add. Locked shots are skipped.
          </div>
        </div>
      )}

      {/* R45b: batch duplicate — expanding panel */}
      {selected.size > 0 && showBatchDupe && (
        <div className="batch-duplicate-panel bg-slate-900 border border-cyan-600/30 rounded-xl px-4 py-3 flex flex-col gap-2">
          <div className="flex items-center gap-2 text-xs text-cyan-200">
            <span className="font-semibold">Duplicate</span>
            <span className="text-slate-400">
              — create {batchDupeCount} cop{batchDupeCount === 1 ? "y" : "ies"} of each of the {selected.size} selected shot(s).
              New shots get "v2", "v3"… suffix and reset status/video/snapshots.
            </span>
          </div>
          <div className="flex gap-2 items-center flex-wrap">
            <label className="text-xs text-slate-300 flex items-center gap-2">
              Copies per shot:
              <input
                type="number"
                min="1"
                max="50"
                value={batchDupeCount}
                onChange={(e) => setBatchDupeCount(Math.max(1, Math.min(50, parseInt(e.target.value) || 1)))}
                className="batch-dupe-count bg-slate-800 border border-slate-600 rounded px-2 py-1 text-xs text-slate-200 focus:border-cyan-500 focus:outline-none w-20"
              />
            </label>
            <span className="text-xs text-slate-500">
              Will create {selected.size * batchDupeCount} new shot(s)
            </span>
            <button
              onClick={batchDuplicate}
              className="batch-dupe-apply px-3 py-1 rounded bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-medium ml-auto"
            >Duplicate</button>
          </div>
        </div>
      )}

      {/* Search bar */}
      <div className="search-bar relative">
        <input
          type="text"
          placeholder="Search shots by prompt, title, or notes..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="search-input w-full bg-slate-800/50 border border-slate-700/50 rounded-lg px-4 py-2 pl-9 text-sm text-slate-300 placeholder-slate-500 focus:outline-none focus:border-amber-500/50 focus:ring-1 focus:ring-amber-500/20"
        />
        <svg className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" />
        </svg>
        {searchQuery && (
          <button onClick={() => setSearchQuery("")} className="search-clear absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300">
            &times;
          </button>
        )}
      </div>

      {/* Shot list */}
      {shots.length === 0 ? (
        <div className="text-center py-16 bg-slate-900/50 border border-amber-600/10 rounded-xl">
          <svg className="mx-auto mb-3 text-amber-600/40" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M19.82 2H4.18A2.18 2.18 0 0 0 2 4.18v15.64A2.18 2.18 0 0 0 4.18 22h15.64A2.18 2.18 0 0 0 22 19.82V4.18A2.18 2.18 0 0 0 19.82 2zM7 2v20M17 2v20M2 12h20M2 7h5M2 17h5M17 17h5M17 7h5" />
          </svg>
          <p className="text-slate-400 text-sm">No shots yet. Click <strong className="text-amber-300">New Shot</strong> to start your storyboard.</p>
        </div>
      ) : filteredShots.length === 0 ? (
        <div className="text-center py-8 text-slate-400 text-sm">
          No shots with status "{statusFilter}".
        </div>
      ) : viewMode === "grid" ? (
        <div className="space-y-2">
          <div className="flex items-center justify-between px-1 py-2 text-xs text-slate-500">
            <label className="flex items-center gap-1.5">
              <input type="checkbox" checked={selected.size === filteredShots.length && filteredShots.length > 0} onChange={selected.size === filteredShots.length ? selectNone : selectAll} className="w-4 h-4 rounded accent-amber-500" />
              {filteredShots.length} shot{filteredShots.length !== 1 ? "s" : ""} · {totalTimelineDuration.toFixed(1)}s total
            </label>
          </div>
          <div className="shot-grid grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
            {filteredShots.map((shot) => (
              <GridCard
                key={shot.id}
                shot={shot}
                presets={presets}
                onRender={renderShot}
                onRemove={removeShot}
                isSelected={selected.has(shot.id)}
                onToggleSelect={toggleSelect}
              />
            ))}
          </div>
        </div>
      ) : (
        <div className="space-y-2">
          <div className="flex items-center justify-between px-1 py-2 text-xs text-slate-500">
            <label className="flex items-center gap-1.5">
              <input type="checkbox" checked={selected.size === filteredShots.length && filteredShots.length > 0} onChange={selected.size === filteredShots.length ? selectNone : selectAll} className="w-4 h-4 rounded accent-amber-500" />
              {filteredShots.length} shot{filteredShots.length !== 1 ? "s" : ""}
            </label>
          </div>
          {showDepGraph && renderOrder && (
          <div className="dep-graph-panel bg-slate-900/80 border border-indigo-500/30 rounded-xl p-4 mb-4">
            <h3 className="text-sm font-semibold text-indigo-300 mb-3">
              Render Order &amp; Dependencies
              {renderOrder.has_cycle && <span className="ml-2 text-red-400 text-xs">(cycle detected)</span>}
            </h3>
            <div className="text-xs text-slate-400 mb-2">
              {renderOrder.ready_count} of {renderOrder.total} shots ready to render
            </div>
            <div className="dep-graph-nodes flex flex-col gap-1">
              {renderOrder.nodes.map((node, i) => (
                <div key={node.id} className={"dep-graph-node flex items-center gap-2 px-3 py-1.5 rounded " +
                  (node.ready_to_render ? "bg-emerald-900/30 border border-emerald-700/30" :
                   node.status === "ready" ? "bg-blue-900/30 border border-blue-700/30" :
                   !node.dependencies_met ? "bg-amber-900/30 border border-amber-700/30" :
                   "bg-slate-800/50 border border-slate-700/30")}>
                  <span className="dep-graph-order text-xs font-mono text-slate-500 w-6">{i + 1}.</span>
                  <span className={"dep-graph-status w-2 h-2 rounded-full " +
                    (node.status === "ready" ? "bg-emerald-400" :
                     node.status === "rendering" ? "bg-amber-400 animate-pulse" :
                     node.status === "failed" ? "bg-red-400" :
                     "bg-slate-500")} />
                  <span className="text-xs text-slate-200 flex-1">{node.title}</span>
                  {node.depends_on.length > 0 && (
                    <span className="dep-graph-arrows text-xs text-indigo-400">
                      {node.dependencies_met ? "✓" : "⏳"} needs {node.depends_on.length} dep{node.depends_on.length > 1 ? "s" : ""}
                    </span>
                  )}
                </div>
              ))}
            </div>
            {renderOrder.edges.length > 0 && (
              <div className="dep-graph-edges mt-3 pt-2 border-t border-slate-700/50">
                <div className="text-xs text-slate-500 mb-1">Dependency links:</div>
                <div className="flex flex-wrap gap-2">
                  {renderOrder.edges.map((edge, i) => {
                    const fromNode = renderOrder.nodes.find(n => n.id === edge.from);
                    const toNode = renderOrder.nodes.find(n => n.id === edge.to);
                    return (
                      <span key={i} className={"dep-graph-edge text-xs px-2 py-0.5 rounded " + (edge.met ? "bg-emerald-900/40 text-emerald-300" : "bg-amber-900/40 text-amber-300")}>
                        {fromNode ? fromNode.title : edge.from.slice(0,6)} {edge.met ? "→" : "⇢"} {toNode ? toNode.title : edge.to.slice(0,6)}
                      </span>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        )}
        {filteredShots.map((shot, idx) => (
            <ShotCard
              key={shot.id}
              shot={shot}
              presets={presets}
              templates={templates}
              onUpdate={updateShot}
              onRemove={removeShot}
              onRender={renderShot}
              onRetry={retryShot}
              onOpenTrajectory={setTrajShot}
              onUploadRef={uploadReference}
              onReorder={reorderShot}
              onContinuity={continuityToNext}
              onDuplicate={duplicateShot}
              onClone={cloneShot}
              onColorLabel={setColorLabel}
              onMove={moveShot}
              onSaveTemplate={saveTemplate}
              onDeleteTemplate={deleteTemplate}
              isSelected={selected.has(shot.id)}
              onToggleSelect={toggleSelect}
              isFirst={idx === 0}
              isLast={idx === filteredShots.length - 1}
              colorLabel={shot.color_label || ""}
              onCancel={cancelShot}
              estimateAvg={null}
              allShots={shots}
              onAddDependency={addDependency}
              onRemoveDependency={removeDependency}
              onToggleLock={toggleLock}
              onSaveSnapshot={saveSnapshot}
              onRestoreSnapshot={restoreSnapshot}
              onDeleteSnapshot={deleteSnapshot}
              onTogglePinSnapshot={togglePinSnapshot}
              focused={focusedShotIndex === idx}
            />
          ))}
        </div>
      )}

      {/* Trajectory modal */}
      {trajShot && (
        <TrajectoryModal
          shot={trajShot}
          onClose={() => setTrajShot(null)}
          onSaved={saveTrajectories}
        />
      )}

      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
      {/* Auto-scroll toggle */}
      <div className="auto-scroll-toggle flex justify-center gap-2 pt-2">
        <label className="auto-scroll-label flex items-center gap-1 text-xs text-slate-500 cursor-pointer">
          <input
            type="checkbox"
            checked={autoScroll}
            onChange={(e) => setAutoScroll(e.target.checked)}
            className="auto-scroll-checkbox w-3 h-3 rounded accent-amber-500"
          />
          Auto-scroll to rendering shot
        </label>
      </div>

      {/* Keyboard shortcuts hint */}
      {queueEta.label && (
        <div className="queue-eta-header text-center text-xs text-amber-400 py-1">
          <span className="queue-eta-label">~{queueEta.label}</span>
        </div>
      )}

      <div className="shortcut-hints text-xs text-slate-500 text-center pt-4 border-t border-slate-800">
        <span className="text-slate-600">Shortcuts:</span> <kbd className="px-1 rounded bg-slate-800">N</kbd> new shot · <kbd className="px-1 rounded bg-slate-800">Ctrl+Shift+R</kbd> render all
      </div>
    </div>
  );

}

window.VideoPanel = VideoPanel;
