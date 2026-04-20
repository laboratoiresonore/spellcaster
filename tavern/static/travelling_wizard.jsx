const { useState, useCallback, useRef, useEffect, useMemo } = React;

// ─── Icons (inline SVG components) ────────────────────────────────
const Icon = ({ d, size = 20, className = "" }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="2" strokeLinecap="round"
    strokeLinejoin="round" className={className}>
    <path d={d} />
  </svg>
);

const Icons = {
  Signal: () => <Icon d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2zm0 4a1.5 1.5 0 1 1 0 3 1.5 1.5 0 0 1 0-3zm3 10H9v-2h2v-3H9v-2h4v5h2z" />,
  Server: () => <Icon d="M2 4h20v6H2zM2 14h20v6H2zM6 7h0M6 17h0" />,
  Users: () => <Icon d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" />,
  Shield: () => <Icon d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />,
  Folder: () => <Icon d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />,
  Save: () => <Icon d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2zM17 21v-8H7v8M7 3v5h8" />,
  Upload: () => <Icon d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12" />,
  Download: () => <Icon d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3" />,
  Plus: () => <Icon d="M12 5v14M5 12h14" />,
  Trash: () => <Icon d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />,
  Check: () => <Icon d="M20 6L9 17l-5-5" />,
  Eye: () => <Icon d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8zM12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z" />,
  EyeOff: () => <Icon d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24M1 1l22 22" />,
  Lock: () => <Icon d="M19 11H5a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7a2 2 0 0 0-2-2zM7 11V7a5 5 0 0 1 10 0v4" />,
  Zap: () => <Icon d="M13 2L3 14h9l-1 10 10-12h-9l1-10z" />,
  AlertTriangle: () => <Icon d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0zM12 9v4M12 17h.01" />,
  Wifi: () => <Icon d="M5 12.55a11 11 0 0 1 14.08 0M1.42 9a16 16 0 0 1 21.16 0M8.53 16.11a6 6 0 0 1 6.95 0M12 20h.01" />,
  Copy: () => <Icon d="M20 9h-9a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h9a2 2 0 0 0 2-2v-9a2 2 0 0 0-2-2zM5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />,
  Wand: () => <Icon d="M15 4V2M15 16v-2M8 9h2M20 9h2M17.8 11.8l1.4 1.4M17.8 6.2l1.4-1.4M12.2 11.8l-1.4 1.4M12.2 6.2l-1.4-1.4M2 22l10-10" />,
  GitBranch: () => <Icon d="M6 3v12M18 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM18 9a9 9 0 0 1-9 9" />,
  Play: () => <Icon d="M5 3l14 9-14 9V3z" />,
  ChevUp: () => <Icon d="M18 15l-6-6-6 6" />,
  ChevDown: () => <Icon d="M6 9l6 6 6-6" />,
  Grip: () => <Icon d="M9 4h0M9 9h0M9 14h0M15 4h0M15 9h0M15 14h0" size={16} />,
  Layout: () => <Icon d="M19 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2zM3 9h18M9 21V9" />,
  Terminal: () => <Icon d="M4 17l6-6-6-6M12 19h8" />,
  MessageSquare: () => <Icon d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />,
  Settings: () => <Icon d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />,
  Image: () => <Icon d="M19 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2zM8.5 10a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3zM21 15l-5-5L5 21" />,
  Film: () => <Icon d="M19.82 2H4.18A2.18 2.18 0 0 0 2 4.18v15.64A2.18 2.18 0 0 0 4.18 22h15.64A2.18 2.18 0 0 0 22 19.82V4.18A2.18 2.18 0 0 0 19.82 2zM7 2v20M17 2v20M2 12h20M2 7h5M2 17h5M17 17h5M17 7h5" />,
  Type: () => <Icon d="M4 7V4h16v3M9 20h6M12 4v16" />,
  Search: () => <Icon d="M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.35-4.35" />,
  ExternalLink: () => <Icon d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14L21 3" />,
  RefreshCw: () => <Icon d="M23 4v6h-6M1 20v-6h6M3.51 9a9 9 0 0 1 14.85-3.36M20.49 15a9 9 0 0 1-14.85 3.36" />,
  HelpCircle: () => <Icon d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10zM12 16v.01M12 13a2 2 0 0 0-2 2M12 13a2 2 0 0 1 2 2M9 9a3 3 0 0 1 6 0" />,
  Compass: () => <Icon d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10zM8 12l3-5 3 5-3 5-3-5z" />,
  Monitor: () => <Icon d="M20 3H4a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2zM4 17h16M9 21h6" />,
  Feather: () => <Icon d="M20.24 12.24a6 6 0 0 0-8.49-8.49L5 10.5V19h8.5zM16 8L2 22M17.5 15H9" />,
};

// ─── Utility ──────────────────────────────────────────────────────
function deepClone(o) { return JSON.parse(JSON.stringify(o)); }
function uid() { return Math.random().toString(36).slice(2, 9); }

// ─── Style constants ──────────────────────────────────────────────
const inputCls = "w-full bg-slate-900 border border-amber-500/20 rounded-lg px-3 py-2 text-amber-50 placeholder-slate-500 focus:border-amber-500/60 focus:ring-2 focus:ring-amber-500/30 outline-none transition-all text-sm";
const btnPrimary = "flex items-center gap-2 bg-amber-600 hover:bg-amber-500 text-white px-4 py-2 rounded-lg font-medium transition-colors text-sm shadow-lg shadow-amber-600/30";
const btnDanger = "flex items-center gap-2 bg-red-600/20 hover:bg-red-600/40 text-red-400 px-3 py-2 rounded-lg font-medium transition-colors text-sm";
const btnGhost = "flex items-center gap-2 bg-purple-700/20 hover:bg-purple-700/40 text-purple-300 px-3 py-2 rounded-lg font-medium transition-colors text-sm";
const btnSmall = "flex items-center gap-1 px-2 py-1 rounded text-xs font-medium transition-colors";

// ─── Tooltip Component ────────────────────────────────────────────
function Tip({ text }) {
  const [show, setShow] = useState(false);
  const [pos, setPos] = useState("top");
  const ref = useRef(null);

  const handleMouseEnter = () => {
    if (ref.current) {
      const rect = ref.current.getBoundingClientRect();
      setPos(rect.top > 100 ? "top" : "bottom");
    }
    setShow(true);
  };

  return (
    <div className="relative inline-block" ref={ref}>
      <button
        type="button"
        onMouseEnter={handleMouseEnter}
        onMouseLeave={() => setShow(false)}
        onClick={() => setShow(!show)}
        className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-amber-600/30 text-amber-400 hover:bg-amber-600/50 transition-colors ml-1"
      >
        <Icons.HelpCircle size={16} />
      </button>
      {show && (
        <div
          className={`absolute z-50 bg-slate-800 border border-amber-500/40 rounded-lg px-3 py-2 text-xs text-amber-50 max-w-xs animate-fadeIn ${
            pos === "top" ? "bottom-full mb-2" : "top-full mt-2"
          } left-1/2 transform -translate-x-1/2 whitespace-normal`}
          style={{
            animation: "fadeIn 0.2s ease-in-out",
            boxShadow: "0 4px 12px rgba(217, 119, 6, 0.2)",
          }}
        >
          {text}
          <div className={`absolute w-2 h-2 bg-slate-800 border-l border-t border-amber-500/40 transform rotate-45 ${
            pos === "top" ? "bottom-full -mb-1" : "top-full -mt-1"
          } left-1/2 -translate-x-1/2`} />
        </div>
      )}
      <style>{`
        @keyframes fadeIn {
          from { opacity: 0; transform: translateY(-4px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
}

// ─── Default config ───────────────────────────────────────────────
const DEFAULT_CONFIG = {
  phone_number: "+1XXXXXXXXXX",
  admin_number: "+1XXXXXXXXXX",
  signal_cli_path: "signal-cli-0.13.24",
  webui_url: "http://127.0.0.1:8080",
  webui_api_key: "",
  ollama_url: "http://127.0.0.1:11434",
  model: "",
  comfyui_url: "http://127.0.0.1:8188",
  comfyui_output_dir: "/opt/ComfyUI/output",
  comfyui_cleanup_minutes: 30,
  users: {},
  allowed_numbers: [],
  poll_interval: 2,
  max_history: 30,
  rate_limit: 20,
  rate_window: 60,
  system_prompt: "",
  google: { credentials_file: "", admin_email: "", scopes: [] },
  paths: { cases_dir: "", agent_dir: "", persona_portraits: "", mood_cache: "", sessions: "", knowledge: "", google_data: "", rag_index: "" },
  locations: {},
  courthouses: {},
  privacy: { clean_comfyui_input: true, clean_comfyui_output: true, cleanup_interval_minutes: 30, strip_metadata_on_send: true, auto_delete_generated: true },
};

// ═══════════════════════════════════════════════════════════════════
// SCAFFOLD DATA MODEL
// ═══════════════════════════════════════════════════════════════════

const PARAM_TYPES = ["text", "number", "choice", "image", "toggle", "slider"];
const STEP_TYPES = ["prompt", "choice", "param_collect", "confirm", "execute"];

const STEP_COLORS = {
  prompt: { bg: "bg-purple-900/25", border: "border-purple-600/40", dot: "bg-purple-500", label: "text-purple-300" },
  choice: { bg: "bg-teal-900/25", border: "border-teal-600/40", dot: "bg-teal-400", label: "text-teal-300" },
  param_collect: { bg: "bg-amber-900/25", border: "border-amber-600/40", dot: "bg-amber-500", label: "text-amber-300" },
  confirm: { bg: "bg-emerald-900/25", border: "border-emerald-600/40", dot: "bg-emerald-500", label: "text-emerald-300" },
  execute: { bg: "bg-red-900/25", border: "border-red-600/40", dot: "bg-red-500", label: "text-red-300" },
};

// ── LoRA Slot Definitions per workflow type ──
// Each workflow type declares what LoRA slots it supports.
// "list" slots accept multiple LoRAs; "single" slots accept exactly one.
// "format" is "model+clip" (full LoRA) or "model_only" (model-only).
// "arch" constrains which LoRA architectures are compatible.
const LORA_SLOT_DEFS = {
  txt2img: {
    arch: ["sd15", "sdxl", "illustrious", "flux1dev", "flux2klein", "chroma", "zit"],
    autoset_mode: "txt2img",
    slots: [
      { key: "loras", label: "Generation LoRAs", type: "list", format: "model+clip",
        help: "Applied to both model and CLIP. Quality/detail/style LoRAs." },
    ],
  },
  img2img: {
    arch: ["sd15", "sdxl", "illustrious", "flux1dev", "flux2klein", "chroma", "zit"],
    autoset_mode: "img2img",
    slots: [
      { key: "loras", label: "Transformation LoRAs", type: "list", format: "model+clip",
        help: "Applied to both model and CLIP during image transformation." },
    ],
  },
  inpaint: {
    arch: ["sd15", "sdxl", "illustrious", "flux1dev", "flux2klein"],
    autoset_mode: "inpaint",
    slots: [
      { key: "loras", label: "Inpaint LoRAs", type: "list", format: "model+clip",
        help: "Applied during inpainting. Use lower strength (0.2-0.5) to avoid artifacts." },
    ],
  },
  detail_hallucinate: {
    arch: ["sd15", "sdxl", "illustrious"],
    autoset_mode: "hallucinate",
    slots: [
      { key: "loras", label: "Detail LoRAs", type: "list", format: "model+clip",
        help: "Detail/quality LoRAs for hallucination pass." },
    ],
  },
  wan_i2v: {
    arch: ["wan"],
    slots: [
      { key: "high_accel_lora", label: "Turbo LoRA (High Model)", type: "single", format: "model_only",
        help: "Acceleration LoRA for the high-quality UNET. Auto-detected: LightX2V / Lightning I2V.",
        preset_key: "wan.high_accel_lora" },
      { key: "low_accel_lora", label: "Turbo LoRA (Low Model)", type: "single", format: "model_only",
        help: "Acceleration LoRA for the low-quality UNET. Usually same family as high.",
        preset_key: "wan.low_accel_lora" },
      { key: "loras_high", label: "High Model LoRAs", type: "list", format: "model_only",
        help: "Additional LoRAs for the high-quality model. Style, detail, etc." },
      { key: "loras_low", label: "Low Model LoRAs", type: "list", format: "model_only",
        help: "Additional LoRAs for the low-quality model. Usually mirror loras_high." },
    ],
  },
  wan_director: {
    arch: ["wan"],
    slots: [
      { key: "high_accel_lora", label: "Turbo LoRA (High)", type: "single", format: "model_only",
        help: "Acceleration LoRA for high-quality UNET.", preset_key: "wan.high_accel_lora" },
      { key: "low_accel_lora", label: "Turbo LoRA (Low)", type: "single", format: "model_only",
        help: "Acceleration LoRA for low-quality UNET.", preset_key: "wan.low_accel_lora" },
      { key: "loras_high", label: "High Model LoRAs", type: "list", format: "model_only" },
      { key: "loras_low", label: "Low Model LoRAs", type: "list", format: "model_only" },
    ],
  },
  ltx_t2v: {
    arch: ["ltx"],
    slots: [
      { key: "distilled_lora", label: "Distilled LoRA (Speed)", type: "single", format: "model_only",
        help: "Distillation LoRA for 8-step mode. Auto-detected from installed models.",
        preset_key: "ltx.distilled_lora" },
      { key: "loras", label: "Additional LoRAs", type: "list", format: "model_only",
        help: "Style/quality LoRAs for LTX video generation." },
    ],
  },
  ltx_i2v: {
    arch: ["ltx"],
    slots: [
      { key: "distilled_lora", label: "Distilled LoRA (Speed)", type: "single", format: "model_only",
        help: "Distillation LoRA for fast mode.", preset_key: "ltx.distilled_lora" },
      { key: "loras", label: "Additional LoRAs", type: "list", format: "model_only" },
    ],
  },
  klein_img2img: {
    arch: ["flux2klein"],
    autoset_mode: "img2img",
    slots: [
      { key: "loras", label: "Klein LoRAs", type: "list", format: "model+clip",
        help: "LoRAs for Flux 2 Klein editing." },
    ],
  },
  faceid: {
    arch: ["sd15", "sdxl", "illustrious"],
    slots: [
      { key: "loras", label: "FaceID LoRAs", type: "list", format: "model+clip",
        help: "Additional LoRAs applied during FaceID generation." },
    ],
  },
};

function newParam() {
  return { id: uid(), name: "", type: "text", label: "", default: "", min: "", max: "", options: [], help: "", required: true, comfyui_node: "", comfyui_param: "" };
}

function newPreset() {
  return { id: uid(), name: "", description: "", values: {} };
}

function newStep(type = "prompt") {
  return {
    id: uid(), type, name: "",
    // prompt step
    message_template: "",
    // choice step
    options: [],
    // param_collect step
    params: [],
    // confirm step
    summary_template: "Here are your settings:\n{params}\n\n1. Confirm\n2. Change a setting\n3. Start over",
    // execute step — supports both parsed workflows and legacy builder functions
    comfyui_workflow: "",       // legacy: builder function name (e.g. "_build_txt2img")
    workflow_source: "parsed",  // "parsed" | "builder" | "uploaded"
    workflow_json: null,        // the actual parsed workflow JSON (API format)
    workflow_path: "",          // path to original workflow file
    timeout: 300,
    // branching
    next_step: null, // null = next in order
    branches: {}, // { "option_value": step_id }
  };
}

// ═══════════════════════════════════════════════════════════════════
// BUILT-IN SCAFFOLDS — pre-populated in the editor for all pipelines
// ═══════════════════════════════════════════════════════════════════

function builtInScaffolds() {
  const defs = [
    // ── Image Generation ──
    { name: "Text-to-Image", key: "txt2img", icon: "Image", type: "Image Generation",
      desc: "Generate images from text prompts. Supports SD 1.5, SDXL, ZIT, Flux Dev, Flux Klein, Illustrious.",
      greeting: "What image would you like to create? Describe it or pick a style preset:",
      params: [
        { name: "prompt", type: "text", label: "Prompt", help: "Describe what you want to see" },
        { name: "negative", type: "text", label: "Negative Prompt", help: "Things to avoid" },
        { name: "width", type: "number", label: "Width", default: "1024", min: "256", max: "2048" },
        { name: "height", type: "number", label: "Height", default: "1024", min: "256", max: "2048" },
        { name: "steps", type: "number", label: "Steps", default: "25", min: "1", max: "50" },
        { name: "cfg", type: "number", label: "CFG Scale", default: "7.0", min: "1", max: "20" },
        { name: "seed", type: "number", label: "Seed (-1 = random)", default: "-1" },
      ]},
    { name: "Image-to-Image", key: "img2img", icon: "Image", type: "Image Transformation",
      desc: "Transform existing images — change style, add detail, reimagine. Per-model presets, LoRA injection, dual ControlNet.",
      greeting: "Upload or select an image to transform. What style or change do you want?",
      params: [
        { name: "prompt", type: "text", label: "Style Prompt" },
        { name: "denoise", type: "slider", label: "Denoise Strength", default: "0.55", min: "0.1", max: "1.0", help: "0.3=subtle, 0.7=heavy" },
        { name: "steps", type: "number", label: "Steps", default: "25" },
      ]},
    { name: "Inpainting", key: "inpaint", icon: "Image", type: "Image Editing",
      desc: "Paint over any area to regenerate it. 44 expert presets with body-part-tuned denoise values.",
      greeting: "Select an area to regenerate. What should appear in the masked region?",
      params: [
        { name: "prompt", type: "text", label: "What to paint" },
        { name: "denoise", type: "slider", label: "Denoise", default: "0.75", min: "0.3", max: "1.0" },
      ]},
    { name: "Outpainting", key: "outpaint", icon: "Image", type: "Image Editing",
      desc: "Extend images beyond their borders in any direction.",
      greeting: "Which direction would you like to extend the canvas?",
      params: [
        { name: "prompt", type: "text", label: "Extension prompt" },
        { name: "padding_top", type: "number", label: "Top padding", default: "0" },
        { name: "padding_bottom", type: "number", label: "Bottom padding", default: "128" },
        { name: "padding_left", type: "number", label: "Left padding", default: "0" },
        { name: "padding_right", type: "number", label: "Right padding", default: "0" },
      ]},
    // ── Klein Suite ──
    { name: "Klein Image Editor", key: "klein_img2img", icon: "Image", type: "Klein Flux 2",
      desc: "Best-quality img2img using Flux 2 Klein 9B/4B. The most advanced image editor available.",
      greeting: "What changes do you want to make to your image?",
      params: [
        { name: "prompt", type: "text", label: "Edit instruction" },
        { name: "denoise", type: "slider", label: "Strength", default: "0.55", min: "0.1", max: "1.0" },
        { name: "model", type: "choice", label: "Klein Model", options: [{ label: "9B (Best)", value: "9b" }, { label: "4B (Fast)", value: "4b" }] },
      ]},
    { name: "Klein Inpaint", key: "klein_inpaint", icon: "Image", type: "Klein Flux 2",
      desc: "Context-aware selection fill with smooth edges. 29 task presets.",
      greeting: "Select the area to regenerate. What should appear there?",
      params: [
        { name: "prompt", type: "text", label: "Inpaint prompt" },
        { name: "denoise", type: "slider", label: "Strength", default: "0.85", min: "0.3", max: "1.0" },
      ]},
    { name: "Klein Re-poser", key: "klein_repose", icon: "Image", type: "Klein Flux 2",
      desc: "Change character poses and positions. 26 poses, 8 camera angles.",
      greeting: "What pose do you want the character in?",
      params: [
        { name: "pose", type: "choice", label: "Pose", options: [
          { label: "Standing", value: "standing" }, { label: "Sitting", value: "sitting" },
          { label: "Walking", value: "walking" }, { label: "Running", value: "running" },
          { label: "Action Pose", value: "action" }, { label: "Custom...", value: "custom" },
        ]},
      ]},
    // ── Upscaling & Restoration ──
    { name: "AI Upscale", key: "upscale", icon: "Image", type: "Restoration",
      desc: "Make any image larger and sharper. 6 upscale models (UltraSharp, RealESRGAN, etc).",
      greeting: "Which upscale model would you like to use?",
      params: [
        { name: "model", type: "choice", label: "Upscale Model", options: [
          { label: "4x UltraSharp", value: "ultrasharp" }, { label: "RealESRGAN x4", value: "realesrgan" },
          { label: "4x Remacri", value: "remacri" }, { label: "Anime 4x", value: "anime" },
        ]},
      ]},
    { name: "Photo Restoration", key: "photo_restore", icon: "Image", type: "Restoration",
      desc: "One-click pipeline: upscale + face fix + sharpen. Multi-stage combined workflow.",
      greeting: "Upload a photo to restore. Choose restoration intensity:",
      params: [
        { name: "preset", type: "choice", label: "Preset", options: [
          { label: "Quick Fix", value: "quick" }, { label: "Full Restoration", value: "full" },
          { label: "Cinematic (2-stage + RTX + RIFE)", value: "cinematic" },
        ]},
      ]},
    { name: "SUPIR Restoration", key: "supir", icon: "Image", type: "Restoration",
      desc: "State-of-the-art AI photo repair using the SUPIR model.",
      greeting: "Upload a damaged or low-quality photo to restore:",
      params: [
        { name: "denoise", type: "slider", label: "Restoration Strength", default: "0.40", min: "0.1", max: "0.8" },
      ]},
    { name: "Detail Hallucination", key: "detail_hallucinate", icon: "Image", type: "Restoration",
      desc: "Add fine texture detail that wasn't there. Upscale + low-denoise img2img pass.",
      greeting: "Upload an image to enhance with hallucinated detail:",
      params: [
        { name: "denoise", type: "slider", label: "Detail Amount", default: "0.35", min: "0.1", max: "0.6" },
      ]},
    // ── Face & Identity ──
    { name: "Face Swap (ReActor)", key: "faceswap", icon: "Image", type: "Face & Identity",
      desc: "Paste a face from one photo onto another. Direct source-to-target with optional face restoration.",
      greeting: "Upload the source face and target image:",
      params: [
        { name: "quality", type: "choice", label: "Quality", options: [
          { label: "High (ReSwapper 256 + GPEN)", value: "high" },
          { label: "Fast (InSwapper 128)", value: "fast" },
        ]},
      ]},
    { name: "FaceID (IPAdapter)", key: "faceid", icon: "Image", type: "Face & Identity",
      desc: "Generate images that look like a specific person. FACEID, PLUS V2, PORTRAIT presets.",
      greeting: "Upload a reference face. What scene should they appear in?",
      params: [
        { name: "prompt", type: "text", label: "Scene description" },
        { name: "weight", type: "slider", label: "Face strength", default: "0.85", min: "0.3", max: "1.0" },
      ]},
    { name: "PuLID Flux", key: "pulid", icon: "Image", type: "Face & Identity",
      desc: "Flux-native identity preservation at the attention level (not post-processing).",
      greeting: "Upload a face reference. Describe the target image:",
      params: [
        { name: "prompt", type: "text", label: "Image description" },
      ]},
    // ── Style & Lighting ──
    { name: "IC-Light Relighting", key: "iclight", icon: "Image", type: "Style & Lighting",
      desc: "Change lighting direction on any photo. 10 presets: Left, Right, Top, Bottom, Golden Hour, Neon, etc.",
      greeting: "Choose a lighting direction for your photo:",
      params: [
        { name: "light_preset", type: "choice", label: "Light Direction", options: [
          { label: "Left", value: "left" }, { label: "Right", value: "right" },
          { label: "Top", value: "top" }, { label: "Golden Hour", value: "golden" },
          { label: "Neon", value: "neon" }, { label: "Dramatic", value: "dramatic" },
        ]},
      ]},
    { name: "Style Transfer", key: "style_transfer", icon: "Image", type: "Style & Lighting",
      desc: "Copy the visual style of any reference image. IPAdapter-based, adjustable strength.",
      greeting: "Upload a style reference and a target image:",
      params: [
        { name: "strength", type: "slider", label: "Style strength", default: "0.8", min: "0.3", max: "1.0" },
      ]},
    // ── Video Generation ──
    { name: "WAN 2.2 Image-to-Video", key: "wan_i2v", icon: "Film", type: "Video Generation",
      desc: "Turn any photo into a 2-5 second video. Dual-UNET 14B, 26 motion presets, pingpong looping.",
      greeting: "Upload an image to animate. Choose a motion style:",
      params: [
        { name: "prompt", type: "text", label: "Motion description", help: "e.g. 'gentle breathing, hair sway'" },
        { name: "length", type: "number", label: "Frames", default: "81", min: "17", max: "129" },
        { name: "turbo", type: "toggle", label: "Turbo mode (4 steps)", default: "true" },
      ]},
    { name: "LTX 2.3 Text-to-Video", key: "ltx_t2v", icon: "Film", type: "Video Generation",
      desc: "Generate video from text — no input image needed. 80 prompt templates, hardware auto-detect.",
      greeting: "Describe the video you want to create:",
      params: [
        { name: "prompt", type: "text", label: "Video description" },
        { name: "width", type: "number", label: "Width", default: "768" },
        { name: "height", type: "number", label: "Height", default: "512" },
        { name: "frames", type: "number", label: "Frames", default: "97" },
      ]},
    { name: "LTX 2.3 Image-to-Video", key: "ltx_i2v", icon: "Film", type: "Video Generation",
      desc: "Animate any photo with text guidance. Same pipeline as T2V with image conditioning.",
      greeting: "Upload an image. How should it animate?",
      params: [
        { name: "prompt", type: "text", label: "Animation prompt" },
        { name: "strength", type: "slider", label: "Image influence", default: "0.85", min: "0.3", max: "1.0" },
      ]},
    { name: "Director's Chair", key: "wan_director", icon: "Film", type: "Video Generation",
      desc: "Multi-step video sequences with face re-injection between shots. Solo, Duo, and Trio actor modes.",
      greeting: "How many actors in this scene? Choose a director script:",
      params: [
        { name: "actors", type: "choice", label: "Actors", options: [
          { label: "Solo (1 actor)", value: "solo" }, { label: "Duo (2 actors)", value: "duo" },
          { label: "Trio (3 actors)", value: "trio" },
        ]},
        { name: "script", type: "choice", label: "Script", options: [
          { label: "Dramatic Reveal", value: "reveal" }, { label: "Living Portrait", value: "portrait" },
          { label: "Walk Cycle", value: "walk" }, { label: "Emotional Arc", value: "arc" },
        ]},
      ]},
    // ── Video Post-Processing ──
    { name: "SeedVR2 Video Upscale", key: "seedvr2", icon: "Film", type: "Video Upscale",
      desc: "AI video upscaling with hallucination control. 3B DiT model, batch processing.",
      greeting: "Upload a video to upscale. Choose quality:",
      params: [
        { name: "hallucination", type: "choice", label: "Detail Level", options: [
          { label: "None (preserve)", value: "none" }, { label: "Light", value: "light" }, { label: "High", value: "high" },
        ]},
      ]},
    { name: "Video Face Swap", key: "video_reactor", icon: "Film", type: "Video Post-Processing",
      desc: "Face swap across video frames with ReActor + upscale.",
      greeting: "Upload a video and a face reference:",
      params: [] },
    // ── Utility ──
    { name: "Remove Background", key: "rembg", icon: "Image", type: "Utility",
      desc: "One-click transparent PNG using rembg segmentation model.",
      greeting: "Upload an image to remove the background from:",
      params: [] },
    { name: "Object Removal (LaMa)", key: "lama", icon: "Image", type: "Utility",
      desc: "Paint over anything to erase it — no prompt needed. LaMa inpainting.",
      greeting: "Select the object to remove by painting a mask over it:",
      params: [] },
    // ── Magic Studios ──
    { name: "Casting Polaroids", key: "photobooth", icon: "Image", type: "Magic Studios",
      desc: "Create a reusable face model from any photo. 3 face restore variants.",
      greeting: "Upload a clear face photo for casting:",
      params: [
        { name: "variant", type: "choice", label: "Quality", options: [
          { label: "CodeFormer Sharp", value: "sharp" }, { label: "GPEN-2048 Balanced", value: "balanced" },
          { label: "CodeFormer Faithful", value: "faithful" },
        ]},
      ]},
    { name: "Body Double", key: "body_factory", icon: "Image", type: "Magic Studios",
      desc: "Generate full-body references with face swap + transparent background removal.",
      greeting: "Describe the body type, clothing, and pose:",
      params: [
        { name: "prompt", type: "text", label: "Body description" },
      ]},
    { name: "Wardrobe Department", key: "clothing_store", icon: "Image", type: "Magic Studios",
      desc: "AI outfit replacement. 50+ presets from casual to fantasy to cultural.",
      greeting: "What outfit should the character wear?",
      params: [
        { name: "outfit", type: "text", label: "Outfit description" },
        { name: "denoise", type: "slider", label: "Change strength", default: "0.85", min: "0.3", max: "0.95" },
      ]},
    { name: "Set Design", key: "studio_set", icon: "Image", type: "Magic Studios",
      desc: "Generate backgrounds and composite actors with AI lighting harmonization.",
      greeting: "Describe the scene, or choose from 20+ presets:",
      params: [
        { name: "scene", type: "text", label: "Scene description" },
        { name: "actors", type: "number", label: "Number of actors", default: "1", min: "0", max: "3" },
      ]},
    // ── ControlNet ──
    { name: "ControlNet Generation", key: "controlnet", icon: "Image", type: "ControlNet",
      desc: "Guide AI using edges, depth, poses, or sketches. Canny, MiDaS, OpenPose, Scribble, LineArt, Tile.",
      greeting: "Choose a ControlNet mode:",
      params: [
        { name: "preprocessor", type: "choice", label: "Preprocessor", options: [
          { label: "Canny Edge", value: "canny" }, { label: "Depth (MiDaS)", value: "depth" },
          { label: "OpenPose", value: "openpose" }, { label: "Scribble", value: "scribble" },
          { label: "LineArt", value: "lineart" }, { label: "Tile", value: "tile" },
        ]},
        { name: "prompt", type: "text", label: "Generation prompt" },
      ]},
  ];

  return defs.map(d => ({
    id: uid(),
    name: d.name,
    description: d.desc,
    icon: d.icon || "Image",
    workflow_key: d.key,
    workflow_source: { type: "builder", path: "", workflow_type: d.type, node_count: 0, category: d.type },
    nsfw: false,
    admin_only: false,
    steps: [
      { ...newStep("prompt"), name: "Greeting", message_template: d.greeting },
      { ...newStep("choice"), name: "Mode", options: [
        { label: "Use a Preset", value: "preset" },
        { label: "Custom (step by step)", value: "custom" },
        { label: "All Defaults", value: "defaults" },
      ]},
      { ...newStep("param_collect"), name: "Parameters", params: d.params.map(p => ({
        ...newParam(), ...p, id: uid(), required: p.required !== false,
        options: (p.options || []).map(o => typeof o === "string" ? { label: o, value: o } : o),
      }))},
      { ...newStep("confirm"), name: "Review" },
      { ...newStep("execute"), name: "Generate", comfyui_workflow: d.key, workflow_source: "builder" },
    ],
    presets: [],
    lora_config: {},
    system_prompt_header: `You are guiding a user through the "${d.name}" workflow.\n${d.desc}\nPresent numbered choices. Keep replies short and clear.`,
    system_prompt_rules: [
      "Present numbered choices for every decision",
      "Accept 'd' or empty input as 'use default'",
      "Show parameter name, range, and default for each param",
      "After all params collected, show confirmation summary",
      "On confirm, output the final JSON and signal ready to execute",
    ],
  }));
}

function newScaffold() {
  return {
    id: uid(),
    name: "New Workflow",
    description: "",
    icon: "Image",
    workflow_key: "",
    workflow_source: null,    // null | { type: "parsed"|"uploaded"|"builder", path, workflow_type, node_count, category }
    nsfw: false,
    admin_only: false,
    steps: [
      { ...newStep("prompt"), name: "Greeting", message_template: "What would you like to create? Type your idea or pick a preset:" },
      { ...newStep("choice"), name: "Mode", options: [{ label: "Use a Preset", value: "preset" }, { label: "Custom (step by step)", value: "custom" }, { label: "All Defaults", value: "defaults" }] },
      { ...newStep("param_collect"), name: "Parameters", params: [newParam()] },
      { ...newStep("confirm"), name: "Review" },
      { ...newStep("execute"), name: "Generate" },
    ],
    presets: [],
    lora_config: {},  // Per-slot LoRA configuration (managed by LoRA tab)
    system_prompt_header: "You are guiding a user through a ComfyUI workflow via text message.\nAlways present numbered choices. Keep replies short and clear.\nNever invent parameter values — only use what the user chose or the defaults.",
    system_prompt_rules: [
      "Present numbered choices for every decision",
      "Accept 'd' or empty input as 'use default'",
      "Show parameter name, range, and default for each param",
      "After all params collected, show confirmation summary",
      "On confirm, output the final JSON and signal ready to execute",
    ],
  };
}

// Generate a scaffold from a parsed workflow's tunable parameters
function scaffoldFromParsedWorkflow(wf) {
  const params = (wf.tunable_params || []).map(p => ({
    id: uid(),
    name: p.name || p.param_name || "",
    type: mapComfyType(p.type || p.widget_type || "STRING"),
    label: p.display_name || p.name || p.param_name || "",
    default: p.default != null ? String(p.default) : "",
    min: p.min != null ? String(p.min) : "",
    max: p.max != null ? String(p.max) : "",
    options: p.choices || p.options || [],
    help: p.tooltip || "",
    required: p.priority === "HIGH" || !p.optional,
    comfyui_node: p.node_id || p.node_title || "",
    comfyui_param: p.input_name || p.name || "",
  }));

  const hasPrompts = params.some(p => p.name.toLowerCase().includes("prompt") || p.name.toLowerCase().includes("text"));
  const hasModels = params.some(p => p.name.toLowerCase().includes("model") || p.name.toLowerCase().includes("ckpt"));

  return {
    id: uid(),
    name: wf.name || wf.filename || "Imported Workflow",
    description: `${wf.workflow_type || "General"} workflow with ${wf.node_count || "?"} nodes. Auto-imported from ComfyUI.`,
    icon: workflowTypeIcon(wf.workflow_type),
    workflow_key: (wf.name || "").toLowerCase().replace(/[^a-z0-9]+/g, "_"),
    workflow_source: {
      type: "parsed",
      path: wf.path || "",
      workflow_type: wf.workflow_type || "General",
      node_count: wf.node_count || 0,
      category: wf.category || "root",
    },
    nsfw: false,
    admin_only: false,
    steps: [
      { ...newStep("prompt"), name: "Greeting", message_template: `${wf.workflow_type || "Workflow"}: ${wf.name || "Untitled"}\n\nWhat would you like to create?${hasPrompts ? " Describe your idea or pick a preset:" : " Choose a preset or configure step by step:"}` },
      { ...newStep("choice"), name: "Mode", options: [
        { label: "Use a Preset", value: "preset" },
        { label: "Custom (step by step)", value: "custom" },
        { label: "All Defaults", value: "defaults" },
      ]},
      { ...newStep("param_collect"), name: "Parameters", params: params.length > 0 ? params : [newParam()] },
      { ...newStep("confirm"), name: "Review" },
      {
        ...newStep("execute"),
        name: "Generate",
        workflow_source: "parsed",
        workflow_json: wf.api_workflow || null,
        workflow_path: wf.path || "",
        comfyui_workflow: "",
      },
    ],
    presets: [],
    system_prompt_header: `You are guiding a user through a ComfyUI ${wf.workflow_type || ""} workflow via text message.\nWorkflow: ${wf.name || "Untitled"} (${wf.node_count || "?"} nodes)\nAlways present numbered choices. Keep replies short and clear.\nNever invent parameter values — only use what the user chose or the defaults.${hasModels ? "\nModel selection is dynamic — show whatever models are available on the server." : ""}`,
    system_prompt_rules: [
      "Present numbered choices for every decision",
      "Accept 'd' or empty input as 'use default'",
      "Show parameter name, range, and default for each param",
      "After all params collected, show confirmation summary",
      "On confirm, output the final JSON and signal ready to execute",
      ...(hasModels ? ["Model names come from the server — never hardcode model filenames"] : []),
    ],
  };
}

// Map ComfyUI types to our param types
function mapComfyType(t) {
  if (!t) return "text";
  const up = t.toUpperCase();
  if (up === "INT" || up === "FLOAT") return "number";
  if (up === "BOOLEAN") return "toggle";
  if (up === "IMAGE") return "image";
  if (up === "COMBO" || up === "ENUM") return "choice";
  return "text";
}

// Map workflow types to icons
function workflowTypeIcon(type) {
  const map = {
    "Text-to-Image": "Image", "Image-to-Image": "Image", "Inpainting": "Image",
    "Text-to-Video": "Film", "Image-to-Video": "Film",
    "Face Swap": "Users", "Upscale": "Zap", "Style Transfer": "Wand",
    "ControlNet": "GitBranch", "Audio/Music": "Wifi", "3D Generation": "Layout",
    "Captioning": "Type",
  };
  return map[type] || "Image";
}

// Legacy hardcoded templates kept for backwards compatibility but no longer primary
const LEGACY_BUILDER_TEMPLATES = [
  { label: "Klein 4B Text-to-Image", icon: "Image", workflow_key: "txt2img", builder: "_build_txt2img" },
  { label: "Klein 4B Image-to-Image", icon: "Image", workflow_key: "img2img", builder: "_build_klein_img2img" },
  { label: "WAN 2.2 Image-to-Video", icon: "Film", workflow_key: "wan_i2v", builder: "_build_wan_i2v" },
  { label: "Upscale (SUPIR)", icon: "Zap", workflow_key: "upscale", builder: "_build_upscale" },
  { label: "Face Swap", icon: "Users", workflow_key: "faceswap", builder: "_build_faceswap" },
  { label: "Spellcaster Enhancement", icon: "Wand", workflow_key: "spellcaster", builder: "_build_spellcaster" },
];

// ─── Tool Detection Definitions ────────────────────────────────────
// Each tool declares either `urlConfigKey` (resolved from live config)
// or `defaultUrl` (a sane local-host default). `configureTab` is the
// SignalBridgeSettings tab the "Setup" button jumps the user to.
const TOOL_DEFINITIONS = [
  {
    id: "sillytavern",
    name: "SillyTavern",
    icon: Icons.MessageSquare,
    defaultUrl: "http://localhost:8000",
    configureTab: "paths",
    description: "Full-featured AI chat interface with character cards, lorebooks, and group chats",
    setupSteps: [
      "Download SillyTavern from https://github.com/SillyTavern/SillyTavern",
      "Extract and run node_modules installation",
      "Start the server (default port 8000)",
      "The bridge will auto-detect when running"
    ]
  },
  {
    id: "openwebui",
    name: "Open WebUI",
    icon: Icons.Monitor,
    urlConfigKey: "webui_url",
    configureTab: "network",
    description: "Open-source ChatGPT-style interface with model management",
    setupSteps: [
      "Install via Docker: docker run -d -p 8080:8080 ghcr.io/open-webui/open-webui:latest",
      "Access at http://localhost:8080",
      "Generate an API key in Settings → Account → API Keys",
      "Update the webui_url in Network settings"
    ]
  },
  {
    id: "lmstudio",
    name: "LM Studio",
    icon: Icons.Server,
    defaultUrl: "http://localhost:1234",
    configureTab: "network",
    description: "Desktop app for running local LLMs with OpenAI-compatible API",
    setupSteps: [
      "Download LM Studio from https://lmstudio.ai",
      "Select and load a model from the library",
      "Start the local server (default port 1234)",
      "Configure model in Advanced settings"
    ]
  },
  {
    id: "koboldcpp",
    name: "KoboldCpp",
    icon: Icons.Zap,
    defaultUrl: "http://localhost:5001",
    configureTab: "network",
    description: "Lightweight local LLM server optimized for roleplay and stories",
    setupSteps: [
      "Download KoboldCpp from https://github.com/LostRuins/koboldcpp",
      "Load a GGUF quantized model",
      "Launch with default port 5001",
      "Access API at http://localhost:5001"
    ]
  },
  {
    id: "comfyui",
    name: "ComfyUI",
    icon: Icons.Image,
    urlConfigKey: "comfyui_url",
    configureTab: "network",
    description: "Node-based image generation pipeline with Spellcaster nodes",
    setupSteps: [
      "Clone ComfyUI: git clone https://github.com/comfyanonymous/ComfyUI.git",
      "Install Spellcaster custom nodes in custom_nodes folder",
      "Run: python main.py",
      "Verify Spellcaster nodes are loaded in the UI"
    ]
  },
  {
    id: "ollama",
    name: "Ollama",
    icon: Icons.Server,
    urlConfigKey: "ollama_url",
    configureTab: "network",
    description: "Local LLM runner with a simple HTTP API and model library",
    setupSteps: [
      "Download from https://ollama.com",
      "ollama pull llama3 (or any model)",
      "ollama serve (default port 11434)",
      "Update ollama_url in Network settings"
    ]
  }
];

// ═══════════════════════════════════════════════════════════════════
// SCAFFOLD EDITOR COMPONENTS
// ═══════════════════════════════════════════════════════════════════

// ─── Step Card ────────────────────────────────────────────────────

function StepCard({ step, index, total, isSelected, onSelect, onMove, onDelete }) {
  const colors = STEP_COLORS[step.type] || STEP_COLORS.prompt;
  return (
    <div className="flex items-stretch gap-0">
      {/* Connection line */}
      <div className="flex flex-col items-center w-8 flex-shrink-0">
        {index > 0 && <div className="w-0.5 flex-1 bg-amber-600/30" />}
        <div className={`w-4 h-4 rounded-full ${colors.dot} flex-shrink-0 ring-2 ring-slate-900 ${isSelected ? "ring-amber-500" : ""}`} style={{boxShadow: isSelected ? "0 0 8px rgba(217, 119, 6, 0.5)" : ""}} />
        {index < total - 1 && <div className="w-0.5 flex-1 bg-amber-600/30" />}
      </div>

      {/* Card */}
      <button
        onClick={onSelect}
        className={`flex-1 ${colors.bg} border ${isSelected ? "border-amber-500 ring-1 ring-amber-500/50" : colors.border} rounded-lg px-4 py-3 text-left transition-all hover:brightness-110 my-1`}
        style={{boxShadow: isSelected ? "0 0 12px rgba(217, 119, 6, 0.3)" : ""}}
      >
        <div className="flex items-center gap-2">
          <span className={`text-xs font-mono uppercase tracking-wider ${colors.label}`}>{step.type.replace("_", " ")}</span>
          <span className="text-xs text-slate-400">#{index + 1}</span>
          <div className="flex-1" />
          {/* Move buttons */}
          <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100" onClick={e => e.stopPropagation()}>
            {index > 0 && (
              <span onClick={() => onMove(index, index - 1)} className="p-0.5 hover:bg-purple-700/40 rounded cursor-pointer text-slate-500 hover:text-amber-400">
                <Icons.ChevUp />
              </span>
            )}
            {index < total - 1 && (
              <span onClick={() => onMove(index, index + 1)} className="p-0.5 hover:bg-purple-700/40 rounded cursor-pointer text-slate-500 hover:text-amber-400">
                <Icons.ChevDown />
              </span>
            )}
          </div>
        </div>
        <p className="text-sm font-medium text-amber-50 mt-1">{step.name || "(unnamed step)"}</p>
        {step.type === "prompt" && step.message_template && (
          <p className="text-xs text-slate-400 mt-1 truncate">{step.message_template.slice(0, 60)}...</p>
        )}
        {step.type === "choice" && (
          <p className="text-xs text-slate-400 mt-1">{step.options?.length || 0} options</p>
        )}
        {step.type === "param_collect" && (
          <p className="text-xs text-slate-400 mt-1">{step.params?.length || 0} parameters</p>
        )}
      </button>
    </div>
  );
}

// ─── Step Detail Editor ───────────────────────────────────────────

function StepEditor({ step, onChange, onDelete, scaffold }) {
  const update = (key, val) => onChange({ ...step, [key]: val });

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className={`w-3 h-3 rounded-full ${(STEP_COLORS[step.type] || STEP_COLORS.prompt).dot}`} />
          <span className="text-sm font-mono text-slate-300 uppercase">{step.type.replace("_", " ")}</span>
        </div>
        <button onClick={onDelete} className={btnDanger + " text-xs py-1 px-2"}>
          <Icons.Trash /> Remove
        </button>
      </div>

      {/* Name */}
      <div>
        <label className="block text-xs font-medium text-amber-200 mb-1">Step Name</label>
        <input value={step.name} onChange={e => update("name", e.target.value)} placeholder="e.g. Greeting, Mode Select, Parameters..." className={inputCls} />
      </div>

      {/* Type selector */}
      <div>
        <label className="block text-xs font-medium text-amber-200 mb-1">Step Type</label>
        <div className="flex gap-1 flex-wrap">
          {STEP_TYPES.map(t => (
            <button key={t} onClick={() => update("type", t)}
              className={`${btnSmall} ${step.type === t ? `${STEP_COLORS[t].bg} ${STEP_COLORS[t].label} border ${STEP_COLORS[t].border}` : "bg-slate-800/50 text-slate-500 hover:text-amber-300"}`}>
              {t.replace("_", " ")}
            </button>
          ))}
        </div>
      </div>

      {/* Type-specific editors */}
      {step.type === "prompt" && (
        <div>
          <label className="block text-xs font-medium text-amber-200 mb-1">Message Template</label>
          <textarea value={step.message_template || ""} onChange={e => update("message_template", e.target.value)}
            rows={4} placeholder="What the LLM should say at this step. Use {param_name} for interpolation."
            className={inputCls + " resize-y font-mono text-xs"} />
          <p className="text-xs text-slate-400 mt-1">Variables: {"{user_name}"}, {"{workflow_name}"}, {"{param_name}"}</p>
        </div>
      )}

      {step.type === "choice" && <ChoiceEditor options={step.options || []} onChange={opts => update("options", opts)} scaffold={scaffold} />}

      {step.type === "param_collect" && <ParamListEditor params={step.params || []} onChange={p => update("params", p)} />}

      {step.type === "confirm" && (
        <div>
          <label className="block text-xs font-medium text-amber-200 mb-1">Confirmation Template</label>
          <textarea value={step.summary_template || ""} onChange={e => update("summary_template", e.target.value)}
            rows={5} placeholder="Summary shown before execution. {params} is replaced with the collected values."
            className={inputCls + " resize-y font-mono text-xs"} />
        </div>
      )}

      {step.type === "execute" && (
        <ExecuteStepEditor step={step} onChange={onChange} />
      )}

      {/* Branching */}
      <div className="border-t border-amber-600/20 pt-3">
        <label className="block text-xs font-medium text-amber-200 mb-2">Flow Control</label>
        <div className="flex items-center gap-2"></div>
      </div>
    </div>
  );
}

// ─── Choice Editor ────────────────────────────────────────────────

function ChoiceEditor({ options, onChange, scaffold }) {
  const addOption = () => onChange([...options, { label: "", value: "", next_step: null }]);
  const removeOption = (i) => onChange(options.filter((_, idx) => idx !== i));
  const updateOption = (i, field, val) => { const opts = [...options]; opts[i][field] = val; onChange(opts); };

  return (
    <div className="space-y-3">
      <label className="block text-xs font-medium text-amber-200">Choice Options</label>
      {options.map((opt, i) => (
        <div key={i} className="bg-slate-800/50 rounded-lg p-3 space-y-2">
          <div className="grid grid-cols-2 gap-2">
            <input value={opt.label} onChange={e => updateOption(i, "label", e.target.value)} placeholder="Display label" className={inputCls} />
            <input value={opt.value} onChange={e => updateOption(i, "value", e.target.value)} placeholder="Option value" className={inputCls} />
          </div>
          <button onClick={() => removeOption(i)} className={btnDanger + " w-full text-xs justify-center"}><Icons.Trash /> Remove</button>
        </div>
      ))}
      <button onClick={addOption} className={btnSmall + " bg-purple-800/40 text-purple-300 hover:text-amber-300"}><Icons.Plus /> Add Option</button>
    </div>
  );
}

// ─── Param List Editor ────────────────────────────────────────────

function ParamListEditor({ params, onChange }) {
  const addParam = () => onChange([...params, newParam()]);
  const removeParam = (i) => onChange(params.filter((_, idx) => idx !== i));
  const updateParam = (i, field, val) => { const ps = [...params]; ps[i][field] = val; onChange(ps); };

  return (
    <div className="space-y-3">
      <label className="block text-xs font-medium text-amber-200">Parameters</label>
      {params.map((p, i) => {
        const isModelParam = (p.name || "").toLowerCase().match(/model|ckpt|checkpoint|lora|vae/);
        return (
          <div key={p.id} className={`bg-slate-800/50 rounded-lg p-4 space-y-3 border ${isModelParam ? "border-cyan-500/30" : "border-purple-600/20"}`}>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-xs font-mono text-slate-400">Param #{i + 1}</span>
                {isModelParam && (
                  <span className="text-[9px] px-1.5 py-0.5 bg-cyan-900/30 text-cyan-300 rounded border border-cyan-500/30 flex items-center gap-1">
                    <Icons.RefreshCw /> Dynamic Model
                  </span>
                )}
                {p.comfyui_node && (
                  <span className="text-[9px] px-1.5 py-0.5 bg-blue-900/30 text-blue-300 rounded">{p.comfyui_node}:{p.comfyui_param}</span>
                )}
              </div>
              <button onClick={() => removeParam(i)} className={btnDanger + " text-xs py-1 px-2"}><Icons.Trash /> Remove</button>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <input value={p.name} onChange={e => updateParam(i, "name", e.target.value)} placeholder="Parameter name (e.g. 'steps')" className={inputCls} />
              <select value={p.type} onChange={e => updateParam(i, "type", e.target.value)} className={inputCls}>
                {PARAM_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
            <input value={p.label} onChange={e => updateParam(i, "label", e.target.value)} placeholder="Display label for user" className={inputCls} />
            {isModelParam ? (
              <div className="bg-cyan-900/15 border border-cyan-500/20 rounded-lg p-2">
                <p className="text-xs text-cyan-300">This is a model parameter. Options are loaded dynamically from ComfyUI's /object_info at runtime — no hardcoded model filenames.</p>
                <input value={p.default} onChange={e => updateParam(i, "default", e.target.value)} placeholder="Leave empty for server default" className={inputCls + " mt-2 text-xs"} />
              </div>
            ) : (
              <input value={p.default} onChange={e => updateParam(i, "default", e.target.value)} placeholder="Default value" className={inputCls} />
            )}
            <textarea value={p.help} onChange={e => updateParam(i, "help", e.target.value)} rows={2} placeholder="Help text for the user" className={inputCls + " resize-none"} />
            {/* ComfyUI node mapping */}
            <div className="grid grid-cols-2 gap-2">
              <input value={p.comfyui_node || ""} onChange={e => updateParam(i, "comfyui_node", e.target.value)} placeholder="ComfyUI node ID/title" className={inputCls + " text-xs font-mono"} />
              <input value={p.comfyui_param || ""} onChange={e => updateParam(i, "comfyui_param", e.target.value)} placeholder="ComfyUI param name" className={inputCls + " text-xs font-mono"} />
            </div>
          </div>
        );
      })}
      <button onClick={addParam} className={btnSmall + " bg-purple-800/40 text-purple-300 hover:text-amber-300"}><Icons.Plus /> Add Parameter</button>
    </div>
  );
}

// ─── Execute Step Editor ─────────────────────────────────────────

function ExecuteStepEditor({ step, onChange }) {
  const update = (key, val) => onChange({ ...step, [key]: val });
  const source = step.workflow_source || "parsed";

  return (
    <div className="space-y-3">
      {/* Source selector */}
      <div>
        <label className="block text-xs font-medium text-amber-200 mb-1 flex items-center gap-1">
          Workflow Source
          <Tip text="Choose how this step finds its ComfyUI workflow. 'Parsed Workflow' uses a JSON file from your server or uploads. 'Legacy Builder' uses a hardcoded Python function." />
        </label>
        <div className="flex gap-1">
          {[
            { key: "parsed", label: "Parsed Workflow", color: "bg-blue-800/40 text-blue-300 border-blue-500/30" },
            { key: "uploaded", label: "Uploaded JSON", color: "bg-green-800/40 text-green-300 border-green-500/30" },
            { key: "builder", label: "Legacy Builder", color: "bg-orange-800/40 text-orange-300 border-orange-500/30" },
          ].map(s => (
            <button key={s.key} onClick={() => update("workflow_source", s.key)}
              className={`${btnSmall} border ${source === s.key ? s.color : "bg-slate-800/50 text-slate-500 border-transparent hover:text-amber-300"}`}>
              {s.label}
            </button>
          ))}
        </div>
      </div>

      {/* Parsed workflow selector */}
      {source === "parsed" && (
        <div className="space-y-2">
          <label className="block text-xs font-medium text-amber-200 mb-1">Workflow File Path</label>
          <input value={step.workflow_path || ""} onChange={e => update("workflow_path", e.target.value)}
            placeholder="/path/to/workflow.json or select from library..." className={inputCls + " font-mono text-xs"} />
          <p className="text-xs text-slate-400">Path to a ComfyUI workflow JSON. The parser auto-detects litegraph or API format.</p>
          {step.workflow_json && (
            <div className="bg-emerald-900/20 border border-emerald-500/30 rounded-lg p-2 flex items-center gap-2">
              <span className="text-emerald-400"><Icons.Check /></span>
              <span className="text-xs text-emerald-300">Workflow loaded — {typeof step.workflow_json === "object" ? Object.keys(step.workflow_json).length : 0} nodes in API format</span>
            </div>
          )}
        </div>
      )}

      {/* Uploaded JSON */}
      {source === "uploaded" && (
        <WorkflowUploadField
          value={step.workflow_json}
          path={step.workflow_path}
          onLoad={(json, name) => {
            onChange({ ...step, workflow_json: json, workflow_path: name });
          }}
        />
      )}

      {/* Legacy builder function */}
      {source === "builder" && (
        <div className="space-y-2">
          <label className="block text-xs font-medium text-amber-200 mb-1 flex items-center gap-1">
            Builder Function
            <Tip text="Name of a Python method in signal_bridge.py that programmatically builds the ComfyUI workflow JSON. Legacy approach — prefer parsed workflows for new setups." />
          </label>
          <select value={step.comfyui_workflow || ""} onChange={e => update("comfyui_workflow", e.target.value)} className={inputCls + " font-mono"}>
            <option value="">Select a builder...</option>
            {LEGACY_BUILDER_TEMPLATES.map(t => (
              <option key={t.builder} value={t.builder}>{t.builder} — {t.label}</option>
            ))}
            <option value="__custom__">Custom function name...</option>
          </select>
          {(step.comfyui_workflow === "__custom__" || (step.comfyui_workflow && !LEGACY_BUILDER_TEMPLATES.find(t => t.builder === step.comfyui_workflow))) && (
            <input value={step.comfyui_workflow === "__custom__" ? "" : step.comfyui_workflow} onChange={e => update("comfyui_workflow", e.target.value)}
              placeholder="_build_my_custom_workflow" className={inputCls + " font-mono"} />
          )}
          <div className="bg-orange-900/20 border border-orange-500/30 rounded-lg p-2">
            <p className="text-xs text-orange-300">Legacy builders are hardcoded Python functions. For maximum flexibility, use "Parsed Workflow" which works with any model and any workflow.</p>
          </div>
        </div>
      )}

      {/* Timeout */}
      <div>
        <label className="block text-xs font-medium text-amber-200 mb-1">Timeout (seconds)</label>
        <input type="number" min={30} max={1200} value={step.timeout || 300} onChange={e => update("timeout", parseInt(e.target.value) || 300)} className={inputCls + " w-32"} />
      </div>
    </div>
  );
}

// ─── Workflow Upload Field ────────────────────────────────────────

function WorkflowUploadField({ value, path, onLoad }) {
  const [dragOver, setDragOver] = useState(false);
  const fileRef = useRef(null);

  const handleFile = (file) => {
    if (!file || !file.name.endsWith(".json")) return;
    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const json = JSON.parse(e.target.result);
        onLoad(json, file.name);
      } catch { /* invalid json */ }
    };
    reader.readAsText(file);
  };

  return (
    <div className="space-y-2">
      <div
        onDragOver={e => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={e => { e.preventDefault(); setDragOver(false); handleFile(e.dataTransfer.files[0]); }}
        onClick={() => fileRef.current?.click()}
        className={`border-2 border-dashed rounded-lg p-6 text-center cursor-pointer transition-all ${
          dragOver ? "border-amber-500 bg-amber-500/10" : "border-amber-600/30 hover:border-amber-500/50 bg-slate-900/30"
        }`}
      >
        <input ref={fileRef} type="file" accept=".json" className="hidden" onChange={e => handleFile(e.target.files?.[0])} />
        <div className="flex justify-center mb-2 text-amber-400"><Icons.Upload /></div>
        <p className="text-sm text-amber-200">Drop a workflow JSON here or click to browse</p>
        <p className="text-xs text-slate-400 mt-1">Supports litegraph (UI-saved) and API format</p>
      </div>
      {value && (
        <div className="bg-emerald-900/20 border border-emerald-500/30 rounded-lg p-2 flex items-center gap-2">
          <span className="text-emerald-400"><Icons.Check /></span>
          <span className="text-xs text-emerald-300">Loaded: {path || "workflow.json"} — {typeof value === "object" ? (value.nodes ? `${value.nodes.length} nodes (litegraph)` : `${Object.keys(value).length} nodes (API)`) : "ready"}</span>
        </div>
      )}
    </div>
  );
}

// ─── Preset Editor ────────────────────────────────────────────────

function PresetEditor({ presets, params, onChange }) {
  const addPreset = () => onChange([...presets, newPreset()]);
  const removePreset = (i) => onChange(presets.filter((_, idx) => idx !== i));
  const updatePreset = (i, field, val) => { const ps = [...presets]; ps[i][field] = val; onChange(ps); };

  return (
    <div className="space-y-3">
      <label className="block text-xs font-medium text-amber-200">Presets</label>
      {presets.map((preset, i) => (
        <div key={preset.id} className="bg-slate-800/50 rounded-lg p-3 border border-teal-600/20">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-mono text-slate-400">Preset #{i + 1}</span>
            <button onClick={() => removePreset(i)} className={btnDanger + " text-xs py-1 px-2"}><Icons.Trash /></button>
          </div>
          <input value={preset.name} onChange={e => updatePreset(i, "name", e.target.value)} placeholder="Preset name" className={inputCls + " mb-2"} />
          <textarea value={preset.description} onChange={e => updatePreset(i, "description", e.target.value)} rows={2} placeholder="Description" className={inputCls + " resize-none"} />
        </div>
      ))}
      <button onClick={addPreset} className={btnSmall + " bg-teal-800/40 text-teal-300 hover:text-amber-300"}><Icons.Plus /> Add Preset</button>
    </div>
  );
}

// ─── Prompt Preview ───────────────────────────────────────────────

function PromptPreview({ scaffold }) {
  return (
    <div className="space-y-3">
      <div>
        <p className="text-xs font-medium text-amber-200 mb-2">System Prompt Header</p>
        <pre className="bg-slate-950 border border-amber-600/20 rounded-lg p-3 text-xs text-slate-300 overflow-auto max-h-48 font-mono whitespace-pre-wrap">
          {scaffold.system_prompt_header}
        </pre>
      </div>
      <div>
        <p className="text-xs font-medium text-amber-200 mb-2">Rules</p>
        <ol className="space-y-1 text-xs text-slate-300">
          {(scaffold.system_prompt_rules || []).map((rule, i) => (
            <li key={i} className="ml-4 list-decimal">{rule}</li>
          ))}
        </ol>
      </div>
    </div>
  );
}

// ─── Conversation Simulator ───────────────────────────────────────

function ConversationSimulator({ scaffold }) {
  const [messages, setMessages] = useState([
    { role: "assistant", text: `Welcome to the ${scaffold.name} simulator!` }
  ]);
  const [input, setInput] = useState("");

  const sendMessage = () => {
    if (!input.trim()) return;
    setMessages(prev => [...prev, { role: "user", text: input }]);
    setTimeout(() => {
      setMessages(prev => [...prev, { role: "assistant", text: "This is a simulation. Responses would be generated by the LLM in production." }]);
    }, 300);
    setInput("");
  };

  return (
    <div className="flex flex-col h-96 bg-slate-950 border border-amber-600/20 rounded-lg overflow-hidden">
      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {messages.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
            <div className={`max-w-xs px-3 py-2 rounded-lg text-sm ${
              msg.role === "user" ? "bg-amber-600/40 text-amber-50" : "bg-slate-800 text-slate-300"
            }`}>
              {msg.text}
            </div>
          </div>
        ))}
      </div>
      <div className="border-t border-amber-600/20 p-3 flex gap-2">
        <input value={input} onChange={e => setInput(e.target.value)} onKeyDown={e => e.key === "Enter" && sendMessage()} placeholder="Type a message..." className={inputCls} />
        <button onClick={sendMessage} className={btnPrimary + " flex-shrink-0"}><Icons.Play size={16} /></button>
      </div>
    </div>
  );
}

// ─── LoRA Slot Manager ───────────────────────────────────────────

function LoraSlotManager({ scaffold, onChange }) {
  const [loraData, setLoraData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [expandedSlot, setExpandedSlot] = useState(null);
  const [searchText, setSearchText] = useState("");

  // Fetch LoRA data from server
  useEffect(() => {
    setLoading(true);
    fetch("/api/scaffold_loras")
      .then(r => r.ok ? r.json() : null)
      .then(data => { setLoraData(data); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  const slotDef = LORA_SLOT_DEFS[scaffold.workflow_key];
  if (!slotDef) {
    return (
      <div className="text-xs text-slate-500 italic py-4 text-center">
        No LoRA slots defined for workflow "{scaffold.workflow_key || "(none)"}".<br/>
        LoRA management is available for: {Object.keys(LORA_SLOT_DEFS).join(", ")}
      </div>
    );
  }

  const config = scaffold.lora_config || {};

  const updateConfig = (newConfig) => {
    onChange({ ...scaffold, lora_config: newConfig });
  };

  // Get compatible LoRAs for this scaffold's architectures
  const compatibleLoras = [];
  if (loraData?.by_arch) {
    for (const arch of slotDef.arch) {
      for (const lora of (loraData.by_arch[arch] || [])) {
        if (!compatibleLoras.find(l => l.name === lora.name)) {
          compatibleLoras.push(lora);
        }
      }
    }
  }

  // Get auto-detected value for a preset_key like "wan.high_accel_lora"
  const getAutoPreset = (presetKey) => {
    if (!presetKey || !loraData?.auto_presets) return null;
    const [group, field] = presetKey.split(".");
    return loraData.auto_presets[group]?.[field] || null;
  };

  // Get autoset LoRAs from architecture config
  const getAutosetLoras = () => {
    if (!slotDef.autoset_mode || !loraData?.arch_autosets) return [];
    const result = [];
    for (const arch of slotDef.arch) {
      const modes = loraData.arch_autosets[arch];
      if (modes?.[slotDef.autoset_mode]) {
        for (const l of modes[slotDef.autoset_mode]) {
          if (!result.find(r => r.name === l.name)) {
            result.push(l);
          }
        }
      }
    }
    return result;
  };

  // Render a single LoRA slot
  const renderSlot = (slot) => {
    const isExpanded = expandedSlot === slot.key;
    const slotConfig = config[slot.key] || (slot.type === "single" ? { name: "", strength: 1.0, enabled: false } : { entries: [] });
    const autoValue = slot.preset_key ? getAutoPreset(slot.preset_key) : null;
    const autosetLoras = (!slot.preset_key && slot.type === "list" && slotDef.autoset_mode) ? getAutosetLoras() : [];

    const updateSlot = (newSlotConfig) => {
      updateConfig({ ...config, [slot.key]: newSlotConfig });
    };

    // For single slots: auto-detected badge + override input
    if (slot.type === "single") {
      const currentName = slotConfig.name || autoValue || "";
      const isAuto = !slotConfig.name && autoValue;
      return (
        <div key={slot.key} className="bg-slate-800/50 border border-cyan-600/30 rounded-lg p-3 space-y-2">
          <div className="flex items-center justify-between">
            <label className="text-xs font-medium text-cyan-200 flex items-center gap-1.5">
              {slot.label}
              {isAuto && <span className="text-[9px] px-1.5 py-0.5 rounded bg-emerald-800/50 text-emerald-300 border border-emerald-600/30">auto</span>}
            </label>
            <label className="flex items-center gap-1.5 cursor-pointer">
              <span className="text-[10px] text-slate-500">{slotConfig.enabled !== false ? "ON" : "OFF"}</span>
              <input type="checkbox" checked={slotConfig.enabled !== false && !!currentName}
                onChange={e => updateSlot({ ...slotConfig, enabled: e.target.checked })}
                className="w-3 h-3 accent-cyan-500" />
            </label>
          </div>
          {slot.help && <p className="text-[10px] text-slate-500">{slot.help}</p>}
          {/* Current value */}
          <div className="flex items-center gap-2">
            <input value={slotConfig.name || ""} placeholder={autoValue || "(none detected)"}
              onChange={e => updateSlot({ ...slotConfig, name: e.target.value })}
              className={inputCls + " text-xs py-1 flex-1 font-mono"} />
            {slotConfig.name && (
              <button onClick={() => updateSlot({ ...slotConfig, name: "" })}
                title="Reset to auto-detected"
                className="text-xs text-slate-500 hover:text-amber-300 px-1">reset</button>
            )}
          </div>
          {/* Strength slider */}
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-slate-500 w-14">Strength</span>
            <input type="range" min="0" max="2" step="0.05"
              value={slotConfig.strength ?? 1.0}
              onChange={e => updateSlot({ ...slotConfig, strength: parseFloat(e.target.value) })}
              className="flex-1 h-1 accent-cyan-500" />
            <span className="text-xs text-cyan-300 w-8 text-right font-mono">{(slotConfig.strength ?? 1.0).toFixed(2)}</span>
          </div>
          {/* Browse compatible LoRAs */}
          <button onClick={() => setExpandedSlot(isExpanded ? null : slot.key)}
            className={btnSmall + " text-[10px] bg-cyan-900/30 text-cyan-300 hover:text-amber-300 border border-cyan-600/20"}>
            {isExpanded ? "Close" : "Browse"} compatible LoRAs ({compatibleLoras.length})
          </button>
          {isExpanded && renderLoraPicker(slot, (name) => updateSlot({ ...slotConfig, name, enabled: true }))}
        </div>
      );
    }

    // For list slots: table of entries + add button
    const entries = slotConfig.entries || [];
    const hasAutoset = autosetLoras.length > 0;

    return (
      <div key={slot.key} className="bg-slate-800/50 border border-cyan-600/30 rounded-lg p-3 space-y-2">
        <div className="flex items-center justify-between">
          <label className="text-xs font-medium text-cyan-200">{slot.label}</label>
          <span className="text-[10px] text-slate-500">{entries.length} LoRA{entries.length !== 1 ? "s" : ""}</span>
        </div>
        {slot.help && <p className="text-[10px] text-slate-500">{slot.help}</p>}
        {/* Auto-detected LoRAs from architecture */}
        {hasAutoset && entries.length === 0 && (
          <div className="bg-emerald-900/20 border border-emerald-600/20 rounded p-2 space-y-1">
            <p className="text-[10px] text-emerald-300 font-medium">Auto-configured from architecture:</p>
            {autosetLoras.map((l, i) => {
              const dn = l.name.replace(/\\/g, "/").split("/").pop().replace(".safetensors","");
              return (
                <div key={i} className="flex items-center justify-between text-[10px]">
                  <span className="text-emerald-200 font-mono truncate flex-1">{dn}</span>
                  <span className="text-emerald-400 ml-2">m:{l.strength_model} c:{l.strength_clip}</span>
                </div>
              );
            })}
            <button onClick={() => {
              const imported = autosetLoras.map(l => ({
                id: uid(), name: l.name, strength_model: l.strength_model,
                strength_clip: l.strength_clip, enabled: true, source: "auto",
              }));
              updateSlot({ entries: imported });
            }} className={btnSmall + " text-[10px] bg-emerald-800/30 text-emerald-300 hover:text-amber-300 mt-1"}>
              Import auto-config to edit
            </button>
          </div>
        )}
        {/* LoRA entries */}
        {entries.map((entry, i) => (
          <div key={entry.id || i} className={`bg-slate-900/50 rounded p-2 space-y-1.5 border ${entry.enabled !== false ? "border-cyan-700/30" : "border-slate-700/30 opacity-60"}`}>
            <div className="flex items-center gap-2">
              <input type="checkbox" checked={entry.enabled !== false}
                onChange={e => {
                  const newEntries = [...entries];
                  newEntries[i] = { ...entry, enabled: e.target.checked };
                  updateSlot({ entries: newEntries });
                }} className="w-3 h-3 accent-cyan-500" />
              <span className="text-xs text-cyan-100 font-mono truncate flex-1"
                title={entry.name}>{entry.name.replace(/\\/g, "/").split("/").pop().replace(".safetensors","")}</span>
              {entry.source === "auto" && <span className="text-[8px] px-1 py-0 rounded bg-emerald-800/40 text-emerald-300">auto</span>}
              <button onClick={() => updateSlot({ entries: entries.filter((_, idx) => idx !== i) })}
                className="text-slate-600 hover:text-red-400 p-0.5"><Icons.Trash /></button>
            </div>
            {/* Strength controls */}
            <div className="flex items-center gap-2">
              <span className="text-[9px] text-slate-500 w-7">Mdl</span>
              <input type="range" min="0" max="2" step="0.05"
                value={entry.strength_model ?? 0.5}
                onChange={e => {
                  const newEntries = [...entries];
                  newEntries[i] = { ...entry, strength_model: parseFloat(e.target.value) };
                  updateSlot({ entries: newEntries });
                }} className="flex-1 h-1 accent-cyan-500" />
              <span className="text-[10px] text-cyan-300 w-7 text-right font-mono">{(entry.strength_model ?? 0.5).toFixed(2)}</span>
            </div>
            {slot.format === "model+clip" && (
              <div className="flex items-center gap-2">
                <span className="text-[9px] text-slate-500 w-7">Clip</span>
                <input type="range" min="0" max="2" step="0.05"
                  value={entry.strength_clip ?? 0.5}
                  onChange={e => {
                    const newEntries = [...entries];
                    newEntries[i] = { ...entry, strength_clip: parseFloat(e.target.value) };
                    updateSlot({ entries: newEntries });
                  }} className="flex-1 h-1 accent-cyan-500" />
                <span className="text-[10px] text-cyan-300 w-7 text-right font-mono">{(entry.strength_clip ?? 0.5).toFixed(2)}</span>
              </div>
            )}
          </div>
        ))}
        {/* Add LoRA button / browser */}
        <button onClick={() => setExpandedSlot(isExpanded ? null : slot.key)}
          className={btnSmall + " text-[10px] bg-cyan-900/30 text-cyan-300 hover:text-amber-300 border border-cyan-600/20"}>
          <Icons.Plus /> {isExpanded ? "Close browser" : "Add LoRA"} ({compatibleLoras.length} available)
        </button>
        {isExpanded && renderLoraPicker(slot, (name) => {
          if (entries.find(e => e.name === name)) return; // already added
          const newEntry = {
            id: uid(), name, strength_model: 0.5,
            strength_clip: slot.format === "model+clip" ? 0.5 : undefined,
            enabled: true, source: "user",
          };
          updateSlot({ entries: [...entries, newEntry] });
        })}
      </div>
    );
  };

  // Searchable LoRA picker dropdown
  const renderLoraPicker = (slot, onPick) => {
    const q = searchText.toLowerCase();
    const filtered = compatibleLoras.filter(l =>
      !q || l.display_name.toLowerCase().includes(q) ||
      (l.purpose || "").toLowerCase().includes(q) ||
      (l.user_desc || "").toLowerCase().includes(q)
    ).slice(0, 50);

    return (
      <div className="bg-slate-900 border border-cyan-700/30 rounded-lg p-2 mt-1 max-h-48 overflow-y-auto space-y-1">
        <input value={searchText} onChange={e => setSearchText(e.target.value)}
          placeholder="Search LoRAs..." className={inputCls + " text-xs py-1 mb-1"} />
        {filtered.length === 0 && <p className="text-xs text-slate-500 italic">No matching LoRAs found</p>}
        {filtered.map(l => (
          <button key={l.name} onClick={() => onPick(l.name)}
            className="w-full text-left px-2 py-1.5 rounded text-xs hover:bg-cyan-900/30 transition-colors group">
            <div className="flex items-center gap-2">
              <span className="text-cyan-100 font-mono truncate flex-1">{l.display_name}</span>
              <span className={`text-[9px] px-1 rounded ${
                l.source === "civitai" ? "bg-blue-900/40 text-blue-300" :
                l.source === "user" ? "bg-purple-900/40 text-purple-300" :
                "bg-slate-700/40 text-slate-400"
              }`}>{l.source === "civitai" ? "CivitAI" : l.source === "user" ? "user" : "auto"}</span>
            </div>
            {(l.purpose || l.user_desc) && (
              <p className="text-[10px] text-slate-500 truncate mt-0.5">{l.purpose || l.user_desc}</p>
            )}
          </button>
        ))}
      </div>
    );
  };

  if (loading) {
    return <div className="text-xs text-slate-400 animate-pulse py-4 text-center">Loading LoRA registry...</div>;
  }
  if (!loraData) {
    return <div className="text-xs text-slate-500 italic py-4 text-center">Could not load LoRA data from server. Is the Guild running?</div>;
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium text-cyan-200">
          LoRA Slots for "{scaffold.name}"
        </p>
        <span className="text-[10px] text-slate-500">
          {compatibleLoras.length} compatible / {loraData.total} total
        </span>
      </div>
      <div className="flex flex-wrap gap-1 mb-1">
        {slotDef.arch.map(a => (
          <span key={a} className="text-[9px] px-1.5 py-0.5 rounded bg-cyan-900/30 text-cyan-400 border border-cyan-700/20">{a}</span>
        ))}
      </div>
      {slotDef.slots.map(renderSlot)}
    </div>
  );
}

// ─── Scaffold Editor ──────────────────────────────────────────────

// ─── Scaffold overview card (shown in place of an empty step list) ──
//
// Every wizard the Guild ships with — studios, model_wizards,
// comfyui_models — has its scaffold expressed via the system prompt
// + build_fns rather than a pre-wired step chain. The earlier UI
// just showed "Workflow Steps" with nothing under it for those,
// making the whole Scaffolds tab look broken. This card makes the
// wizard's real scaffold visible at a glance: the archetype, the
// tools it can invoke, its default model + arch, a preview of the
// system prompt, and a "Seed steps from tools" CTA so anyone who
// wants a step-based flow can start from a populated chain instead
// of an empty canvas.
function ScaffoldOverviewCard({ scaffold, onSeedSteps, onAddBlankStep, onEditRules, onEditProps }) {
  const toolCount = (scaffold.build_fns || []).length;
  const rawPrompt = scaffold._raw_system_prompt || scaffold.system_prompt_header || "";
  const promptLen = rawPrompt.length;
  const archKey = scaffold.default_arch || "";
  const meta = (typeof window !== "undefined" && window.ARCH_META)
    ? window.ARCH_META[archKey] : null;

  return (
    <div className="space-y-3">
      {/* Identity strip — archetype + arch pill + model filename */}
      <div className="bg-slate-950 border border-amber-600/20 rounded-lg p-3 relative overflow-hidden"
        style={meta ? {
          boxShadow: `inset 4px 0 16px rgba(${meta.glow}, 0.15), 0 0 18px rgba(${meta.glow}, 0.08)`,
        } : undefined}>
        {meta && (
          <div className="absolute top-0 left-0 bottom-0 w-1"
            style={{ background: `linear-gradient(180deg, ${meta.c1}, ${meta.c2})` }} />
        )}
        <div className="flex items-start justify-between gap-3 pl-2">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 mb-1 flex-wrap">
              <span className="text-xs uppercase tracking-wider text-slate-500">Archetype</span>
              {meta && (
                <span className="text-[10px] px-1.5 py-0 rounded font-medium"
                  style={{
                    color: meta.c1,
                    background: `rgba(${meta.glow}, 0.14)`,
                    border: `1px solid rgba(${meta.glow}, 0.35)`,
                  }}>
                  {meta.icon} {meta.fullName}
                </span>
              )}
              {scaffold.type && (
                <span className="text-[10px] px-1.5 py-0 rounded text-slate-400 bg-slate-800/50 border border-slate-700">
                  {scaffold.type.replace(/_/g, " ")}
                </span>
              )}
            </div>
            <p className="text-sm text-amber-100 italic leading-snug">
              {scaffold.archetype || <span className="text-slate-500 not-italic">(no archetype set)</span>}
            </p>
          </div>
        </div>
        {scaffold.default_model && (
          <div className="mt-2 pl-2 flex items-center gap-2">
            <span className="text-xs uppercase tracking-wider text-slate-500">Model</span>
            <code className="text-xs text-slate-300 font-mono truncate" title={scaffold.default_model}>
              {scaffold.default_model.split(/[/\\]/).pop()}
            </code>
          </div>
        )}
      </div>

      {/* Build functions — the actual tools the wizard invokes ────────
          For wizards with only a system prompt (studios especially) this
          is the single most useful thing to show: "this wizard calls
          THESE Spellcaster functions when it decides to generate". */}
      {toolCount > 0 && (
        <div className="bg-slate-950 border border-cyan-600/20 rounded-lg p-3">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <span className="text-xs uppercase tracking-wider text-cyan-300">Tools</span>
              <span className="text-[10px] text-slate-500">{toolCount} available</span>
            </div>
            <button onClick={onSeedSteps}
              className="text-[10px] px-2 py-0.5 rounded bg-cyan-900/40 text-cyan-200 hover:bg-cyan-800/60 hover:text-white border border-cyan-500/30 transition-colors">
              Seed steps from tools →
            </button>
          </div>
          <div className="flex flex-wrap gap-1">
            {(scaffold.build_fns || []).map(fn => (
              <span key={fn}
                className="text-[10px] px-2 py-0.5 rounded bg-slate-800/70 text-cyan-200 border border-cyan-700/40 font-mono">
                {fn.replace(/^build_/, "")}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* System prompt preview — collapsed to first ~300 chars with a
          link to jump to the Rules tab where the full thing is editable. */}
      {promptLen > 0 && (
        <div className="bg-slate-950 border border-purple-600/20 rounded-lg p-3">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <span className="text-xs uppercase tracking-wider text-purple-300">System prompt</span>
              <span className="text-[10px] text-slate-500">{promptLen.toLocaleString()} chars</span>
              {(scaffold.system_prompt_rules || []).length > 0 && (
                <span className="text-[10px] text-emerald-400">
                  {scaffold.system_prompt_rules.length} rules parsed
                </span>
              )}
            </div>
            <button onClick={onEditRules}
              className="text-[10px] px-2 py-0.5 rounded bg-purple-900/40 text-purple-200 hover:bg-purple-800/60 hover:text-white border border-purple-500/30 transition-colors">
              Edit in Rules →
            </button>
          </div>
          <p className="text-xs text-slate-300 leading-relaxed whitespace-pre-wrap line-clamp-6"
            style={{ display: "-webkit-box", WebkitLineClamp: 6, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
            {rawPrompt.slice(0, 600)}{promptLen > 600 ? "…" : ""}
          </p>
        </div>
      )}

      {/* Workflow source — parsed-from-JSON wizards carry extra meta
          from workflow_parser (node count, category, original path). */}
      {scaffold.workflow_source && (
        <div className="bg-slate-950 border border-blue-600/20 rounded-lg p-3">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs uppercase tracking-wider text-blue-300">Workflow source</span>
          </div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-slate-400">
            <span>Type:</span><span className="text-slate-300">{scaffold.workflow_source.workflow_type || "—"}</span>
            <span>Nodes:</span><span className="text-slate-300">{scaffold.workflow_source.node_count || "?"}</span>
            <span>Category:</span><span className="text-slate-300">{scaffold.workflow_source.category || "root"}</span>
          </div>
          {scaffold.workflow_source.path && (
            <p className="text-xs text-slate-500 mt-1 font-mono truncate" title={scaffold.workflow_source.path}>
              {scaffold.workflow_source.path}
            </p>
          )}
        </div>
      )}

      {/* Call-to-action row. The scaffold works AS-IS via its system
          prompt — the user doesn't need to build a step chain to use
          the wizard. These buttons let them opt in to a step-based
          flow when they want one. */}
      <div className="bg-slate-950/60 border border-amber-600/20 rounded-lg p-3 flex items-start gap-3">
        <div className="flex-1">
          <p className="text-sm text-amber-200">This scaffold runs prompt-driven</p>
          <p className="text-xs text-slate-400 mt-0.5 leading-relaxed">
            No pre-wired step chain. The Guild's 7B model reads the system prompt + rules, decides which tool to invoke from the list above, and collects parameters conversationally. Add explicit steps only when you want to force a specific order.
          </p>
        </div>
        <div className="flex flex-col gap-1">
          <button onClick={onAddBlankStep}
            className={btnSmall + " bg-purple-800/40 text-purple-300 hover:text-amber-300 whitespace-nowrap"}>
            <Icons.Plus /> Blank step
          </button>
          <button onClick={onEditProps}
            className={btnSmall + " bg-slate-800/60 text-slate-300 hover:text-amber-300 whitespace-nowrap"}>
            <Icons.Settings /> Props
          </button>
        </div>
      </div>
    </div>
  );
}


function ScaffoldEditor({ scaffolds, setScaffolds }) {
  const [selectedId, setSelectedId] = useState(scaffolds[0]?.id || null);
  const [rightPanel, setRightPanel] = useState("props");
  const [showImportPanel, setShowImportPanel] = useState(false);
  const [selectedStep, setSelectedStep] = useState(null);
  const [saveStatus, setSaveStatus] = useState(""); // "" | "saving" | "saved" | "error"
  const saveTimerRef = useRef(null);
  const scaffold = scaffolds.find(s => s.id === selectedId);

  // Debounced save to server — persists scaffold edits after 800ms of inactivity.
  // Sends the full editable surface so the step editor, lora slots, and
  // access flags actually round-trip through the server.
  const persistScaffold = (updated) => {
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(() => {
      setSaveStatus("saving");
      fetch("/api/scaffold_edit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          id: updated.id,
          name: updated.name,
          subtext: updated.description || updated.subtext || "",
          description: updated.description || "",
          archetype: updated.archetype || "",
          system_prompt: [
            updated.system_prompt_header || "",
            ...(updated.system_prompt_rules || []).map(r => `- ${r}`)
          ].join("\n"),
          color1: updated.color1 || "",
          color2: updated.color2 || "",
          default_model: updated.default_model || "",
          default_arch: updated.default_arch || "",
          // Full visual step editor state
          steps: updated.steps || [],
          lora_slots: updated.lora_slots || [],
          workflow_key: updated.workflow_key || "",
          nsfw: !!updated.nsfw,
          admin_only: !!updated.admin_only,
        }),
      })
        .then(r => r.json())
        .then(() => { setSaveStatus("saved"); setTimeout(() => setSaveStatus(""), 2000); })
        .catch(() => { setSaveStatus("error"); setTimeout(() => setSaveStatus(""), 3000); });
    }, 800);
  };

  const updateScaffold = (updated) => {
    setScaffolds(prev => prev.map(s => s.id === selectedId ? updated : s));
    persistScaffold(updated);
  };

  // Create a new scaffold both locally and on the server so a page
  // refresh doesn't wipe it. The server assigns the canonical id (with
  // custom_ prefix); we adopt whatever it returns.
  const addScaffold = () => {
    const newScaff = newScaffold();
    const id = "custom_" + newScaff.id;
    fetch("/api/scaffold_create", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        id: id,
        name: newScaff.name || "New Scaffold",
        description: newScaff.description || "",
        subtext: newScaff.description || "",
        archetype: newScaff.archetype || "",
        system_prompt: "",
        color1: newScaff.color1 || "#7c3aed",
        color2: newScaff.color2 || "#f59e0b",
        steps: newScaff.steps || [],
      }),
    })
      .then(r => r.json())
      .then(() => {
        const local = { ...newScaff, id };
        setScaffolds(prev => [...prev, local]);
        setSelectedId(id);
      })
      .catch(() => {
        // Network down — still add locally so the user isn't stuck,
        // but the save will be lost on refresh.
        setScaffolds(prev => [...prev, newScaff]);
        setSelectedId(newScaff.id);
      });
  };

  // Create scaffold from a parsed workflow object
  const importFromWorkflow = (wf) => {
    const newScaff = scaffoldFromParsedWorkflow(wf);
    const id = "custom_" + newScaff.id;
    fetch("/api/scaffold_create", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        id: id,
        name: newScaff.name || "Imported Scaffold",
        description: newScaff.description || "",
        subtext: newScaff.description || "",
        archetype: newScaff.archetype || "",
        system_prompt: "",
        color1: newScaff.color1 || "#7c3aed",
        color2: newScaff.color2 || "#f59e0b",
        steps: newScaff.steps || [],
        workflow_key: newScaff.workflow_key || "",
      }),
    })
      .then(() => {
        const local = { ...newScaff, id };
        setScaffolds(prev => [...prev, local]);
        setSelectedId(id);
        setShowImportPanel(false);
      })
      .catch(() => {
        setScaffolds(prev => [...prev, newScaff]);
        setSelectedId(newScaff.id);
        setShowImportPanel(false);
      });
  };

  const deleteScaffold = () => {
    if (!selectedId) return;
    // Built-in studios can't be deleted — warn and bail.
    if (!selectedId.startsWith("custom_")) {
      alert("Built-in scaffolds can't be deleted. Use the Guild's banish flow instead.");
      return;
    }
    const nextId = scaffolds.find(s => s.id !== selectedId)?.id;
    fetch("/api/scaffold_delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: selectedId }),
    })
      .then(() => {
        setScaffolds(prev => prev.filter(s => s.id !== selectedId));
        if (nextId) setSelectedId(nextId);
      })
      .catch(() => {
        // Server unreachable — remove locally anyway so the UI isn't stuck
        setScaffolds(prev => prev.filter(s => s.id !== selectedId));
        if (nextId) setSelectedId(nextId);
      });
  };

  const duplicateScaffold = () => {
    if (!scaffold) return;
    const dup = deepClone(scaffold);
    dup.id = uid();
    dup.name = dup.name + " (Copy)";
    const id = "custom_" + dup.id;
    fetch("/api/scaffold_create", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        id,
        name: dup.name,
        description: dup.description || "",
        subtext: dup.description || "",
        archetype: dup.archetype || "",
        system_prompt: "",
        color1: dup.color1 || "#7c3aed",
        color2: dup.color2 || "#f59e0b",
        steps: dup.steps || [],
        lora_slots: dup.lora_slots || [],
        workflow_key: dup.workflow_key || "",
        nsfw: !!dup.nsfw,
        admin_only: !!dup.admin_only,
      }),
    })
      .then(() => {
        const local = { ...dup, id };
        setScaffolds(prev => [...prev, local]);
        setSelectedId(id);
      })
      .catch(() => {
        setScaffolds(prev => [...prev, dup]);
        setSelectedId(dup.id);
      });
  };

  if (showImportPanel) {
    return <WorkflowImporter onImport={importFromWorkflow} onCancel={() => setShowImportPanel(false)} />;
  }

  if (!scaffold) return <div className="text-slate-400">No scaffolds available.</div>;

  return (
    <div className="grid grid-cols-4 gap-4 h-screen max-h-screen">
      {/* Left: Scaffold list */}
      <div className="col-span-1 bg-slate-900 border border-amber-600/30 rounded-xl p-4 overflow-y-auto flex flex-col">
        <h3 className="text-sm font-medium text-amber-200 mb-3">Scaffolds</h3>
        <div className="space-y-2 flex-1 overflow-y-auto">
          {scaffolds.map(s => {
            const src = s.workflow_source;
            const typeBadge = src?.workflow_type;
            // Pick the most informative secondary line per scaffold:
            //   1. N steps   — if the wizard has an explicit step machine
            //   2. N tools   — if it's prompt-driven via build_fns
            //   3. "prompt"  — if it's purely system-prompt driven (no steps, no tools)
            const stepCount = s.steps?.length || 0;
            const toolCount = s.build_fns?.length || 0;
            let secondary = null;
            if (stepCount > 0) {
              secondary = `${stepCount} step${stepCount === 1 ? "" : "s"}`;
            } else if (toolCount > 0) {
              secondary = `${toolCount} tool${toolCount === 1 ? "" : "s"}`;
            } else if ((s.system_prompt_header || "").length > 100) {
              secondary = "prompt-driven";
            }
            // Arch pill — carries the ARCH_META colour if we know the
            // wizard's default_arch. Lets the left rail visually group
            // SDXL vs Flux Klein vs Chroma vs video etc at a glance.
            const archKey = s.default_arch || "";
            const meta = (typeof window !== "undefined" && window.ARCH_META)
              ? window.ARCH_META[archKey] : null;
            return (
              <button key={s.id} onClick={() => setSelectedId(s.id)}
                className={`w-full text-left px-3 py-2 rounded-lg text-sm transition-all ${
                  s.id === selectedId ? "bg-amber-600/40 text-amber-50 border border-amber-500/50" : "bg-slate-800/50 text-slate-400 hover:text-amber-300"
                }`}
                style={meta && s.id !== selectedId
                  ? { borderLeft: `2px solid ${meta.c1}` }
                  : undefined}>
                <p className="font-medium truncate">{s.name}</p>
                <div className="flex items-center gap-2 mt-0.5 flex-wrap">
                  {secondary && (
                    <span className="text-[10px] text-slate-500">{secondary}</span>
                  )}
                  {meta && (
                    <span className="text-[9px] px-1.5 py-0 rounded"
                      style={{
                        color: meta.c1,
                        background: `rgba(${meta.glow}, 0.12)`,
                        border: `1px solid rgba(${meta.glow}, 0.35)`,
                      }}>{meta.short || archKey}</span>
                  )}
                  {typeBadge && (
                    <span className={`text-[9px] px-1.5 py-0 rounded border ${WORKFLOW_TYPE_COLORS[typeBadge] || WORKFLOW_TYPE_COLORS.General}`}>
                      {typeBadge}
                    </span>
                  )}
                  {s.nsfw && (
                    <span className="text-[9px] px-1.5 py-0 rounded bg-red-900/30 text-red-300 border border-red-500/30">NSFW</span>
                  )}
                  {s.admin_only && (
                    <span className="text-[9px] px-1.5 py-0 rounded bg-amber-900/30 text-amber-300 border border-amber-500/30">admin</span>
                  )}
                  {src?.type === "parsed" && <span className="text-[9px] text-blue-400">parsed</span>}
                </div>
              </button>
            );
          })}
        </div>
        <div className="space-y-2 mt-4 border-t border-amber-600/20 pt-3">
          <button onClick={() => setShowImportPanel(true)} className={btnSmall + " w-full justify-center bg-blue-800/40 text-blue-300 hover:text-amber-300 border border-blue-500/30"}>
            <Icons.Upload /> Import Workflow
          </button>
          <button onClick={addScaffold} className={btnSmall + " w-full justify-center bg-purple-800/40 text-purple-300 hover:text-amber-300"}><Icons.Plus /> Blank Scaffold</button>
          <button onClick={duplicateScaffold} className={btnSmall + " w-full justify-center bg-purple-800/40 text-purple-300 hover:text-amber-300"}><Icons.Copy /> Duplicate</button>
          <button onClick={deleteScaffold} className={btnSmall + " w-full justify-center bg-red-900/40 text-red-400 hover:text-red-300"}><Icons.Trash /> Delete</button>
        </div>
      </div>

      {/* Center: Steps + prompt-driven scaffold overview ──────────────
          Wizards that ship with no explicit step machine (every studio
          and every auto-generated model_wizard — their scaffold is
          expressed via the system prompt + build_fns) used to show a
          blank section labelled "Workflow Steps" with nothing under it,
          which read as "the scaffold is empty". The overview card below
          surfaces what the wizard actually does: its archetype, the
          tools it invokes (build_fns), default model + arch, a preview
          of the system prompt, and the workflow source when present.
          When the user starts adding steps, the step list replaces the
          overview. */}
      <div className="col-span-2 bg-slate-900 border border-amber-600/30 rounded-xl p-4 overflow-y-auto">
        <div className="flex items-center gap-2 mb-3">
          <h3 className="text-sm font-medium text-amber-200">
            {scaffold.steps.length > 0 ? "Workflow Steps" : "Scaffold Overview"}
          </h3>
          {saveStatus === "saving" && <span className="text-[10px] text-slate-500 animate-pulse">saving...</span>}
          {saveStatus === "saved" && <span className="text-[10px] text-emerald-400">saved</span>}
          {saveStatus === "error" && <span className="text-[10px] text-red-400">save failed</span>}
        </div>
        {scaffold.steps.length > 0 ? (
          <>
            <div className="space-y-2">
              {scaffold.steps.map((step, idx) => (
                <StepCard key={step.id} step={step} index={idx} total={scaffold.steps.length}
                  isSelected={selectedStep === step.id}
                  onSelect={() => setSelectedStep(selectedStep === step.id ? null : step.id)}
                  onMove={(fromIdx, toIdx) => {
                    const newSteps = [...scaffold.steps];
                    [newSteps[fromIdx], newSteps[toIdx]] = [newSteps[toIdx], newSteps[fromIdx]];
                    updateScaffold({ ...scaffold, steps: newSteps });
                  }}
                  onDelete={() => updateScaffold({ ...scaffold, steps: scaffold.steps.filter((_, i) => i !== idx) })}
                />
              ))}
            </div>
            <button onClick={() => updateScaffold({ ...scaffold, steps: [...scaffold.steps, newStep()] })}
              className={btnSmall + " mt-4 bg-purple-800/40 text-purple-300 hover:text-amber-300"}><Icons.Plus /> Add Step</button>
          </>
        ) : (
          <ScaffoldOverviewCard
            scaffold={scaffold}
            onSeedSteps={() => {
              // Seed a step chain from the wizard's build_fns so the
              // user has a starting point to reorder + customise.
              const seeded = (scaffold.build_fns || []).slice(0, 8)
                .map((fn, i) => {
                  const step = newStep("execute");
                  step.label = fn.replace(/^build_/, "").replace(/_/g, " ");
                  step.params = step.params || {};
                  step.params.build_fn = fn;
                  return step;
                });
              if (!seeded.length) {
                // No build_fns — seed a single prompt step so the user
                // has somewhere to start.
                seeded.push(newStep("prompt"));
              }
              updateScaffold({ ...scaffold, steps: seeded });
            }}
            onAddBlankStep={() => {
              updateScaffold({ ...scaffold, steps: [...scaffold.steps, newStep()] });
            }}
            onEditRules={() => setRightPanel("rules")}
            onEditProps={() => setRightPanel("props")}
          />
        )}
      </div>

      {/* Right: Details */}
      <div className="col-span-1 bg-slate-900 border border-amber-600/30 rounded-xl p-4 overflow-y-auto">
        {selectedStep && scaffold.steps.find(s => s.id === selectedStep) ? (
          <>
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-medium text-amber-200">Edit Step</span>
              <button onClick={() => setSelectedStep(null)}
                className="text-xs text-slate-400 hover:text-amber-300 px-2 py-1 rounded bg-slate-800/50">
                ← Back to Props
              </button>
            </div>
            <StepEditor
              step={scaffold.steps.find(s => s.id === selectedStep)}
              scaffold={scaffold}
              onChange={(updatedStep) => {
                updateScaffold({
                  ...scaffold,
                  steps: scaffold.steps.map(s => s.id === selectedStep ? updatedStep : s)
                });
              }}
              onDelete={() => {
                updateScaffold({ ...scaffold, steps: scaffold.steps.filter(s => s.id !== selectedStep) });
                setSelectedStep(null);
              }}
            />
          </>
        ) : (
        <>
        <div className="flex gap-1 mb-3">
          <button onClick={() => setRightPanel("props")}
            className={`text-xs px-2 py-1 rounded ${rightPanel === "props" ? "bg-amber-600/40 text-amber-50" : "bg-slate-800/50 text-slate-400 hover:text-amber-300"}`}>
            Props
          </button>
          <button onClick={() => setRightPanel("rules")}
            className={`text-xs px-2 py-1 rounded ${rightPanel === "rules" ? "bg-amber-600/40 text-amber-50" : "bg-slate-800/50 text-slate-400 hover:text-amber-300"}`}>
            Rules
          </button>
          <button onClick={() => setRightPanel("loras")}
            className={`text-xs px-2 py-1 rounded ${rightPanel === "loras" ? "bg-cyan-600/40 text-cyan-50" : "bg-slate-800/50 text-slate-400 hover:text-cyan-300"}`}>
            LoRAs
          </button>
        </div>

        {rightPanel === "props" && (
          <div className="space-y-3">
            <div>
              <label className="text-xs text-amber-200 mb-1 block flex items-center gap-1">
                Workflow Name
                <Tip text="Name shown to users when selecting workflows" />
              </label>
              <input value={scaffold.name} onChange={e => updateScaffold({ ...scaffold, name: e.target.value })}
                className={inputCls} />
            </div>
            <div>
              <label className="text-xs text-amber-200 mb-1 block">Description</label>
              <textarea value={scaffold.description} onChange={e => updateScaffold({ ...scaffold, description: e.target.value })}
                rows={3} className={inputCls + " resize-none"} />
            </div>
            <div>
              <label className="text-xs text-amber-200 mb-1 block flex items-center gap-1">
                Workflow Key
                <Tip text="Internal identifier for this scaffold. Auto-generated from workflow name on import. Used for routing in Signal Bridge commands." />
              </label>
              <input value={scaffold.workflow_key} onChange={e => updateScaffold({ ...scaffold, workflow_key: e.target.value })}
                placeholder="my_workflow_key" className={inputCls + " font-mono"} />
            </div>
            {/* Workflow source info */}
            {scaffold.workflow_source && (
              <div className="bg-blue-900/20 border border-blue-500/30 rounded-lg p-3 space-y-1">
                <p className="text-xs font-medium text-blue-200">Workflow Source</p>
                <p className="text-xs text-blue-300/70">Type: {scaffold.workflow_source.workflow_type || "General"}</p>
                <p className="text-xs text-blue-300/70">Nodes: {scaffold.workflow_source.node_count || "?"}</p>
                <p className="text-xs text-blue-300/70">Category: {scaffold.workflow_source.category || "root"}</p>
                {scaffold.workflow_source.path && (
                  <p className="text-xs text-blue-300/70 font-mono truncate">Path: {scaffold.workflow_source.path}</p>
                )}
              </div>
            )}
            <label className="flex items-start gap-2 cursor-pointer">
              <input type="checkbox" checked={scaffold.nsfw} onChange={e => updateScaffold({ ...scaffold, nsfw: e.target.checked })}
                className="mt-1" />
              <div>
                <span className="text-sm text-amber-200 flex items-center gap-1">
                  NSFW Only
                  <Tip text="When checked, this scaffold is only available to users with unrestricted (NSFW) access" />
                </span>
              </div>
            </label>
            <label className="flex items-start gap-2 cursor-pointer">
              <input type="checkbox" checked={scaffold.admin_only} onChange={e => updateScaffold({ ...scaffold, admin_only: e.target.checked })}
                className="mt-1" />
              <div>
                <span className="text-sm text-amber-200 flex items-center gap-1">
                  Admin Only
                  <Tip text="When checked, only the admin phone number can use this scaffold" />
                </span>
              </div>
            </label>
          </div>
        )}

        {rightPanel === "rules" && (
          <div className="space-y-3">
            <p className="text-sm font-medium text-amber-50">LLM Instructions — how the 7B should behave</p>
            <div>
              <label className="text-xs text-slate-400 mb-1 block">System Prompt Header</label>
              <textarea value={scaffold.system_prompt_header}
                onChange={e => updateScaffold({ ...scaffold, system_prompt_header: e.target.value })}
                rows={4} className={inputCls + " resize-y font-mono text-xs"} />
            </div>
            <div>
              <label className="text-xs text-slate-400 mb-1 block">Rules (one per line)</label>
              {(scaffold.system_prompt_rules || []).map((rule, i) => (
                <div key={i} className="flex items-center gap-2 mb-1">
                  <span className="text-xs text-slate-600 w-5">{i + 1}.</span>
                  <input value={rule} onChange={e => {
                    const rules = [...scaffold.system_prompt_rules];
                    rules[i] = e.target.value;
                    updateScaffold({ ...scaffold, system_prompt_rules: rules });
                  }} className={inputCls + " text-xs py-1 flex-1"} />
                  <button onClick={() => {
                    updateScaffold({ ...scaffold, system_prompt_rules: scaffold.system_prompt_rules.filter((_, idx) => idx !== i) });
                  }} className="text-slate-600 hover:text-red-400 p-0.5"><Icons.Trash /></button>
                </div>
              ))}
              <button onClick={() => updateScaffold({ ...scaffold, system_prompt_rules: [...(scaffold.system_prompt_rules || []), ""] })}
                className={btnSmall + " bg-purple-800/40 text-purple-300 hover:text-amber-300 mt-1"}>
                <Icons.Plus /> Add Rule
              </button>
            </div>
          </div>
        )}

        {rightPanel === "loras" && (
          <LoraSlotManager scaffold={scaffold} onChange={updateScaffold} />
        )}
        </>
        )}
      </div>
    </div>
  );
}

// ─── Tool Detection Card ──────────────────────────────────────────

function ToolDetectionCard({ tool, config, appControl, onConfigure }) {
  const [status, setStatus] = useState("unchecked"); // unchecked | checking | found | not_found
  const [probeInfo, setProbeInfo] = useState(""); // server-returned status text
  const [expanded, setExpanded] = useState(false);

  // R143: resolve the probe URL with the Guild's app_control registry
  // as the highest-priority source so sidebar chip edits reflect here
  // without a manual refresh. Precedence: app_control entry → tool's
  // urlConfigKey in signal_bridge_config → hardcoded defaultUrl.
  const acKey = APP_CONTROL_KEY_MAP[tool.id];
  const acUrl = acKey ? appControlUrl(appControl, acKey) : null;
  const effectiveUrl = acUrl
    || (tool.urlConfigKey && config && config[tool.urlConfigKey])
    || tool.defaultUrl
    || "";

  const handleDetect = async () => {
    if (!effectiveUrl) {
      setStatus("not_found");
      setProbeInfo("no URL configured");
      return;
    }
    setStatus("checking");
    setProbeInfo("");
    try {
      const r = await fetch("/api/probe_tool", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tool: tool.id, url: effectiveUrl }),
      });
      const data = await r.json().catch(() => ({}));
      if (data && data.found) {
        setStatus("found");
        setProbeInfo(data.info ? `HTTP ${data.status} via ${data.endpoint || ""}` : `HTTP ${data.status}`);
      } else {
        setStatus("not_found");
        setProbeInfo(data.info || "no response");
      }
    } catch (e) {
      setStatus("not_found");
      setProbeInfo(String(e && e.message || e));
    }
  };

  const handleSetup = () => {
    if (onConfigure && tool.configureTab) onConfigure(tool.configureTab);
  };

  const handleOpen = () => {
    if (effectiveUrl) window.open(effectiveUrl, "_blank", "noopener");
  };

  const statusColors = {
    unchecked: "bg-slate-500",
    checking: "bg-amber-500 animate-pulse",
    found: "bg-emerald-500",
    not_found: "bg-red-500"
  };

  const statusText = {
    unchecked: "Not checked",
    checking: "Probing...",
    found: "Online",
    not_found: "Offline"
  };

  const ToolIcon = tool.icon;

  return (
    <div className="bg-slate-900 border border-amber-600/30 rounded-lg overflow-hidden">
      <div className="p-4">
        <div className="flex items-start gap-4 mb-3">
          <div className="w-12 h-12 bg-purple-900/40 rounded-lg flex items-center justify-center text-amber-400 flex-shrink-0">
            <ToolIcon size={24} />
          </div>
          <div className="flex-1">
            <h3 className="text-sm font-semibold text-amber-50">{tool.name}</h3>
            <p className="text-xs text-slate-400 mt-1">{tool.description}</p>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            <div className={`w-3 h-3 rounded-full ${statusColors[status]}`} />
            <span className="text-xs text-slate-400">{statusText[status]}</span>
          </div>
        </div>

        <div className="space-y-1 mb-3">
          <p className="text-xs text-slate-400">
            <span className="font-mono text-amber-300">{effectiveUrl || "(no URL)"}</span>
          </p>
          {probeInfo && (
            <p className={`text-xs font-mono ${status === "found" ? "text-emerald-400/80" : "text-red-400/80"}`}>
              {probeInfo}
            </p>
          )}
        </div>

        <div className="flex gap-2">
          <button onClick={handleDetect} disabled={status === "checking"}
            className={btnSmall + " bg-amber-600/50 text-amber-100 hover:bg-amber-600 disabled:opacity-50 disabled:cursor-wait flex-1"}>
            <Icons.Search size={16} /> Detect
          </button>
          {tool.configureTab && (
            <button onClick={handleSetup}
              className={btnSmall + " bg-emerald-600/50 text-emerald-100 hover:bg-emerald-600 flex-1"}>
              <Icons.Check size={16} /> Configure
            </button>
          )}
          {status === "found" && effectiveUrl && (
            <button onClick={handleOpen}
              className={btnSmall + " bg-purple-600/50 text-purple-100 hover:bg-purple-600 flex-1"}>
              <Icons.ExternalLink size={16} /> Open
            </button>
          )}
        </div>

        <button onClick={() => setExpanded(!expanded)}
          className="w-full mt-2 text-xs text-slate-400 hover:text-amber-300 transition-colors flex items-center justify-center gap-1">
          {expanded ? "Hide" : "Show"} Setup Guide
          <Icons.ChevDown size={14} style={{transform: expanded ? "rotate(180deg)" : ""}} />
        </button>
      </div>

      {expanded && (
        <div className="bg-slate-950 border-t border-amber-600/20 p-4">
          <ol className="space-y-2 text-xs text-slate-300">
            {tool.setupSteps.map((step, i) => (
              <li key={i} className="flex gap-2">
                <span className="text-amber-400 font-semibold flex-shrink-0">{i + 1}.</span>
                <span>{step}</span>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}

// ─── Cross-Plugin Scaffold Manifest (R144) ───────────────────────
// Read-only inventory of every callable method across every plugin
// (Wizard Guild + GIMP + Darktable + Resolve + SillyTavern), served
// by /api/scaffolds/all. Single-source-of-truth status is annotated
// per method based on whether the handler routes through
// spellcaster_core.workflows (canonical), builds its own workflow
// JSON (duplicate), or is non-classifiable (unknown / cross-plugin
// send etc). Groups are collapsible so users with 80+ GIMP procs
// don't get wall-of-text.

function SsotBadge({ status }) {
  const spec = {
    canonical:   { color: "emerald", label: "✓ canonical",
                    tip: "Routes through spellcaster_core.workflows — single source of truth." },
    duplicate:   { color: "rose",    label: "⚠ duplicate",
                    tip: "Builds its own workflow JSON (SSoT violation). Should refactor to a canonical builder or a thin-client Guild API call." },
    thin_client: { color: "sky",     label: "→ thin client",
                    tip: "Calls the Guild HTTP API. Correct design for out-of-process clients (Resolve / SillyTavern / cross-plugin send)." },
    utility:     { color: "amber",   label: "· utility",
                    tip: "Local UI / preferences handler — no workflow to unify." },
    unknown:     { color: "slate",   label: "? unknown",
                    tip: "Could not classify automatically. Likely worth a manual look." },
  }[status] || { color: "slate", label: status, tip: "" };
  const cls = {
    emerald: "bg-emerald-500/20 text-emerald-300 border-emerald-500/40",
    rose:    "bg-rose-500/20 text-rose-300 border-rose-500/40",
    sky:     "bg-sky-500/20 text-sky-300 border-sky-500/40",
    amber:   "bg-amber-500/20 text-amber-300 border-amber-500/40",
    slate:   "bg-slate-500/20 text-slate-300 border-slate-500/40",
  }[spec.color];
  return (
    <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded border ${cls} whitespace-nowrap`}
          title={spec.tip}>{spec.label}</span>
  );
}

function CrossPluginManifest() {
  const [groups, setGroups] = useState([]);
  const [totals, setTotals] = useState({ total: 0, canonical: 0, duplicate: 0, unknown: 0 });
  const [status, setStatus] = useState("loading"); // loading | loaded | error
  const [err, setErr] = useState("");
  // Collapsed by default — the user wants to scan the plugin counts
  // first and expand on demand, not wade through 150+ rows on load.
  const [openIds, setOpenIds] = useState(() => new Set());
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all"); // all | canonical | duplicate | thin_client | utility | unknown
  const [groupBy, setGroupBy] = useState("category"); // category | status | none

  const load = useCallback((force = false) => {
    setStatus("loading");
    const qs = force ? "?force=1" : "";
    fetch(`/api/scaffolds/all${qs}`)
      .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then(d => {
        setGroups(Array.isArray(d) ? d : (d.groups || []));
        setTotals(d.totals || { total: 0, canonical: 0, duplicate: 0, unknown: 0 });
        setStatus("loaded");
      })
      .catch(e => { setStatus("error"); setErr(String(e.message || e)); });
  }, []);
  useEffect(() => { load(false); }, [load]);

  const toggle = (id) => {
    setOpenIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const filtered = (scaffolds) => {
    let r = scaffolds;
    if (filter !== "all") r = r.filter(s => (s.ssot_status || "unknown") === filter);
    if (search) {
      const q = search.toLowerCase();
      r = r.filter(s => (s.name || "").toLowerCase().includes(q)
                     || (s.id || "").toLowerCase().includes(q)
                     || (s.description || "").toLowerCase().includes(q));
    }
    return r;
  };

  return (
    <div className="space-y-3">
      <div className="bg-slate-900 border border-amber-600/30 rounded-xl p-4">
        <div className="flex items-start justify-between gap-3 mb-3 flex-wrap">
          <div>
            <h3 className="text-lg font-semibold text-amber-50">Cross-plugin scaffold manifest</h3>
            <p className="text-xs text-slate-400 mt-1">
              Every callable method across the Wizard Guild, GIMP, Darktable, DaVinci Resolve, and SillyTavern plugins. Read-only here; Guild wizards are editable in the panel below.
            </p>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            <span className="text-xs text-slate-400">
              <b className="text-amber-200">{totals.total}</b> methods
              &nbsp;•&nbsp; <b className="text-emerald-400">{totals.canonical}</b> canonical
              &nbsp;•&nbsp; <b className="text-sky-400">{totals.thin_client || 0}</b> thin-client
              &nbsp;•&nbsp; <b className="text-rose-400">{totals.duplicate}</b> duplicate
              &nbsp;•&nbsp; <b className="text-amber-400">{totals.utility || 0}</b> utility
              &nbsp;•&nbsp; <b className="text-slate-400">{totals.unknown}</b> unknown
            </span>
            <button onClick={() => load(true)} disabled={status === "loading"}
                    className="text-xs px-3 py-1 rounded-full border border-amber-600/40 hover:bg-amber-500/10 text-amber-200 disabled:opacity-50">
              {status === "loading" ? "refreshing…" : "↻ re-scan"}
            </button>
          </div>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <input value={search} onChange={e => setSearch(e.target.value)}
                 placeholder="Filter by name / id / description"
                 className="bg-slate-950 border border-amber-600/20 rounded px-2 py-1 text-sm text-amber-100 flex-1 min-w-[200px]" />
          <select value={filter} onChange={e => setFilter(e.target.value)}
                  className="bg-slate-950 border border-amber-600/20 rounded px-2 py-1 text-sm text-amber-100">
            <option value="all">All SSoT statuses</option>
            <option value="canonical">canonical only</option>
            <option value="thin_client">thin-client only</option>
            <option value="duplicate">duplicate only (SSoT violations)</option>
            <option value="utility">utility only</option>
            <option value="unknown">unknown only</option>
          </select>
          <select value={groupBy} onChange={e => setGroupBy(e.target.value)}
                  className="bg-slate-950 border border-amber-600/20 rounded px-2 py-1 text-sm text-amber-100">
            <option value="category">Group by category</option>
            <option value="status">Group by SSoT status</option>
            <option value="none">Flat list</option>
          </select>
        </div>
        {status === "error" && (
          <p className="text-xs text-rose-400 mt-2">Failed to load: {err}</p>
        )}
      </div>

      {groups.map(g => {
        const list = filtered(g.scaffolds || []);
        const open = openIds.has(g.id);
        // Sub-group within each plugin. `category` is the default —
        // maps every method to its "what it does" bucket; `status`
        // groups by canonical/thin-client/duplicate/utility/unknown;
        // `none` shows the flat sorted list (server already sorts
        // by category → name).
        const subBuckets = {};
        for (const s of list) {
          let key;
          if (groupBy === "status") {
            key = {
              canonical: "✓ Canonical (spellcaster_core)",
              thin_client: "→ Thin client (Guild API)",
              duplicate: "⚠ Duplicate (SSoT violation)",
              utility: "· Utility",
              unknown: "? Unknown",
            }[s.ssot_status] || "? Unknown";
          } else if (groupBy === "category") {
            key = s.category_label || "Other";
          } else {
            key = "";
          }
          (subBuckets[key] = subBuckets[key] || []).push(s);
        }
        const subKeys = Object.keys(subBuckets).sort();
        return (
          <div key={g.id} className="bg-slate-900 border border-amber-600/30 rounded-xl overflow-hidden">
            <button onClick={() => toggle(g.id)}
                    className="w-full flex items-center gap-3 px-5 py-3 text-left hover:bg-purple-800/20 transition-colors">
              <span className="text-xl">{g.icon}</span>
              <span className="flex-1">
                <span className="block text-base font-semibold text-amber-50">{g.label}</span>
                <span className="block text-xs text-slate-400">{g.description}</span>
              </span>
              <span className="text-xs text-slate-400 flex items-center gap-2 flex-wrap justify-end">
                <b className="text-amber-200">{list.length}</b>/{g.summary.total}
                {g.summary.canonical > 0 && <span className="text-emerald-400">{g.summary.canonical}✓</span>}
                {g.summary.thin_client > 0 && <span className="text-sky-400">{g.summary.thin_client}→</span>}
                {g.summary.duplicate > 0 && <span className="text-rose-400">{g.summary.duplicate}⚠</span>}
                {g.summary.utility > 0 && <span className="text-amber-400">{g.summary.utility}·</span>}
                {g.summary.unknown > 0 && <span className="text-slate-400">{g.summary.unknown}?</span>}
                <span className={`text-amber-500 transition-transform ${open ? "rotate-180" : ""}`}>▾</span>
              </span>
            </button>
            {open && (
              <div className="border-t border-amber-600/20">
                {list.length === 0 ? (
                  <div className="px-5 py-4 text-sm text-slate-500 italic">
                    {g.scaffolds.length === 0
                      ? "No methods detected in the repo tree. If this plugin has been recently added / updated, click ↻ re-scan above."
                      : "No methods match the current filter."}
                  </div>
                ) : subKeys.map(sub => (
                  <div key={sub}>
                    {sub && (
                      <div className="px-5 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-amber-300/80 bg-slate-950/50 border-t border-amber-600/10 flex items-center justify-between">
                        <span>{sub}</span>
                        <span className="text-slate-500 font-mono normal-case">{subBuckets[sub].length}</span>
                      </div>
                    )}
                    <div className="divide-y divide-slate-800">
                      {subBuckets[sub].map(s => (
                        <div key={s.id} className="px-5 py-2 hover:bg-slate-800/30">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-sm font-medium text-amber-100">{s.name || s.id}</span>
                            <SsotBadge status={s.ssot_status || "unknown"} />
                            {s.category_label && groupBy !== "category" && (
                              <span className="text-[10px] text-slate-400 italic">{s.category_label}</span>
                            )}
                            {s.feature_gate && s.feature_gate !== "None" && (
                              <span className="text-[10px] font-mono text-slate-400">gate:{s.feature_gate}</span>
                            )}
                          </div>
                          {(s.description || s.ssot_notes) && (
                            <p className="text-xs text-slate-400 mt-0.5">
                              {s.description}
                              {s.description && s.ssot_notes ? " · " : ""}
                              {s.ssot_notes && <span className="italic">{s.ssot_notes}</span>}
                            </p>
                          )}
                          <p className="text-[10px] font-mono text-slate-600 mt-0.5">{s.id}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ─── Integrations Panel ───────────────────────────────────────────

function IntegrationsPanel({ config, appControl, onConfigure }) {
  return (
    <div className="space-y-4">
      <div className="bg-amber-500/10 border border-amber-600/30 rounded-lg p-3 flex items-start gap-3">
        <span className="text-amber-500 mt-0.5"><Icons.Compass size={18} /></span>
        <p className="text-sm text-amber-200">
          Auto-detect installed tools and services. Click "Detect" to probe for running instances, then configure connections.
          ComfyUI / Ollama / Kobold URLs come from the main Guild sidebar's app-control registry — single source of truth.
        </p>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {TOOL_DEFINITIONS.map(tool => (
          <ToolDetectionCard key={tool.id} tool={tool}
            config={config} appControl={appControl} onConfigure={onConfigure} />
        ))}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════
// SHARED COMPONENTS (from original)
// ═══════════════════════════════════════════════════════════════════

function PasswordField({ value, onChange, placeholder, className = "" }) {
  const [show, setShow] = useState(false);
  return (
    <div className="relative">
      <input type={show ? "text" : "password"} value={value} onChange={onChange} placeholder={placeholder} className={`w-full pr-10 ${className}`} />
      <button type="button" onClick={() => setShow(!show)} className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-amber-300 transition-colors">
        {show ? <Icons.EyeOff /> : <Icons.Eye />}
      </button>
    </div>
  );
}

function SectionCard({ title, icon, children, collapsible = true }) {
  const [open, setOpen] = useState(true);
  return (
    <div className="bg-slate-900 border border-amber-600/30 rounded-xl overflow-hidden mb-4 transition-all">
      <button onClick={() => collapsible && setOpen(!open)}
        className="w-full flex items-center gap-3 px-5 py-4 text-left hover:bg-purple-800/20 transition-colors">
        <span className="text-amber-500">{icon}</span>
        <span className="text-lg font-semibold text-amber-50 flex-1">{title}</span>
        {collapsible && <span className={`text-amber-600 transition-transform ${open ? "rotate-180" : ""}`}><Icons.ChevDown /></span>}
      </button>
      {open && <div className="px-5 pb-5 space-y-4 border-t border-amber-600/20">{children}</div>}
    </div>
  );
}

function Field({ label, tip, children }) {
  return (
    <div>
      <label className="block text-sm font-medium text-amber-200 mb-1 flex items-center gap-1">
        {label}
        {tip && <Tip text={tip} />}
      </label>
      {children}
    </div>
  );
}

// R143: input bound to the Guild's app_control registry. Reads the
// current URL from a live snapshot, accepts host:port or full URL on
// edit, and writes through `onSave` (usually the parent's
// `saveServiceUrl` wrapper around /api/app_control/register).
function AppControlField({ label, tip, serviceKey, appControl, fallback, onSave }) {
  const canonical = appControlUrl(appControl, serviceKey);
  const [draft, setDraft] = useState(canonical || fallback || "");
  const [status, setStatus] = useState(""); // "" | "saving" | "saved" | "error"
  const [err, setErr] = useState("");
  // Keep the draft in sync when the upstream changes (e.g. a sidebar
  // edit propagates via the 10s poll). Don't clobber while the user
  // is mid-edit — only overwrite if the field lost focus.
  const focusedRef = useRef(false);
  useEffect(() => {
    if (focusedRef.current) return;
    setDraft(canonical || fallback || "");
  }, [canonical, fallback]);
  const commit = async () => {
    const v = draft.trim();
    if (v === (canonical || "")) { setStatus(""); return; }
    setStatus("saving"); setErr("");
    const res = await onSave(serviceKey, v);
    if (res && res.ok) { setStatus("saved"); setTimeout(() => setStatus(""), 1400); }
    else { setStatus("error"); setErr(res ? res.error : "save failed"); }
  };
  const entry = appControl && appControl[serviceKey];
  return (
    <div>
      <label className="block text-sm font-medium text-amber-200 mb-1 flex items-center gap-1">
        {label}
        {tip && <Tip text={tip} />}
        {status === "saving" && <span className="text-xs text-amber-500 ml-2">saving…</span>}
        {status === "saved"  && <span className="text-xs text-emerald-400 ml-2">✓ saved</span>}
        {status === "error"  && <span className="text-xs text-red-400 ml-2" title={err}>✗ {err.slice(0, 40)}</span>}
      </label>
      <input
        value={draft}
        onChange={e => setDraft(e.target.value)}
        onFocus={() => { focusedRef.current = true; }}
        onBlur={() => { focusedRef.current = false; commit(); }}
        onKeyDown={e => { if (e.key === "Enter") { e.currentTarget.blur(); } }}
        placeholder="http://192.168.x.x:PORT or host:port"
        className={inputCls} />
      {entry && (
        <p className="text-xs text-slate-500 mt-1">
          app_control entry: target=<code>{entry.target || "local"}</code>
          {entry.host && <> · host=<code>{entry.host}</code></>}
          {entry.port && <> · port=<code>{entry.port}</code></>}
          {entry.url && <> · url=<code>{entry.url}</code></>}
        </p>
      )}
    </div>
  );
}

function PhoneManager({ config, setConfig }) {
  const [newPhone, setNewPhone] = useState("");
  const [newName, setNewName] = useState("");
  const [newTier, setNewTier] = useState("restricted");
  const [newKey, setNewKey] = useState("");
  const users = config.users || {};
  const userList = Object.entries(users);

  const addUser = () => {
    if (!newPhone.trim()) return;
    const phone = newPhone.trim();
    const updated = deepClone(config);
    updated.users[phone] = { name: newName.trim() || phone, api_key: newKey.trim(), nsfw_access: newTier === "unrestricted", model: config.model };
    if (!updated.allowed_numbers.includes(phone)) updated.allowed_numbers.push(phone);
    setConfig(updated);
    setNewPhone(""); setNewName(""); setNewKey(""); setNewTier("restricted");
  };
  const removeUser = (phone) => { const u = deepClone(config); delete u.users[phone]; u.allowed_numbers = u.allowed_numbers.filter(n => n !== phone); setConfig(u); };
  const toggleNsfw = (phone) => { const u = deepClone(config); u.users[phone].nsfw_access = !u.users[phone].nsfw_access; setConfig(u); };

  return (
    <div className="space-y-4">
      {userList.length > 0 ? (
        <div className="space-y-2">
          {userList.map(([phone, u]) => (
            <div key={phone} className="flex items-center gap-3 bg-slate-900/50 rounded-lg px-4 py-3 border border-amber-600/20">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-amber-50 font-medium text-sm truncate">{u.name || phone}</span>
                  {phone === config.admin_number && <span className="text-xs bg-amber-500/20 text-amber-400 px-2 py-0.5 rounded-full font-medium">Admin</span>}
                </div>
                <span className="text-xs text-slate-400 font-mono">{phone}</span>
              </div>
              <button onClick={() => toggleNsfw(phone)}
                className={`text-xs px-3 py-1.5 rounded-full font-medium transition-colors ${u.nsfw_access ? "bg-red-500/20 text-red-400 hover:bg-red-500/30 border border-red-500/30" : "bg-emerald-500/20 text-emerald-400 hover:bg-emerald-500/30 border border-emerald-500/30"}`}>
                {u.nsfw_access ? "Unrestricted" : "Restricted"}
              </button>
              <button onClick={() => removeUser(phone)} className="text-slate-500 hover:text-red-400 transition-colors p-1"><Icons.Trash /></button>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-center py-6 text-slate-500 text-sm border border-dashed border-amber-600/20 rounded-lg">No authorized users yet.</div>
      )}
      <div className="bg-slate-900/50 border border-amber-600/20 rounded-lg p-4 space-y-3">
        <p className="text-sm font-medium text-amber-200">Add Authorized User</p>
        <div className="grid grid-cols-2 gap-3">
          <input value={newPhone} onChange={e => setNewPhone(e.target.value)} placeholder="+1234567890" className={inputCls} />
          <input value={newName} onChange={e => setNewName(e.target.value)} placeholder="Display name" className={inputCls} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <PasswordField value={newKey} onChange={e => setNewKey(e.target.value)} placeholder="WebUI API key (optional)" className={inputCls} />
          <select value={newTier} onChange={e => setNewTier(e.target.value)} className={inputCls}>
            <option value="restricted">Restricted (SFW only)</option>
            <option value="unrestricted">Unrestricted (NSFW)</option>
          </select>
        </div>
        <button onClick={addUser} className={btnPrimary}><Icons.Plus /> Add User</button>
      </div>
    </div>
  );
}

function PrivacyPanel({ config, setConfig }) {
  const privacy = config.privacy || DEFAULT_CONFIG.privacy;
  const update = (key, val) => { const u = deepClone(config); if (!u.privacy) u.privacy = deepClone(DEFAULT_CONFIG.privacy); u.privacy[key] = val; setConfig(u); };
  const Toggle = ({ checked, onChange, label, description }) => (
    <label className="flex items-start gap-3 cursor-pointer group">
      <div className={`relative w-11 h-6 rounded-full transition-colors mt-0.5 flex-shrink-0 ${checked ? "bg-amber-600 shadow-lg shadow-amber-600/40" : "bg-slate-700"}`} onClick={onChange}>
        <div className="absolute top-0.5 w-5 h-5 rounded-full bg-amber-50 shadow transition-transform left-0.5" style={{ transform: checked ? "translateX(22px)" : "translateX(0)" }} />
      </div>
      <div>
        <span className="text-sm font-medium text-amber-50 group-hover:text-amber-100 transition-colors flex items-center gap-1">
          {label}
        </span>
        {description && <p className="text-xs text-slate-400 mt-0.5">{description}</p>}
      </div>
    </label>
  );
  return (
    <div className="space-y-4">
      <div className="bg-amber-500/10 border border-amber-600/30 rounded-lg p-3 flex items-start gap-3">
        <span className="text-amber-500 mt-0.5"><Icons.Shield /></span>
        <p className="text-sm text-amber-200">Privacy controls use Spellcaster methods to sanitize all ComfyUI input/output.</p>
      </div>
      <Toggle checked={privacy.clean_comfyui_input} onChange={() => update("clean_comfyui_input", !privacy.clean_comfyui_input)} label="Sanitize ComfyUI Input" description="Strips EXIF metadata, GPS coordinates, camera info, and other identifying data from images before they reach ComfyUI." />
      <Toggle checked={privacy.clean_comfyui_output} onChange={() => update("clean_comfyui_output", !privacy.clean_comfyui_output)} label="Sanitize ComfyUI Output" description="Removes all embedded metadata from AI-generated images before sending them back to users via Signal." />
      <Toggle checked={privacy.strip_metadata_on_send} onChange={() => update("strip_metadata_on_send", !privacy.strip_metadata_on_send)} label="Strip Metadata on Send" description="Additional metadata scrubbing on every outbound image, regardless of source. Prevents accidental location leaks." />
      <Toggle checked={privacy.auto_delete_generated} onChange={() => update("auto_delete_generated", !privacy.auto_delete_generated)} label="Auto-Delete Generated" description="Automatically removes generated image files from the ComfyUI server after they've been delivered to the user." />
      <Field label="Cleanup Interval" tip="Time in minutes between automatic cleanup sweeps of generated files. Minimum 5 minutes, max 1440 (24 hours)">
        <input type="number" min="5" max="1440" value={privacy.cleanup_interval_minutes} onChange={e => update("cleanup_interval_minutes", parseInt(e.target.value) || 30)} className={inputCls + " w-32"} />
      </Field>
    </div>
  );
}

function PathEditor({ config, setConfig }) {
  const paths = config.paths || {};
  const pathFields = [
    { key: "cases_dir", label: "Cases Directory", tip: "Root folder for legal case files. Each case gets its own subfolder with documents, notes, and correspondence" },
    { key: "agent_dir", label: "Agent Directory", tip: "Working directory for the Signal Bridge agent. Contains config, persona data, knowledge base, and session logs" },
    { key: "persona_portraits", label: "Persona Portraits", tip: "Folder containing avatar images for each persona (Biggie, Mika, Cody, Zima). Used in character cards and profile pictures" },
    { key: "mood_cache", label: "Mood Cache", tip: "Temporary storage for persona mood state tracking. Cleared on restart. Allows personas to maintain emotional continuity" },
    { key: "sessions", label: "Sessions", tip: "Per-user conversation session logs. Stores message history for context window management and conversation continuity" },
    { key: "knowledge", label: "Knowledge Base", tip: "RAG knowledge documents. Add PDF, TXT, or MD files here and they'll be indexed for retrieval-augmented generation" },
    { key: "google_data", label: "Google Data", tip: "Cached Google API data (calendar events, emails, tasks). Reduces API calls and provides offline access to recent data" },
    { key: "rag_index", label: "RAG Index", tip: "Vector database index files for the retrieval-augmented generation system. Auto-rebuilt when knowledge base changes" },
  ];
  const updatePath = (key, val) => { const u = deepClone(config); if (!u.paths) u.paths = {}; u.paths[key] = val; setConfig(u); };
  return (
    <div className="space-y-3">
      {pathFields.map(f => (
        <Field key={f.key} label={f.label} tip={f.tip}>
          <input value={paths[f.key] || ""} onChange={e => updatePath(f.key, e.target.value)} placeholder={`/path/to/${f.key}`} className={inputCls} />
        </Field>
      ))}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════
// WORKFLOW IMPORTER (Power User Upload)
// ═══════════════════════════════════════════════════════════════════

function WorkflowImporter({ onImport, onCancel }) {
  const [mode, setMode] = useState("upload"); // "upload" | "server" | "legacy"
  const [files, setFiles] = useState([]);      // uploaded workflow files
  const [parsing, setParsing] = useState(false);
  const [parsed, setParsed] = useState([]);    // parsed results
  const [serverWfs, setServerWfs] = useState([]);
  const [serverLoading, setServerLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const folderRef = useRef(null);
  const fileRef = useRef(null);

  // Client-side workflow parsing (basic — real parsing is server-side)
  const clientParse = (json, filename) => {
    // Detect format
    const isLitegraph = !!(json.nodes && Array.isArray(json.nodes));
    const isApi = !isLitegraph && typeof json === "object" && Object.values(json).some(n => n && n.class_type);

    let nodeCount = 0;
    let nodeTypes = [];
    let tunableParams = [];
    let workflowType = "General";

    if (isLitegraph) {
      nodeCount = json.nodes.length;
      nodeTypes = json.nodes.map(n => n.type).filter(Boolean);
      // Extract widgets_values as basic params
      json.nodes.forEach(n => {
        if (n.widgets_values && n.type) {
          // Heuristic: common tunable types
          const lowerType = (n.type || "").toLowerCase();
          if (lowerType.includes("ksampler") || lowerType.includes("sampler")) {
            tunableParams.push({ name: "steps", node_title: n.title || n.type, type: "INT", default: "", priority: "HIGH" });
            tunableParams.push({ name: "cfg", node_title: n.title || n.type, type: "FLOAT", default: "", priority: "HIGH" });
            tunableParams.push({ name: "seed", node_title: n.title || n.type, type: "INT", default: "", priority: "MEDIUM" });
          }
          if (lowerType.includes("clip") && lowerType.includes("text")) {
            tunableParams.push({ name: "text", node_title: n.title || n.type, type: "STRING", default: "", priority: "HIGH", display_name: "Prompt" });
          }
          if (lowerType.includes("checkpoint") || lowerType.includes("loader")) {
            tunableParams.push({ name: "ckpt_name", node_title: n.title || n.type, type: "COMBO", default: "", priority: "HIGH", display_name: "Model" });
          }
        }
      });
    } else if (isApi) {
      const entries = Object.entries(json);
      nodeCount = entries.length;
      nodeTypes = entries.map(([_, n]) => n.class_type).filter(Boolean);
      entries.forEach(([id, n]) => {
        if (!n.inputs) return;
        const ct = (n.class_type || "").toLowerCase();
        Object.entries(n.inputs).forEach(([key, val]) => {
          if (Array.isArray(val)) return; // connection, not a value
          const lk = key.toLowerCase();
          if (lk.includes("prompt") || lk === "text" || lk === "positive" || lk === "negative") {
            tunableParams.push({ name: key, node_title: n.class_type, node_id: id, type: "STRING", default: typeof val === "string" ? val : "", priority: "HIGH", display_name: key });
          } else if (lk.includes("steps") || lk === "cfg" || lk === "denoise" || lk === "seed") {
            tunableParams.push({ name: key, node_title: n.class_type, node_id: id, type: typeof val === "number" ? (Number.isInteger(val) ? "INT" : "FLOAT") : "STRING", default: val, priority: "HIGH" });
          } else if (lk.includes("ckpt") || lk.includes("model") || lk.includes("checkpoint")) {
            tunableParams.push({ name: key, node_title: n.class_type, node_id: id, type: "COMBO", default: typeof val === "string" ? val : "", priority: "HIGH", display_name: "Model" });
          }
        });
      });
    }

    // Classify workflow type
    const allTypes = nodeTypes.join(" ").toLowerCase();
    if (allTypes.includes("video") || allTypes.includes("animate") || allTypes.includes("wan")) workflowType = allTypes.includes("img2") ? "Image-to-Video" : "Text-to-Video";
    else if (allTypes.includes("faceswap") || allTypes.includes("reactor") || allTypes.includes("roop")) workflowType = "Face Swap";
    else if (allTypes.includes("inpaint")) workflowType = "Inpainting";
    else if (allTypes.includes("upscale") || allTypes.includes("supir") || allTypes.includes("esrgan")) workflowType = "Upscale";
    else if (allTypes.includes("controlnet") || allTypes.includes("canny") || allTypes.includes("depth")) workflowType = "ControlNet";
    else if (allTypes.includes("loadimage") || allTypes.includes("img2img")) workflowType = "Image-to-Image";
    else if (allTypes.includes("ksampler") || allTypes.includes("sampler")) workflowType = "Text-to-Image";

    // De-duplicate params by name
    const seen = new Set();
    tunableParams = tunableParams.filter(p => {
      const k = `${p.node_title}:${p.name}`;
      if (seen.has(k)) return false;
      seen.add(k);
      return true;
    });

    return {
      name: filename.replace(/\.json$/, "").replace(/[_-]+/g, " "),
      filename,
      format: isLitegraph ? "litegraph" : isApi ? "api" : "unknown",
      node_count: nodeCount,
      node_types: [...new Set(nodeTypes)],
      workflow_type: workflowType,
      tunable_params: tunableParams,
      api_workflow: isApi ? json : null,
      category: "uploaded",
      path: filename,
    };
  };

  const handleFiles = (fileList) => {
    const newFiles = Array.from(fileList).filter(f => f.name.endsWith(".json"));
    if (newFiles.length === 0) return;
    setParsing(true);
    const results = [];
    let remaining = newFiles.length;
    newFiles.forEach(f => {
      const reader = new FileReader();
      reader.onload = (e) => {
        try {
          const json = JSON.parse(e.target.result);
          results.push(clientParse(json, f.name));
        } catch { /* skip invalid */ }
        remaining--;
        if (remaining === 0) {
          setParsed(prev => [...prev, ...results]);
          setFiles(prev => [...prev, ...newFiles.map(f => f.name)]);
          setParsing(false);
        }
      };
      reader.readAsText(f);
    });
  };

  const filteredParsed = search
    ? parsed.filter(p => p.name.toLowerCase().includes(search.toLowerCase()) || p.workflow_type.toLowerCase().includes(search.toLowerCase()))
    : parsed;

  return (
    <div className="bg-slate-900 border border-amber-600/30 rounded-xl p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-bold text-amber-50">Import Workflow as Scaffold</h2>
        <button onClick={onCancel} className={btnGhost}>Cancel</button>
      </div>

      <p className="text-sm text-slate-400">
        Upload ComfyUI workflow JSON files or entire folders. The parser extracts tunable parameters and auto-generates a complete scaffold with steps, prompts, and model-agnostic defaults.
      </p>

      {/* Mode tabs */}
      <div className="flex gap-1">
        {[
          { key: "upload", label: "Upload Files", icon: <Icons.Upload /> },
          { key: "legacy", label: "Legacy Templates", icon: <Icons.Layout /> },
        ].map(m => (
          <button key={m.key} onClick={() => setMode(m.key)}
            className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-all ${
              mode === m.key ? "bg-amber-600/30 text-amber-50 border border-amber-500/50" : "text-slate-400 hover:text-amber-300"
            }`}>
            {m.icon} {m.label}
          </button>
        ))}
      </div>

      {/* Upload mode */}
      {mode === "upload" && (
        <div className="space-y-4">
          <div
            onDragOver={e => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={e => { e.preventDefault(); setDragOver(false); handleFiles(e.dataTransfer.files); }}
            className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-all ${
              dragOver ? "border-amber-500 bg-amber-500/10" : "border-amber-600/30 hover:border-amber-500/50"
            }`}
          >
            <input ref={fileRef} type="file" accept=".json" multiple className="hidden" onChange={e => handleFiles(e.target.files)} />
            <input ref={folderRef} type="file" webkitdirectory="" directory="" multiple className="hidden" onChange={e => handleFiles(e.target.files)} />
            <div className="flex justify-center mb-3 text-amber-400"><Icons.Upload /></div>
            <p className="text-base text-amber-200 font-medium">Drop workflow JSON files here</p>
            <p className="text-xs text-slate-400 mt-1">or</p>
            <div className="flex justify-center gap-3 mt-3">
              <button onClick={() => fileRef.current?.click()} className={btnPrimary + " text-xs py-1.5"}>
                <Icons.Upload /> Select Files
              </button>
              <button onClick={() => folderRef.current?.click()} className={btnGhost + " text-xs py-1.5"}>
                <Icons.Folder /> Select Folder
              </button>
            </div>
            <p className="text-xs text-slate-500 mt-3">Supports litegraph (UI export) and API format. Multiple files and folders accepted.</p>
          </div>

          {parsing && (
            <div className="flex items-center gap-2 text-sm text-amber-300 animate-pulse">
              <Icons.RefreshCw /> Parsing workflows...
            </div>
          )}

          {/* Parsed results */}
          {parsed.length > 0 && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <p className="text-sm font-medium text-amber-200">{parsed.length} workflow(s) parsed</p>
                {parsed.length > 3 && (
                  <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Filter..." className={inputCls + " w-48 text-xs"} />
                )}
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3 max-h-96 overflow-y-auto">
                {filteredParsed.map((wf, i) => {
                  const typeColor = WORKFLOW_TYPE_COLORS[wf.workflow_type] || WORKFLOW_TYPE_COLORS.General;
                  return (
                    <div key={i} className="bg-slate-800/50 border border-amber-600/20 rounded-lg p-4 space-y-2">
                      <div className="flex items-start justify-between">
                        <h3 className="text-sm font-medium text-amber-50">{wf.name}</h3>
                        <span className={`text-[10px] px-1.5 py-0.5 rounded border ${typeColor}`}>{wf.workflow_type}</span>
                      </div>
                      <div className="flex items-center gap-3 text-xs text-slate-400">
                        <span>{wf.node_count} nodes</span>
                        <span>{wf.format}</span>
                        <span>{wf.tunable_params.length} params</span>
                      </div>
                      {wf.tunable_params.length > 0 && (
                        <div className="flex flex-wrap gap-1">
                          {wf.tunable_params.slice(0, 5).map((p, j) => (
                            <span key={j} className="text-[10px] px-1.5 py-0.5 bg-purple-900/30 text-purple-300 rounded">{p.display_name || p.name}</span>
                          ))}
                          {wf.tunable_params.length > 5 && <span className="text-[10px] text-slate-500">+{wf.tunable_params.length - 5} more</span>}
                        </div>
                      )}
                      <button onClick={() => onImport(wf)} className={btnPrimary + " w-full justify-center text-xs py-1.5"}>
                        <Icons.Wand /> Create Scaffold
                      </button>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Legacy templates */}
      {mode === "legacy" && (
        <div className="space-y-3">
          <p className="text-xs text-slate-400">These use hardcoded Python builder functions. For maximum flexibility with any model, use "Upload Files" instead.</p>
          <div className="grid grid-cols-2 gap-3">
            {LEGACY_BUILDER_TEMPLATES.map((t, i) => (
              <button key={i} onClick={() => {
                const s = newScaffold();
                s.name = t.label;
                s.icon = t.icon;
                s.workflow_key = t.workflow_key;
                const execStep = s.steps.find(st => st.type === "execute");
                if (execStep) { execStep.comfyui_workflow = t.builder; execStep.workflow_source = "builder"; }
                onImport({ name: t.label, workflow_type: t.label, node_count: 0, tunable_params: [], category: "legacy" });
              }}
                className="text-left bg-slate-800/50 border border-orange-500/20 rounded-lg p-3 hover:border-orange-500/40 transition-all"
              >
                <p className="text-sm font-medium text-amber-50">{t.label}</p>
                <p className="text-xs text-slate-400 font-mono mt-1">{t.builder}</p>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════
// WORKFLOW BROWSER
// ═══════════════════════════════════════════════════════════════════

const WORKFLOW_TYPE_COLORS = {
  "Text-to-Image": "bg-blue-500/20 text-blue-300 border-blue-500/30",
  "Image-to-Image": "bg-green-500/20 text-green-300 border-green-500/30",
  "Text-to-Video": "bg-purple-500/20 text-purple-300 border-purple-500/30",
  "Image-to-Video": "bg-indigo-500/20 text-indigo-300 border-indigo-500/30",
  "Face Swap": "bg-pink-500/20 text-pink-300 border-pink-500/30",
  "Inpainting": "bg-orange-500/20 text-orange-300 border-orange-500/30",
  "Upscale": "bg-cyan-500/20 text-cyan-300 border-cyan-500/30",
  "ControlNet": "bg-yellow-500/20 text-yellow-300 border-yellow-500/30",
  "Audio/Music": "bg-red-500/20 text-red-300 border-red-500/30",
  "Captioning": "bg-teal-500/20 text-teal-300 border-teal-500/30",
  "Style Transfer": "bg-fuchsia-500/20 text-fuchsia-300 border-fuchsia-500/30",
  "3D Generation": "bg-emerald-500/20 text-emerald-300 border-emerald-500/30",
  General: "bg-slate-500/20 text-slate-300 border-slate-500/30",
};

function WorkflowBrowser({ comfyuiUrl, onCreateScaffold }) {
  const [workflows, setWorkflows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [selectedCat, setSelectedCat] = useState(null);
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [serverOnline, setServerOnline] = useState(null);

  // Fetch workflow catalog from ComfyUI MCP server or parse locally
  const loadWorkflows = useCallback(async () => {
    setLoading(true);
    setError("");
    // R142: probe ComfyUI via the Guild's /api/comfy_status endpoint
    // instead of hitting ComfyUI directly from the browser. The
    // browser-side fetch would always fail when ComfyUI is on another
    // machine (CORS blocks the response + typical LAN ComfyUI servers
    // never set Access-Control-Allow-Origin), which is why the library
    // chip stayed red ("ComfyUI Offline") even when every other Guild
    // chip correctly showed it online — they all go through the Guild.
    try {
      const resp = await fetch("/api/comfy_status",
        { signal: AbortSignal.timeout(6000) });
      if (resp.ok) {
        const d = await resp.json();
        // comfy_status returns {"connected": bool, ...} or similar;
        // treat missing field as "looks up, got 200" = online.
        setServerOnline(d.connected !== false);
      } else {
        setServerOnline(false);
      }
    } catch {
      setServerOnline(false);
    }

    // R141: the Guild wraps scaffold.discover_workflows() behind
    // /api/workflows/list. That keeps a single source of truth
    // (scaffold/workflow_parser.py) and means the ComfyUI side needs
    // no custom endpoint. The older code pointed directly at
    // `${comfyuiUrl}/spellcaster/workflows` which never existed, so
    // every user hit "workflow_api_unavailable" on first open.
    try {
      const resp = await fetch(`/api/workflows/list`,
        { signal: AbortSignal.timeout(6000) });
      if (resp.ok) {
        const data = await resp.json();
        // Endpoint returns {workflows: [...], categories, total}.
        // Accept a bare array too in case the shape ever simplifies.
        setWorkflows(Array.isArray(data) ? data : (data.workflows || []));
      } else {
        throw new Error(`HTTP ${resp.status}`);
      }
    } catch {
      setWorkflows([]);
      setError("workflow_api_unavailable");
    }
    setLoading(false);
  }, [comfyuiUrl]);

  useEffect(() => { loadWorkflows(); }, [loadWorkflows]);

  // Group by category
  const categories = useMemo(() => {
    const cats = {};
    workflows.forEach(w => {
      const cat = w.category || "root";
      if (!cats[cat]) cats[cat] = [];
      cats[cat].push(w);
    });
    return cats;
  }, [workflows]);

  // Filter
  const filtered = useMemo(() => {
    let result = workflows;
    if (selectedCat) result = result.filter(w => w.category === selectedCat);
    if (search) {
      const s = search.toLowerCase();
      result = result.filter(w => w.name.toLowerCase().includes(s) || (w.workflow_type || "").toLowerCase().includes(s));
    }
    return result;
  }, [workflows, selectedCat, search]);

  const catList = Object.keys(categories).sort();

  return (
    <div className="space-y-4">
      {/* Status bar */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-bold text-amber-50">ComfyUI Workflow Library</h2>
          <Tip text="Browse all ComfyUI workflows saved on your server. The parser reads any workflow JSON — litegraph or API format — and extracts tunable parameters so you can run them from Signal, GIMP, or any integration." />
          {serverOnline !== null && (
            <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium ${
              serverOnline ? "bg-green-500/20 text-green-400 border border-green-500/30" : "bg-red-500/20 text-red-400 border border-red-500/30"
            }`}>
              <span className={`w-1.5 h-1.5 rounded-full ${serverOnline ? "bg-green-400" : "bg-red-400"}`} />
              {serverOnline ? "ComfyUI Online" : "ComfyUI Offline"}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button onClick={loadWorkflows} className={btnGhost} disabled={loading}>
            <Icons.RefreshCw /> {loading ? "Scanning..." : "Refresh"}
          </button>
        </div>
      </div>

      {/* Search + category filter */}
      <div className="flex gap-3">
        <div className="flex-1 relative">
          <span className="absolute left-3 top-1/2 -translate-y-1/2 text-amber-400/60"><Icons.Search /></span>
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search workflows by name or type..."
            className={inputCls + " pl-10"}
          />
        </div>
        <select
          value={selectedCat || ""}
          onChange={e => setSelectedCat(e.target.value || null)}
          className={inputCls + " w-48"}
        >
          <option value="">All categories</option>
          {catList.map(c => (
            <option key={c} value={c}>{c} ({categories[c].length})</option>
          ))}
        </select>
      </div>

      {/* Error / setup instructions */}
      {error === "workflow_api_unavailable" && (
        <SectionCard title="Setup Required" icon={<Icons.AlertTriangle />}>
          <div className="space-y-3">
            <p className="text-sm text-amber-200">
              The workflow browser needs the Spellcaster scaffold API to discover your workflows.
              The parser can read <strong>all {catList.length > 0 ? catList.length + " categories of" : ""}</strong> ComfyUI workflows automatically.
            </p>
            <div className="bg-slate-900 rounded-lg p-3 font-mono text-xs text-slate-300 space-y-1">
              <p className="text-amber-400"># Python — discover all workflows</p>
              <p>from scaffold import discover_workflows, parse_workflow</p>
              <p>entries = discover_workflows()  <span className="text-slate-500"># scans user/default/workflows/</span></p>
              <p>print(f"Found &#123;len(entries)&#125; workflows")</p>
              <p></p>
              <p className="text-amber-400"># Parse any single workflow</p>
              <p>wf = parse_workflow("path/to/workflow.json")</p>
              <p>print(wf.summary())  <span className="text-slate-500"># shows type, nodes, tunable params</span></p>
              <p></p>
              <p className="text-amber-400"># Interactive wizard for chat interfaces</p>
              <p>from scaffold import WorkflowWizard</p>
              <p>wizard = WorkflowWizard(comfyui_url="{comfyuiUrl || "http://localhost:8188"}")</p>
              <p>reply = wizard.handle("user1", "workflows")  <span className="text-slate-500"># starts browse menu</span></p>
            </div>
            <div className="bg-purple-800/20 border border-purple-500/30 rounded-lg p-3">
              <p className="text-sm text-purple-200 font-medium mb-1">What the parser supports:</p>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-purple-300">
                <span>✓ Litegraph (UI-saved) format</span>
                <span>✓ API (numbered-node) format</span>
                <span>✓ 600+ custom node types</span>
                <span>✓ UUID-based node references</span>
                <span>✓ Auto workflow classification</span>
                <span>✓ Smart parameter prioritization</span>
                <span>✓ /object_info enrichment</span>
                <span>✓ Muted/bypassed node filtering</span>
              </div>
            </div>
          </div>
        </SectionCard>
      )}

      {/* Workflow grid */}
      {filtered.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {filtered.map((w, i) => {
            const typeColor = WORKFLOW_TYPE_COLORS[w.workflow_type] || WORKFLOW_TYPE_COLORS.General;
            const isSelected = selected === i;
            return (
              <button
                key={w.path || w.name + i}
                onClick={() => setSelected(isSelected ? null : i)}
                className={`text-left p-4 rounded-xl border transition-all ${
                  isSelected
                    ? "bg-amber-600/20 border-amber-500/50 ring-2 ring-amber-500/30"
                    : "bg-slate-900/50 border-amber-500/10 hover:border-amber-500/30 hover:bg-slate-900/80"
                }`}
              >
                <div className="flex items-start justify-between mb-2">
                  <h3 className="text-sm font-medium text-amber-50 leading-tight">{w.name}</h3>
                  <span className={`inline-flex px-1.5 py-0.5 rounded text-[10px] font-medium border ${typeColor} whitespace-nowrap ml-2`}>
                    {w.workflow_type || "General"}
                  </span>
                </div>
                <div className="flex items-center gap-3 text-xs text-slate-400">
                  <span>{w.node_count} nodes</span>
                  <span className="text-amber-600/40">·</span>
                  <span>{w.category}</span>
                </div>
                {isSelected && onCreateScaffold && (
                  <button
                    onClick={(e) => { e.stopPropagation(); onCreateScaffold(w); }}
                    className={btnPrimary + " w-full justify-center text-xs py-1.5 mt-2"}
                  >
                    <Icons.Wand /> Create Scaffold from This
                  </button>
                )}
              </button>
            );
          })}
        </div>
      )}

      {/* Empty state */}
      {!loading && workflows.length === 0 && error !== "workflow_api_unavailable" && (
        <div className="text-center py-12 text-slate-500">
          <div className="text-4xl mb-3">🔮</div>
          <p className="text-lg font-medium text-amber-200/60">No workflows found</p>
          <p className="text-sm mt-1">Make sure ComfyUI is running and has saved workflows</p>
        </div>
      )}

      {/* Stats footer */}
      {workflows.length > 0 && (
        <div className="flex items-center justify-between pt-2 border-t border-amber-600/10">
          <span className="text-xs text-amber-200/40">
            {filtered.length} of {workflows.length} workflows shown
            {catList.length > 0 && ` · ${catList.length} categories`}
          </span>
          <span className="text-xs text-amber-200/40">
            Powered by Spellcaster Workflow Parser
          </span>
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════
// GUILD SIDEBAR — Collapsible right panel with characters + chat
// ═══════════════════════════════════════════════════════════════════

function GuildSidebar({ isOpen, onToggle, comfyUrl, koboldUrl: initialKoboldUrl, onWizardSelect }) {
  const [characters, setCharacters] = useState([]);
  const [activeCharId, setActiveCharId] = useState(null);
  const [chatHistory, setChatHistory] = useState([]);
  const [chatInput, setChatInput] = useState("");
  const [searchFilter, setSearchFilter] = useState("");
  const [loading, setLoading] = useState(false);
  const [llmConnected, setLlmConnected] = useState(false);
  const [systemPrompt, setSystemPrompt] = useState("");
  const [koboldUrl, setKoboldUrl] = useState(initialKoboldUrl || "http://127.0.0.1:5001");
  const chatEndRef = useRef(null);

  // Initialize — fetch characters and system prompt
  useEffect(() => {
    (async () => {
      try {
        const [charRes, promptRes, assetsRes] = await Promise.all([
          fetch("/api/characters"), fetch("/api/system_prompt"), fetch("/api/generated_assets")
        ]);
        const chars = await charRes.json();
        const promptData = await promptRes.json();
        let serverAssets = {};
        try { serverAssets = await assetsRes.json(); } catch {}
        // Restore saved identities (stale-URL-aware)
        const _isCached = u => u && u.includes('/api/cached_asset/');
        const _isStale = u => u && u.includes('/view?');
        let saved = {};
        try { saved = JSON.parse(localStorage.getItem("guild_identities") || "{}"); } catch {}
        chars.forEach(c => {
          // Prefer server-side cached assets over stale localStorage URLs
          const srvAsset = serverAssets[c.id];
          if (srvAsset && srvAsset.avatar_url && _isCached(srvAsset.avatar_url)) {
            c.avatar_url = srvAsset.avatar_url;
          }
          if (saved[c.id]) {
            c.name = saved[c.id].name || c.name;
            c.personality = saved[c.id].personality || c.personality;
            const savedAvatar = saved[c.id].avatar_url;
            // Only use saved avatar if it's not a stale ComfyUI URL being overwritten by a cached one
            if (savedAvatar && !(_isStale(savedAvatar) && _isCached(c.avatar_url))) {
              c.avatar_url = savedAvatar || c.avatar_url;
            }
          }
        });
        setCharacters(chars);
        setSystemPrompt(promptData.prompt || "");
        if (chars.length > 0) setActiveCharId(chars[0].id);
      } catch (e) { console.error("Guild init error:", e); }
    })();
  }, []);

  // Check LLM on mount — probe both Ollama (/api/tags) and KoboldCpp (/api/v1/model)
  useEffect(() => {
    (async () => {
      for (const path of ['/api/tags', '/api/v1/model']) {
        try {
          const res = await fetch(`${koboldUrl}${path}`, { signal: AbortSignal.timeout(5000) });
          if (res.ok) { setLlmConnected(true); return; }
        } catch { /* try next */ }
      }
      setLlmConnected(false);
    })();
  }, [koboldUrl]);

  // Auto-scroll chat
  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: "smooth" }); }, [chatHistory]);

  const activeChar = characters.find(c => c.id === activeCharId);

  const saveIdentity = (char) => {
    const saved = JSON.parse(localStorage.getItem("guild_identities") || "{}");
    saved[char.id] = { name: char.name, personality: char.personality, avatar_url: char.avatar_url };
    localStorage.setItem("guild_identities", JSON.stringify(saved));
  };

  const selectChar = (id) => {
    setActiveCharId(id);
    const char = characters.find(c => c.id === id);
    if (char) {
      const intro = `Greetings. I am ${char.name}, master of ${char.subtext}. Tell me what you wish to conjure.`;
      setChatHistory([{ role: "assistant", content: intro }]);
      if (onWizardSelect) onWizardSelect(char);
    }
  };

  const sendMessage = async () => {
    const text = chatInput.trim();
    if (!text || !activeChar) return;
    setChatInput("");
    const newHistory = [...chatHistory, { role: "user", content: text }];
    setChatHistory(newHistory);
    setLoading(true);

    let context = `${systemPrompt}\n\nYour Persona:\nYou are ${activeChar.name}, a magical expert in ${activeChar.subtext}.\n${activeChar.personality || ""}\n\n`;
    for (const h of newHistory) {
      context += `${h.role === "user" ? "User" : "Assistant"}: ${h.content}\n`;
    }
    context += "Assistant: ";

    try {
      const response = await fetch(`${koboldUrl}/api/v1/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: context, max_context_length: 4096, max_length: 300, temperature: 0.7, stop_sequence: ["User:", "\nUser"] }),
      });
      const data = await response.json();
      const aiReply = data.results[0].text.trim();
      setChatHistory(prev => [...prev, { role: "assistant", content: aiReply }]);
    } catch (err) {
      setChatHistory(prev => [...prev, { role: "assistant", content: `[Error: Could not connect to LLM at ${koboldUrl}]` }]);
    }
    setLoading(false);
  };

  const filteredChars = characters.filter(c => {
    if (!searchFilter) return true;
    const q = searchFilter.toLowerCase();
    return c.name.toLowerCase().includes(q) || c.subtext.toLowerCase().includes(q);
  });

  if (!isOpen) return null;

  return (
    <div className="fixed right-0 top-0 h-full w-96 bg-slate-950/95 border-l border-amber-600/30 z-40 flex flex-col shadow-2xl"
      style={{ backdropFilter: "blur(12px)", boxShadow: "-8px 0 30px rgba(0,0,0,0.5)" }}>

      {/* Guild Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-amber-600/20 bg-slate-900/80">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 bg-gradient-to-br from-purple-600 to-amber-600 rounded-lg flex items-center justify-center">
            <Icons.MessageSquare />
          </div>
          <div>
            <h2 className="text-sm font-bold text-amber-50">The Wizard Guild</h2>
            <div className="flex items-center gap-1.5 text-xs">
              <span className={`w-1.5 h-1.5 rounded-full ${llmConnected ? "bg-green-400" : "bg-red-400"}`} />
              <span className="text-amber-200/60">{llmConnected ? "LLM Connected" : "LLM Offline"}</span>
            </div>
          </div>
        </div>
        <button onClick={onToggle} className="p-1.5 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-amber-300 transition-colors">
          <Icon d="M18 6L6 18M6 6l12 12" size={16} />
        </button>
      </div>

      {/* Character List (collapsible) */}
      <div className="border-b border-amber-600/20">
        <div className="px-3 py-2">
          <input
            value={searchFilter} onChange={e => setSearchFilter(e.target.value)}
            placeholder="Search wizards..."
            className="w-full bg-slate-900/60 border border-amber-500/15 rounded-md px-2.5 py-1.5 text-xs text-amber-50 placeholder-slate-500 focus:border-amber-500/40 outline-none"
          />
        </div>
        <div className="max-h-44 overflow-y-auto px-2 pb-2 space-y-0.5" style={{ scrollbarWidth: "thin" }}>
          {filteredChars.map(c => (
            <button key={c.id} onClick={() => selectChar(c.id)}
              className={`w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-left transition-all ${
                c.id === activeCharId
                  ? "bg-purple-700/30 border border-purple-500/40"
                  : "hover:bg-slate-800/60"
              }`}>
              <div className="w-8 h-8 rounded-lg flex-shrink-0"
                style={{
                  background: c.avatar_url
                    ? `url(${c.avatar_url}) center/cover, linear-gradient(135deg, ${c.color1}, ${c.color2})`
                    : `linear-gradient(135deg, ${c.color1}, ${c.color2})`,
                }} />
              <div className="min-w-0">
                <div className="text-xs font-medium text-amber-50 truncate">{c.name}</div>
                <div className="text-[10px] text-amber-200/50 truncate">{c.subtext}</div>
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Active Character Header */}
      {activeChar && (
        <div className="flex items-center gap-3 px-4 py-2.5 border-b border-amber-600/10 bg-slate-900/40">
          <div className="w-10 h-10 rounded-xl flex-shrink-0"
            style={{
              background: activeChar.avatar_url
                ? `url(${activeChar.avatar_url}) center/cover, linear-gradient(135deg, ${activeChar.color1}, ${activeChar.color2})`
                : `linear-gradient(135deg, ${activeChar.color1}, ${activeChar.color2})`,
            }} />
          <div className="min-w-0">
            <div className="text-sm font-semibold text-amber-50 truncate">{activeChar.name}</div>
            <div className="text-xs text-amber-200/50 truncate">{activeChar.subtext}</div>
          </div>
        </div>
      )}

      {/* Chat Stream */}
      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-3" style={{ scrollbarWidth: "thin" }}>
        {chatHistory.map((msg, i) => (
          <div key={i} className={`flex gap-2 ${msg.role === "user" ? "flex-row-reverse" : ""}`}>
            {msg.role === "assistant" && activeChar && (
              <div className="w-6 h-6 rounded-md flex-shrink-0 mt-0.5"
                style={{ background: `linear-gradient(135deg, ${activeChar.color1}, ${activeChar.color2})` }} />
            )}
            <div className={`max-w-[80%] rounded-xl px-3 py-2 text-xs leading-relaxed ${
              msg.role === "user"
                ? "bg-purple-700/40 text-purple-100 border border-purple-500/20"
                : "bg-slate-800/60 text-amber-50/90 border border-amber-500/10"
            }`}>
              {msg.content}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex gap-2">
            <div className="w-6 h-6 rounded-md flex-shrink-0" style={{ background: activeChar ? `linear-gradient(135deg, ${activeChar.color1}, ${activeChar.color2})` : "#444" }} />
            <div className="bg-slate-800/60 border border-amber-500/10 rounded-xl px-3 py-2">
              <div className="flex gap-1">
                <span className="w-1.5 h-1.5 bg-amber-400 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
                <span className="w-1.5 h-1.5 bg-amber-400 rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
                <span className="w-1.5 h-1.5 bg-amber-400 rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
              </div>
            </div>
          </div>
        )}
        <div ref={chatEndRef} />
      </div>

      {/* Chat Input */}
      <div className="border-t border-amber-600/20 px-3 py-2.5 bg-slate-900/60">
        <div className="flex gap-2">
          <textarea
            value={chatInput}
            onChange={e => setChatInput(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); } }}
            placeholder={activeChar ? `Ask ${activeChar.name}...` : "Select a wizard..."}
            rows={1}
            className="flex-1 bg-slate-900 border border-amber-500/20 rounded-lg px-3 py-2 text-xs text-amber-50 placeholder-slate-500 focus:border-amber-500/50 outline-none resize-none"
            style={{ maxHeight: "80px" }}
          />
          <button onClick={sendMessage} disabled={loading || !chatInput.trim()}
            className="px-3 py-2 bg-amber-600 hover:bg-amber-500 disabled:opacity-30 disabled:cursor-not-allowed text-white rounded-lg transition-colors">
            <Icon d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z" size={14} />
          </button>
        </div>
      </div>
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════
// MAIN APP
// ═══════════════════════════════════════════════════════════════════

// R143: single-source-of-truth helpers for service URLs.
// `signal_bridge_config.json` and the Guild's `app_control` matrix
// both carried ComfyUI / Ollama / Kobold endpoints; the Travelling
// Wizard only read the former, so any edit the user made in the
// sidebar chip row never surfaced here. These two helpers let the
// Network + Integrations tabs read+write the canonical `app_control`
// entry via /api/app_control/config + /api/app_control/register.

// Map Travelling Wizard tool ids → app_control service key.
const APP_CONTROL_KEY_MAP = {
  comfyui: "comfyui",
  ollama: "ollama",
  koboldcpp: "kobold",
  kobold_rp: "kobold_rp",
  kobold_tts: "kobold_tts",
};

// Default port per service (used when app_control entry has host but
// no explicit port — matches the Guild's register endpoint defaults).
const DEFAULT_PORT = {
  comfyui: 8188, ollama: 11434, kobold: 5001,
  kobold_rp: 5001, kobold_tts: 5002,
};

function appControlUrl(appControl, serviceKey) {
  const entry = (appControl && appControl[serviceKey]) || null;
  if (!entry) return null;
  if (entry.url) return String(entry.url).replace(/\/+$/, "");
  const host = entry.host
    || (entry.target && entry.target !== "local" ? entry.target : null);
  if (!host) return null;
  const port = entry.port || DEFAULT_PORT[serviceKey] || 8188;
  return `http://${host}:${port}`;
}

function parseUrlToRegisterPayload(app, rawInput) {
  const raw = (rawInput || "").trim();
  if (!raw) return null;
  const payload = { app, target: "local" };
  if (/^https?:\/\//i.test(raw)) {
    payload.url = raw.replace(/\/+$/, "");
    payload.launcher = payload.url;
    // Also split out host+port for the legacy codepath.
    try {
      const u = new URL(raw);
      if (u.hostname) payload.host = u.hostname;
      if (u.port) payload.port = parseInt(u.port, 10);
    } catch { /* best-effort */ }
  } else {
    // bare host:port or just host
    const [h, p] = raw.replace(/^https?[:/]+/i, "").split(":");
    payload.host = h;
    if (p) {
      const n = parseInt(p, 10);
      if (!Number.isNaN(n)) payload.port = n;
    }
    payload.launcher = raw;
  }
  return payload;
}

function SignalBridgeSettings() {
  const [config, setConfig] = useState(deepClone(DEFAULT_CONFIG));
  const [scaffolds, setScaffolds] = useState(() => builtInScaffolds());
  const [activeTab, setActiveTab] = useState("scaffolds");
  const [saved, setSaved] = useState(false);
  const [importError, setImportError] = useState("");
  const [guildOpen, setGuildOpen] = useState(false);
  // R143: app_control cached from /api/app_control/config so the
  // Network + Integrations tabs point at the Guild's canonical
  // service registry instead of diverging from signal_bridge_config.
  const [appControl, setAppControl] = useState({});
  // R120: prevTabRef + isVideoWizard / handleWizardSelect auto-switch
  // logic were removed along with the Video tab — the main Guild GUI
  // handles Cinematographer mode directly.
  //
  // Server config status: "" (idle) | "loading" | "loaded" | "saving" |
  // "saved" | "error". Surfaced in the header so the user knows their
  // edits are actually persisting.
  const [configStatus, setConfigStatus] = useState("loading");
  const fileInputRef = useRef(null);
  // Suppresses the auto-save effect on the very first render (right
  // after we hydrate from the server) so we don't immediately POST a
  // copy of what we just received.
  const hydratedRef = useRef(false);
  const saveTimerRef = useRef(null);

  // Hydrate config from the server's signal_bridge_config.json. Missing
  // keys are filled in from DEFAULT_CONFIG so partial files don't break
  // the editor. If the request fails we leave the defaults in place but
  // mark the status as "error" so the user knows nothing will persist.
  useEffect(() => {
    let cancelled = false;
    fetch("/api/signal_bridge_config")
      .then(r => r.ok ? r.json() : null)
      .then(serverCfg => {
        if (cancelled) return;
        if (serverCfg && typeof serverCfg === "object") {
          // Deep merge: top-level keys from server override defaults,
          // nested objects (paths, privacy, google) merge field-by-field
          // so a server file missing one privacy flag still hydrates the
          // others from DEFAULT_CONFIG.
          const merged = deepClone(DEFAULT_CONFIG);
          for (const k of Object.keys(serverCfg)) {
            const v = serverCfg[k];
            if (v && typeof v === "object" && !Array.isArray(v)
                && merged[k] && typeof merged[k] === "object" && !Array.isArray(merged[k])) {
              merged[k] = { ...merged[k], ...v };
            } else {
              merged[k] = v;
            }
          }
          setConfig(merged);
        }
        setConfigStatus("loaded");
        // Defer so the setConfig above commits before we arm auto-save.
        setTimeout(() => { hydratedRef.current = true; }, 0);
      })
      .catch(() => {
        if (cancelled) return;
        setConfigStatus("error");
        // Still allow editing locally — Import/Export remains the
        // escape hatch if the server is unreachable.
        setTimeout(() => { hydratedRef.current = true; }, 0);
      });
    return () => { cancelled = true; };
  }, []);

  // Debounced auto-save: any change to `config` after hydration POSTs
  // the full document to /api/signal_bridge_config 800ms later. Skips
  // the first render so we don't echo back what we just loaded.
  useEffect(() => {
    if (!hydratedRef.current) return;
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    setConfigStatus("saving");
    saveTimerRef.current = setTimeout(() => {
      fetch("/api/signal_bridge_config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(config),
      })
        .then(r => r.ok ? setConfigStatus("saved") : setConfigStatus("error"))
        .catch(() => setConfigStatus("error"));
    }, 800);
    return () => { if (saveTimerRef.current) clearTimeout(saveTimerRef.current); };
  }, [config]);

  // R143: load app_control on mount + refresh it every 10s so chip
  // edits made in the main Guild sidebar surface here without a hard
  // reload. The Network / Integrations tabs render from this state.
  useEffect(() => {
    let cancelled = false;
    const load = () => {
      fetch("/api/app_control/config")
        .then(r => r.ok ? r.json() : null)
        .then(d => {
          if (cancelled || !d) return;
          setAppControl(d.app_control || {});
        })
        .catch(() => {});
    };
    load();
    const t = setInterval(load, 10000);
    return () => { cancelled = true; clearInterval(t); };
  }, []);

  // R143: register a service URL back into the Guild's app_control.
  // Called from the Network tab inputs + ToolDetectionCard's
  // configure flow. Returns a Promise so callers can surface save
  // status locally without polling.
  const saveServiceUrl = useCallback(async (serviceKey, rawInput) => {
    const payload = parseUrlToRegisterPayload(serviceKey, rawInput);
    if (!payload) return { ok: false, error: "empty input" };
    try {
      const r = await fetch("/api/app_control/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) return { ok: false, error: d.error || `HTTP ${r.status}` };
      // Optimistic local update so the UI doesn't wait for the 10s poll.
      setAppControl(prev => ({ ...prev, [serviceKey]: d.entry || prev[serviceKey] }));
      return { ok: true, entry: d.entry };
    } catch (e) {
      return { ok: false, error: String(e.message || e) };
    }
  }, []);

  // Load server-side scaffolds (auto-detected wizards + persisted
  // overrides) and merge with built-ins. The server now returns the
  // full editable surface (steps, lora_slots, nsfw flags, workflow_key)
  // so refreshing the page restores the user's edits from disk.
  useEffect(() => {
    fetch("/api/scaffolds")
      .then(r => r.ok ? r.json() : [])
      .then(serverScaffs => {
        if (!serverScaffs.length) return;
        setScaffolds(prev => {
          const existingIds = new Set(prev.map(s => s.id));
          const newOnes = serverScaffs
            .filter(s => !existingIds.has(s.id))
            .map(s => {
              // Split the server's flat `system_prompt` into an editable
              // header + a list of `- …` bullet rules. The server ships
              // wizards with no explicit step list — the scaffold is
              // expressed via the system prompt + build_fns — so surfacing
              // the structured form here lets the user edit it instead of
              // staring at a single 3000-char textarea.
              const sp = s.system_prompt || "";
              const lines = sp.split("\n");
              const ruleIdxs = [];
              lines.forEach((ln, i) => {
                if (/^\s*[-*•]\s+/.test(ln)) ruleIdxs.push(i);
              });
              let header = sp;
              let rules = [];
              if (ruleIdxs.length >= 2) {
                // Treat everything up to the first "- " line as the header,
                // everything from there on (that matches "- …") as rules.
                const firstRuleAt = ruleIdxs[0];
                header = lines.slice(0, firstRuleAt).join("\n").trim();
                rules = lines.slice(firstRuleAt)
                  .filter(ln => /^\s*[-*•]\s+/.test(ln))
                  .map(ln => ln.replace(/^\s*[-*•]\s+/, "").trim())
                  .filter(Boolean);
              }
              return {
                id: s.id,
                name: s.name,
                description: s.description || s.subtext || "",
                subtext: s.subtext || "",
                type: s.type || "",                 // studio / model_wizard / comfyui_model / custom_…
                workflow_key: s.workflow_key || s.id,
                system_prompt_header: header,
                system_prompt_rules: rules,
                // Keep the raw prompt around so we can render a preview
                // without re-joining the split pieces every render. The
                // editor writes back through updateScaffold → persistScaffold
                // which rebuilds the flat string from header + rules.
                _raw_system_prompt: sp,
                steps: s.steps || [],
                build_fns: s.build_fns || [],       // tools the wizard invokes
                nsfw: !!s.nsfw,
                admin_only: !!s.admin_only,
                lora_slots: s.lora_slots || [],
                color1: s.color1 || "",
                color2: s.color2 || "",
                archetype: s.archetype || "",
                source: s.source || "auto_model",
                banished: s.banished || false,
                default_model: s.default_model || "",
                default_arch: s.default_arch || "",
                workflow_source: s.workflow_source || null,
              };
            });
          return newOnes.length ? [...prev, ...newOnes] : prev;
        });
      })
      .catch(() => {}); // fail silently if guild not running
  }, []);

  const tabs = [
    // R120: the Video / Cinematographer tab was removed from the
    // Travelling Wizard — video generation now lives exclusively in
    // the main Guild GUI (🎬 toggle next to the send button).
    { id: "workflows", label: "Workflows", icon: <Icons.Film /> },
    { id: "scaffolds", label: "Scaffolds", icon: <Icons.Wand /> },
    { id: "integrations", label: "Integrations", icon: <Icons.Compass /> },
    { id: "network", label: "Network", icon: <Icons.Wifi /> },
    { id: "signal", label: "Signal", icon: <Icons.Signal /> },
    { id: "users", label: "Users & Access", icon: <Icons.Users /> },
    { id: "privacy", label: "Privacy", icon: <Icons.Shield /> },
    { id: "paths", label: "Paths", icon: <Icons.Folder /> },
    { id: "advanced", label: "Advanced", icon: <Icons.Zap /> },
  ];

  const update = useCallback((key, val) => setConfig(prev => ({ ...prev, [key]: val })), []);
  const updateNested = useCallback((section, key, val) => {
    setConfig(prev => { const u = deepClone(prev); if (!u[section]) u[section] = {}; u[section][key] = val; return u; });
  }, []);

  const exportAll = () => {
    const bundle = { config: deepClone(config), scaffolds: deepClone(scaffolds) };
    const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url; a.download = "signal_bridge_config.json"; a.click();
    URL.revokeObjectURL(url);
  };

  const importAll = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      try {
        const parsed = JSON.parse(ev.target.result);
        if (parsed.config) {
          const merged = { ...deepClone(DEFAULT_CONFIG), ...parsed.config };
          setConfig(merged);
        }
        if (parsed.scaffolds && Array.isArray(parsed.scaffolds)) {
          setScaffolds(parsed.scaffolds);
        }
        setImportError("");
      } catch { setImportError("Invalid JSON file."); }
    };
    reader.readAsText(file);
  };

  const copyJson = () => {
    const bundle = { config: deepClone(config), scaffolds: deepClone(scaffolds) };
    navigator.clipboard?.writeText(JSON.stringify(bundle, null, 2));
    setSaved(true); setTimeout(() => setSaved(false), 2000);
  };

  // R120: isVideoWizard + handleWizardSelect removed with the Video tab.
  // Clicking a wizard in the GuildSidebar no longer retargets tabs here.

  return (
    <div className="min-h-screen text-amber-50" style={{marginRight: guildOpen ? "384px" : "0", transition: "margin-right 0.3s ease"}}>
      {/* Header — translucent so the page-level purple/pentagram backdrop
          defined in guild.html's <style> bleeds through. The sigil image
          replaces the flat amber squircle so the page has a real
          character icon instead of a filler button. */}
      <div className="border-b border-amber-600/25 sticky top-0 z-50"
           style={{
             background: "linear-gradient(180deg, rgba(20, 12, 40, 0.88), rgba(15, 10, 30, 0.82))",
             backdropFilter: "blur(10px)",
             WebkitBackdropFilter: "blur(10px)",
             boxShadow: "0 4px 30px rgba(178, 70, 242, 0.18), 0 2px 10px rgba(217, 119, 6, 0.12)"
           }}>
        <div className="max-w-6xl mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="tw-sigil-wrap" title="The Travelling Wizard">
                <div className="tw-sigil" />
              </div>
              <div>
                <h1 className="text-xl font-bold text-amber-50"
                    style={{letterSpacing: "0.01em",
                            textShadow: "0 0 18px rgba(178, 70, 242, 0.35)"}}>
                  The Travelling Wizard
                </h1>
                <p className="text-xs text-amber-200/70">Signal Bridge &amp; Spellcaster Scaffold</p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <span title="Server config sync status"
                className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium border ${
                  configStatus === "saved" ? "bg-emerald-900/30 border-emerald-600/40 text-emerald-300"
                  : configStatus === "saving" ? "bg-amber-900/30 border-amber-600/40 text-amber-300 animate-pulse"
                  : configStatus === "error" ? "bg-red-900/30 border-red-600/40 text-red-300"
                  : configStatus === "loaded" ? "bg-slate-800 border-slate-600/40 text-slate-300"
                  : "bg-slate-800 border-slate-600/40 text-slate-400 animate-pulse"
                }`}>
                <span className={`w-1.5 h-1.5 rounded-full ${
                  configStatus === "saved" ? "bg-emerald-400"
                  : configStatus === "saving" ? "bg-amber-400"
                  : configStatus === "error" ? "bg-red-400"
                  : configStatus === "loaded" ? "bg-slate-400"
                  : "bg-slate-500"
                }`} />
                {configStatus === "loading" ? "loading…"
                  : configStatus === "loaded" ? "synced"
                  : configStatus === "saving" ? "saving…"
                  : configStatus === "saved" ? "saved"
                  : "offline"}
              </span>
              <input type="file" ref={fileInputRef} accept=".json" onChange={importAll} className="hidden" />
              <button onClick={() => fileInputRef.current?.click()} className={btnGhost}><Icons.Upload /> Import</button>
              <button onClick={exportAll} className={btnGhost}><Icons.Download /> Export</button>
              <button onClick={copyJson} className={btnPrimary}>
                {saved ? <><Icons.Check /> Copied!</> : <><Icons.Copy /> Copy JSON</>}
              </button>
              <div className="w-px h-6 bg-amber-600/20 mx-1" />
              <button onClick={() => window.location.href = '/'}
                className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-all bg-purple-700/20 hover:bg-purple-700/40 text-purple-300">
                <Icons.MessageSquare /> Guild
              </button>
            </div>
          </div>
          {importError && (
            <div className="mt-3 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2 text-sm text-red-400 flex items-center gap-2">
              <Icons.AlertTriangle /> {importError}
            </div>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div className="bg-gradient-to-r from-slate-900/50 to-slate-900/30 border-b border-amber-600/20">
        <div className="max-w-6xl mx-auto px-6">
          <nav className="flex gap-1 overflow-x-auto py-2">
            {tabs.map(t => (
              <button key={t.id} onClick={() => setActiveTab(t.id)}
                className={`flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium whitespace-nowrap transition-all ${
                  activeTab === t.id ? "bg-amber-600/30 text-amber-50 border border-amber-500/50" : "text-slate-400 hover:text-amber-300 hover:bg-purple-800/20"
                }`}
                style={{boxShadow: activeTab === t.id ? "0 0 12px rgba(217, 119, 6, 0.2)" : ""}}>
                {t.icon} {t.label}
              </button>
            ))}
          </nav>
        </div>
      </div>

      {/* Content — wrapped in .tw-tab-panel so each tab switch has a
          gentle 180ms fade-in (defined in guild.html). Keyed on activeTab
          so React remounts the panel and the animation replays. */}
      <div className="max-w-6xl mx-auto px-6 py-6 tw-tab-panel" key={activeTab}>
        {/* R120: Video tab removed — Cinematographer lives only in the
            main Guild GUI (🎬 toggle next to the chat send button). */}

        {/* ── Workflows Tab ── */}
        {activeTab === "workflows" && (
          <WorkflowBrowser comfyuiUrl={config.comfyui_url} onCreateScaffold={(wf) => {
            const newScaff = scaffoldFromParsedWorkflow(wf);
            setScaffolds(prev => [...prev, newScaff]);
            setActiveTab("scaffolds");
          }} />
        )}

        {/* ── Scaffolds Tab ── */}
        {activeTab === "scaffolds" && (
          <div className="space-y-4">
            <CrossPluginManifest />
            <div className="bg-slate-900 border border-amber-600/30 rounded-xl overflow-hidden">
              <div className="px-5 py-4 border-b border-amber-600/20 bg-purple-900/20">
                <h3 className="text-lg font-semibold text-amber-50 flex items-center gap-2">
                  <Icons.Feather /> Wizard Guild — edit scaffold behaviour
                </h3>
                <p className="text-xs text-slate-400 mt-1">
                  Writes per-wizard overrides to <code className="text-amber-200">scaffold_overrides.json</code>
                  &nbsp;(steps, LoRA slots, system prompt, NSFW flag, workflow_key).
                  Only Wizard Guild scaffolds are editable here — GIMP/Darktable/Resolve/SillyTavern methods
                  live in their plugin source and are audited above (read-only).
                </p>
              </div>
              <div className="p-5">
                <ScaffoldEditor scaffolds={scaffolds} setScaffolds={setScaffolds} />
              </div>
            </div>
          </div>
        )}

        {/* ── Integrations Tab ── */}
        {activeTab === "integrations" && (
          <IntegrationsPanel config={config} appControl={appControl}
            onConfigure={(tabId) => setActiveTab(tabId)} />
        )}

        {/* ── Network Tab ── */}
        {activeTab === "network" && (
          <div className="space-y-4">
            <div className="bg-amber-500/10 border border-amber-600/30 rounded-lg p-3 flex items-start gap-3">
              <span className="text-amber-500 mt-0.5"><Icons.Compass size={18} /></span>
              <p className="text-sm text-amber-200">
                <strong>ComfyUI / Ollama / Kobold URLs below reflect the
                main Guild sidebar's app-control registry (single source of
                truth).</strong> Edits here are persisted via
                <code className="mx-1 px-1 rounded bg-slate-800/60 text-amber-200">/api/app_control/register</code>
                so chip status and Travelling Wizard stay in sync.
              </p>
            </div>
            <SectionCard title="LLM Server" icon={<Icons.Server />}>
              <Field label="Open WebUI URL" tip="The address of your Open WebUI instance. This is where the LLM processes messages. Default: http://localhost:8080">
                <input value={config.webui_url} onChange={e => update("webui_url", e.target.value)} className={inputCls} />
              </Field>
              <Field label="Open WebUI API Key" tip="Authentication token for the WebUI API. Generate this from Open WebUI → Settings → Account → API Keys">
                <PasswordField value={config.webui_api_key} onChange={e => update("webui_api_key", e.target.value)} placeholder="sk-..." className={inputCls} />
              </Field>
              <AppControlField
                label="Ollama URL"
                tip="Direct Ollama API endpoint, shared with the main Guild sidebar. Default: http://localhost:11434"
                serviceKey="ollama"
                appControl={appControl}
                fallback={config.ollama_url || ""}
                onSave={saveServiceUrl}
              />
              <Field label="Default Model" tip="The Ollama model tag used for all conversations. Must be pulled on the Ollama server first (e.g. llama3:latest, mistral:latest)">
                <input value={config.model} onChange={e => update("model", e.target.value)} className={inputCls} />
              </Field>
              <AppControlField
                label="KoboldCpp URL"
                tip="KoboldCpp chat/RP instance URL. Default: http://localhost:5001"
                serviceKey="kobold"
                appControl={appControl}
                fallback={config.kobold_url || ""}
                onSave={saveServiceUrl}
              />
              <AppControlField
                label="Kobold · TTS/STT URL"
                tip="Separate KoboldCpp instance for voice (walkie-talkie + text-to-speech). Default: http://localhost:5002"
                serviceKey="kobold_tts"
                appControl={appControl}
                fallback=""
                onSave={saveServiceUrl}
              />
            </SectionCard>
            <SectionCard title="ComfyUI Server" icon={<Icons.Zap />}>
              <AppControlField
                label="ComfyUI URL"
                tip="Address of your ComfyUI server for image generation. Shared with the main Guild sidebar. Default: http://localhost:8188"
                serviceKey="comfyui"
                appControl={appControl}
                fallback={config.comfyui_url || ""}
                onSave={saveServiceUrl}
              />
              <Field label="Output Directory" tip="Where ComfyUI saves generated images on the server filesystem. Used for cleanup and retrieval">
                <input value={config.comfyui_output_dir || ""} onChange={e => update("comfyui_output_dir", e.target.value)} className={inputCls} />
              </Field>
              <Field label="Cleanup Timer (minutes)" tip="How often (in minutes) to purge old generated files from the ComfyUI output directory. Set to 0 to disable">
                <input type="number" min="0" max="1440" value={config.comfyui_cleanup_minutes || 30} onChange={e => update("comfyui_cleanup_minutes", parseInt(e.target.value) || 30)} className={inputCls + " w-32"} />
              </Field>
            </SectionCard>
          </div>
        )}

        {/* ── Signal Tab ── */}
        {activeTab === "signal" && (
          <div className="space-y-4">
            <SectionCard title="Signal Configuration" icon={<Icons.Signal />}>
              <Field label="Signal Phone Number" tip="The phone number registered with signal-cli that the bridge sends/receives messages from. Must be registered first via signal-cli">
                <input value={config.phone_number} onChange={e => update("phone_number", e.target.value)} className={inputCls} />
              </Field>
              <Field label="Admin Phone Number" tip="Your personal Signal number. Messages from this number bypass all restrictions and have full NSFW + admin access">
                <input value={config.admin_number} onChange={e => update("admin_number", e.target.value)} className={inputCls} />
              </Field>
              <Field label="signal-cli Path" tip="Path to the signal-cli binary or wrapper script. Can be absolute path or just the version folder name">
                <input value={config.signal_cli_path} onChange={e => update("signal_cli_path", e.target.value)} className={inputCls} />
              </Field>
              <Field label="Poll Interval (seconds)" tip="How often (in seconds) the bridge checks for new Signal messages. Lower = faster response, higher = less CPU usage">
                <input type="number" min="1" max="30" value={config.poll_interval} onChange={e => update("poll_interval", parseInt(e.target.value) || 2)} className={inputCls + " w-32"} />
              </Field>
            </SectionCard>
            <SectionCard title="Google Integration" icon={<Icons.Lock />}>
              <Field label="Credentials File" tip="Path to the Google OAuth client_secret JSON file. Required for Gmail, Calendar, Tasks, and Drive integration">
                <input value={config.google?.credentials_file || ""} onChange={e => updateNested("google", "credentials_file", e.target.value)} className={inputCls} />
              </Field>
              <Field label="Admin Email" tip="The Google account email used for OAuth. Calendar events, emails, and tasks are synced from this account">
                <input value={config.google?.admin_email || ""} onChange={e => updateNested("google", "admin_email", e.target.value)} className={inputCls} />
              </Field>
            </SectionCard>
          </div>
        )}

        {/* ── Users Tab ── */}
        {activeTab === "users" && (
          <SectionCard title="Authorized Users" icon={<Icons.Users />} collapsible={false}>
            <div className="bg-amber-500/10 border border-amber-600/30 rounded-lg p-3 flex items-start gap-3 mb-2">
              <span className="text-amber-500 mt-0.5"><Icons.AlertTriangle /></span>
              <p className="text-sm text-amber-200"><strong>Restricted</strong> = SFW only. <strong>Unrestricted</strong> = full NSFW access. Admin always has unrestricted access.</p>
            </div>
            <PhoneManager config={config} setConfig={setConfig} />
          </SectionCard>
        )}

        {/* ── Privacy Tab ── */}
        {activeTab === "privacy" && <SectionCard title="Privacy & Cleanup" icon={<Icons.Shield />} collapsible={false}><PrivacyPanel config={config} setConfig={setConfig} /></SectionCard>}

        {/* ── Paths Tab ── */}
        {activeTab === "paths" && <SectionCard title="File Paths" icon={<Icons.Folder />} collapsible={false}><PathEditor config={config} setConfig={setConfig} /></SectionCard>}

        {/* ── Advanced Tab ── */}
        {activeTab === "advanced" && (
          <div className="space-y-4">
            <SectionCard title="Rate Limiting" icon={<Icons.Zap />}>
              <div className="grid grid-cols-2 gap-4">
                <Field label="Max Requests" tip="Maximum number of messages a user can send within the rate window. Prevents abuse and runaway API costs">
                  <input type="number" value={config.rate_limit} onChange={e => update("rate_limit", parseInt(e.target.value) || 20)} className={inputCls} />
                </Field>
                <Field label="Window (seconds)" tip="Time window for rate limiting. A user can send 'Max Requests' messages within this many seconds before being throttled">
                  <input type="number" value={config.rate_window} onChange={e => update("rate_window", parseInt(e.target.value) || 60)} className={inputCls} />
                </Field>
              </div>
              <Field label="Max History" tip="Number of previous messages kept in the conversation context. Higher = better memory but more tokens per request">
                <input type="number" value={config.max_history} onChange={e => update("max_history", parseInt(e.target.value) || 30)} className={inputCls + " w-32"} />
              </Field>
            </SectionCard>
            <SectionCard title="System Prompt" icon={<Icons.Server />}>
              <Field label="Default System Prompt" tip="Base system prompt injected into every LLM conversation. Persona-specific instructions are appended after this">
                <textarea value={config.system_prompt} onChange={e => update("system_prompt", e.target.value)} rows={6} className={inputCls + " resize-y"} />
              </Field>
            </SectionCard>
            <SectionCard title="Raw JSON" icon={<Icons.Copy />}>
              <pre className="bg-slate-950 border border-amber-600/20 rounded-lg p-4 text-xs text-slate-300 overflow-auto max-h-96 font-mono">
                {JSON.stringify({ config, scaffolds }, null, 2)}
              </pre>
            </SectionCard>
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="bg-gradient-to-r from-slate-900 via-slate-900/95 to-slate-900 border-t border-amber-600/30 mt-8">
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
          <p className="text-xs text-amber-200/60">The Travelling Wizard · Spellcaster Suite · {scaffolds.length} scaffold(s) configured</p>
          <button onClick={exportAll} className={btnPrimary}><Icons.Save /> Export All</button>
        </div>
      </div>

      {/* Guild Sidebar Panel */}
      <GuildSidebar
        isOpen={guildOpen}
        onToggle={() => setGuildOpen(false)}
        comfyUrl={config.comfyui_url || "http://127.0.0.1:8188"}
        koboldUrl={config.kobold_url || "http://127.0.0.1:5001"}
        // R120: onWizardSelect dropped — video auto-switch logic gone.
      />
    </div>
  );
}

window.SignalBridgeSettings = SignalBridgeSettings;
