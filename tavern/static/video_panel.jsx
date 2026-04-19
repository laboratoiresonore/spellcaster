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
  delete: (url) => fetch(url, { method: "DELETE" }).then(r => r.json()),
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
  promptDupeCount = 0,
  onToggleArchive,
  onMakeVariation,
  onPromoteVariation,
  variationSiblings = [],
  focused = false,
}) {
  const [expanded, setExpanded] = _useState(shot.status === "draft");
  const [showHistory, setShowHistory] = _useState(false);
  const [showCompare, setShowCompare] = _useState(false);
  const [showSnapshots, setShowSnapshots] = _useState(false);
  const [snapLabel, setSnapLabel] = _useState("");
  const [snapCompare, setSnapCompare] = _useState([]);  // R46b: 0-2 snap ids selected for diff

  const isLocked = shot.locked || false;

  // R63a: client-side port of shotboard.shot_warnings() — avoids an
  // N+1 API call when rendering a big shot grid. Backend helper stays
  // authoritative (GIMP/other consumers use it); UI mirrors the logic
  // it can compute locally without a filesystem check (ref_image
  // existence is skipped client-side — browser can't stat paths).
  const shotWarnings = _useMemo(() => {
    const warnings = [];
    if (!(shot.prompt || "").trim()) {
      warnings.push({code: "empty_prompt", severity: "error",
                     message: "Prompt is empty"});
    }
    for (const depId of (shot.depends_on || [])) {
      const dep = (allShots || []).find(s => s.id === depId);
      if (!dep) {
        warnings.push({code: "broken_dependency", severity: "error",
                       message: `Depends on deleted shot ${String(depId).slice(0,8)}…`});
        continue;
      }
      const hasReadyHistory = (dep.render_history || []).some(
        e => e.status === "ready");
      if (dep.status === "failed" && !hasReadyHistory) {
        warnings.push({code: "failed_dependency", severity: "warn",
                       message: `Depends on "${dep.title || depId.slice(0,8)}" which has never rendered successfully.`});
      }
    }
    if (shot.carry_last_frame) {
      const idx = (allShots || []).findIndex(s => s.id === shot.id);
      if (idx === 0) {
        warnings.push({code: "carry_frame_without_deps", severity: "warn",
                       message: "carry_last_frame=True but this is the first shot"});
      }
    }
    return warnings;
  }, [shot.prompt, shot.depends_on, shot.carry_last_frame,
       shot.id, allShots]);
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
  // R74a: hover preview state — show an overlaid <video> on thumbnail hover
  const [showHoverPreview, setShowHoverPreview] = _useState(false);
  const [showAdvanced, setShowAdvanced] = _useState(false);
  // R73b: tag input field
  const [newTag, setNewTag] = _useState("");
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
        {/* R74a: thumb area — hover triggers a small muted preview when
            a video exists. No preview for drafts/failed. */}
        <div className="relative w-12 h-8 rounded bg-slate-950 border border-amber-600/20 overflow-hidden flex-shrink-0"
             onMouseEnter={(e) => { e.stopPropagation(); if (shot.video_path) setShowHoverPreview(true); }}
             onMouseLeave={() => setShowHoverPreview(false)}>
          {shot.thumb ? (
            <img src={shot.thumb || `/api/video/shots/${shot.id}/thumbnail`} alt="thumb" className="w-full h-full object-cover" />
          ) : (
            <div className="w-full h-full flex items-center justify-center text-slate-600">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="8.5" cy="8.5" r="1.5" /><path d="M21 15l-5-5L5 21" /></svg>
            </div>
          )}
          {showHoverPreview && shot.video_path && (
            <div className="shot-hover-preview absolute -top-1 -left-1 z-20 w-64 h-40 bg-black border-2 border-amber-500 rounded shadow-2xl pointer-events-none">
              <video src={`/api/video/shots/${shot.id}/video`}
                     autoPlay muted loop playsInline
                     className="w-full h-full object-contain rounded" />
            </div>
          )}
        </div>
        <span className="flex-1 text-amber-50 text-sm font-medium truncate">
          {editTitle || <span className="text-slate-500 italic">Untitled shot</span>}
        </span>
        {/* R76b: rating stars — compact display, click-to-edit */}
        {(() => {
          const r = shot.rating || 0;
          return (
            <span className="shot-rating-inline inline-flex gap-0.5 text-[11px] leading-none"
                  onClick={(e) => e.stopPropagation()}>
              {[1, 2, 3, 4, 5].map(n => (
                <button key={n}
                  onClick={() => onUpdate(shot.id, {rating: (r === n ? 0 : n)})}
                  className={n <= r ? "text-amber-400 hover:text-amber-300"
                                     : "text-slate-700 hover:text-amber-500"}
                  title={`Rate ${n}★ ${n === r ? "(click again to clear)" : ""}`}
                >{n <= r ? "★" : "☆"}</button>
              ))}
            </span>
          );
        })()}
        {/* R73b: tag chips (compact, up to 3 shown in collapsed header) */}
        {(shot.tags || []).slice(0, 3).map(t => (
          <span key={t} className="shot-tag-chip px-1.5 py-0.5 rounded bg-teal-900/40 text-teal-200 text-[10px] font-medium">
            #{t}
          </span>
        ))}
        {(shot.tags || []).length > 3 && (
          <span className="text-[10px] text-slate-400">+{shot.tags.length - 3}</span>
        )}
        {/* R65a: bookmark toggle */}
        <button
          onClick={(e) => { e.stopPropagation(); onUpdate(shot.id, {bookmarked: !shot.bookmarked}); }}
          className={"shot-bookmark text-sm leading-none transition-colors " +
            (shot.bookmarked ? "text-yellow-400 hover:text-yellow-300"
                              : "text-slate-600 hover:text-yellow-400")}
          title={shot.bookmarked ? "Remove bookmark" : "Bookmark this shot"}
        >{shot.bookmarked ? "★" : "☆"}</button>
        {/* R71a: archive toggle — appears only for archived view or on hover */}
        {onToggleArchive && (
          <button
            onClick={(e) => { e.stopPropagation(); onToggleArchive(shot); }}
            className={"shot-archive-toggle text-[11px] leading-none transition-colors px-1 " +
              (shot.archived ? "text-emerald-400 hover:text-emerald-300"
                              : "text-slate-600 hover:text-amber-400")}
            title={shot.archived ? "Restore from archive" : "Archive (soft-delete)"}
          >{shot.archived ? "↩" : "🗑"}</button>
        )}
        {/* R65b: duplicate-prompt badge — N shots share this exact prompt */}
        {promptDupeCount > 1 && (
          <span className="shot-dupe-badge px-1 rounded bg-purple-900/40 text-purple-200 text-[10px] font-semibold"
                title={`${promptDupeCount} shots share this exact prompt — possible duplicate`}>
            ×{promptDupeCount}
          </span>
        )}
        {/* R72a: variation badge */}
        {shot.variation_group && (
          <span className={"shot-variation-badge px-1 rounded text-[10px] font-semibold " +
                  (shot.is_primary
                    ? "bg-emerald-900/40 text-emerald-200"
                    : "bg-slate-700/40 text-slate-300")}
                title={shot.is_primary
                  ? `Primary variation of ${1 + variationSiblings.length}`
                  : `Alternate variation (primary elsewhere) — click Promote to activate`}>
            {shot.is_primary ? "VAR★" : "VAR"}
          </span>
        )}
        <StatusBadge status={shot.status} />
        {/* R63a: warning icons — click to expand (uses setExpanded via parent) */}
        {shotWarnings.length > 0 && (() => {
          const errorCount = shotWarnings.filter(w => w.severity === "error").length;
          const warnCount = shotWarnings.filter(w => w.severity === "warn").length;
          const dominant = errorCount > 0 ? "error" : "warn";
          const color = dominant === "error" ? "text-rose-400" : "text-amber-400";
          const total = shotWarnings.length;
          const tooltip = shotWarnings.map(w => `• ${w.message}`).join("\n");
          return (
            <span className={`shot-warnings ${color} text-xs font-medium`}
                  title={tooltip}>
              ⚠ {total > 1 ? total : ""}
            </span>
          );
        })()}
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

          {/* R73b: tag editor */}
          <div>
            <label className="block text-xs font-medium text-amber-200 mb-1">Tags</label>
            <div className="shot-tag-editor flex flex-wrap gap-1 items-center">
              {(shot.tags || []).map(t => (
                <span key={t}
                  className="shot-tag-pill inline-flex items-center gap-1 px-2 py-0.5 rounded bg-teal-900/40 text-teal-200 text-[11px]">
                  #{t}
                  <button
                    onClick={async () => {
                      await fetch(`/api/video/shots/${shot.id}/tags?tag=${encodeURIComponent(t)}`,
                                  {method: "DELETE"});
                      // Refresh via parent's onUpdate mechanism (fallback: set same field)
                      onUpdate(shot.id, {});
                    }}
                    className="text-teal-300 hover:text-rose-300 leading-none"
                    title="Remove tag"
                  >×</button>
                </span>
              ))}
              <input type="text" value={newTag}
                onChange={(e) => setNewTag(e.target.value)}
                onKeyDown={async (e) => {
                  if (e.key === "Enter" && newTag.trim()) {
                    e.preventDefault();
                    await fetch(`/api/video/shots/${shot.id}/tags`, {
                      method: "POST",
                      headers: {"Content-Type": "application/json"},
                      body: JSON.stringify({tag: newTag.trim()}),
                    });
                    setNewTag("");
                    onUpdate(shot.id, {});
                  }
                }}
                placeholder="+ tag (Enter)"
                className="shot-tag-input bg-slate-800 border border-slate-600 rounded px-2 py-0.5 text-[11px] text-slate-200 placeholder-slate-500 focus:border-teal-500 focus:outline-none w-32" />
            </div>
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
            {/* R61b: priority badge — click cycles high → normal → low */}
            <button
              onClick={() => {
                const next = {high: "normal", normal: "low", low: "high"}[shot.priority || "normal"];
                onUpdate(shot.id, {priority: next});
              }}
              className={
                "shot-priority-badge px-1.5 py-0.5 rounded text-[10px] font-semibold transition-colors " +
                (shot.priority === "high"
                   ? "bg-rose-600/30 text-rose-300 hover:bg-rose-600/50"
                   : (shot.priority === "low"
                       ? "bg-slate-700/40 text-slate-400 hover:bg-slate-700/60"
                       : "bg-slate-600/30 text-slate-300 hover:bg-slate-600/50"))
              }
              title={`Priority: ${shot.priority || "normal"} — click to cycle. Higher-priority shots queue first.`}
            >
              {shot.priority === "high" ? "⬆ HIGH"
                : shot.priority === "low" ? "⬇ low"
                : "normal"}
            </button>
            <button
              onClick={() => onDuplicate(shot.id)}
              className="flex items-center gap-1.5 bg-slate-700/30 hover:bg-slate-700/50 text-slate-300 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M8 16H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v2m-6 12h8a2 2 0 0 0 2-2v-8a2 2 0 0 0-2-2h-8a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2z" /></svg>
              Duplicate
            </button>
            {/* R72a: variation controls */}
            {onMakeVariation && (
              <button
                onClick={() => {
                  const label = prompt("Variation label (e.g. 'darker tone', 'closer crop'):", "");
                  if (label !== null) onMakeVariation(shot.id, label);
                }}
                className="make-variation-btn flex items-center gap-1.5 bg-emerald-700/30 hover:bg-emerald-700/50 text-emerald-300 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors"
                title="Create an alternate version of this shot (shares creative state; gets fresh id + draft status)"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="4"/><circle cx="12" cy="4" r="2"/><circle cx="4" cy="20" r="2"/><circle cx="20" cy="20" r="2"/><line x1="12" y1="8" x2="12" y2="10"/><line x1="8" y1="14" x2="6" y2="18"/><line x1="16" y1="14" x2="18" y2="18"/></svg>
                + Variation
              </button>
            )}
            {onPromoteVariation && shot.variation_group && !shot.is_primary && (
              <button
                onClick={() => onPromoteVariation(shot.id)}
                className="promote-variation-btn flex items-center gap-1.5 bg-emerald-600/50 hover:bg-emerald-500/70 text-white px-3 py-1.5 rounded-lg text-xs font-medium transition-colors"
                title="Make this the primary variation — the one rendered/exported"
              >
                ★ Promote
              </button>
            )}
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
  // R78b: which fields the search scans. All three default on; unchecking
  // narrows the scope. Persists in component state only.
  const [searchFields, setSearchFields] = _useState({prompt: true, title: true, notes: true, tags: true});
  const [assembling, setAssembling] = _useState(false);
  const [assembledPath, setAssembledPath] = _useState(null);
  const [error, setError] = _useState("");
  const [statusFilter, setStatusFilter] = _useState("all");
  // R73b: tag filter — when set, filters to shots that carry this tag.
  // Distinct axis from statusFilter so a user can combine "stale" + "tag:hero".
  const [tagFilter, setTagFilter] = _useState("");
  // R77a: sort mode — "board" (default), "rating", "duration", "last_rendered"
  const [sortMode, setSortMode] = _useState("board");
  // R77b: focus mode — hides all the chrome for distraction-free review
  const [focusMode, setFocusMode] = _useState(false);
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
  // R49b + R52: Antenna admin dialog. antennaStatus is the legacy
  // single-antenna snapshot; antennaList is the R52 multi-antenna list
  // (one entry per physical machine).
  const [showAntennaAdmin, setShowAntennaAdmin] = _useState(false);
  const [antennaStatus, setAntennaStatus] = _useState(null);
  const [antennaList, setAntennaList] = _useState([]);
  const [antennaPairUrl, setAntennaPairUrl] = _useState("");
  const [antennaPairToken, setAntennaPairToken] = _useState("");
  const [antennaBusy, setAntennaBusy] = _useState(false);
  // R54: which features are currently satisfied by at least one online
  // antenna. Features NOT in this set are hidden from the UI entirely
  // (matches the "nothing dead-renders" rule).
  const [featureMap, setFeatureMap] = _useState({});
  // R55b: the FULL /api/features response (both satisfied and unsatisfied)
  // so the Antenna modal can tell the user WHY a feature isn't showing up.
  const [featureReport, setFeatureReport] = _useState(null);
  // R60a: snapshot-restore preview (populated when user clicks Restore;
  // cleared when they confirm or cancel in the modal).
  const [restorePreview, setRestorePreview] = _useState(null);
  // R66a: keyboard shortcuts cheatsheet modal (toggled with '?')
  const [showShortcuts, setShowShortcuts] = _useState(false);
  // R76a: command palette (Ctrl+K) — fuzzy-searchable action launcher
  const [showCommandPalette, setShowCommandPalette] = _useState(false);
  const [commandQuery, setCommandQuery] = _useState("");
  const [commandSelectedIdx, setCommandSelectedIdx] = _useState(0);
  // R68a: side-by-side compare modal + its selected shot ids
  const [compareModal, setCompareModal] = _useState(null);  // {a: shotId, b: shotId}
  // R68b: board-stats mini-dashboard toggle
  const [showBoardStats, setShowBoardStats] = _useState(false);
  // R70a: outline/jump-list panel toggle (sticky sidebar-like nav)
  const [showOutline, setShowOutline] = _useState(false);
  // R74b: near-duplicates panel
  const [showNearDupes, setShowNearDupes] = _useState(false);
  const [nearDupes, setNearDupes] = _useState([]);
  const refreshNearDupes = _useCallback(async () => {
    try {
      const res = await api.get("/api/video/near-duplicates?threshold=0.80");
      setNearDupes(res?.pairs || []);
    } catch (_) {}
  }, []);
  _useEffect(() => { if (showNearDupes) refreshNearDupes(); },
             [showNearDupes, refreshNearDupes]);
  // R66b: bulk search-replace panel toggle
  const [showSearchReplace, setShowSearchReplace] = _useState(false);
  const [searchReplaceFind, setSearchReplaceFind] = _useState("");
  const [searchReplaceWith, setSearchReplaceWith] = _useState("");
  const [searchReplaceCase, setSearchReplaceCase] = _useState(false);
  // R60b: render-cost estimate + live antenna telemetry (GPU util, VRAM,
  // ComfyUI queue depth). Polled every 20s; null when backend is old.
  const [queueCost, setQueueCost] = _useState(null);
  // R61a: Fleet telemetry — one row per online antenna with GPU/RAM/
  // queue-depth, refreshed every 10s when the modal is open.
  const [fleetTelemetry, setFleetTelemetry] = _useState(null);
  // R56: per-service launch state so the "Start" buttons show progress
  const [serviceStartBusy, setServiceStartBusy] = _useState({});
  const pollRef = _useRef(null);
  const sseRef = _useRef(null);
  const [sseConnected, setSseConnected] = _useState(false);

  // ── Filtered shots ──
  // R62a: "modified since last render" helper + filter toggle.
  // A shot is STALE when: it has a ready render_history entry AND the
  // current creative state differs from what that entry recorded. These
  // are the shots the user probably wants to re-render.
  const isShotStale = _useCallback((shot) => {
    const hist = shot.render_history || [];
    let lastOk = null;
    for (let i = hist.length - 1; i >= 0; i--) {
      if (hist[i].status === "ready") { lastOk = hist[i]; break; }
    }
    if (!lastOk) return false;
    if ((shot.prompt || "") !== (lastOk.prompt || "")) return true;
    if ((shot.negative || "") !== (lastOk.negative || "")) return true;
    if ((shot.preset || "") !== (lastOk.preset || "")) return true;
    const curOv = JSON.stringify(shot.overrides || {});
    const lastOv = JSON.stringify(lastOk.overrides || {});
    if (curOv !== lastOv) return true;
    return false;
  }, []);

  const filteredShots = _useMemo(() => {
    // R71a: archived shots never appear in the main list unless the
    // user explicitly picks the "archived" filter.
    const base = statusFilter === "archived"
      ? shots.filter(s => s.archived)
      : shots.filter(s => !s.archived);
    let result = statusFilter === "all" ? base
      : statusFilter === "archived" ? base
      : statusFilter === "stale" ? base.filter(isShotStale)
      : statusFilter === "starred" ? base.filter(s => s.bookmarked)
      : statusFilter === "rated" ? base.filter(s => (s.rating || 0) > 0)
      : base.filter(s => s.status === statusFilter);
    if (tagFilter) {
      result = result.filter(s => (s.tags || []).includes(tagFilter));
    }
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      result = result.filter(s => {
        if (searchFields.prompt && (s.prompt || "").toLowerCase().includes(q)) return true;
        if (searchFields.title  && (s.title  || "").toLowerCase().includes(q)) return true;
        if (searchFields.notes  && (s.notes  || "").toLowerCase().includes(q)) return true;
        if (searchFields.tags   && (s.tags || []).some(t => t.includes(q))) return true;
        return false;
      });
    }
    // R77a: apply sort if not board-order
    if (sortMode !== "board") {
      const sorted = [...result];
      if (sortMode === "rating") {
        sorted.sort((a, b) => (b.rating || 0) - (a.rating || 0) || a.index - b.index);
      } else if (sortMode === "duration") {
        sorted.sort((a, b) => (b.render_duration_s || 0) - (a.render_duration_s || 0) || a.index - b.index);
      } else if (sortMode === "last_rendered") {
        const lastRender = (s) => {
          const hist = s.render_history || [];
          let ts = 0;
          for (const e of hist) {
            if (e.status === "ready" && e.timestamp > ts) ts = e.timestamp;
          }
          return ts;
        };
        sorted.sort((a, b) => lastRender(b) - lastRender(a) || a.index - b.index);
      } else if (sortMode === "recent_edit") {
        sorted.sort((a, b) => (b.last_updated || 0) - (a.last_updated || 0) || a.index - b.index);
      }
      return sorted;
    }
    return result;
  }, [shots, statusFilter, tagFilter, searchQuery, searchFields, sortMode, isShotStale]);

  // R73b: distinct tags in use (derived from shots)
  const allTags = _useMemo(() => {
    const counts = {};
    for (const s of shots) {
      if (s.archived) continue;
      for (const t of (s.tags || [])) counts[t] = (counts[t] || 0) + 1;
    }
    return Object.entries(counts)
      .sort(([,a], [,b]) => b - a)
      .map(([tag, count]) => ({tag, count}));
  }, [shots]);

  // R65b: shot-id → cluster size when prompt is shared with 2+ other shots.
  // Recomputed from shot list only (no API call) — duplicate detection
  // is a pure derived view.
  const promptClusters = _useMemo(() => {
    const byPrompt = new Map();
    for (const s of shots) {
      const p = (s.prompt || "").trim().replace(/\s+/g, " ").toLowerCase();
      if (!p) continue;
      if (!byPrompt.has(p)) byPrompt.set(p, []);
      byPrompt.get(p).push(s.id);
    }
    const out = new Map();
    for (const [, ids] of byPrompt) {
      if (ids.length >= 2) {
        for (const id of ids) out.set(id, ids.length);
      }
    }
    return out;
  }, [shots]);

  // R44: keyboard navigation — Arrow up/down moves focus between cards,
  // Escape clears it, Space toggles the focused card's selection.
  // Enter intentionally NOT handled here so it stays available for form
  // submission inside ShotCard (prompt editor, etc.).
  // Typing in an input/textarea bypasses this handler so users can
  // Arrow through text.
  _useEffect(() => {
    const onKeyDown = (e) => {
      // Skip when the user is typing in any editable control,
      // UNLESS this is the Ctrl+K command palette (available everywhere).
      const tag = (e.target?.tagName || "").toUpperCase();
      const isPaletteKey = (e.key === "k" && (e.ctrlKey || e.metaKey));
      if ((tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT"
          || e.target?.isContentEditable) && !isPaletteKey) {
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
      } else if (e.key === "z" && (e.ctrlKey || e.metaKey)
                 && !e.shiftKey && focusedShotIndex !== null) {
        // R59b: Ctrl+Z on a focused card → restore its most recent
        // "Auto:" snapshot (the one auto-captured before the last
        // destructive batch op from R46a).
        e.preventDefault();
        const focusedShot = filteredShots[focusedShotIndex];
        if (focusedShot) undoLastAutoSnapshot(focusedShot);
      } else if (e.key === "?" || (e.key === "/" && e.shiftKey)) {
        // R66a: '?' toggles the keyboard-shortcuts cheatsheet
        e.preventDefault();
        setShowShortcuts(v => !v);
      } else if (e.key === "k" && (e.ctrlKey || e.metaKey)) {
        // R76a: Ctrl+K / Cmd+K opens the command palette
        e.preventDefault();
        setCommandPaletteOpen();
      } else if (e.key === "f" && !e.ctrlKey && !e.metaKey && !e.shiftKey) {
        // R77b: F toggles focus mode (when no other modifier)
        e.preventDefault();
        setFocusMode(v => !v);
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

  // R60a: restore flow is now two-step — first fetch a non-mutating
  // preview of what would change, show the user, then apply on confirm.
  // `restoreSnapshot` opens the preview; `confirmSnapshotRestore` applies.
  const restoreSnapshot = async (id, snapId) => {
    try {
      const diff = await api.get(`/api/video/shots/${id}/snapshot/${snapId}/preview`);
      if (diff && Array.isArray(diff.changes)) {
        // No changes? skip the modal, just tell the user.
        if (diff.changes.length === 0) {
          addToast(`Snapshot "${diff.snap_label}" already matches current state`,
                   "info");
          return;
        }
        setRestorePreview(diff);
      } else if (diff && diff.error) {
        addToast(`Preview failed: ${diff.error}`, "error");
      } else {
        addToast("Preview failed: unknown response", "error");
      }
    } catch (e) {
      addToast("Preview failed: " + (e.message || "unknown"), "error");
    }
  };

  const confirmSnapshotRestore = async () => {
    if (!restorePreview) return;
    const { shot_id, snap_id, snap_label } = restorePreview;
    setRestorePreview(null);
    try {
      const res = await api.post(
        `/api/video/shots/${shot_id}/snapshot/${snap_id}/restore`, {});
      if (res && res.restored) {
        addToast(`Restored "${snap_label}"`, "success");
      } else {
        addToast(res?.error || "Could not restore (shot may be locked)", "error");
      }
      await refresh();
    } catch (e) {
      addToast("Restore failed: " + (e.message || "unknown"), "error");
    }
  };

  // R59b: Ctrl+Z shortcut — restore the most recent auto-snapshot for
  // `shot` (the one captured before the last destructive batch op).
  // Does nothing if there's no Auto: snapshot on this shot. The
  // snapshot is NOT deleted after restore — the user can still undo
  // the undo by hitting Restore on it manually.
  const undoLastAutoSnapshot = async (shot) => {
    const autos = (shot.snapshots || []).filter(s =>
      (s.label || "").startsWith("Auto:"));
    if (autos.length === 0) {
      addToast("No auto-snapshot to undo — nothing destructive has run on this shot",
               "info");
      return;
    }
    // Newest Auto: snapshot (they're appended in order, newest last)
    const latest = autos[autos.length - 1];
    try {
      const res = await api.post(
        `/api/video/shots/${shot.id}/snapshot/${latest.id}/restore`, {});
      if (res && res.restored) {
        addToast(`Undid "${latest.label}"`, "success");
      } else {
        addToast(res?.error || "Undo failed (shot may be locked)", "error");
      }
      await refresh();
    } catch (e) {
      addToast("Undo failed: " + (e.message || "unknown"), "error");
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
  // R49b: auto-opens the Antenna admin modal if no antenna is paired.
  const sendToResolve = async () => {
    const readyCount = shots.filter(s => s.status === "ready" && s.video_path).length;
    if (readyCount === 0) {
      addToast("No ready shots to send — render something first", "error");
      return;
    }
    // Check pairing first
    try {
      const st = await api.get("/api/antenna/status");
      setAntennaStatus(st);
      if (!st.has_token || !(st.paired_url || st.heartbeat_url)) {
        setShowAntennaAdmin(true);
        if (st.heartbeat_url) setAntennaPairUrl(st.heartbeat_url);
        addToast("No antenna paired — enter credentials once, then retry", "info");
        return;
      }
    } catch (_) { /* fall through to attempt */ }

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

  // R49b: Antenna admin helpers. R52: also refreshes the multi-antenna list.
  // R56: trigger a service start on the paired antenna.
  const startServiceOnAntenna = async (service) => {
    setServiceStartBusy(prev => ({ ...prev, [service]: true }));
    addToast(`Starting ${service} on antenna…`, "info");
    try {
      const res = await api.post("/api/antenna/service/start", { service });
      const ar = res && res.antenna_response;
      if (ar && (ar.state === "started" || ar.state === "already_running")) {
        addToast(`${service}: ${ar.state.replace("_", " ")} `
                 + `(${ar.strategy || "—"}, ${ar.waited_seconds ?? 0}s)`,
                 "success");
        // Trigger an immediate /api/features poll to refresh the UI
        try {
          const r = await api.get("/api/features?refresh=1");
          const m = {};
          for (const row of (r.satisfied || [])) m[row.key] = row;
          setFeatureMap(m);
          setFeatureReport(r);
        } catch (_) {}
      } else if (ar && ar.state === "not_installed") {
        addToast(`${service}: not installed on the antenna host`, "error");
      } else if (ar && ar.state === "timeout") {
        addToast(`${service}: launched but didn't become reachable in ${ar.waited_seconds}s`,
                 "error");
      } else if (ar && ar.error) {
        addToast(`${service}: ${ar.error}`, "error");
      } else {
        addToast(`${service}: unexpected response (check console)`, "error");
        console.warn("[service-start]", res);
      }
    } catch (e) {
      addToast(`${service} start failed: ${e.message || "unknown"}`, "error");
    } finally {
      setServiceStartBusy(prev => ({ ...prev, [service]: false }));
    }
  };

  const refreshAntennaStatus = async () => {
    try {
      const st = await api.get("/api/antenna/status");
      setAntennaStatus(st);
      if (!antennaPairUrl && st.heartbeat_url) setAntennaPairUrl(st.heartbeat_url);
    } catch (e) { /* ignore */ }
    try {
      const list = await api.get("/api/antennas");
      setAntennaList(Array.isArray(list?.antennas) ? list.antennas : []);
    } catch (e) { /* registry may not be available on older Guild */ }
  };

  const refreshFleetTelemetry = async () => {
    try {
      const res = await api.get("/api/antennas/telemetry");
      setFleetTelemetry(res);
    } catch (_) { /* older Guild or antenna offline */ }
  };

  const openAntennaAdmin = async () => {
    setShowAntennaAdmin(true);
    await refreshAntennaStatus();
    await refreshFleetTelemetry();
  };

  // R61a: while the modal is open, poll telemetry every 10s
  _useEffect(() => {
    if (!showAntennaAdmin) return;
    const id = setInterval(refreshFleetTelemetry, 10000);
    return () => clearInterval(id);
  }, [showAntennaAdmin]);

  const pairAntenna = async () => {
    if (!antennaPairUrl.trim() || !antennaPairToken.trim()) {
      addToast("Enter both URL and token", "error");
      return;
    }
    setAntennaBusy(true);
    try {
      const res = await api.post("/api/antenna/pair",
                                 { url: antennaPairUrl.trim(), token: antennaPairToken.trim() });
      if (res && res.ok) {
        addToast("Antenna paired — token saved", "success");
        setAntennaPairToken("");
        await refreshAntennaStatus();
      } else {
        addToast(`Pair failed: ${res && res.error ? res.error : "unknown"}`, "error");
      }
    } catch (e) {
      addToast(`Pair failed: ${e.message || "unknown"}`, "error");
    } finally {
      setAntennaBusy(false);
    }
  };

  // R50a: Guild self-update (hits the same updater the launcher uses,
  // then re-execs the server process)
  const selfUpdateGuild = async () => {
    setAntennaBusy(true);
    addToast("Checking Guild for updates...", "info");
    try {
      const res = await api.post("/api/guild/self-update", {});
      if (res && res.started) {
        addToast("Guild update started — page may briefly disconnect", "info");
        // After ~5s, re-check version to detect a successful restart
        setTimeout(async () => {
          try {
            await api.get("/api/guild/version");
            addToast("Guild restart complete — reload to see new code", "success");
          } catch (e) {
            // Expected 502 while exec is in flight
            addToast("Guild restart in progress — wait a few seconds and reload", "info");
          } finally {
            setAntennaBusy(false);
          }
        }, 5000);
      } else {
        addToast("Guild update not started", "error");
        setAntennaBusy(false);
      }
    } catch (e) {
      addToast(`Guild update failed: ${e.message || "unknown"}`, "error");
      setAntennaBusy(false);
    }
  };

  const selfUpdateAntenna = async () => {
    setAntennaBusy(true);
    addToast("Triggering antenna self-update...", "info");
    try {
      const res = await api.post("/api/antenna/self-update", {});
      if (res && (res.ok || res.note)) {
        addToast(`Antenna: ${res.note || "updated"}`, "success");
      } else if (res && res.error) {
        addToast(`Update failed: ${res.error}`, "error");
      } else {
        addToast("Update status: check console", "info");
        console.log("[antenna self-update]", res);
      }
      // Give the antenna a moment to restart, then refresh status
      setTimeout(() => refreshAntennaStatus(), 5000);
    } catch (e) {
      addToast(`Update failed: ${e.message || "unknown"}`, "error");
    } finally {
      setAntennaBusy(false);
    }
  };

  // R47b: pin/unpin a snapshot so it survives the 20-slot cap
  // R50b + R51a: trigger a Resolve render with a proper modal + preset dropdown.
  const [resolveRenderBusy, setResolveRenderBusy] = _useState(false);
  const [resolveRenderJob, setResolveRenderJob] = _useState(null);
  const [resolveRenderStatus, setResolveRenderStatus] = _useState(null);
  const [showRenderDialog, setShowRenderDialog] = _useState(false);
  const [renderPresets, setRenderPresets] = _useState([]);
  const [renderPresetsLoading, setRenderPresetsLoading] = _useState(false);
  const [renderPresetsError, setRenderPresetsError] = _useState("");
  const [renderPreset, setRenderPreset] = _useState("");
  const [renderTargetDir, setRenderTargetDir] = _useState("C:\\Spellcaster\\renders");
  const [renderFileName, setRenderFileName] = _useState("spellcaster_cut");

  const openRenderDialog = async () => {
    setShowRenderDialog(true);
    setRenderPresetsLoading(true);
    setRenderPresetsError("");
    try {
      const res = await api.get("/api/antenna/resolve/render-presets");
      const ar = res && res.antenna_response;
      if (ar && Array.isArray(ar.presets)) {
        setRenderPresets(ar.presets);
        if (!renderPreset && ar.presets.length > 0) {
          // Prefer H.264 Master if present, else first
          const pref = ar.presets.find(p => /h\.?264/i.test(p)) || ar.presets[0];
          setRenderPreset(pref);
        }
      } else if (ar && ar.error) {
        setRenderPresetsError(ar.error);
      } else if (res && res.error) {
        setRenderPresetsError(res.error);
      } else {
        setRenderPresetsError("Could not load presets");
      }
    } catch (e) {
      setRenderPresetsError(e.message || "unknown");
    } finally {
      setRenderPresetsLoading(false);
    }
  };

  const startRender = async () => {
    if (!renderPreset) {
      addToast("Pick a render preset", "error");
      return;
    }
    if (!renderTargetDir.trim()) {
      addToast("Target directory required", "error");
      return;
    }
    setResolveRenderBusy(true);
    setShowRenderDialog(false);
    addToast("Starting Resolve render…", "info");
    try {
      const res = await api.post("/api/antenna/resolve/render-timeline", {
        preset: renderPreset,
        target_dir: renderTargetDir.trim(),
        file_name: (renderFileName.trim() || "spellcaster_cut") + "_" + Date.now(),
      });
      const ar = res && res.antenna_response;
      if (ar && ar.ok && ar.job_id) {
        setResolveRenderJob(ar.job_id);
        addToast(`Resolve render started (job ${ar.job_id.slice(0,8)}…)`, "success");
        const tick = async () => {
          try {
            const s = await api.get(
              "/api/antenna/resolve/render-status?job_id=" + encodeURIComponent(ar.job_id));
            const sr = s && s.antenna_response;
            if (sr) {
              setResolveRenderStatus(sr);
              if (sr.status === "Complete") {
                addToast("Resolve render complete!", "success");
                setResolveRenderBusy(false);
                return;
              }
              if (sr.status === "Cancelled" || sr.status === "Failed") {
                addToast(`Resolve render ${sr.status}`, "error");
                setResolveRenderBusy(false);
                return;
              }
            }
            setTimeout(tick, 2000);
          } catch (_) {
            setTimeout(tick, 4000);
          }
        };
        setTimeout(tick, 2000);
      } else {
        const err = (ar && ar.error) || (res && res.error) || "unknown";
        addToast(`Resolve render failed: ${err}`, "error");
        if (ar && Array.isArray(ar.available_presets)) {
          setRenderPresets(ar.available_presets);
          setShowRenderDialog(true);
          addToast("Pick one of the available presets", "info");
        }
        setResolveRenderBusy(false);
      }
    } catch (e) {
      addToast(`Resolve render failed: ${e.message || "unknown"}`, "error");
      setResolveRenderBusy(false);
    }
  };

  // R51b: listen for antenna.resolve.render_complete events via SSE so the UI
  // reacts even if the user closed the tab mid-render.
  _useEffect(() => {
    const src = new EventSource("/api/events/sse?topic=antenna.resolve.render_complete");
    src.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data || "{}");
        const d = data.data || data;
        const status = d.status || "Unknown";
        if (status === "Complete") {
          addToast(`Resolve render complete (${d.time_elapsed_s?.toFixed?.(1) || "?"}s)`,
                    "success");
          // Fire a browser notification if permission granted
          try {
            if (typeof Notification !== "undefined" && Notification.permission === "granted") {
              new Notification("Spellcaster: Resolve render complete", {
                body: d.project ? `Project: ${d.project}` : "Render finished",
              });
            }
          } catch (_) {}
        } else {
          addToast(`Resolve render ${status}`, "error");
        }
        setResolveRenderBusy(false);
      } catch (_) { /* ignore malformed */ }
    };
    src.onerror = () => { /* transient — browser retries automatically */ };
    return () => { try { src.close(); } catch (_) {} };
  }, []);

  // R52: poll /api/antennas every 15s so the header chip reflects the live
  // state without opening the modal. Cheap endpoint (in-memory snapshot).
  _useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const list = await api.get("/api/antennas");
        if (!cancelled) setAntennaList(Array.isArray(list?.antennas) ? list.antennas : []);
      } catch (_) { /* older Guild: no endpoint */ }
    };
    poll();
    const id = setInterval(poll, 15000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  // R60b: poll /api/video/queue-cost every 20s. Lightweight — the
  // backend response is <1KB and we use it to render the header chip.
  _useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const res = await api.get("/api/video/queue-cost");
        if (!cancelled) setQueueCost(res);
      } catch (_) { /* older Guild: no endpoint */ }
    };
    poll();
    const id = setInterval(poll, 20000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  // R54: poll /api/features every 30s so capability-gated buttons
  // (→ Resolve, Render, Klein, …) appear/disappear as antennas come
  // and go. R55b also retains the unsatisfied list for the diag panel.
  _useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const res = await api.get("/api/features");
        if (cancelled) return;
        const m = {};
        for (const row of (res.satisfied || [])) m[row.key] = row;
        setFeatureMap(m);
        setFeatureReport(res);
      } catch (_) { /* older Guild: no endpoint → leave map empty, features hide */ }
    };
    poll();
    const id = setInterval(poll, 30000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  // Ask for notification permission on first load so render_complete can surface
  _useEffect(() => {
    try {
      if (typeof Notification !== "undefined"
          && Notification.permission === "default") {
        // Non-blocking request
        Notification.requestPermission().catch(() => {});
      }
    } catch (_) {}
  }, []);

  const renderInResolve = openRenderDialog;

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

  // R69a: named board states — save/load/delete whole-board snapshots
  const [namedStates, setNamedStates] = _useState([]);
  const [showStatesPanel, setShowStatesPanel] = _useState(false);

  const refreshNamedStates = _useCallback(async () => {
    try {
      const res = await api.get("/api/video/named-states");
      setNamedStates(res?.states || []);
    } catch (_) {}
  }, []);

  _useEffect(() => { if (showStatesPanel) refreshNamedStates(); },
             [showStatesPanel, refreshNamedStates]);

  const saveNamedState = async () => {
    const name = window.prompt("Name this board state:", "");
    if (!name) return;
    try {
      const res = await api.post("/api/video/named-states", {name});
      if (res?.status === "ok") {
        addToast(`Saved state "${name}" (${res.shot_count} shots, ${res.scene_count} scenes)`,
                 "success");
        await refreshNamedStates();
      } else {
        addToast(`Save failed: ${res?.message || "unknown"}`, "error");
      }
    } catch (e) {
      addToast("Save failed: " + (e.message || "unknown"), "error");
    }
  };

  const loadNamedState = async (name, merge = false) => {
    const ok = window.confirm(
      merge
        ? `Merge "${name}" into the current board?`
        : `REPLACE the current board with "${name}"? Current shots will be discarded.`);
    if (!ok) return;
    try {
      const res = await api.post(`/api/video/named-states/${encodeURIComponent(name)}/load`,
                                   {merge});
      if (res?.status === "ok") {
        addToast(`Loaded "${name}" — ${res.loaded_shots} shots, ${res.loaded_scenes} scenes`,
                 "success");
        await refresh();
      } else {
        addToast(`Load failed: ${res?.message || "unknown"}`, "error");
      }
    } catch (e) {
      addToast("Load failed: " + (e.message || "unknown"), "error");
    }
  };

  const deleteNamedState = async (name) => {
    if (!window.confirm(`Delete saved state "${name}"?`)) return;
    try {
      await api.delete(`/api/video/named-states/${encodeURIComponent(name)}`);
      addToast(`Deleted "${name}"`, "success");
      await refreshNamedStates();
    } catch (e) {
      addToast("Delete failed: " + (e.message || "unknown"), "error");
    }
  };

  // R71a: archive/unarchive one shot
  const toggleArchiveShot = async (shot) => {
    const endpoint = shot.archived
      ? `/api/video/shots/${shot.id}/unarchive`
      : `/api/video/shots/${shot.id}/archive`;
    try {
      const res = await api.post(endpoint, {});
      if (res && (res.archived !== undefined || res.shot_id)) {
        addToast(shot.archived ? "Restored from archive" : "Archived",
                 "success");
        await refresh();
      } else {
        addToast(`Archive failed: ${res?.error || "unknown"}`, "error");
      }
    } catch (e) {
      addToast("Archive failed: " + (e.message || "unknown"), "error");
    }
  };

  // R71b: project metadata — edit in a small modal
  const [showProjectMeta, setShowProjectMeta] = _useState(false);
  const [projectMeta, setProjectMeta] = _useState({});
  const loadProjectMeta = _useCallback(async () => {
    try {
      const pm = await api.get("/api/video/project-meta");
      setProjectMeta(pm || {});
    } catch (_) {}
  }, []);
  _useEffect(() => { loadProjectMeta(); }, [loadProjectMeta]);
  const saveProjectMeta = async () => {
    try {
      const pm = await api.post("/api/video/project-meta", projectMeta);
      setProjectMeta(pm || {});
      addToast("Project metadata saved", "success");
      setShowProjectMeta(false);
    } catch (e) {
      addToast("Save failed: " + (e.message || "unknown"), "error");
    }
  };

  // R72a: create a variation from the given shot
  const makeVariation = async (shotId, label = "") => {
    try {
      const res = await api.post(`/api/video/shots/${shotId}/variation`, {label});
      if (res && res.shot) {
        addToast(`Created variation "${res.shot.title}"`, "success");
        await refresh();
      } else {
        addToast(`Variation failed: ${res?.error || "unknown"}`, "error");
      }
    } catch (e) {
      addToast("Variation failed: " + (e.message || "unknown"), "error");
    }
  };

  const promoteVariation = async (shotId) => {
    try {
      await api.post(`/api/video/shots/${shotId}/promote-variation`, {});
      addToast("Promoted to primary variation", "success");
      await refresh();
    } catch (e) {
      addToast("Promote failed: " + (e.message || "unknown"), "error");
    }
  };

  // R72b: activity log panel
  const [showActivityLog, setShowActivityLog] = _useState(false);
  const [activityEntries, setActivityEntries] = _useState([]);
  const refreshActivityLog = _useCallback(async () => {
    try {
      const res = await api.get("/api/video/activity-log?limit=200");
      setActivityEntries((res?.entries || []).slice().reverse());
    } catch (_) {}
  }, []);
  _useEffect(() => { if (showActivityLog) refreshActivityLog(); },
              [showActivityLog, refreshActivityLog]);

  // R76a: command palette — opens with Ctrl+K, fuzzy-filters actions
  const setCommandPaletteOpen = () => {
    setCommandQuery("");
    setCommandSelectedIdx(0);
    setShowCommandPalette(true);
  };

  // The list of commands available to the palette. Each entry:
  //   {label, group, run, when?}  — when=() => bool gates visibility.
  const commandPaletteActions = _useMemo(() => [
    // Board-level
    {label: "Import CSV…", group: "Import/Export",
      run: () => importCsvRef.current?.click()},
    {label: "Export CSV (shotboard)", group: "Import/Export",
      run: () => { window.location.href = "/api/video/shotboard.csv"; }},
    {label: "Export CSV (render history)", group: "Import/Export",
      run: () => { window.location.href = "/api/video/render-history.csv"; }},
    {label: "Export Outline.txt", group: "Import/Export",
      run: () => { window.location.href = "/api/video/outline.txt"; }},
    {label: "Export EDL", group: "Import/Export",
      run: () => { window.location.href = "/api/video/export/edl?fps=30"; }},
    {label: "Export FCPXML", group: "Import/Export",
      run: () => { window.location.href = "/api/video/export/fcpxml?fps=30"; }},
    {label: "Auto-group scenes", group: "Scenes",
      run: autoGroupScenes},
    // Panels
    {label: "Toggle outline panel", group: "View",
      run: () => setShowOutline(v => !v)},
    {label: "Toggle board-stats panel", group: "View",
      run: () => setShowBoardStats(v => !v)},
    {label: "Toggle near-duplicates panel", group: "View",
      run: () => setShowNearDupes(v => !v)},
    {label: "Toggle activity log", group: "View",
      run: () => setShowActivityLog(v => !v)},
    {label: "Toggle named-states panel", group: "View",
      run: () => setShowStatesPanel(v => !v)},
    {label: "Open Project metadata…", group: "View",
      run: () => { loadProjectMeta(); setShowProjectMeta(true); }},
    {label: "Open Antenna admin…", group: "View",
      run: openAntennaAdmin},
    {label: "Show keyboard shortcuts", group: "View",
      run: () => setShowShortcuts(true)},
    {label: "Toggle focus mode", group: "View",
      run: () => setFocusMode(v => !v)},
    // Queue
    {label: "Pause render queue", group: "Queue",
      when: () => !queuePaused, run: togglePause},
    {label: "Resume render queue", group: "Queue",
      when: () => queuePaused, run: togglePause},
    {label: "Render next (step queue)", group: "Queue",
      run: renderNext},
    {label: "Render all drafts", group: "Queue",
      run: renderAll},
    {label: "Reset failed shots", group: "Queue",
      run: resetFailed},
    // Selection-aware
    {label: "Batch: Randomize seeds of selected", group: "Bulk",
      when: () => selected.size > 0, run: batchRandomizeSeeds},
    {label: "Batch: Lock selected", group: "Bulk",
      when: () => selected.size > 0, run: () => batchLock(true)},
    {label: "Batch: Unlock selected", group: "Bulk",
      when: () => selected.size > 0, run: () => batchLock(false)},
    {label: "Batch: Archive selected", group: "Bulk",
      when: () => selected.size > 0,
      run: async () => {
        try {
          await api.post("/api/video/batch-archive",
                         {shot_ids: Array.from(selected), archive: true});
          addToast(`Archived ${selected.size} shot(s)`, "success");
          await refresh();
        } catch (e) { addToast("Batch archive failed", "error"); }
      }},
    {label: "Lock all ready shots", group: "Bulk",
      run: () => batchLockByStatus(["ready"])},
    // Filter shortcuts
    {label: "Filter: All", group: "Filter", run: () => setStatusFilter("all")},
    {label: "Filter: Draft", group: "Filter", run: () => setStatusFilter("draft")},
    {label: "Filter: Ready", group: "Filter", run: () => setStatusFilter("ready")},
    {label: "Filter: Failed", group: "Filter", run: () => setStatusFilter("failed")},
    {label: "Filter: Stale", group: "Filter", run: () => setStatusFilter("stale")},
    {label: "Filter: Starred", group: "Filter", run: () => setStatusFilter("starred")},
    {label: "Filter: Archived", group: "Filter", run: () => setStatusFilter("archived")},
    // New shot
    {label: "New shot", group: "Create", run: addShot},
    {label: "Save named state…", group: "Create", run: saveNamedState},
  ].filter(a => !a.when || a.when()), [
    selected, queuePaused, importCsvRef,
  ]);

  const filteredCommands = _useMemo(() => {
    const q = commandQuery.toLowerCase().trim();
    if (!q) return commandPaletteActions;
    // Simple substring-on-label + group match for fuzziness.
    return commandPaletteActions.filter(a =>
      a.label.toLowerCase().includes(q) ||
      a.group.toLowerCase().includes(q));
  }, [commandQuery, commandPaletteActions]);

  const runCommand = (cmd) => {
    setShowCommandPalette(false);
    setCommandQuery("");
    setTimeout(() => { try { cmd.run(); } catch (e) { console.error(e); } }, 0);
  };

  // R70a: jump to a shot by id (scroll its card into view + focus it)
  const jumpToShot = _useCallback((shotId) => {
    const idx = filteredShots.findIndex(s => s.id === shotId);
    if (idx >= 0) {
      setFocusedShotIndex(idx);
      setTimeout(() => {
        const card = document.querySelector(`[data-shot-id="${shotId}"]`);
        if (card) card.scrollIntoView({block: "center", behavior: "smooth"});
      }, 50);
    }
  }, [filteredShots]);

  // R70b: lock every shot whose status is in statusSet (e.g. all ready)
  // so accidental edits don't happen after approval.
  const batchLockByStatus = async (statusSet) => {
    const ids = shots.filter(s => statusSet.includes(s.status) && !s.locked)
                     .map(s => s.id);
    if (ids.length === 0) {
      addToast(`No unlocked shots matching ${statusSet.join(", ")}`, "info");
      return;
    }
    try {
      await api.post("/api/video/batch-lock", {shot_ids: ids, lock: true});
      addToast(`Locked ${ids.length} shot(s) with status in ${statusSet.join(", ")}`,
               "success");
      await refresh();
    } catch (e) {
      addToast("Batch-lock failed: " + (e.message || "unknown"), "error");
    }
  };

  // R79b: paste-to-shots — paste multi-line text to create many shots
  const [showPasteShots, setShowPasteShots] = _useState(false);
  const [pasteShotsText, setPasteShotsText] = _useState("");
  const pasteShots = async () => {
    if (!pasteShotsText.trim()) return;
    try {
      const res = await api.post("/api/video/import-lines",
                                  {text: pasteShotsText});
      if (res?.created != null) {
        addToast(
          `Created ${res.created} shot(s)`
          + (res.scenes_created ? ` + ${res.scenes_created} scene(s)` : "")
          + (res.skipped ? ` (${res.skipped} skipped)` : ""),
          res.created > 0 ? "success" : "info");
        setShowPasteShots(false);
        setPasteShotsText("");
        await refresh();
      } else {
        addToast(`Paste failed: ${res?.error || "unknown"}`, "error");
      }
    } catch (e) {
      addToast("Paste failed: " + (e.message || "unknown"), "error");
    }
  };

  // R79a: diff two named states
  const [diffModal, setDiffModal] = _useState(null);  // {a, b, result}
  const [diffSelection, setDiffSelection] = _useState({a: "", b: "current"});
  const runStateDiff = async () => {
    const {a, b} = diffSelection;
    if (!a || !b) {
      addToast("Pick two states to diff", "error");
      return;
    }
    try {
      const res = await api.post("/api/video/named-states/diff", {a, b});
      setDiffModal({a, b, result: res});
    } catch (e) {
      addToast("Diff failed: " + (e.message || "unknown"), "error");
    }
  };

  // R67a: bulk-import shots from a CSV file. Triggered by a hidden file
  // input; the button click opens the picker.
  const importCsvRef = _useRef(null);
  const handleCsvFile = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = "";  // allow picking the same file again later
    try {
      const csv = await file.text();
      const res = await api.post("/api/video/import-csv", {csv});
      if (res && res.created != null) {
        addToast(`Imported ${res.created} shot(s) from ${file.name}`
                 + (res.errors?.length ? ` (${res.errors.length} rows skipped)` : ""),
                 res.created > 0 ? "success" : "error");
        if (res.errors?.length) {
          console.warn("[CSV import errors]", res.errors);
        }
        await refresh();
      } else {
        addToast(`Import failed: ${res?.error || "unknown"}`, "error");
      }
    } catch (err) {
      addToast("CSV import failed: " + (err.message || "unknown"), "error");
    }
  };

  // R67b: auto-group shots into scenes by title prefix
  const autoGroupScenes = async () => {
    try {
      const res = await api.post("/api/video/auto-group-scenes", {assign: true});
      if (res && res.clusters_found != null) {
        addToast(
          `Auto-grouped ${res.shots_assigned} shot(s) into `
          + `${res.scenes_created + res.clusters_found - res.scenes_created} scene(s) `
          + `(${res.scenes_created} new)`,
          res.clusters_found > 0 ? "success" : "info");
        await refresh();
      }
    } catch (e) {
      addToast("Auto-group failed: " + (e.message || "unknown"), "error");
    }
  };

  // R62b: "Select all in scene X" populates the selection set from
  // scene membership. Every existing batch op (lock, color, priority,
  // preset, prompt edit, revert, duplicate, delete) then applies to the
  // whole scene without any per-op scene plumbing.
  const selectSceneShots = (sceneId, additive = false) => {
    const ids = shots.filter(s => s.scene_id === sceneId).map(s => s.id);
    if (ids.length === 0) {
      addToast("Scene has no shots yet", "info");
      return;
    }
    setSelected(prev => {
      const next = new Set(additive ? prev : []);
      ids.forEach(id => next.add(id));
      return next;
    });
    const scene = scenes.find(sc => sc.id === sceneId);
    addToast(`Selected ${ids.length} shot(s) from "${scene?.name || sceneId}"`,
             "info");
  };

  // R66b: bulk search/replace across selected shots' prompts.
  // Unlike batch_prompt_edit (prepend/append), this replaces ALL
  // occurrences of `find` with `replaceWith` inside each prompt.
  const batchSearchReplace = async () => {
    if (selected.size === 0 || !searchReplaceFind) return;
    let changed = 0;
    const flags = searchReplaceCase ? "g" : "gi";
    // Escape regex special chars — we're doing literal replacement
    const escaped = searchReplaceFind.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const re = new RegExp(escaped, flags);
    for (const id of selected) {
      const shot = shots.find(s => s.id === id);
      if (!shot || shot.locked) continue;
      const newPrompt = (shot.prompt || "").replace(re, searchReplaceWith);
      if (newPrompt !== shot.prompt) {
        try {
          await api.post(`/api/video/shots/${id}`, {prompt: newPrompt});
          changed++;
        } catch (_) { /* skip failures, keep going */ }
      }
    }
    addToast(`Search/replace: updated ${changed} shot(s)`,
             changed > 0 ? "success" : "info");
    setShowSearchReplace(false);
    await refresh();
  };

  // R64a: assign fresh random seeds to every selected shot
  const batchRandomizeSeeds = async () => {
    if (selected.size === 0) return;
    try {
      const res = await api.post("/api/video/batch-randomize-seeds", {
        shot_ids: Array.from(selected),
      });
      if (res && res.changed != null) {
        addToast(`Randomized seed on ${res.changed} shot(s)`,
                 res.changed > 0 ? "success" : "info");
      }
      await refresh();
    } catch (e) {
      addToast("Batch randomize failed: " + (e.message || "unknown"), "error");
    }
  };

  // R61b: set priority on all selected shots
  const batchPriority = async (priority) => {
    if (selected.size === 0) return;
    try {
      const res = await api.post("/api/video/batch-priority", {
        shot_ids: Array.from(selected),
        priority,
      });
      if (res && res.changed != null) {
        addToast(`Set priority="${priority}" on ${res.changed} shot(s)`,
                 res.changed > 0 ? "success" : "info");
      }
      await refresh();
    } catch (e) {
      addToast("Batch priority failed: " + (e.message || "unknown"), "error");
    }
  };

  // R45b: clone each selected shot N times. Each copy gets a fresh id,
  // status='draft', empty render_history + snapshots, and a versioned
  // title ("Hero" → "Hero v2", "Hero v3", ...).
  // R75a: track the fresh-seeds checkbox for the batch duplicate panel
  const [batchDupeFreshSeeds, setBatchDupeFreshSeeds] = _useState(false);

  const batchDuplicate = async () => {
    if (selected.size === 0) return;
    const count = Math.max(1, Math.min(50, parseInt(batchDupeCount) || 1));
    try {
      const res = await api.post("/api/video/batch-duplicate", {
        shot_ids: Array.from(selected),
        count: count,
        title_suffix_mode: "counter",
        fresh_seeds: batchDupeFreshSeeds,
      });
      addToast(
        `Duplicated ${selected.size} shot(s) × ${count} = ${res.created} new`
          + (batchDupeFreshSeeds ? " (with fresh seeds)" : ""),
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

  // R59a: release exactly one queued shot then auto-pause again.
  // Useful for iterative review: render, inspect, render, inspect...
  const renderNext = async () => {
    try {
      const res = await api.post("/api/video/queue/next", {});
      if (res && res.status === "stepping") {
        addToast("Stepping queue — will pause after next render", "info");
        // Queue is now running; reflect that until the auto-pause fires
        setQueuePaused(false);
      } else if (res && res.status === "nothing_to_step") {
        addToast("Nothing to render — queue is empty", "info");
      } else {
        addToast("Render-next: unexpected response", "error");
      }
    } catch (e) {
      addToast("Render-next failed: " + (e.message || "unknown"), "error");
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
    <div className={"space-y-4 " + (focusMode ? "focus-mode" : "")}>
      {/* R77b: focus-mode toggle (floats top-right, always visible) */}
      <button
        onClick={() => setFocusMode(v => !v)}
        className={"focus-mode-toggle fixed top-3 right-3 z-40 px-2 py-1 rounded text-[10px] font-medium "
          + (focusMode ? "bg-amber-600 text-white" : "bg-slate-800/80 hover:bg-slate-700 text-slate-400")}
        title={focusMode ? "Exit focus mode" : "Enter focus mode (hide toolbars for distraction-free review)"}
      >{focusMode ? "◯ Exit focus" : "◐ Focus"}</button>
      {/* Error banner */}
      {error && (
        <div className="error-banner bg-red-500/10 border border-red-500/30 rounded-xl px-4 py-3 text-sm text-red-400 flex items-center gap-2">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0zM12 9v4M12 17h.01" /></svg>
          {error}
          <button onClick={() => setError("")} className="ml-auto text-red-500 hover:text-red-300">&times;</button>
        </div>
      )}

      {/* Header with health + buttons — hidden in focus mode */}
      <div className={"flex items-center justify-between " + (focusMode ? "hidden" : "")}>
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
            <button onClick={renderNext}
              className="queue-next-btn flex items-center gap-1 bg-sky-700/30 hover:bg-sky-700/50 text-sky-300 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors"
              title="Render one shot then pause (step-through mode for iterative review)"
            >⏭ Next
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
          <input type="file" accept=".csv,text/csv"
            ref={importCsvRef} onChange={handleCsvFile}
            className="hidden" />
          <button onClick={() => importCsvRef.current?.click()}
            className="import-csv-btn flex items-center gap-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 px-3 py-2 rounded-lg text-xs font-medium transition-colors"
            title="Bulk-import shots from a CSV (prompt required; title/preset/seed/etc optional)">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"/></svg>
            Import CSV
          </button>
          <a href="/api/video/shotboard.csv" download
            className="export-shotboard-csv flex items-center gap-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 px-3 py-2 rounded-lg text-xs font-medium transition-colors"
            title="Export current board as CSV (round-trips with Import CSV for spreadsheet edits)">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
            Export CSV
          </a>
          <button onClick={() => setShowStatesPanel(v => !v)}
            className="states-toggle-btn flex items-center gap-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 px-3 py-2 rounded-lg text-xs font-medium transition-colors"
            title="Save and restore named board states (alternate storyboards)">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>
            States
          </button>
          <button onClick={() => setShowOutline(v => !v)}
            className="outline-toggle-btn flex items-center gap-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 px-3 py-2 rounded-lg text-xs font-medium transition-colors"
            title="Outline nav — jump to any shot/scene">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>
            Outline
          </button>
          <button onClick={() => { loadProjectMeta(); setShowProjectMeta(true); }}
            className="project-meta-btn flex items-center gap-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 px-3 py-2 rounded-lg text-xs font-medium transition-colors"
            title="Project metadata (title, author, synopsis…) — appears in EDL/FCPXML exports">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 2l10 6v8l-10 6-10-6V8z"/><path d="M12 12l10-6M12 12l-10-6M12 12v10"/></svg>
            {projectMeta.title ? projectMeta.title.slice(0, 18) : "Project"}
          </button>
          <button onClick={() => setShowActivityLog(v => !v)}
            className="activity-log-btn flex items-center gap-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 px-3 py-2 rounded-lg text-xs font-medium transition-colors"
            title="Activity log — who did what, when">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
            Activity
          </button>
          <button onClick={() => setShowNearDupes(v => !v)}
            className="near-dupes-btn flex items-center gap-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 px-3 py-2 rounded-lg text-xs font-medium transition-colors"
            title="Find shots with similar (but not identical) prompts">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/></svg>
            Dupes
          </button>
          <a href="/api/video/outline.txt" download
            className="export-outline flex items-center gap-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 px-3 py-2 rounded-lg text-xs font-medium transition-colors"
            title="Export board as a human-readable outline (for sharing with non-technical team members)">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>
            Outline.txt
          </a>
          <a href="/api/video/render-history.csv" download
            className="export-csv flex items-center gap-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 px-3 py-2 rounded-lg text-xs font-medium transition-colors"
            title="Download flat CSV of every render attempt across all shots (for analysis / sharing)">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="8" y1="13" x2="16" y2="13"/><line x1="8" y1="17" x2="16" y2="17"/></svg>
            CSV
          </a>
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
          {/* R54: only render Resolve-dependent buttons when the capability
              resolves on at least one online antenna. Host hint shows which
              machine will handle the request. */}
          {featureMap["video.send_to_resolve"] && (
            <button onClick={sendToResolve}
              className="send-to-resolve flex items-center gap-1.5 bg-pink-900/40 hover:bg-pink-700/50 text-pink-200 hover:text-pink-100 px-3 py-2 rounded-lg text-xs font-medium transition-colors"
              title={`Build timeline directly in DaVinci Resolve via antenna${featureMap["video.send_to_resolve"].host ? " (on " + featureMap["video.send_to_resolve"].host + ")" : ""}`}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
              → Resolve
            </button>
          )}
          {featureMap["video.render_in_resolve"] && (
            <button onClick={renderInResolve}
              disabled={resolveRenderBusy}
              className="render-in-resolve flex items-center gap-1.5 bg-rose-900/40 hover:bg-rose-700/50 text-rose-200 hover:text-rose-100 px-3 py-2 rounded-lg text-xs font-medium transition-colors disabled:bg-slate-700 disabled:text-slate-500"
              title={`Render the current Resolve timeline via antenna${featureMap["video.render_in_resolve"].host ? " (on " + featureMap["video.render_in_resolve"].host + ")" : ""}`}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3"/></svg>
              {resolveRenderBusy && resolveRenderStatus && resolveRenderStatus.completion_percent != null
                ? `Rendering ${resolveRenderStatus.completion_percent}%`
                : (resolveRenderBusy ? "Rendering…" : "Render")}
            </button>
          )}
          {(() => {
            // R52: Antenna button shows hostnames instead of the generic "Antenna".
            // - 0 online : "No antenna" (greyed, tooltip hints to pair)
            // - 1 online : "📡 <hostname>"  (parabola + actual machine name)
            // - >1 online: "📡 <host-a> +N" (host-a is lex-first, +N says more)
            const online = antennaList.filter(a => a.online);
            const onlineCount = online.length;
            let label, tooltipLines;
            if (onlineCount === 0) {
              label = "No antenna";
              tooltipLines = ["No antennas online — click to pair one."];
            } else if (onlineCount === 1) {
              label = online[0].hostname || "antenna";
              tooltipLines = [
                `${label}: ${online[0].services.join(", ") || "(no services declared)"}`,
                `Click for pair + self-update.`,
              ];
            } else {
              label = `${online[0].hostname} +${onlineCount - 1}`;
              tooltipLines = [
                `${onlineCount} antennas online:`,
                ...online.map(a =>
                  `  • ${a.hostname} — ${a.services.join(", ") || "(none)"}`),
              ];
            }
            const dim = onlineCount === 0;
            return (
              <button
                onClick={openAntennaAdmin}
                className={`antenna-admin-btn flex items-center gap-1.5 ${dim ? "bg-slate-800 text-slate-500" : "bg-slate-800 hover:bg-indigo-700/50 text-slate-300 hover:text-indigo-100"} px-3 py-2 rounded-lg text-xs font-medium transition-colors`}
                title={tooltipLines.join("\n")}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M5 12a7 7 0 0 1 14 0"/><path d="M8.5 12a3.5 3.5 0 0 1 7 0"/>
                  <circle cx="12" cy="12" r="1"/><path d="M12 18v4"/>
                </svg>
                <span className="antenna-btn-label">{label}</span>
                {onlineCount > 0 && <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>}
              </button>
            );
          })()}
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

      {/* Status summary + filter — hidden in focus mode */}
      <div className={"flex items-center justify-between " + (focusMode ? "hidden" : "")}>
        <div className="flex items-center gap-4">
          <StatusSummary shots={shots} />
          <span className="total-duration text-xs text-slate-500 font-mono">
            {shots.length} shots &middot; ~{shots.reduce((sum, s) => sum + (s.duration_s || 0), 0).toFixed(1)}s total
          </span>
        </div>
        <ShotSummary shots={shots} />
        <div className="flex gap-1.5 flex-wrap">
          {allTags.length > 0 && (
            <select
              className="tag-filter-select bg-slate-800 border border-slate-600 text-slate-300 text-xs rounded px-2 py-1 self-center"
              value={tagFilter}
              onChange={(e) => setTagFilter(e.target.value)}
              title="Filter to shots carrying this tag"
            >
              <option value="">All tags</option>
              {allTags.map(({tag, count}) => (
                <option key={tag} value={tag}>#{tag} ({count})</option>
              ))}
            </select>
          )}
          {/* R77a: sort-order selector */}
          <select
            className="sort-mode-select bg-slate-800 border border-slate-600 text-slate-300 text-xs rounded px-2 py-1 self-center"
            value={sortMode}
            onChange={(e) => setSortMode(e.target.value)}
            title="Change sort order (doesn't change render order — only display)"
          >
            <option value="board">Sort: board order</option>
            <option value="rating">Sort: rating ↓</option>
            <option value="duration">Sort: render time ↓</option>
            <option value="last_rendered">Sort: last rendered ↓</option>
            <option value="recent_edit">Sort: recently edited ↓</option>
          </select>
          {["all", "draft", "queued", "running", "ready", "failed", "stale", "starred", "rated", "archived"].map(status => {
            const count = status === "stale" ? shots.filter(s => !s.archived && isShotStale(s)).length
                        : status === "starred" ? shots.filter(s => !s.archived && s.bookmarked).length
                        : status === "rated" ? shots.filter(s => !s.archived && (s.rating || 0) > 0).length
                        : status === "archived" ? shots.filter(s => s.archived).length
                        : null;
            const extraClass =
              status === "stale"    ? "bg-amber-900/30 hover:bg-amber-800/40 text-amber-300"
              : status === "starred" ? "bg-yellow-900/30 hover:bg-yellow-800/40 text-yellow-300"
              : status === "rated"   ? "bg-amber-900/30 hover:bg-amber-800/40 text-amber-200"
              : status === "archived" ? "bg-slate-800/40 hover:bg-slate-700/60 text-slate-500"
              : "bg-slate-800 hover:bg-slate-700 text-slate-300";
            const tipByStatus = {
              stale:    "Shots whose prompt/preset/overrides changed since last render",
              starred:  "Bookmarked shots (click the star on any card)",
              rated:    "Shots with a non-zero rating (★)",
              archived: "Soft-deleted shots — click any card's ×/restore to manage",
            };
            return (
              <button
                key={status}
                onClick={() => setStatusFilter(status)}
                className={`px-3 py-1 rounded-lg text-xs font-medium transition-colors ${
                  statusFilter === status ? "bg-amber-600 text-white" : extraClass
                }`}
                title={tipByStatus[status] || ""}
              >
                {status === "stale" ? "⚠ stale"
                  : status === "starred" ? "⭐ starred"
                  : status === "rated" ? "★ rated"
                  : status === "archived" ? "🗑 archived"
                  : status}
                {count !== null && count > 0 && (
                  <span className="ml-1 text-[10px] opacity-70">({count})</span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* R74b: near-duplicates detector — find shots with similar prompts */}
      {showNearDupes && (
        <div className="near-dupes-panel bg-slate-900 border border-purple-600/20 rounded-xl p-3 max-h-96 overflow-y-auto">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-semibold text-purple-200">Near-duplicate prompts</h3>
            <div className="flex gap-2">
              <button onClick={refreshNearDupes}
                className="near-dupes-refresh-btn text-xs text-slate-400 hover:text-purple-300">↻ Refresh</button>
              <button onClick={() => setShowNearDupes(false)}
                className="text-slate-400 hover:text-slate-200 text-xs">Close</button>
            </div>
          </div>
          {nearDupes.length === 0 ? (
            <div className="text-xs text-slate-500 italic">
              No near-duplicate prompts (≥ 0.80 Jaccard similarity).
              {promptClusters.size > 0 && " Exact-match clusters are still flagged on each card with ×N."}
            </div>
          ) : (
            <div className="space-y-2">
              {nearDupes.map((p, i) => {
                const a = shots.find(s => s.id === p.shot_a);
                const b = shots.find(s => s.id === p.shot_b);
                if (!a || !b) return null;
                const simPct = (p.similarity * 100).toFixed(0);
                const color = p.similarity >= 0.95 ? "text-rose-300"
                            : p.similarity >= 0.90 ? "text-amber-300"
                            : "text-purple-300";
                return (
                  <div key={i} className="dupe-pair rounded bg-slate-800/60 border border-slate-700/40 p-2 text-[11px] space-y-1">
                    <div className="flex items-center gap-2">
                      <span className={"font-semibold " + color}>{simPct}%</span>
                      <span className="text-slate-500">similar</span>
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <button onClick={() => jumpToShot(a.id)}
                              className="dupe-jump-a text-left rounded bg-slate-900/60 p-1.5 hover:bg-slate-900">
                        <div className="text-slate-300 font-medium">{a.title || "Untitled"}</div>
                        <div className="text-slate-500 line-clamp-2 font-mono">{p.prompt_a_sample}</div>
                      </button>
                      <button onClick={() => jumpToShot(b.id)}
                              className="dupe-jump-b text-left rounded bg-slate-900/60 p-1.5 hover:bg-slate-900">
                        <div className="text-slate-300 font-medium">{b.title || "Untitled"}</div>
                        <div className="text-slate-500 line-clamp-2 font-mono">{p.prompt_b_sample}</div>
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* R72b: activity log — read-only event stream */}
      {showActivityLog && (
        <div className="activity-log-panel bg-slate-900 border border-sky-600/20 rounded-xl p-3 max-h-96 overflow-y-auto">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-semibold text-sky-200">Activity log (newest first)</h3>
            <div className="flex gap-2">
              <button onClick={refreshActivityLog}
                className="activity-refresh-btn text-xs text-slate-400 hover:text-sky-300">↻ Refresh</button>
              <button onClick={() => setShowActivityLog(false)}
                className="text-slate-400 hover:text-slate-200 text-xs">Close</button>
            </div>
          </div>
          {activityEntries.length === 0 ? (
            <div className="text-xs text-slate-500 italic">No activity yet.</div>
          ) : (
            <div className="space-y-0.5">
              {activityEntries.map((e, i) => {
                const when = e.ts ? new Date(e.ts * 1000).toLocaleString() : "?";
                const { action, ts, ...rest } = e;
                const details = Object.entries(rest)
                  .map(([k, v]) => `${k}=${typeof v === "string" ? v.slice(0, 40) : JSON.stringify(v)}`)
                  .join(" · ");
                return (
                  <div key={i} className="activity-row flex items-center gap-2 text-[11px] font-mono">
                    <span className="text-slate-600 w-40 flex-shrink-0">{when}</span>
                    <span className="text-sky-300 font-semibold w-36 flex-shrink-0">{action}</span>
                    <span className="text-slate-400 truncate">{details}</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* R70a: outline panel — jump-list with all scenes and shots */}
      {showOutline && (
        <div className="outline-panel bg-slate-900 border border-indigo-600/20 rounded-xl p-3 max-h-96 overflow-y-auto">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-semibold text-indigo-200">Outline</h3>
            <div className="flex gap-2">
              {/* R70b: quick lock-by-status actions */}
              <button onClick={() => batchLockByStatus(["ready"])}
                className="outline-lock-ready-btn px-2 py-0.5 rounded bg-emerald-700/40 hover:bg-emerald-600/50 text-emerald-100 text-[10px] font-medium"
                title="Lock every ready-status shot so accidental edits can't sneak in"
              >🔒 Lock all ready</button>
              <button onClick={() => setShowOutline(false)}
                className="text-slate-400 hover:text-slate-200 text-xs">Close</button>
            </div>
          </div>
          <div className="outline-groups space-y-2">
            {/* One section per scene, plus an "ungrouped" section */}
            {(() => {
              const sceneMap = new Map(scenes.map(sc => [sc.id, sc]));
              const groups = new Map();  // sceneId → shots
              const ungrouped = [];
              for (const s of shots) {
                if (s.scene_id && sceneMap.has(s.scene_id)) {
                  if (!groups.has(s.scene_id)) groups.set(s.scene_id, []);
                  groups.get(s.scene_id).push(s);
                } else {
                  ungrouped.push(s);
                }
              }
              const sections = [];
              for (const [sid, shotList] of groups) {
                const sc = sceneMap.get(sid);
                sections.push([sc?.name || sid, sc?.color, shotList]);
              }
              if (ungrouped.length) sections.push(["(ungrouped)", null, ungrouped]);
              return sections.map(([name, color, shotList], i) => (
                <div key={i} className="outline-section">
                  <div className="text-[11px] font-semibold uppercase tracking-wider mb-1"
                       style={{color: color || "#94a3b8"}}>
                    {name} <span className="opacity-60">({shotList.length})</span>
                  </div>
                  <div className="space-y-0.5">
                    {shotList.map(s => (
                      <button key={s.id}
                        onClick={() => jumpToShot(s.id)}
                        className="outline-item w-full text-left flex items-center gap-2 px-2 py-1 rounded hover:bg-slate-800/80 text-[11px]"
                        title={`${s.status} · ${s.preset || "?"}`}>
                        <span className="text-slate-500 font-mono w-5 text-right">{s.index + 1}</span>
                        <StatusBadge status={s.status} />
                        {s.bookmarked && <span className="text-yellow-400">★</span>}
                        <span className="flex-1 truncate text-slate-300">
                          {s.title || <span className="italic text-slate-500">untitled</span>}
                        </span>
                        {s.locked && <span className="text-slate-500">🔒</span>}
                      </button>
                    ))}
                  </div>
                </div>
              ));
            })()}
          </div>
        </div>
      )}

      {/* R69a: named-states panel — save/load/delete whole-board snapshots */}
      {showStatesPanel && (
        <div className="states-panel bg-slate-900 border border-amber-600/20 rounded-xl p-3 space-y-2">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-amber-200">Named board states</h3>
            <div className="flex gap-2">
              <button onClick={saveNamedState}
                className="states-save-btn px-2 py-0.5 rounded bg-emerald-700/40 hover:bg-emerald-600/50 text-emerald-100 text-xs font-medium"
              >+ Save current</button>
              <button onClick={() => setShowStatesPanel(false)}
                className="text-slate-400 hover:text-slate-200 text-xs">Close</button>
            </div>
          </div>
          {namedStates.length === 0 ? (
            <div className="text-xs text-slate-500 italic">
              No saved states yet. Click "+ Save current" to snapshot the board.
            </div>
          ) : (
            <div className="space-y-1">
              {namedStates.map(st => (
                <div key={st.file_name} className="states-row flex items-center gap-2 text-[11px] px-2 py-1 rounded bg-slate-800/60">
                  <span className="font-medium text-slate-200 flex-1 truncate">{st.name}</span>
                  <span className="text-slate-500">
                    {st.shot_count} shot(s){st.scene_count > 0 ? `, ${st.scene_count} scene(s)` : ""}
                  </span>
                  {st.saved_at && (
                    <span className="text-slate-500 text-[10px]">
                      {new Date(st.saved_at * 1000).toLocaleString()}
                    </span>
                  )}
                  <button onClick={() => loadNamedState(st.name, false)}
                    className="states-load-btn px-2 py-0.5 rounded bg-amber-700/40 hover:bg-amber-600/50 text-amber-100 font-medium"
                  >Load</button>
                  <button onClick={() => loadNamedState(st.name, true)}
                    className="states-merge-btn px-2 py-0.5 rounded bg-cyan-700/40 hover:bg-cyan-600/50 text-cyan-100 font-medium"
                    title="Append this state's shots + scenes to the current board"
                  >Merge</button>
                  <button onClick={() => deleteNamedState(st.name)}
                    className="states-delete-btn px-2 py-0.5 rounded bg-red-700/30 hover:bg-red-600/50 text-red-200 font-medium"
                  >×</button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* R68b: board-stats fold-out — lazy-compute on click */}
      {shots.length > 0 && (
        <div className="board-stats-wrapper">
          <button onClick={() => setShowBoardStats(v => !v)}
            className="board-stats-toggle text-xs text-slate-400 hover:text-amber-300 flex items-center gap-1"
          >{showBoardStats ? "▼" : "▶"} Board stats</button>
          {showBoardStats && (() => {
            const stats = {
              total: shots.length,
              by_status: {},
              by_preset: {},
              by_backend: {},
              by_priority: {},
              total_render_s: 0,
              rendered_count: 0,
              bookmarked: 0,
              with_refs: 0,
              with_trajectories: 0,
              with_scene: 0,
            };
            for (const s of shots) {
              stats.by_status[s.status] = (stats.by_status[s.status] || 0) + 1;
              if (s.preset) stats.by_preset[s.preset] = (stats.by_preset[s.preset] || 0) + 1;
              if (s.backend) stats.by_backend[s.backend] = (stats.by_backend[s.backend] || 0) + 1;
              const prio = s.priority || "normal";
              stats.by_priority[prio] = (stats.by_priority[prio] || 0) + 1;
              if (s.render_duration_s) { stats.total_render_s += s.render_duration_s; stats.rendered_count++; }
              if (s.bookmarked) stats.bookmarked++;
              if (s.ref_image) stats.with_refs++;
              if ((s.trajectories || []).length) stats.with_trajectories++;
              if (s.scene_id) stats.with_scene++;
            }
            const avgRender = stats.rendered_count > 0
              ? (stats.total_render_s / stats.rendered_count).toFixed(1) : "—";
            const totalMin = Math.round(stats.total_render_s / 60);
            const fmtPairs = (obj) => Object.entries(obj)
              .sort(([,a],[,b]) => b - a)
              .map(([k, v]) => `${k}: ${v}`).join(" · ");
            return (
              <div className="board-stats-panel bg-slate-900 border border-amber-600/20 rounded-xl p-3 text-[11px] space-y-1.5 mt-2">
                <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                  <div><span className="text-slate-500">Total:</span> <span className="text-amber-200 font-semibold">{stats.total}</span></div>
                  <div><span className="text-slate-500">Rendered:</span> <span className="text-emerald-300">{stats.rendered_count}</span></div>
                  <div><span className="text-slate-500">Avg render:</span> <span className="text-slate-200">{avgRender}s</span></div>
                  <div><span className="text-slate-500">Total GPU time:</span> <span className="text-slate-200">{totalMin}m</span></div>
                  <div><span className="text-slate-500">Bookmarked:</span> <span className="text-yellow-300">{stats.bookmarked}</span></div>
                  <div><span className="text-slate-500">With refs:</span> <span className="text-purple-300">{stats.with_refs}</span></div>
                  <div><span className="text-slate-500">With trajectories:</span> <span className="text-teal-300">{stats.with_trajectories}</span></div>
                  <div><span className="text-slate-500">In scenes:</span> <span className="text-indigo-300">{stats.with_scene}</span></div>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2 pt-1.5 border-t border-slate-700/40 text-slate-400">
                  <div><span className="text-slate-500">By status: </span>{fmtPairs(stats.by_status)}</div>
                  <div><span className="text-slate-500">By preset: </span>{fmtPairs(stats.by_preset) || "—"}</div>
                  <div><span className="text-slate-500">By backend: </span>{fmtPairs(stats.by_backend) || "—"}</div>
                  <div><span className="text-slate-500">By priority: </span>{fmtPairs(stats.by_priority) || "—"}</div>
                </div>
              </div>
            );
          })()}
        </div>
      )}

      {/* R67b: auto-group scenes button — always shown (useful even
          when no scenes exist yet, since it CAN create them). Placed
          just above the scene quick-select bar. */}
      {shots.length >= 2 && (
        <div className="auto-group-scenes-bar flex items-center gap-2 text-xs text-slate-500">
          <button onClick={autoGroupScenes}
            className="auto-group-scenes-btn px-2 py-1 rounded bg-slate-800 hover:bg-indigo-700/50 hover:text-indigo-200 text-xs font-medium"
            title="Cluster shots with the same title prefix into a Scene. Shots already in a scene are left alone."
          >🧩 Auto-group scenes</button>
        </div>
      )}

      {/* R78a: timeline duration ruler — colored segments proportional to
          each shot's effective duration. Click to jump, hover for tooltip. */}
      {!focusMode && shots.length > 0 && (() => {
        const visibleShots = shots.filter(s => !s.archived && s.is_primary);
        const durations = visibleShots.map(s =>
          s.render_duration_s || s.target_duration_s || s.duration_s || 2.0);
        const totalDur = durations.reduce((a, b) => a + b, 0) || 1;
        const statusColor = {
          ready:   "#34d399",  // emerald
          running: "#fbbf24",  // amber
          queued:  "#60a5fa",  // sky
          draft:   "#94a3b8",  // slate
          failed:  "#fb7185",  // rose
        };
        return (
          <div className="timeline-ruler-wrap">
            <div className="timeline-ruler flex gap-0.5 h-3 rounded overflow-hidden bg-slate-950 border border-slate-800">
              {visibleShots.map((s, i) => {
                const widthPct = (durations[i] / totalDur) * 100;
                if (widthPct < 0.3) return null;  // skip slivers too thin to see
                const bg = statusColor[s.status] || "#94a3b8";
                return (
                  <div key={s.id}
                    onClick={() => jumpToShot(s.id)}
                    className="timeline-seg cursor-pointer transition-all hover:opacity-70 hover:shadow-[0_0_0_2px_rgba(251,191,36,0.6)]"
                    style={{width: widthPct + "%", backgroundColor: bg, minWidth: "2px"}}
                    title={`${i+1}. ${s.title || "Untitled"} (${s.status}, ${durations[i].toFixed(1)}s)`}
                  />
                );
              })}
            </div>
            <div className="flex justify-between text-[9px] text-slate-500 mt-0.5">
              <span>0s</span>
              <span>{visibleShots.length} shots · {totalDur.toFixed(1)}s total</span>
              <span>{(totalDur/60).toFixed(1)}m</span>
            </div>
          </div>
        );
      })()}

      {/* R62b: scene-quick-select + R73a scene export */}
      {scenes && scenes.length > 0 && (
        <div className="scene-quick-select flex items-center gap-2 text-xs text-slate-400 flex-wrap">
          <span>Scenes:</span>
          {scenes.map(sc => {
            const count = shots.filter(s => s.scene_id === sc.id).length;
            if (count === 0) return null;
            return (
              <div key={sc.id} className="scene-quick-group inline-flex items-center gap-0.5">
                <button
                  onClick={(e) => selectSceneShots(sc.id, e.shiftKey)}
                  className="scene-quick-btn px-2 py-0.5 rounded-l text-[10px] font-medium border"
                  style={{
                    borderColor: sc.color || "#4a9eff",
                    color: sc.color || "#4a9eff",
                  }}
                  title={`${count} shot(s). Shift-click to add to current selection.`}
                >
                  {sc.name || sc.id.slice(0,6)} <span className="opacity-70">({count})</span>
                </button>
                {/* R73a: per-scene export dropdown */}
                <div className="relative group">
                  <button
                    className="scene-export-menu-btn px-1.5 py-0.5 rounded-r text-[10px] font-medium border border-l-0"
                    style={{borderColor: sc.color || "#4a9eff",
                             color: sc.color || "#4a9eff"}}
                    title="Export this scene only"
                  >▾</button>
                  <div className="scene-export-menu hidden group-hover:flex absolute top-5 left-0 z-10 bg-slate-800 rounded-lg shadow-xl border border-slate-700 p-1 flex-col gap-0.5 min-w-max">
                    <a href={`/api/video/export/edl?fps=30&scene=${encodeURIComponent(sc.id)}`}
                       download
                       className="px-2 py-1 rounded hover:bg-slate-700 text-[10px] text-slate-200">
                      Export scene EDL
                    </a>
                    <a href={`/api/video/export/fcpxml?fps=30&scene=${encodeURIComponent(sc.id)}`}
                       download
                       className="px-2 py-1 rounded hover:bg-slate-700 text-[10px] text-slate-200">
                      Export scene FCPXML
                    </a>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

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
            <select
              className="batch-priority-select bg-slate-800 border border-slate-600 text-slate-300 text-xs rounded px-2 py-1"
              defaultValue=""
              onChange={(e) => { if (e.target.value !== "") { batchPriority(e.target.value); e.target.value = ""; } }}
              title="Set render priority for selected shots"
            >
              <option value="" disabled>Priority...</option>
              <option value="high">⬆ High</option>
              <option value="normal">Normal</option>
              <option value="low">⬇ Low</option>
            </select>
            <button onClick={batchRandomizeSeeds}
              className="batch-randomize-seeds-btn px-3 py-1 rounded bg-indigo-700/40 hover:bg-indigo-600/50 text-indigo-100 text-xs"
              title="Assign a fresh random seed to each selected shot (variation exploration)"
            >🎲 Seeds</button>
            <button onClick={() => setShowSearchReplace(v => !v)}
              className="batch-search-replace-btn px-3 py-1 rounded bg-violet-700/40 hover:bg-violet-600/50 text-violet-100 text-xs"
              title="Find & replace text across selected shots' prompts"
            >{showSearchReplace ? "Close S/R" : "Find/Replace"}</button>
            {/* R68a: compare — needs exactly 2 shots, both with videos */}
            {(() => {
              const selectedList = Array.from(selected);
              const pair = selectedList.length === 2
                ? selectedList.map(id => shots.find(s => s.id === id)).filter(Boolean)
                : null;
              const playable = pair && pair.every(s => s?.video_path);
              const tip = !pair ? "Select exactly 2 shots to compare"
                : !playable ? "Both shots must have a rendered video"
                : `Play ${pair[0].title || "Shot 1"} and ${pair[1].title || "Shot 2"} side-by-side`;
              return (
                <button onClick={() => playable && setCompareModal({a: pair[0].id, b: pair[1].id})}
                  disabled={!playable}
                  className="batch-compare-btn px-3 py-1 rounded bg-teal-700/40 hover:bg-teal-600/50 text-teal-100 text-xs disabled:bg-slate-700 disabled:text-slate-500"
                  title={tip}
                >↔ Compare</button>
              );
            })()}
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
            <label className="text-xs text-slate-300 flex items-center gap-1 cursor-pointer"
                   title="Assign a random seed to each clone — great for exploring prompt variations">
              <input type="checkbox" checked={batchDupeFreshSeeds}
                onChange={(e) => setBatchDupeFreshSeeds(e.target.checked)}
                className="w-3 h-3 accent-cyan-500" />
              🎲 Fresh seeds per clone
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

      {/* R66b: batch search/replace — expanding panel */}
      {selected.size > 0 && showSearchReplace && (
        <div className="batch-search-replace-panel bg-slate-900 border border-violet-600/30 rounded-xl px-4 py-3 flex flex-col gap-2">
          <div className="flex items-center gap-2 text-xs text-violet-200">
            <span className="font-semibold">Find / Replace</span>
            <span className="text-slate-400">
              — replace ALL occurrences of "find" with "replace" across all {selected.size} selected shots' prompts.
            </span>
          </div>
          <div className="flex gap-2 items-center flex-wrap">
            <input
              type="text"
              value={searchReplaceFind}
              onChange={(e) => setSearchReplaceFind(e.target.value)}
              placeholder="find..."
              className="batch-sr-find bg-slate-800 border border-slate-600 rounded px-2 py-1 text-xs text-slate-200 placeholder-slate-500 focus:border-violet-500 focus:outline-none flex-1 min-w-[180px]"
            />
            <input
              type="text"
              value={searchReplaceWith}
              onChange={(e) => setSearchReplaceWith(e.target.value)}
              placeholder="replace with..."
              className="batch-sr-with bg-slate-800 border border-slate-600 rounded px-2 py-1 text-xs text-slate-200 placeholder-slate-500 focus:border-violet-500 focus:outline-none flex-1 min-w-[180px]"
            />
            <label className="text-[10px] text-slate-400 flex items-center gap-1 cursor-pointer">
              <input type="checkbox" checked={searchReplaceCase}
                onChange={(e) => setSearchReplaceCase(e.target.checked)}
                className="w-3 h-3 accent-violet-500" />
              Case-sensitive
            </label>
            <button
              onClick={batchSearchReplace}
              disabled={!searchReplaceFind}
              className="batch-sr-apply px-3 py-1 rounded bg-violet-600 hover:bg-violet-500 text-white text-xs font-medium disabled:bg-slate-700 disabled:text-slate-500"
            >Replace all</button>
          </div>
          <div className="text-xs text-slate-500">
            Locked shots are skipped. Changes are committed per-shot and cannot be
            undone atomically — use Ctrl+Z on a focused card to restore its
            auto-snapshot if you need to roll back.
          </div>
        </div>
      )}

      {/* Search bar + R78b scope toggles */}
      <div className={"search-bar-wrap space-y-1 " + (focusMode ? "hidden" : "")}>
        <div className="search-bar relative">
          <input
            type="text"
            placeholder="Search shots…"
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
        {/* R78b: scope toggles — narrow what the search matches against */}
        {searchQuery && (
          <div className="search-scope-row flex items-center gap-3 text-[10px] text-slate-500 px-1">
            <span>Scope:</span>
            {["prompt", "title", "notes", "tags"].map(field => (
              <label key={field} className="flex items-center gap-1 cursor-pointer">
                <input type="checkbox"
                  checked={searchFields[field]}
                  onChange={(e) => setSearchFields(sf => ({...sf, [field]: e.target.checked}))}
                  className="w-3 h-3 accent-amber-500" />
                {field}
              </label>
            ))}
          </div>
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
              promptDupeCount={promptClusters.get(shot.id) || 0}
              onToggleArchive={toggleArchiveShot}
              onMakeVariation={makeVariation}
              onPromoteVariation={promoteVariation}
              variationSiblings={shot.variation_group
                ? shots.filter(x => x.variation_group === shot.variation_group && x.id !== shot.id)
                : []}
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

      {/* R68a: side-by-side compare modal — two video tags locked to
          the same playback controls. Scrubbing/pausing one affects both. */}
      {compareModal && (() => {
        const shotA = shots.find(s => s.id === compareModal.a);
        const shotB = shots.find(s => s.id === compareModal.b);
        if (!shotA || !shotB) return null;
        return (
          <div className="compare-modal fixed inset-0 bg-black/90 z-50 flex items-center justify-center p-4"
               onClick={() => setCompareModal(null)}>
            <div className="bg-slate-900 border border-teal-600/40 rounded-xl p-4 max-w-6xl w-full space-y-3"
                 onClick={(e) => e.stopPropagation()}>
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-semibold text-teal-200">Side-by-side compare</h2>
                <button onClick={() => setCompareModal(null)}
                  className="text-slate-400 hover:text-slate-200 text-xl leading-none">×</button>
              </div>
              <div className="grid grid-cols-2 gap-3">
                {[shotA, shotB].map((s, i) => (
                  <div key={s.id} className="compare-pane space-y-2">
                    <div className="text-xs text-slate-300">
                      <span className="font-medium">{s.title || `Shot ${s.index + 1}`}</span>
                      <span className="text-slate-500 ml-2">({s.preset})</span>
                      {s.seed != null && <span className="text-slate-500 ml-2">seed {s.seed}</span>}
                    </div>
                    <video src={`/api/video/shots/${s.id}/video`}
                      className="compare-video w-full rounded bg-black"
                      controls
                      onPlay={(e) => {
                        // Sync: playing one plays the other
                        const siblings = e.currentTarget.parentNode.parentNode.querySelectorAll("video");
                        siblings.forEach(v => { if (v !== e.currentTarget && v.paused) v.play().catch(() => {}); });
                      }}
                      onPause={(e) => {
                        const siblings = e.currentTarget.parentNode.parentNode.querySelectorAll("video");
                        siblings.forEach(v => { if (v !== e.currentTarget && !v.paused) v.pause(); });
                      }}
                      onSeeked={(e) => {
                        const t = e.currentTarget.currentTime;
                        const siblings = e.currentTarget.parentNode.parentNode.querySelectorAll("video");
                        siblings.forEach(v => { if (v !== e.currentTarget && Math.abs(v.currentTime - t) > 0.3) v.currentTime = t; });
                      }}
                    />
                    <div className="text-[10px] text-slate-500 line-clamp-3 font-mono">{s.prompt}</div>
                  </div>
                ))}
              </div>
              <p className="text-[10px] text-slate-500">
                Pressing play / scrubbing either side keeps the other in sync.
                Click outside or press × to close.
              </p>
            </div>
          </div>
        );
      })()}

      {/* R71b: project metadata editor — title/author/synopsis at board level */}
      {showProjectMeta && (
        <div className="project-meta-modal fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-4"
             onClick={() => setShowProjectMeta(false)}>
          <div className="bg-slate-900 border border-indigo-600/40 rounded-xl p-5 max-w-lg w-full space-y-3"
               onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold text-indigo-200">Project metadata</h2>
              <button onClick={() => setShowProjectMeta(false)}
                className="text-slate-400 hover:text-slate-200 text-xl leading-none">×</button>
            </div>
            <p className="text-[10px] text-slate-500">
              Title populates EDL/FCPXML export headers when set. All fields
              are optional; leave blank to clear.
            </p>
            {[
              {key: "title", label: "Title", placeholder: "e.g. Project Red Duke"},
              {key: "author", label: "Author", placeholder: "Your name"},
              {key: "production", label: "Production", placeholder: "Studio / client"},
              {key: "copyright", label: "Copyright", placeholder: "© 2026 Your Name"},
            ].map(f => (
              <div key={f.key}>
                <label className="block text-xs font-semibold text-slate-300 mb-1">{f.label}</label>
                <input type="text"
                  value={projectMeta[f.key] || ""}
                  onChange={(e) => setProjectMeta(p => ({...p, [f.key]: e.target.value}))}
                  placeholder={f.placeholder}
                  className="w-full bg-slate-950 border border-slate-600 rounded px-2 py-1 text-xs text-slate-200 placeholder-slate-500 focus:border-indigo-500 focus:outline-none" />
              </div>
            ))}
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">Synopsis</label>
              <textarea
                value={projectMeta.synopsis || ""}
                onChange={(e) => setProjectMeta(p => ({...p, synopsis: e.target.value}))}
                placeholder="Short description of the project…"
                rows={3}
                className="w-full bg-slate-950 border border-slate-600 rounded px-2 py-1 text-xs text-slate-200 placeholder-slate-500 focus:border-indigo-500 focus:outline-none resize-y" />
            </div>
            <div className="flex gap-2 pt-2 border-t border-slate-700/40">
              <button onClick={() => setShowProjectMeta(false)}
                className="flex-1 px-3 py-1.5 rounded bg-slate-700 hover:bg-slate-600 text-slate-200 text-xs font-medium">Cancel</button>
              <button onClick={saveProjectMeta}
                className="flex-1 px-3 py-1.5 rounded bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium">Save</button>
            </div>
          </div>
        </div>
      )}

      {/* R76a: command palette — Ctrl+K opens, ↑/↓ navigate, Enter runs */}
      {showCommandPalette && (
        <div className="command-palette-modal fixed inset-0 bg-black/70 z-50 flex items-start justify-center pt-24 p-4"
             onClick={() => setShowCommandPalette(false)}>
          <div className="bg-slate-900 border border-amber-600/40 rounded-xl shadow-2xl max-w-xl w-full overflow-hidden"
               onClick={(e) => e.stopPropagation()}>
            <input type="text"
              autoFocus
              value={commandQuery}
              onChange={(e) => { setCommandQuery(e.target.value); setCommandSelectedIdx(0); }}
              onKeyDown={(e) => {
                if (e.key === "Escape") setShowCommandPalette(false);
                else if (e.key === "ArrowDown") {
                  e.preventDefault();
                  setCommandSelectedIdx(i => Math.min(i + 1, filteredCommands.length - 1));
                } else if (e.key === "ArrowUp") {
                  e.preventDefault();
                  setCommandSelectedIdx(i => Math.max(i - 1, 0));
                } else if (e.key === "Enter") {
                  e.preventDefault();
                  const cmd = filteredCommands[commandSelectedIdx];
                  if (cmd) runCommand(cmd);
                }
              }}
              placeholder="Type a command or action…"
              className="command-palette-input w-full bg-slate-950 border-b border-slate-700 px-4 py-3 text-sm text-slate-200 placeholder-slate-500 focus:outline-none" />
            <div className="command-palette-list max-h-96 overflow-y-auto">
              {filteredCommands.length === 0 ? (
                <div className="px-4 py-3 text-xs text-slate-500 italic">
                  No actions match "{commandQuery}".
                </div>
              ) : filteredCommands.map((cmd, i) => (
                <button key={cmd.label}
                  onMouseEnter={() => setCommandSelectedIdx(i)}
                  onClick={() => runCommand(cmd)}
                  className={"command-palette-item w-full text-left flex items-center gap-3 px-4 py-2 text-xs "
                    + (i === commandSelectedIdx
                       ? "bg-amber-900/40 text-amber-100"
                       : "text-slate-300 hover:bg-slate-800/60")}>
                  <span className="text-slate-500 w-20 flex-shrink-0 font-semibold uppercase tracking-wider text-[9px]">
                    {cmd.group}
                  </span>
                  <span className="flex-1 truncate">{cmd.label}</span>
                </button>
              ))}
            </div>
            <div className="border-t border-slate-700/60 px-3 py-1.5 text-[10px] text-slate-500 flex gap-3">
              <span><kbd className="px-1 rounded bg-slate-800">↑↓</kbd> navigate</span>
              <span><kbd className="px-1 rounded bg-slate-800">Enter</kbd> run</span>
              <span><kbd className="px-1 rounded bg-slate-800">Esc</kbd> close</span>
              <span className="ml-auto">{filteredCommands.length} actions</span>
            </div>
          </div>
        </div>
      )}

      {/* R66a: keyboard shortcuts cheatsheet — toggle with '?' */}
      {showShortcuts && (
        <div className="shortcuts-modal fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-4"
             onClick={() => setShowShortcuts(false)}>
          <div className="bg-slate-900 border border-amber-600/40 rounded-xl p-5 max-w-lg w-full space-y-3"
               onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold text-amber-200">Keyboard shortcuts</h2>
              <button onClick={() => setShowShortcuts(false)}
                className="text-slate-400 hover:text-slate-200 text-xl leading-none">×</button>
            </div>
            <div className="grid grid-cols-2 gap-2 text-xs">
              {[
                ["?", "Show/hide this panel"],
                ["Ctrl+K", "Open command palette (any action by name)"],
                ["F", "Toggle focus mode (hide toolbars)"],
                ["N", "Create a new shot"],
                ["↑ / ↓", "Focus previous / next shot"],
                ["Esc", "Clear shot focus / close modal"],
                ["Space", "Toggle selection on focused shot"],
                ["Ctrl+Z", "Restore last auto-snapshot (focused shot)"],
                ["Ctrl+Shift+R", "Render all drafts"],
                ["Shift+click (scene chip)", "Add scene's shots to selection"],
                ["Click star (☆/★)", "Bookmark shot"],
                ["Drag card", "Reorder shots across the board"],
              ].map(([k, v]) => (
                <React.Fragment key={k}>
                  <div className="text-slate-300">
                    <kbd className="px-1.5 py-0.5 rounded bg-slate-800 border border-slate-700 text-amber-300 font-mono text-[11px]">{k}</kbd>
                  </div>
                  <div className="text-slate-400">{v}</div>
                </React.Fragment>
              ))}
            </div>
            <p className="text-[10px] text-slate-500 pt-2 border-t border-slate-700/40">
              Shortcuts are ignored while typing in an input/textarea.
              Shot focus is required for per-shot shortcuts (use arrows to focus).
            </p>
          </div>
        </div>
      )}

      {/* R60a: snapshot-restore preview (shows diff before applying) */}
      {restorePreview && (
        <div className="restore-preview-modal fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-cyan-600/40 rounded-xl p-5 max-w-2xl w-full space-y-3 max-h-[80vh] overflow-y-auto">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold text-cyan-200">
                Restore snapshot
                {restorePreview.snap_label && (
                  <span className="text-slate-400 font-normal ml-2 text-sm">"{restorePreview.snap_label}"</span>
                )}
              </h2>
              <button onClick={() => setRestorePreview(null)}
                className="text-slate-400 hover:text-slate-200 text-xl leading-none">×</button>
            </div>
            {restorePreview.locked && (
              <div className="rounded bg-amber-900/40 border border-amber-600/40 text-amber-200 text-xs p-2">
                ⚠ This shot is locked. Restore will be refused until you unlock it.
              </div>
            )}
            <div className="text-xs text-slate-400">
              {restorePreview.changes.length} field{restorePreview.changes.length === 1 ? "" : "s"} will change:
            </div>
            <div className="restore-preview-diff space-y-2">
              {restorePreview.changes.map((c, i) => (
                <div key={i} className="restore-preview-row rounded bg-slate-800/60 border border-slate-700/40 p-2 text-[11px] space-y-1">
                  <div className="font-medium text-slate-200">{c.field}</div>
                  <div className="grid grid-cols-2 gap-2">
                    <div className="rounded bg-red-950/30 border border-red-800/20 p-1.5">
                      <div className="text-[9px] text-red-400/80 uppercase">current</div>
                      <div className="text-red-200 whitespace-pre-wrap break-words font-mono">
                        {typeof c.from === "object"
                          ? JSON.stringify(c.from, null, 1)
                          : (c.from === null || c.from === undefined || c.from === ""
                              ? <span className="italic text-slate-600">empty</span>
                              : String(c.from))}
                      </div>
                    </div>
                    <div className="rounded bg-emerald-950/30 border border-emerald-800/20 p-1.5">
                      <div className="text-[9px] text-emerald-400/80 uppercase">restored</div>
                      <div className="text-emerald-200 whitespace-pre-wrap break-words font-mono">
                        {typeof c.to === "object"
                          ? JSON.stringify(c.to, null, 1)
                          : (c.to === null || c.to === undefined || c.to === ""
                              ? <span className="italic text-slate-600">empty</span>
                              : String(c.to))}
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
            <div className="flex gap-2 pt-2 border-t border-slate-700/40">
              <button onClick={() => setRestorePreview(null)}
                className="flex-1 px-3 py-1.5 rounded bg-slate-700 hover:bg-slate-600 text-slate-200 text-xs font-medium">Cancel</button>
              <button onClick={confirmSnapshotRestore}
                disabled={restorePreview.locked}
                className="restore-confirm-btn flex-1 px-3 py-1.5 rounded bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-medium disabled:bg-slate-700 disabled:text-slate-500"
              >Apply restore</button>
            </div>
          </div>
        </div>
      )}

      {/* R51a: Resolve render dialog with a proper preset picker */}
      {showRenderDialog && (
        <div className="render-dialog fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-rose-600/40 rounded-xl p-5 max-w-md w-full space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold text-rose-200">Render in Resolve</h2>
              <button onClick={() => setShowRenderDialog(false)}
                className="text-slate-400 hover:text-slate-200 text-xl leading-none">×</button>
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">Render preset</label>
              {renderPresetsLoading ? (
                <div className="text-xs text-slate-500 italic">Loading presets from Resolve…</div>
              ) : renderPresetsError ? (
                <div className="text-xs text-amber-300">{renderPresetsError}</div>
              ) : (
                <select
                  value={renderPreset}
                  onChange={(e) => setRenderPreset(e.target.value)}
                  className="render-preset-select w-full bg-slate-950 border border-slate-600 rounded px-2 py-1 text-xs text-slate-200 focus:border-rose-500 focus:outline-none"
                >
                  {renderPresets.length === 0 && <option value="">(no presets found)</option>}
                  {renderPresets.map(p => <option key={p} value={p}>{p}</option>)}
                </select>
              )}
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">Target directory (on the Resolve host)</label>
              <input
                type="text"
                value={renderTargetDir}
                onChange={(e) => setRenderTargetDir(e.target.value)}
                placeholder="C:\\Spellcaster\\renders"
                className="render-target-dir w-full bg-slate-950 border border-slate-600 rounded px-2 py-1 text-xs text-slate-200 placeholder-slate-500 focus:border-rose-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">File name (a timestamp is appended)</label>
              <input
                type="text"
                value={renderFileName}
                onChange={(e) => setRenderFileName(e.target.value)}
                className="render-file-name w-full bg-slate-950 border border-slate-600 rounded px-2 py-1 text-xs text-slate-200 placeholder-slate-500 focus:border-rose-500 focus:outline-none"
              />
            </div>
            <div className="flex gap-2 pt-1">
              <button onClick={() => setShowRenderDialog(false)}
                className="flex-1 px-3 py-1.5 rounded bg-slate-700 hover:bg-slate-600 text-slate-200 text-xs font-medium">Cancel</button>
              <button
                onClick={startRender}
                disabled={!renderPreset || renderPresetsLoading}
                className="render-start-btn flex-1 px-3 py-1.5 rounded bg-rose-600 hover:bg-rose-500 text-white text-xs font-medium disabled:bg-slate-700 disabled:text-slate-500"
              >Start render</button>
            </div>
            <p className="text-[10px] text-slate-500">
              The render runs on the Resolve machine; you'll get a toast (and a browser
              notification if you allow them) when it finishes. You can close this tab and
              the antenna will still send the completion event on reconnection.
            </p>
          </div>
        </div>
      )}

      {/* R49b: Antenna admin modal — pair + self-update, no JSON editing */}
      {showAntennaAdmin && (
        <div className="antenna-admin-modal fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-indigo-600/40 rounded-xl p-5 max-w-lg w-full space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold text-indigo-200">Antenna</h2>
              <button onClick={() => setShowAntennaAdmin(false)}
                className="text-slate-400 hover:text-slate-200 text-xl leading-none">×</button>
            </div>
            {/* R52: list ALL known antennas (one chip per hostname). Falls
                back to single-row legacy view when the registry is empty. */}
            <div className="antenna-admin-list space-y-1">
              {antennaList.length > 0 ? (
                antennaList.map(a => (
                  <div key={a.hostname}
                    className={`antenna-entry rounded border p-2 text-xs space-y-0.5
                      ${a.online ? "bg-slate-800/60 border-indigo-600/30" : "bg-slate-900/40 border-slate-700/40"}`}>
                    <div className="flex items-center gap-2">
                      <span className={`w-2 h-2 rounded-full ${a.online ? "bg-emerald-400" : "bg-slate-600"}`}></span>
                      <span className="antenna-entry-hostname font-semibold text-slate-200">{a.hostname}</span>
                      <span className="text-slate-500">{a.ip}</span>
                      <span className="text-slate-500 ml-auto">{a.agent_url}</span>
                    </div>
                    <div>
                      <span className="text-slate-500">Services:</span>{' '}
                      {a.services && a.services.length > 0 ? (
                        a.services.map(s => (
                          <span key={s} className="inline-block mx-0.5 px-1.5 py-0.5 rounded bg-indigo-900/30 text-indigo-200 text-[10px]">{s}</span>
                        ))
                      ) : <span className="text-slate-500 italic">(none declared)</span>}
                    </div>
                    {a.last_heartbeat > 0 && (
                      <div className="text-[10px] text-slate-500">
                        last heartbeat: {new Date(a.last_heartbeat * 1000).toLocaleTimeString()}
                      </div>
                    )}
                  </div>
                ))
              ) : antennaStatus ? (
                <div className="rounded bg-slate-800/60 border border-slate-700/40 p-2 text-xs space-y-1">
                  <div><span className="text-slate-500">Paired URL:</span>{' '}
                    <span className="text-slate-200">{antennaStatus.paired_url || <span className="text-slate-500 italic">(not set)</span>}</span></div>
                  <div><span className="text-slate-500">Heartbeat URL:</span>{' '}
                    <span className="text-slate-200">{antennaStatus.heartbeat_url || <span className="text-slate-500 italic">(no antenna seen)</span>}</span></div>
                  <div><span className="text-slate-500">Token stored:</span>{' '}
                    <span className={antennaStatus.has_token ? "text-emerald-400" : "text-amber-400"}>
                      {antennaStatus.has_token ? "yes" : "no"}
                    </span></div>
                </div>
              ) : <span className="text-slate-500 text-xs">Loading antenna registry…</span>}
            </div>

            {/* R61a: Fleet telemetry — per-antenna GPU/RAM/VRAM/queue grid */}
            {fleetTelemetry && Object.keys(fleetTelemetry.antennas || {}).length > 0 && (
              <div className="antenna-fleet-telemetry border-t border-slate-700/40 pt-3 space-y-2">
                <div className="text-xs font-semibold text-slate-300 flex items-center gap-2">
                  Live telemetry
                  <span className="text-slate-500 font-normal">
                    ({Object.keys(fleetTelemetry.antennas).length} online, refreshes every 10s)
                  </span>
                </div>
                <div className="space-y-1">
                  {Object.entries(fleetTelemetry.antennas).map(([host, t]) => {
                    if (!t || t.error) {
                      return (
                        <div key={host} className="fleet-row rounded bg-slate-800/40 border border-slate-700/30 p-2 text-[10px]">
                          <span className="font-medium text-slate-200">{host}</span>
                          <span className="text-rose-300 ml-2">{t?.error || "no response"}</span>
                        </div>
                      );
                    }
                    const gpuPct = t.gpu_util_percent || 0;
                    const gpuColor = gpuPct > 80 ? "bg-rose-500" : gpuPct > 50 ? "bg-amber-500" : "bg-emerald-500";
                    const vramUsed = t.vram_used_mb || 0;
                    const vramTotal = t.vram_total_mb || 1;
                    const vramPct = (vramUsed / vramTotal) * 100;
                    const ramPct = t.ram_percent || 0;
                    const cpuPct = t.cpu_percent || 0;
                    const comfy = t.services?.comfyui?.extra;
                    const kobold = t.services?.kobold?.extra;
                    return (
                      <div key={host} className="fleet-row rounded bg-slate-800/60 border border-indigo-600/20 p-2 text-[10px] space-y-1">
                        <div className="flex items-center gap-2">
                          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
                          <span className="font-medium text-slate-200">{host}</span>
                          <span className="text-slate-500">{t.gpu_name || ""}</span>
                          <span className="text-slate-500 ml-auto">{Math.round(t.disk_free_gb || 0)}GB free</span>
                        </div>
                        <div className="grid grid-cols-3 gap-2">
                          <div>
                            <div className="flex items-center justify-between text-[9px] text-slate-400">
                              <span>GPU</span><span>{gpuPct.toFixed(0)}%</span>
                            </div>
                            <div className="h-1.5 bg-slate-900 rounded overflow-hidden">
                              <div className={`h-full ${gpuColor}`} style={{width: `${gpuPct}%`}} />
                            </div>
                            <div className="text-[9px] text-slate-500">{t.gpu_temp_c || 0}°C</div>
                          </div>
                          <div>
                            <div className="flex items-center justify-between text-[9px] text-slate-400">
                              <span>VRAM</span>
                              <span>{(vramUsed/1024).toFixed(1)}/{(vramTotal/1024).toFixed(1)}G</span>
                            </div>
                            <div className="h-1.5 bg-slate-900 rounded overflow-hidden">
                              <div className="h-full bg-cyan-500" style={{width: `${vramPct}%`}} />
                            </div>
                          </div>
                          <div>
                            <div className="flex items-center justify-between text-[9px] text-slate-400">
                              <span>CPU/RAM</span>
                              <span>{cpuPct.toFixed(0)}% / {ramPct.toFixed(0)}%</span>
                            </div>
                            <div className="flex gap-0.5 h-1.5">
                              <div className="flex-1 bg-slate-900 rounded overflow-hidden">
                                <div className="h-full bg-slate-400" style={{width: `${cpuPct}%`}} />
                              </div>
                              <div className="flex-1 bg-slate-900 rounded overflow-hidden">
                                <div className="h-full bg-slate-400" style={{width: `${ramPct}%`}} />
                              </div>
                            </div>
                          </div>
                        </div>
                        <div className="flex gap-3 text-[9px] text-slate-500 pt-0.5 border-t border-slate-700/30">
                          {comfy && (
                            <span>Comfy: <span className="text-cyan-300">{comfy.queue_running || 0}R/{comfy.queue_pending || 0}P</span></span>
                          )}
                          {kobold && (
                            <span>Kobold: <span className="text-fuchsia-300">{(kobold.tok_per_sec||0).toFixed(1)} t/s</span></span>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
            <div className="antenna-admin-pair space-y-2">
              <div className="text-xs font-semibold text-slate-300">Pair antenna (one-time, stores URL + token)</div>
              <input
                type="text"
                value={antennaPairUrl}
                onChange={(e) => setAntennaPairUrl(e.target.value)}
                placeholder="https://192.168.x.x:7334"
                className="antenna-pair-url w-full bg-slate-950 border border-slate-600 rounded px-2 py-1 text-xs text-slate-200 placeholder-slate-500 focus:border-indigo-500 focus:outline-none"
              />
              <input
                type="password"
                value={antennaPairToken}
                onChange={(e) => setAntennaPairToken(e.target.value)}
                placeholder="bearer token (see antenna_config.json on the remote host)"
                className="antenna-pair-token w-full bg-slate-950 border border-slate-600 rounded px-2 py-1 text-xs text-slate-200 placeholder-slate-500 focus:border-indigo-500 focus:outline-none"
              />
              <button
                onClick={pairAntenna}
                disabled={antennaBusy || !antennaPairUrl.trim() || !antennaPairToken.trim()}
                className="antenna-pair-btn w-full px-3 py-1.5 rounded bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium disabled:bg-slate-700 disabled:text-slate-500"
              >{antennaBusy ? "Pairing…" : "Pair"}</button>
            </div>
            <div className="antenna-admin-update space-y-2 border-t border-slate-700/40 pt-3">
              <div className="text-xs font-semibold text-slate-300">Actions</div>
              <button
                onClick={selfUpdateGuild}
                disabled={antennaBusy}
                className="guild-update-btn w-full px-3 py-1.5 rounded bg-amber-700/40 hover:bg-amber-600/50 text-amber-100 text-xs font-medium disabled:bg-slate-700 disabled:text-slate-500"
                title="Triggers the Guild's GitHub auto-updater, then restarts the server process in place"
              >{antennaBusy ? "Working…" : "Self-update Guild (this server)"}</button>
              <button
                onClick={selfUpdateAntenna}
                disabled={antennaBusy || !antennaStatus?.has_token}
                className="antenna-update-btn w-full px-3 py-1.5 rounded bg-emerald-700/40 hover:bg-emerald-600/50 text-emerald-100 text-xs font-medium disabled:bg-slate-700 disabled:text-slate-500"
                title="Triggers /self-update on the paired antenna (git pull + restart)"
              >{antennaBusy ? "Working…" : "Self-update antenna"}</button>
              <button
                onClick={refreshAntennaStatus}
                className="antenna-refresh-btn w-full px-3 py-1.5 rounded bg-slate-700 hover:bg-slate-600 text-slate-200 text-xs font-medium"
              >Refresh status</button>
            </div>
            <p className="text-[10px] text-slate-500">
              The antenna now auto-detects Resolve on startup — you no longer need to add
              services to <span className="font-mono">antenna_config.json</span>. Just pair once
              and use "→ Resolve".
            </p>

            {/* R55b: feature diagnostics — why a button isn't showing up */}
            {featureReport && (featureReport.unsatisfied || []).length > 0 && (
              <div className="antenna-features-diag border-t border-slate-700/40 pt-3 space-y-2">
                <div className="text-xs font-semibold text-slate-300">
                  Features hidden from UI
                  <span className="text-slate-500 font-normal">
                    {' '}({featureReport.unsatisfied.length}/{featureReport.total} unmet)
                  </span>
                </div>
                <div className="space-y-1 max-h-48 overflow-y-auto">
                  {featureReport.unsatisfied.map(f => {
                    // R56: infer if this feature is blocked by a launchable
                    // service (comfyui/kobold/ollama). If so, offer a
                    // "Start <svc>" button that POSTs /api/antenna/service/start.
                    const startableServices = ["comfyui", "kobold", "ollama"];
                    const launchable = [];
                    for (const m of (f.missing || [])) {
                      for (const svc of startableServices) {
                        if ((m.startsWith(`service:${svc}`) ||
                             m.startsWith(`${svc}:`)) &&
                            !launchable.includes(svc)) {
                          launchable.push(svc);
                        }
                      }
                    }
                    return (
                      <div key={f.key} className="feature-diag-row rounded bg-slate-800/40 border border-slate-700/30 p-2 text-[10px] space-y-0.5">
                        <div className="flex items-center gap-2">
                          <span className="w-1.5 h-1.5 rounded-full bg-amber-500"></span>
                          <span className="font-medium text-slate-200">{f.label || f.key}</span>
                          <span className="text-slate-500 ml-auto">{f.key}</span>
                        </div>
                        <div className="text-slate-400">Needs:</div>
                        <ul className="ml-3 space-y-0.5">
                          {(f.missing || []).map((m, i) => (
                            <li key={i} className="text-amber-300/80 leading-tight">{m}</li>
                          ))}
                        </ul>
                        {launchable.length > 0 && (
                          <div className="flex gap-1 pt-1">
                            {launchable.map(svc => (
                              <button
                                key={svc}
                                onClick={() => startServiceOnAntenna(svc)}
                                disabled={!!serviceStartBusy[svc]}
                                className="service-start-btn px-2 py-0.5 rounded bg-emerald-700/40 hover:bg-emerald-600/50 text-emerald-100 font-medium disabled:bg-slate-700 disabled:text-slate-500 text-[10px]"
                                title={`POST /service/start on the paired antenna to launch ${svc}`}
                              >
                                {serviceStartBusy[svc] ? `Starting ${svc}…` : `Start ${svc}`}
                              </button>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
                {(featureReport.satisfied || []).length > 0 && (
                  <div className="text-[10px] text-slate-500">
                    {featureReport.satisfied.length} feature(s) satisfied and visible.
                  </div>
                )}
              </div>
            )}
            {featureReport && (featureReport.unsatisfied || []).length === 0
                && (featureReport.satisfied || []).length > 0 && (
              <div className="text-[10px] text-emerald-300 border-t border-slate-700/40 pt-3">
                ✓ All {featureReport.total} features are satisfied and visible.
              </div>
            )}
          </div>
        </div>
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
      {/* R60b: render-cost chip — pending work + live antenna telemetry */}
      {queueCost && queueCost.pending_count > 0 && (() => {
        const serial = queueCost.total_seconds_serial || 0;
        const parallel = queueCost.total_seconds_parallel || 0;
        const mins = Math.floor(serial / 60);
        const secs = Math.round(serial % 60);
        const costLabel = mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
        const tel = queueCost.antenna_telemetry;
        const gpuPct = tel?.gpu_util_percent;
        const vramUsed = tel?.vram_used_mb;
        const vramTotal = tel?.vram_total_mb;
        const comfy = tel?.services?.comfyui?.extra;
        return (
          <div className="queue-cost-header flex items-center justify-center gap-2 flex-wrap text-[11px] text-slate-400 py-1">
            <span className="queue-cost-label">💸 {queueCost.pending_count} pending · {costLabel} serial
              {parallel > 0 && parallel < serial && (
                <span className="text-slate-500"> ({Math.floor(parallel/60)}m{Math.round(parallel%60)}s @{queueCost.total_seconds_serial/parallel|0}×)</span>
              )}
            </span>
            <span className="text-slate-600">·</span>
            <span className="queue-cost-source text-slate-500">avg from {queueCost.avg_source}</span>
            {queueCost.antenna_hostname && (
              <>
                <span className="text-slate-600">·</span>
                <span className="queue-cost-antenna text-indigo-300">📡 {queueCost.antenna_hostname}</span>
              </>
            )}
            {gpuPct != null && (
              <>
                <span className="text-slate-600">·</span>
                <span className={"queue-cost-gpu " + (gpuPct > 80 ? "text-rose-300" : gpuPct > 50 ? "text-amber-300" : "text-emerald-300")}>
                  GPU {gpuPct.toFixed(0)}%
                </span>
              </>
            )}
            {vramUsed && vramTotal && (
              <>
                <span className="text-slate-600">·</span>
                <span className="queue-cost-vram text-slate-400">
                  VRAM {(vramUsed/1024).toFixed(1)}/{(vramTotal/1024).toFixed(1)}GB
                </span>
              </>
            )}
            {comfy && comfy.queue_pending + comfy.queue_running > 0 && (
              <>
                <span className="text-slate-600">·</span>
                <span className="queue-cost-comfy text-cyan-300">
                  Comfy {comfy.queue_running}R/{comfy.queue_pending}P
                </span>
              </>
            )}
          </div>
        );
      })()}

      <div className="shortcut-hints text-xs text-slate-500 text-center pt-4 border-t border-slate-800">
        <span className="text-slate-600">Shortcuts:</span> <kbd className="px-1 rounded bg-slate-800">N</kbd> new shot · <kbd className="px-1 rounded bg-slate-800">Ctrl+Shift+R</kbd> render all
      </div>
    </div>
  );

}

window.VideoPanel = VideoPanel;
