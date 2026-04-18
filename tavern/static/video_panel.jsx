/**
 * VideoPanel — React component for the Guild's Video/Shotboard tab.
 *
 * Provides full CRUD for shots, backend/preset configuration,
 * reference image attachment, trajectory drawing (via TrajectoryCanvas),
 * render queueing, and status polling.
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
// Shot Card — one row per shot
// ════════════════════════════════════════════════════════════════════

function ShotCard({ shot, presets, onUpdate, onRemove, onRender, onOpenTrajectory, onUploadRef, onReorder }) {
  const [expanded, setExpanded] = _useState(false);
  const [editTitle, setEditTitle] = _useState(shot.title);
  const [editPrompt, setEditPrompt] = _useState(shot.prompt);
  const [editBackend, setEditBackend] = _useState(shot.backend);
  const [editPreset, setEditPreset] = _useState(shot.preset);
  const [uploading, setUploading] = _useState(false);
  const fileRef = _useRef(null);
  const [dragOver, setDragOver] = _useState(false);

  // Sync from props when shot changes externally (e.g. poll refresh)
  _useEffect(() => {
    setEditTitle(shot.title);
    setEditPrompt(shot.prompt);
    setEditBackend(shot.backend);
    setEditPreset(shot.preset);
  }, [shot.title, shot.prompt, shot.backend, shot.preset]);

  const doSave = () => {
    onUpdate(shot.id, {
      title: editTitle,
      prompt: editPrompt,
      backend: editBackend,
      preset: editPreset,
    });
  };

  const dirty =
    editTitle !== shot.title ||
    editPrompt !== shot.prompt ||
    editBackend !== shot.backend ||
    editPreset !== shot.preset;

  const presetKeys = presets ? Object.keys(presets) : [];

  return (
    <div className="bg-slate-900 border border-amber-600/20 rounded-xl overflow-hidden transition-all">
      {/* Collapsed header */}
      <div
        draggable
        onDragStart={e => { e.dataTransfer.setData("text/plain", shot.id); e.dataTransfer.effectAllowed = "move"; }}
        onDragOver={e => { e.preventDefault(); e.dataTransfer.dropEffect = "move"; setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={e => { e.preventDefault(); setDragOver(false); const from = e.dataTransfer.getData("text/plain"); if (from !== shot.id) onReorder(from, shot.id); }}
        className={`flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-purple-800/10 transition-colors ${dragOver ? "border-t-2 border-amber-400" : ""}`}
        onClick={() => setExpanded(!expanded)}
      >
        <span className="text-amber-600/60 text-xs font-mono w-6 text-center">{shot.index + 1}</span>
        <span className="flex-1 text-amber-50 text-sm font-medium truncate">
          {shot.title || <span className="text-slate-500 italic">Untitled shot</span>}
        </span>
        <StatusBadge status={shot.status} />
        {shot.ref_image && (
          <span className="text-xs text-purple-400" title="Has reference image">REF</span>
        )}
        {shot.trajectories && shot.trajectories.length > 0 && (
          <span className="text-xs text-teal-400" title={`${shot.trajectories.length} trajectory(s)`}>
            {shot.trajectories.length}T
          </span>
        )}
        <span className={`text-amber-600 transition-transform ${expanded ? "rotate-180" : ""}`}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M6 9l6 6 6-6"/></svg>
        </span>
      </div>

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

          {/* Backend + Preset row */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-amber-200 mb-1">Backend</label>
              <select
                value={editBackend}
                onChange={e => setEditBackend(e.target.value)}
                className="w-full bg-slate-950 border border-amber-500/20 rounded-lg px-3 py-2 text-amber-50 text-sm outline-none"
              >
                {BACKENDS.map(b => <option key={b} value={b}>{b}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-amber-200 mb-1">Preset</label>
              <select
                value={editPreset}
                onChange={e => setEditPreset(e.target.value)}
                className="w-full bg-slate-950 border border-amber-500/20 rounded-lg px-3 py-2 text-amber-50 text-sm outline-none"
              >
                {presetKeys.length > 0
                  ? presetKeys.map(k => {
                      const p = presets[k];
                      const d = p.defaults || {};
                      const info = [d.resolution, d.fps && (d.fps + "fps"), d.frames && (d.frames + "f")].filter(Boolean).join(" · ");
                      return <option key={k} value={k}>{p.label || k}{info ? ` (${info})` : ""}</option>;
                    })
                  : <option value={editPreset}>{editPreset}</option>
                }
              </select>
              {presets[editPreset] && presets[editPreset].notes && (
                <p className="text-xs text-slate-500 mt-1">{presets[editPreset].notes}</p>
              )}
            </div>
          </div>

          {/* Reference image */}
          <div>
            <label className="block text-xs font-medium text-amber-200 mb-1">Reference Image</label>
            {shot.ref_image && (
              <div className="bg-slate-950 rounded-lg p-2 inline-block mb-2">
                <img
                  src={`/api/video/shots/${shot.id}/reference`}
                  alt="ref"
                  className="max-h-32 rounded"
                  onError={e => { e.target.style.display = 'none'; }}
                />
              </div>
            )}
            <div className="flex items-center gap-2">
              <input
                ref={fileRef}
                type="file"
                accept="image/*"
                className="hidden"
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
                className="flex items-center gap-1.5 bg-purple-700/30 hover:bg-purple-700/50 text-purple-300 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors disabled:opacity-40"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"/></svg>
                {uploading ? "Uploading..." : (shot.ref_image ? "Replace" : "Upload")}
              </button>
            </div>
          </div>

          {/* Video preview */}
          {shot.video_path && shot.status === "ready" && (
            <div>
              <label className="block text-xs font-medium text-amber-200 mb-1">Output Video</label>
              <video
                src={`/api/video/shots/${shot.id}/video`}
                controls
                autoPlay
                loop
                muted
                className="max-h-48 rounded-lg"
              />
            </div>
          )}

          {/* Error display */}
          {shot.error && (
            <div className="bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2 text-sm text-red-400">
              {shot.error}
            </div>
          )}

          {/* Action buttons */}
          <div className="flex gap-2 flex-wrap pt-1">
            {dirty && (
              <button
                onClick={doSave}
                className="flex items-center gap-1.5 bg-amber-600 hover:bg-amber-500 text-white px-3 py-1.5 rounded-lg text-xs font-medium transition-colors"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/></svg>
                Save
              </button>
            )}
            <button
              onClick={() => onRender(shot.id)}
              disabled={shot.status === "running" || shot.status === "queued"}
              className="flex items-center gap-1.5 bg-emerald-700/30 hover:bg-emerald-700/50 text-emerald-300 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M5 3l14 9-14 9V3z"/></svg>
              Render
            </button>
            {shot.ref_image && (
              <button
                onClick={() => onOpenTrajectory(shot)}
                className="flex items-center gap-1.5 bg-purple-700/30 hover:bg-purple-700/50 text-purple-300 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M2 22l10-10M15 4V2M15 16v-2M8 9h2M20 9h2"/></svg>
                Trajectories
              </button>
            )}
            <button
              onClick={() => { if (confirm(`Delete shot "${shot.title || 'Untitled'}"?`)) onRemove(shot.id); }}
              className="flex items-center gap-1.5 bg-red-600/20 hover:bg-red-600/40 text-red-400 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ml-auto"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
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

    // Clear any previous canvas
    containerRef.current.innerHTML = '';

    const tc = new TrajectoryCanvas({
      container: containerRef.current,
      imageUrl: `/api/video/shots/${shot.id}/reference`,
      onSave: (trajectories) => {
        onSaved(shot.id, trajectories);
      },
    });

    // Load existing trajectories if any
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
// VideoPanel — main component for the "Video" tab
// ════════════════════════════════════════════════════════════════════

function VideoPanel() {
  const [shots, setShots] = _useState([]);
  const [presets, setPresets] = _useState({});
  const [health, setHealth] = _useState(null);
  const [trajShot, setTrajShot] = _useState(null); // shot for trajectory modal
  const [loading, setLoading] = _useState(true);
  const [error, setError] = _useState("");
  const pollRef = _useRef(null);

  // ── Initial load ──
  const refresh = _useCallback(async () => {
    try {
      const [shotsData, presetsData, healthData] = await Promise.all([
        api.get("/api/video/shots"),
        api.get("/api/video/presets"),
        api.get("/api/video/health"),
      ]);
      setShots(shotsData.shots || []);
      setPresets(presetsData || {});
      setHealth(healthData || null);
      setError("");
    } catch (e) {
      setError("Video Bridge not available. Make sure the server is running with video support enabled.");
    } finally {
      setLoading(false);
    }
  }, []);

  _useEffect(() => {
    refresh();
    // Poll every 3s for status updates (running renders etc.)
    pollRef.current = setInterval(async () => {
      try {
        const data = await api.get("/api/video/shots");
        setShots(data.shots || []);
      } catch {}
    }, 3000);
    return () => clearInterval(pollRef.current);
  }, [refresh]);

  // ── CRUD ops ──
  const addShot = async () => {
    try {
      const result = await api.post("/api/video/shots", {
        title: `Shot ${shots.length + 1}`,
        prompt: "",
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

  const removeShot = async (id) => {
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

  const reorderShot = async (fromId, toId) => {
    // Move fromId to just before toId in the ordering
    const ids = shots.map(s => s.id);
    const filtered = ids.filter(id => id !== fromId);
    const targetIdx = filtered.indexOf(toId);
    filtered.splice(targetIdx, 0, fromId);
    try {
      await api.post("/api/video/reorder", { ordered_ids: filtered });
      await refresh();
    } catch (e) {
      setError("Failed to reorder shots");
    }
  };

  const renderAll = async () => {
    const draftShots = shots.filter(s => s.status === "draft" || s.status === "failed");
    for (const s of draftShots) {
      try {
        await api.post(`/api/video/shots/${s.id}/render`, {});
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
        <div className="bg-red-500/10 border border-red-500/30 rounded-xl px-4 py-3 text-sm text-red-400 flex items-center gap-2">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0zM12 9v4M12 17h.01"/></svg>
          {error}
          <button onClick={() => setError("")} className="ml-auto text-red-500 hover:text-red-300">&times;</button>
        </div>
      )}

      {/* Header with health + add button */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-amber-50">Shotboard</h2>
          <HealthPanel health={health} />
        </div>
        <div className="flex gap-2">
          <button onClick={refresh}
            className="flex items-center gap-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 px-3 py-2 rounded-lg text-xs font-medium transition-colors">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M23 4v6h-6M1 20v-6h6M3.51 9a9 9 0 0 1 14.85-3.36M20.49 15a9 9 0 0 1-14.85 3.36"/></svg>
            Refresh
          </button>
          {shots.length > 0 && shots.some(s => s.status === "draft" || s.status === "failed") && (
            <button onClick={renderAll}
              className="flex items-center gap-1.5 bg-emerald-700/30 hover:bg-emerald-700/50 text-emerald-300 px-3 py-2 rounded-lg text-xs font-medium transition-colors">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M5 3l14 9-14 9V3z"/></svg>
              Render All
            </button>
          )}
          <button onClick={addShot}
            className="flex items-center gap-1.5 bg-amber-600 hover:bg-amber-500 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors shadow-lg shadow-amber-600/30">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 5v14M5 12h14"/></svg>
            New Shot
          </button>
        </div>
      </div>

      {/* Shot list */}
      {shots.length === 0 ? (
        <div className="text-center py-16 bg-slate-900/50 border border-amber-600/10 rounded-xl">
          <svg className="mx-auto mb-3 text-amber-600/40" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M19.82 2H4.18A2.18 2.18 0 0 0 2 4.18v15.64A2.18 2.18 0 0 0 4.18 22h15.64A2.18 2.18 0 0 0 22 19.82V4.18A2.18 2.18 0 0 0 19.82 2zM7 2v20M17 2v20M2 12h20M2 7h5M2 17h5M17 17h5M17 7h5"/>
          </svg>
          <p className="text-slate-400 text-sm">No shots yet. Click <strong className="text-amber-300">New Shot</strong> to start your storyboard.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {shots.map(shot => (
            <ShotCard
              key={shot.id}
              shot={shot}
              presets={presets}
              onUpdate={updateShot}
              onRemove={removeShot}
              onRender={renderShot}
              onOpenTrajectory={setTrajShot}
              onUploadRef={uploadReference}
              onReorder={reorderShot}
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
    </div>
  );
}

// Export for the tab system
window.VideoPanel = VideoPanel;
