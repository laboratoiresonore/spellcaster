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
}) {
  const [expanded, setExpanded] = _useState(shot.status === "draft");
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
    setOvSteps(shot.overrides?.steps ?? "");
    setOvGuidance(shot.overrides?.guidance ?? "");
    setOvFrames(shot.overrides?.frames ?? "");
    setOvFps(shot.overrides?.fps ?? "");
    setOvResolution(shot.overrides?.resolution ?? "");
  }, [shot.title, shot.prompt, shot.negative, shot.notes, shot.seed, shot.backend, shot.preset, shot.carry_last_frame, JSON.stringify(shot.overrides)]);

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
  }, [editTitle, editPrompt, editNegative, editNotes, editSeed, editBackend, editPreset, editCarryFrame, ovSteps, ovGuidance, ovFrames, ovFps, ovResolution]);

  const presetKeys = presets ? Object.keys(presets) : [];
  const currentPreset = presets[editPreset];

  return (
    <div className={`bg-slate-900 border rounded-xl overflow-hidden transition-all ${isSelected ? "border-amber-400 shadow-lg shadow-amber-600/30" : "border-amber-600/20"}`}>
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

function HealthPanel({ health }) {
  if (!health) return null;

  const dot = (ok) => ok
    ? "w-2 h-2 rounded-full bg-emerald-400"
    : "w-2 h-2 rounded-full bg-red-400";

  return (
    <div className="flex gap-4 text-xs">
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
        <div className="text-xs font-medium text-amber-50 truncate">{shot.title || `Shot ${shot.index + 1}`}</div>
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

function VideoPanel() {
  const [shots, setShots] = _useState([]);
  const [presets, setPresets] = _useState({});
  const [health, setHealth] = _useState(null);
  const [trajShot, setTrajShot] = _useState(null);
  const [queuePaused, setQueuePaused] = _useState(false);
  const [viewMode, setViewMode] = _useState("list");
  const [loading, setLoading] = _useState(true);
  const [selectedShotId, setSelectedShotId] = useState(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [assembling, setAssembling] = _useState(false);
  const [assembledPath, setAssembledPath] = _useState(null);
  const [error, setError] = _useState("");
  const [statusFilter, setStatusFilter] = _useState("all");
  const [templates, setTemplates] = _useState([]);
  const [selected, setSelected] = _useState(new Set());
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
      const [shotsData, presetsData, healthData, templatesData] = await Promise.all([
        api.get("/api/video/shots"),
        api.get("/api/video/presets"),
        api.get("/api/video/health"),
        api.get("/api/video/templates"),
      ]);
      setShots((shotsData.shots || []).map((s, i) => ({ ...s, index: i })));
      setPresets(presetsData || {});
      setHealth(healthData || null);
      setTemplates(templatesData.templates || []);
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
    if (!window.confirm("Delete this shot? This cannot be undone.")) return;
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
    // Note: /api/video/render-all batch endpoint available for future optimization
    const draftShots = shots.filter(s => s.status === "draft" || s.status === "failed");
    for (const s of draftShots) {
      try {
        await api.post(`/api/video/shots/${s.id}/render`, {});
      } catch {}
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
          <HealthPanel health={health} />
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
          <div className="flex gap-2">
            <button onClick={selectNone} className="text-xs text-slate-400 hover:text-slate-300">Deselect</button>
            <button onClick={renderSelected} className="flex items-center gap-1 bg-emerald-700/30 hover:bg-emerald-700/50 text-emerald-300 px-3 py-1 rounded text-xs font-medium">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M5 3l14 9-14 9V3z" /></svg>
              Render
            </button>
            <button onClick={deleteSelected} className="flex items-center gap-1 bg-red-600/20 hover:bg-red-600/40 text-red-400 px-3 py-1 rounded text-xs font-medium">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /></svg>
              Delete
            </button>
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
              {filteredShots.length} shot{filteredShots.length !== 1 ? "s" : ""}
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

      {/* Keyboard shortcuts hint */}
      <div className="shortcut-hints text-xs text-slate-500 text-center pt-4 border-t border-slate-800">
        <span className="text-slate-600">Shortcuts:</span> <kbd className="px-1 rounded bg-slate-800">N</kbd> new shot · <kbd className="px-1 rounded bg-slate-800">Ctrl+Shift+R</kbd> render all
      </div>
    </div>
  );
}
