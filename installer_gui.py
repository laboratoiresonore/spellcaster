"""
Spellcaster Premium Installer GUI
==================================
A polished 4-step wizard that transforms any machine into a generative-AI
powerhouse — no prior knowledge required.

Every preset, every model, every parameter has been hand-tuned by AI
professionals so you get studio-quality results from day one. The wizard
auto-detects your hardware, pre-selects the optimal configuration, and
handles every download, clone, and configuration step automatically.

Built with customtkinter for a premium dark-themed UI. The wizard walks
the user through:
  1. System Layout   — locate ComfyUI, GIMP, Darktable dirs + server URL
  2. Magic Profiles  — categorised feature selection matching in-app menus
                       (Generation, Restoration, Style, Face, Video, Utility, ControlNet)
  3. Components      — per-node / per-model granular control with CivitAI previews
  4. Review & Deploy — installation summary + progress bar + live log

All heavy lifting (git clones, file copies, downloads) is delegated to
install.py, imported here as ``builder``.
"""

import sys
import os
import subprocess
import threading
import time
from pathlib import Path

def ensure_dependencies():
    """Auto-install GUI deps when running from source. Skip in frozen builds."""
    if getattr(sys, 'frozen', False):
        return  # Dependencies are bundled by PyInstaller
    missing = []
    try:
        import customtkinter
    except ImportError:
        missing.append("customtkinter")
    try:
        import PIL
    except ImportError:
        missing.append("pillow")
    try:
        import requests
    except ImportError:
        missing.append("requests")

    if missing:
        print(f"Installing missing GUI dependencies: {', '.join(missing)}...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--user"] + missing)
        except Exception as e:
            print(f"Error installing dependencies: {e}")
            sys.exit(1)

# Must run before importing customtkinter / PIL / requests below
ensure_dependencies()

import customtkinter as ctk
from PIL import Image
import requests
import io

# Import actual installation logic (git clone, file copy, download helpers)
import install as builder


# ---------------------------------------------------------------------------
# Lightweight tooltip helper — no external packages required
# ---------------------------------------------------------------------------

class _ToolTip:
    """Lightweight tooltip for customtkinter widgets using only tkinter builtins."""
    def __init__(self, widget, text, delay=400):
        self.widget = widget
        self.text = text
        self.delay = delay
        self._tip = None
        self._id = None
        widget.bind("<Enter>", self._on_enter)
        widget.bind("<Leave>", self._on_leave)

    def _on_enter(self, event=None):
        self._id = self.widget.after(self.delay, self._show)

    def _on_leave(self, event=None):
        if self._id:
            self.widget.after_cancel(self._id)
            self._id = None
        if self._tip:
            self._tip.destroy()
            self._tip = None

    def _show(self):
        import tkinter as tk
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5
        self._tip = tk.Toplevel(self.widget)
        self._tip.wm_overrideredirect(True)
        self._tip.wm_geometry(f"+{x}+{y}")
        label = tk.Label(self._tip, text=self.text, background="#1a1a2e", foreground="#e2dfeb",
                         relief="solid", borderwidth=1, font=("Inter", 10),
                         wraplength=350, justify="left", padx=8, pady=4)
        label.pack()


# ---------------------------------------------------------------------------
# CivitAI thumbnail helpers — used on the Advanced (granular) tab to show
# model preview images fetched from the CivitAI API.
# ---------------------------------------------------------------------------

def fetch_civitai_thumb(page_url):
    """Extract the first preview-image URL for a CivitAI model page."""
    import requests, re
    match = re.search(r"civitai\.com/models/(\d+)", page_url)
    if not match: return None
    try:
        r = requests.get(f"https://civitai.com/api/v1/models/{match.group(1)}", timeout=5)
        if r.status_code == 200:
            return r.json().get("modelVersions", [{}])[0].get("images", [{}])[0].get("url")
    except Exception:
        pass
    return None

def load_image_async(url, label, size=(100, 100)):
    """Download an image in a daemon thread and update a CTkLabel on the main thread."""
    def worker():
        import requests, io
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                img = Image.open(io.BytesIO(r.content))
                img.thumbnail(size)
                ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=img.size)
                label.after(0, lambda: label.configure(image=ctk_img))
        except Exception:
            pass
    threading.Thread(target=worker, daemon=True).start()


# ---------------------------------------------------------------------------
# Main application window
# ---------------------------------------------------------------------------

class InstallerApp(ctk.CTk):
    """Four-step wizard window for Spellcaster installation.

    Every preset, model weight, sampler schedule, and CFG value has been
    hand-tuned by generative-AI professionals — the user simply picks what
    they want and the installer configures everything for studio-quality
    results from the very first generation.
    """

    def __init__(self, args, manifest):
        super().__init__()
        self.args = args
        self.manifest = manifest

        # --- Tk StringVars bound to the Paths UI entries ---
        self.server_url = ctk.StringVar(value=builder.DEFAULT_SERVER_URL)
        self.comfyui_path = ctk.StringVar(value=builder.find_default_comfyui())
        self.gimp_path = ctk.StringVar(value=builder.find_default_gimp())
        self.darktable_path = ctk.StringVar(value=builder.find_default_darktable())

        self.feature_vars = {}  # {feature_key: BooleanVar}
        self.model_vars = {}    # {composite_key: {var, data, feature, widget}}
        self.node_vars = {}     # {node_key: BooleanVar}
        self.lut_path = ctk.StringVar(value="")          # optional LUT import folder
        self.apply_theme = ctk.BooleanVar(value=False)   # replace system splash screens

        self.title("Spellcaster Premium Setup")
        self.geometry("960x640")
        self.minsize(860, 540)

        # Premium Magical Theme Colors
        self.bg_color = "#0B0715"
        self.sidebar_color = "#150D26"
        self.accent_color = "#D122E3"
        self.accent_hover = "#E84DF7"
        self.accent_green = "#00E676"
        self.accent_amber = "#FFB300"
        self.accent_red = "#FF5252"
        self.text_main = "#FFFFFF"
        self.text_muted = "#8E889D"

        ctk.set_appearance_mode("dark")
        self.configure(fg_color=self.bg_color)

        # Root grid: sidebar in column 0, content frames in column 1
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        # Detect GPU/VRAM early for display and feature filtering
        self._gpu_name, self._vram_mb = builder.detect_gpu_vram()
        self._vram_tier = builder.vram_tier(self._vram_mb)

        self._build_sidebar()
        self._build_main_frames()
        self._init_variables()

        self.select_frame("paths")

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_sidebar(self):
        """Create the left-hand navigation panel with hardware info,
        step buttons, and a running download-size estimate."""
        self.sidebar_frame = ctk.CTkFrame(self, width=230, corner_radius=0, fg_color=self.sidebar_color)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        self.sidebar_frame.grid_rowconfigure(7, weight=1)

        logo_label = ctk.CTkLabel(self.sidebar_frame, text="Spellcaster",
                                  font=ctk.CTkFont(family="Inter", size=24, weight="bold"),
                                  text_color=self.accent_hover)
        logo_label.grid(row=0, column=0, padx=20, pady=(20, 5))

        # Hardware detection banner
        if self._vram_mb > 0:
            vram_gb = self._vram_mb / 1024
            tier_colors = {"low": self.accent_amber, "medium": self.accent_amber,
                           "high": self.accent_green, "ultra": self.accent_green}
            tier_labels = {"low": "Starter", "medium": "Advanced",
                           "high": "Pro", "ultra": "Ultra"}
            tier_color = tier_colors.get(self._vram_tier, self.text_muted)
            tier_name = tier_labels.get(self._vram_tier, "Unknown")
            hw_text = f"{vram_gb:.0f} GB VRAM  -  {tier_name}"
        else:
            tier_color = self.accent_red
            hw_text = "No GPU Detected"

        hw_label = ctk.CTkLabel(self.sidebar_frame, text=hw_text,
                                font=ctk.CTkFont(family="Inter", size=11, weight="bold"),
                                text_color=tier_color)
        hw_label.grid(row=1, column=0, padx=20, pady=(0, 20))

        # Helper for themed buttons
        def mk_btn(text, cmd):
            return ctk.CTkButton(self.sidebar_frame, text=text, anchor="w", command=cmd,
                                 fg_color="transparent", hover_color="#21153B",
                                 text_color=self.text_main,
                                 font=ctk.CTkFont(family="Inter", size=14, weight="bold"))

        self.btn_paths = mk_btn("1. System Layout", lambda: self.select_frame("paths"))
        self.btn_paths.grid(row=2, column=0, padx=15, pady=8, sticky="ew")
        _ToolTip(self.btn_paths, "Step 1: Set the file paths where ComfyUI, GIMP, and Darktable are installed on your system. The installer auto-detects common locations, but you can override them here.")

        self.btn_features = mk_btn("2. Magic Profiles", lambda: self.select_frame("features"))
        self.btn_features.grid(row=3, column=0, padx=15, pady=8, sticky="ew")
        _ToolTip(self.btn_features, "Step 2: Choose AI capabilities organised by category (Generation, Restoration, Style, Face, Video, etc.). Each feature bundles all the models and nodes needed. Categories match the in-app menus inside GIMP and Darktable.")

        self.btn_granular = mk_btn("3. Components", lambda: self.select_frame("granular"))
        self.btn_granular.grid(row=4, column=0, padx=15, pady=8, sticky="ew")
        _ToolTip(self.btn_granular, "Step 3: Fine-tune individual models and custom nodes. Core components required by your selected profiles are locked; optional extras can be toggled freely.")

        self.btn_install = mk_btn("4. Review & Deploy", lambda: self.select_frame("install"))
        self.btn_install.grid(row=5, column=0, padx=15, pady=8, sticky="ew")
        _ToolTip(self.btn_install, "Step 4: Review a summary of your selections (features, models, download size) and launch the installation. The installer clones repositories, downloads models, and configures plugins automatically.")

        self.size_label = ctk.CTkLabel(self.sidebar_frame, text="Payload: 0 MB",
                                       font=ctk.CTkFont(family="Inter", size=13, weight="bold"),
                                       text_color=self.text_muted)
        self.size_label.grid(row=8, column=0, padx=20, pady=(10, 5), sticky="s")
        _ToolTip(self.size_label, "Estimated total download size for all selected models. Actual size may vary slightly. Make sure you have enough free disk space before starting the installation.")

        # Feature count label
        self.feat_count_label = ctk.CTkLabel(self.sidebar_frame, text="0 features selected",
                                              font=ctk.CTkFont(family="Inter", size=11),
                                              text_color=self.text_muted)
        self.feat_count_label.grid(row=9, column=0, padx=20, pady=(0, 20), sticky="s")
        _ToolTip(self.feat_count_label, "Number of Magic Profiles currently enabled. Each profile adds a set of models and nodes. More profiles means a longer installation time.")

    def _build_main_frames(self):
        """Construct the four content frames (paths, features, granular, install)."""
        self.frames = {}

        # ---- Step 1: Paths ----
        f_paths = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.frames["paths"] = f_paths

        ctk.CTkLabel(f_paths, text="System Architecture Setup",
                     font=ctk.CTkFont(family="Inter", size=28, weight="bold")).pack(anchor="w", padx=30, pady=(35, 5))
        ctk.CTkLabel(f_paths, text="Define where the magic happens. Paths are auto-detected when possible.",
                     font=ctk.CTkFont(family="Inter", size=14), text_color=self.text_muted).pack(anchor="w", padx=30, pady=(0, 25))

        def add_path_row(parent, label, var, entry_tip="", browse_tip=""):
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x", padx=30, pady=12)
            ctk.CTkLabel(row, text=label, width=170, anchor="w",
                         font=ctk.CTkFont(family="Inter", size=13, weight="bold")).pack(side="left")
            entry = ctk.CTkEntry(row, textvariable=var, width=350,
                         border_color="#3A2863", fg_color="#100B1A")
            entry.pack(side="left", padx=10)
            btn = ctk.CTkButton(row, text="Browse", width=80, command=lambda: self._browse_dir(var),
                          fg_color=self.sidebar_color, hover_color="#3A2863",
                          border_width=1, border_color="#3A2863")
            btn.pack(side="left")
            if entry_tip:
                _ToolTip(entry, entry_tip)
            if browse_tip:
                _ToolTip(btn, browse_tip)
            return entry, btn

        # ---- Step 2: Quick Features (categorised) ----
        f_feat = ctk.CTkScrollableFrame(self, corner_radius=0, fg_color="transparent")
        self.frames["features"] = f_feat
        ctk.CTkLabel(f_feat, text="Magic Profiles",
                     font=ctk.CTkFont(family="Inter", size=28, weight="bold")).pack(anchor="w", padx=30, pady=(35, 5))
        ctk.CTkLabel(f_feat, text="Choose what you want Spellcaster to do. Each category matches a menu inside GIMP/Darktable.\n"
                     "Every option is pre-tuned for studio-quality results — just check what interests you.",
                     font=ctk.CTkFont(family="Inter", size=14), text_color=self.text_muted,
                     justify="left").pack(anchor="w", padx=30, pady=(0, 10))
        ctk.CTkLabel(f_feat, text="Tip: If you are new to AI image editing, start with Generation + Restoration & Enhancement. You can always re-run the installer later to add more.",
                     font=ctk.CTkFont(family="Inter", size=12, slant="italic"), text_color=self.accent_amber,
                     wraplength=800, justify="left").pack(anchor="w", padx=30, pady=(0, 25))
        # Container frame for categorised feature cards (populated in _init_variables)
        self.feat_container = f_feat

        # ---- Step 3: Advanced / Granular ----
        f_gran = ctk.CTkScrollableFrame(self, corner_radius=0, fg_color="transparent")
        self.frames["granular"] = f_gran
        ctk.CTkLabel(f_gran, text="Mana & Ingredients",
                     font=ctk.CTkFont(family="Inter", size=28, weight="bold")).pack(anchor="w", padx=30, pady=(35, 5))
        ctk.CTkLabel(f_gran, text="Fine-tune your models and extensions manually. Core components are locked by their parent profiles.",
                     font=ctk.CTkFont(family="Inter", size=14), text_color=self.text_muted).pack(anchor="w", padx=30, pady=(0, 20))
        self.gran_content = ctk.CTkFrame(f_gran, fg_color="transparent")
        self.gran_content.pack(fill="both", expand=True, padx=30)

        # ---- Step 4: Summary + Install Console ----
        f_inst = ctk.CTkScrollableFrame(self, corner_radius=0, fg_color="transparent")
        self.frames["install"] = f_inst
        ctk.CTkLabel(f_inst, text="Review & Deploy",
                     font=ctk.CTkFont(family="Inter", size=28, weight="bold")).pack(anchor="w", padx=30, pady=(35, 5))
        ctk.CTkLabel(f_inst, text="Review your selections below, then launch the installation. Failed downloads are retried automatically.",
                     font=ctk.CTkFont(family="Inter", size=14), text_color=self.text_muted).pack(anchor="w", padx=30, pady=(0, 20))

        # --- Summary panel ---
        summary_outer = ctk.CTkFrame(f_inst, fg_color=self.sidebar_color, corner_radius=10,
                                      border_width=1, border_color="#3A2863")
        summary_outer.pack(fill="x", padx=30, pady=(0, 15))

        ctk.CTkLabel(summary_outer, text="Installation Summary",
                     font=ctk.CTkFont(family="Inter", size=18, weight="bold"),
                     text_color=self.accent_hover).pack(anchor="w", padx=20, pady=(15, 10))

        # Summary stats row
        self.summary_stats_frame = ctk.CTkFrame(summary_outer, fg_color="transparent")
        self.summary_stats_frame.pack(fill="x", padx=20, pady=(0, 5))

        self.summary_features_label = ctk.CTkLabel(self.summary_stats_frame, text="Features: 0",
                                                     font=ctk.CTkFont(family="Inter", size=14, weight="bold"),
                                                     text_color=self.accent_green)
        self.summary_features_label.pack(side="left", padx=(0, 30))

        self.summary_models_label = ctk.CTkLabel(self.summary_stats_frame, text="Models: 0",
                                                   font=ctk.CTkFont(family="Inter", size=14, weight="bold"),
                                                   text_color=self.accent_amber)
        self.summary_models_label.pack(side="left", padx=(0, 30))

        self.summary_size_label = ctk.CTkLabel(self.summary_stats_frame, text="Download: 0 MB",
                                                 font=ctk.CTkFont(family="Inter", size=14, weight="bold"),
                                                 text_color=self.accent_hover)
        self.summary_size_label.pack(side="left")

        # Summary details text
        self.summary_details = ctk.CTkTextbox(summary_outer, wrap="word", height=140,
                                               font=ctk.CTkFont(family="Consolas", size=12),
                                               fg_color="#0A0610", text_color="#A9A4B3",
                                               border_width=1, border_color="#21153B")
        self.summary_details.pack(fill="x", padx=20, pady=(5, 15))
        self.summary_details.configure(state="disabled")

        # Per-file progress label
        self.file_progress_label = ctk.CTkLabel(f_inst, text="",
                                                 font=ctk.CTkFont(family="Inter", size=12),
                                                 text_color=self.accent_hover)
        self.file_progress_label.pack(anchor="w", padx=30, pady=(0, 5))
        _ToolTip(self.file_progress_label, "Shows which file or phase is currently being processed. Updates in real-time as the installer works through plugins, nodes, and model downloads.")

        self.progress_bar = ctk.CTkProgressBar(f_inst, height=12,
                                                progress_color=self.accent_color,
                                                fg_color=self.sidebar_color)
        self.progress_bar.pack(fill="x", padx=30, pady=(0, 5))
        self.progress_bar.set(0)
        _ToolTip(self.progress_bar, "Overall installation progress. The bar advances as plugins are configured, nodes are cloned, and models are downloaded. Large models may cause the bar to pause — this is normal.")

        # Progress percentage label
        self.progress_pct_label = ctk.CTkLabel(f_inst, text="0%",
                                                font=ctk.CTkFont(family="Inter", size=11, weight="bold"),
                                                text_color=self.text_muted)
        self.progress_pct_label.pack(anchor="e", padx=30, pady=(0, 10))
        _ToolTip(self.progress_pct_label, "Percentage of the total installation completed. Calculated across all three phases: plugin configuration, node cloning, and model downloading.")

        self.log_box = ctk.CTkTextbox(f_inst, wrap="word", height=250,
                                       font=ctk.CTkFont(family="Consolas", size=13),
                                       fg_color="#0A0610", text_color="#A9A4B3",
                                       border_width=1, border_color="#21153B")
        self.log_box.pack(fill="both", expand=True, padx=30, pady=(0, 20))
        _ToolTip(self.log_box, "Live installation log. Shows each step as it executes: plugin copies, git clones, model downloads, and any warnings or errors. Scroll up to review earlier messages.")

        self.start_btn = ctk.CTkButton(f_inst, text="Launch Installation",
                                        command=self.start_installation, height=45,
                                        font=ctk.CTkFont(family="Inter", size=16, weight="bold"),
                                        fg_color=self.accent_color, hover_color=self.accent_hover)
        self.start_btn.pack(pady=15)
        _ToolTip(self.start_btn, "Start the installation! This will download all selected models and clone all required custom nodes into your ComfyUI directory. The button is disabled once installation begins. Failed downloads are automatically retried once.")

        # Now add the actual path rows into f_paths
        add_path_row(f_paths, "ComfyUI Directory:", self.comfyui_path,
                     entry_tip="Root folder of your ComfyUI installation (contains 'models', 'custom_nodes', etc.). The installer auto-detects this if ComfyUI is in a standard location. All models and nodes will be installed here.",
                     browse_tip="Open a folder picker to locate your ComfyUI installation directory.")
        add_path_row(f_paths, "GIMP 3 Plugins Dir:", self.gimp_path,
                     entry_tip="GIMP 3 plug-ins directory where the ComfyUI connector will be installed. Usually auto-detected. On Windows this is typically under AppData/Roaming/GIMP/3.0/plug-ins.",
                     browse_tip="Open a folder picker to locate your GIMP 3 plug-ins directory.")
        add_path_row(f_paths, "Darktable lua Dir:", self.darktable_path,
                     entry_tip="Darktable Lua scripts directory where the ComfyUI connector will be installed. Usually auto-detected. On Linux this is typically ~/.config/darktable/lua/.",
                     browse_tip="Open a folder picker to locate your Darktable Lua scripts directory.")

        # LUT source folder row
        lut_row = ctk.CTkFrame(f_paths, fg_color="transparent")
        lut_row.pack(fill="x", padx=30, pady=12)
        ctk.CTkLabel(lut_row, text="LUT Source Folder:", width=170, anchor="w",
                     font=ctk.CTkFont(family="Inter", size=13, weight="bold")).pack(side="left")
        lut_entry = ctk.CTkEntry(lut_row, textvariable=self.lut_path, width=350,
                     border_color="#3A2863", fg_color="#100B1A",
                     placeholder_text="Optional — .cube/.3dl files from Davinci Resolve…")
        lut_entry.pack(side="left", padx=10)
        _ToolTip(lut_entry, "Optional: Point this to a folder containing .cube or .3dl LUT files (e.g. exported from DaVinci Resolve). They will be copied into ComfyUI's models/luts/ folder for use in Color Grading workflows. Leave blank to skip.")
        lut_browse = ctk.CTkButton(lut_row, text="Browse", width=80,
                      command=lambda: self._browse_dir(self.lut_path),
                      fg_color=self.sidebar_color, hover_color="#3A2863",
                      border_width=1, border_color="#3A2863")
        lut_browse.pack(side="left")
        _ToolTip(lut_browse, "Open a folder picker to locate your LUT files directory.")
        ctk.CTkLabel(f_paths,
                     text="💡 LUT files will be copied to ComfyUI/models/luts/ and appear in Color Grading presets.",
                     font=ctk.CTkFont(family="Inter", size=11), text_color=self.text_muted,
                     wraplength=700, justify="left").pack(anchor="w", padx=30, pady=(0, 8))

        # Server URL row (no Browse button needed)
        row = ctk.CTkFrame(f_paths, fg_color="transparent")
        row.pack(fill="x", padx=30, pady=12)
        ctk.CTkLabel(row, text="ComfyUI Endpoint:", width=170, anchor="w",
                     font=ctk.CTkFont(family="Inter", size=13, weight="bold")).pack(side="left")
        server_entry = ctk.CTkEntry(row, textvariable=self.server_url, width=350,
                     border_color="#3A2863", fg_color="#100B1A")
        server_entry.pack(side="left", padx=10)
        _ToolTip(server_entry, "The URL where ComfyUI's API server is running. Default is http://127.0.0.1:8188. Only change this if you run ComfyUI on a different port or on a remote machine.")

        # Theme override checkbox
        theme_frame = ctk.CTkFrame(f_paths, fg_color="#150D26", corner_radius=8,
                                   border_width=1, border_color="#3A2863")
        theme_frame.pack(fill="x", padx=30, pady=(10, 20))
        theme_cb = ctk.CTkCheckBox(
            theme_frame,
            text="  Apply Spellcaster Visual Theme  (replaces GIMP/Darktable system splash screens)",
            variable=self.apply_theme,
            font=ctk.CTkFont(family="Inter", size=13, weight="bold"),
            fg_color=self.accent_color, hover_color=self.accent_hover,
        )
        theme_cb.pack(anchor="w", padx=20, pady=10)
        _ToolTip(theme_cb, "Replace the default GIMP and Darktable splash screens with custom Spellcaster artwork. This is purely cosmetic and does not affect functionality. WARNING: Requires Administrator/sudo privileges because system splash files are write-protected. Run generate_showcase.py --only splash first to create the images.")
        ctk.CTkLabel(
            theme_frame,
            text=("⚠  Requires Administrator rights on Windows / sudo on Linux.  "
                  "Run generate_showcase.py --only splash first to create the artwork."),
            font=ctk.CTkFont(family="Inter", size=11),
            text_color=self.accent_amber,
            wraplength=760, justify="left",
        ).pack(anchor="w", padx=35, pady=(0, 10))

    def _browse_dir(self, var):
        """Open a native directory picker and write the result into *var*."""
        from customtkinter import filedialog
        path = filedialog.askdirectory()
        if path: var.set(path)

    # ------------------------------------------------------------------
    # Variable / checkbox initialisation
    # ------------------------------------------------------------------

    def _init_variables(self):
        """Populate the Quick Features and Advanced tabs with checkboxes
        derived from the installation manifest.

        Features are VRAM-filtered: incompatible features are shown but
        disabled, so even a first-time user gets a perfectly tuned selection.
        """

        # --- Feature checkboxes (step 2) — organised by in-app menu category ---

        # Category definitions: (icon, title, description, feature_keys, examples_hint)
        _categories = [
            ("paint", "Generation",
             "Transform, create, and refine images. This is the core of Spellcaster — turn text into images, "
             "transform existing photos, fill in masked areas, extend canvas edges, or generate multiple "
             "variations in one batch. Recommended for beginners.",
             ["img2img", "txt2img", "klein_flux2", "inpaint", "outpaint", "batch_variations"],
             "See the Fantasy Landscape and Portrait Retouch showcases for examples."),

            ("wand", "Restoration & Enhancement",
             "Fix, enhance, and restore photos to pristine quality. Upscale low-resolution images up to 8x, "
             "restore damaged or blurry faces, run a full one-click restoration pipeline, or hallucinate "
             "fine details that were never there. Great for rescuing old family photos.",
             ["upscale", "face_restore", "photo_restore", "detail_hallucinate", "supir", "seedv2r", "lama_remove", "colorize"],
             "See the Photo Restoration and Upscale showcases for before/after examples."),

            ("palette", "Style & Color",
             "Change the mood of any image. Apply cinematic film-stock LUTs (Kodak, Fujifilm, ACES), "
             "transfer the visual style of a reference image, or relight a photo with 10 directional "
             "lighting presets — all without re-generating.",
             ["style_transfer", "lut_grading", "iclight"],
             "See the Film Looks and Relighting showcases for examples."),

            ("masks", "Face & Identity",
             "Swap faces between photos or generate new images that preserve a specific person's identity. "
             "Two face-swap engines (ReActor and MTB) are included for maximum compatibility. PuLID Flux "
             "is the most advanced option but requires 12 GB+ VRAM.",
             ["face_swap_reactor", "face_swap_mtb", "faceid_img2img", "pulid_flux"],
             "See the Face Swap showcase for examples."),

            ("film", "Video",
             "Generate short video clips from a single still image using Wan 2.2. Includes optional "
             "frame interpolation (RIFE) and RTX upscaling for smooth, high-resolution output. "
             "Requires at least 8 GB VRAM; 12 GB+ recommended.",
             ["wan_i2v"],
             "See the Video Generation showcase for examples."),

            ("tools", "Utility",
             "Handy single-purpose tools. Remove backgrounds with one click (produces transparent PNG), "
             "or embed invisible watermark metadata into your generated images.",
             ["rembg"],
             None),

            ("grid", "ControlNet",
             "Guide image generation using structural constraints extracted from a reference image. "
             "Supports Canny edges, depth maps, pose detection, scribble sketches, lineart, and tile. "
             "Essential for precise control over composition and structure.",
             ["controlnet"],
             "See the ControlNet Poses showcase for examples."),
        ]

        # Icon map for category headers
        _cat_icons = {
            "paint": "\U0001F3A8",      # artist palette
            "wand": "\U00002728",        # sparkles
            "palette": "\U0001F308",     # rainbow
            "masks": "\U0001F465",       # busts in silhouette
            "film": "\U0001F3AC",        # clapper board
            "tools": "\U0001F9F0",       # toolbox
            "grid": "\U0001F4D0",        # triangular ruler
        }

        # Helper text for features
        _feature_helper = {
            "img2img": "Recommended for beginners. The bread-and-butter of AI image editing.",
            "txt2img": "Recommended for beginners. Type a description and get an image.",
            "klein_flux2": "Optional — newest architecture, best quality. Requires 6+ GB VRAM.",
            "inpaint": "Recommended. Paint a mask over any area to regenerate it with 38 presets.",
            "outpaint": "Optional — extends your canvas in any direction using AI.",
            "batch_variations": "Optional — great for exploring creative options quickly.",
            "upscale": "Recommended for beginners. Make any image larger and sharper.",
            "face_restore": "Recommended. Fixes blurry or damaged faces automatically.",
            "photo_restore": "Recommended. One-click pipeline: upscale + face fix + sharpen.",
            "detail_hallucinate": "Optional — enhances fine texture detail using AI re-imagination.",
            "supir": "Optional — state-of-the-art but heavy. Requires 10+ GB VRAM.",
            "seedv2r": "Optional — enhances upscaling with 5 hallucination intensity levels.",
            "lama_remove": "Recommended. Paint over any object to erase it — no prompt needed.",
            "colorize": "Optional — adds natural color to black-and-white photographs.",
            "style_transfer": "Optional — copy the visual style of any reference image.",
            "lut_grading": "Optional — zero VRAM needed. Apply cinematic film stock color grades.",
            "iclight": "Optional — change lighting direction on portraits and scenes.",
            "face_swap_reactor": "Primary face-swap engine. Works on most images reliably.",
            "face_swap_mtb": "Optional — alternative face-swap engine for edge cases.",
            "faceid_img2img": "Optional — generate new images that look like a specific person. Requires 8+ GB VRAM.",
            "pulid_flux": "Advanced — highest-quality identity preservation. Requires 12+ GB VRAM.",
            "wan_i2v": "Optional — animate any still image into a short video clip. Requires 8+ GB VRAM.",
            "rembg": "Recommended for beginners. One-click background removal to transparent PNG.",
            "controlnet": "Optional — advanced structural guidance for precise image generation.",
        }

        for cat_key, cat_title, cat_desc, cat_features, cat_examples in _categories:
            # Filter out features not present in manifest
            valid_features = [f for f in cat_features if f in self.manifest["features"]]
            if not valid_features:
                continue

            icon = _cat_icons.get(cat_key, "")

            # Category container
            cat_frame = ctk.CTkFrame(self.feat_container,
                                      fg_color="#110A1F", corner_radius=12,
                                      border_width=1, border_color="#3A2863")
            cat_frame.pack(fill="x", padx=30, pady=(0, 18))

            # Category header
            cat_header = ctk.CTkFrame(cat_frame, fg_color="transparent")
            cat_header.pack(fill="x", padx=20, pady=(18, 5))

            ctk.CTkLabel(cat_header, text=f"{icon}  {cat_title}",
                         font=ctk.CTkFont(family="Inter", size=20, weight="bold"),
                         text_color=self.accent_hover).pack(side="left")

            # Category description
            ctk.CTkLabel(cat_frame, text=cat_desc,
                         font=ctk.CTkFont(family="Inter", size=13),
                         text_color=self.text_muted, wraplength=780,
                         justify="left").pack(anchor="w", padx=25, pady=(0, 12))

            # Each feature within the category
            for fkey in valid_features:
                feat = self.manifest["features"][fkey]

                # VRAM-aware default
                vram_status, vram_reason = builder.feature_compatible(feat, self._vram_mb)
                default_on = vram_status in ("ok", "warn") if self._vram_mb > 0 else False

                var = ctk.BooleanVar(value=default_on)
                self.feature_vars[fkey] = var
                var.trace_add("write", lambda *args, k=fkey: self._on_feature_toggle(k))

                feat_card = ctk.CTkFrame(cat_frame, fg_color=self.sidebar_color,
                                          corner_radius=8, border_width=1, border_color="#21153B")
                feat_card.pack(fill="x", padx=20, pady=5)

                # Top row: checkbox + badges
                top_row = ctk.CTkFrame(feat_card, fg_color="transparent")
                top_row.pack(fill="x", padx=15, pady=(10, 0))

                box = ctk.CTkCheckBox(top_row, text=feat["label"], variable=var,
                                      font=ctk.CTkFont(family="Inter", weight="bold", size=14),
                                      fg_color=self.accent_color, hover_color=self.accent_hover)
                box.pack(side="left")
                _ToolTip(box, f"Enable or disable '{feat['label']}'. When enabled, all required models and custom nodes are automatically selected on the Components tab. {feat['description']}")

                # VRAM requirement badge
                vram_min = feat.get("vram_min_gb", 0)
                vram_rec = feat.get("vram_recommended_gb", 0)
                if vram_min > 0:
                    vram_badge_text = f"{vram_min} GB VRAM"
                    if vram_rec > vram_min:
                        vram_badge_text = f"{vram_min}-{vram_rec} GB VRAM"
                    ctk.CTkLabel(top_row, text=vram_badge_text,
                                 font=ctk.CTkFont(family="Inter", size=10, weight="bold"),
                                 text_color="#0B0715", fg_color="#3A2863",
                                 corner_radius=4, width=90, height=22).pack(side="right", padx=(5, 0))

                # Compatibility badge
                if self._vram_mb > 0:
                    if vram_status == "ok":
                        badge_text = "Compatible"
                        badge_color = self.accent_green
                    elif vram_status == "warn":
                        badge_text = "May be slow"
                        badge_color = self.accent_amber
                    else:
                        badge_text = f"Needs {vram_min}+ GB"
                        badge_color = self.accent_red

                    ctk.CTkLabel(top_row, text=badge_text,
                                 font=ctk.CTkFont(family="Inter", size=11, weight="bold"),
                                 text_color=badge_color).pack(side="right", padx=8)

                # Description + model size
                desc_text = feat["description"]
                models = feat.get("models", {})
                total_mb = sum(m.get("size_mb", 0) for cat_m, arr in models.items()
                              if isinstance(arr, list) for m in arr if not m.get("optional", True))
                if total_mb > 0:
                    size_str = f"{total_mb/1024:.1f} GB" if total_mb > 1024 else f"{total_mb} MB"
                    desc_text += f"  [{size_str} required download]"

                ctk.CTkLabel(feat_card, text=desc_text, text_color=self.text_muted,
                             font=ctk.CTkFont(family="Inter", size=12), justify="left",
                             wraplength=700).pack(anchor="w", padx=45, pady=(3, 0))

                # Helper text
                helper = _feature_helper.get(fkey, "")
                if helper:
                    helper_color = self.accent_green if "Recommended" in helper else self.text_muted
                    ctk.CTkLabel(feat_card, text=helper,
                                 font=ctk.CTkFont(family="Inter", size=11, slant="italic"),
                                 text_color=helper_color).pack(anchor="w", padx=45, pady=(2, 10))
                else:
                    # Small padding at bottom if no helper
                    ctk.CTkFrame(feat_card, fg_color="transparent", height=8).pack()

            # Examples hint at bottom of category
            if cat_examples:
                ctk.CTkLabel(cat_frame, text=cat_examples,
                             font=ctk.CTkFont(family="Inter", size=11, slant="italic"),
                             text_color="#6B5F80").pack(anchor="w", padx=25, pady=(5, 15))
            else:
                ctk.CTkFrame(cat_frame, fg_color="transparent", height=10).pack()

        # --- Custom-node checkboxes (step 3, top section) ---
        ctk.CTkLabel(self.gran_content, text="Custom ComfyUI Nodes",
                     font=ctk.CTkFont(family="Inter", weight="bold", size=18),
                     text_color=self.accent_hover).pack(anchor="w", pady=(10, 10))
        for key, node in self.manifest["custom_nodes"].items():
            var = ctk.BooleanVar(value=False)
            self.node_vars[key] = var
            var.trace_add("write", lambda *args: self._update_size())
            cb = ctk.CTkCheckBox(self.gran_content,
                                 text=f"{key}   [Provides: {', '.join(node.get('provides', []))}]",
                                 variable=var,
                                 font=ctk.CTkFont(family="Inter", size=13),
                                 fg_color=self.accent_color, hover_color=self.accent_hover)
            cb.pack(anchor="w", padx=15, pady=6)
            self.node_vars[key]._widget = cb
            provides_list = ', '.join(node.get('provides', []))
            _ToolTip(cb, f"Custom ComfyUI node pack: {key}. Provides these node types: {provides_list}. If this checkbox is grayed out, it is required by one of your enabled Magic Profiles and cannot be unchecked independently.")

        # --- Model checkboxes (step 3, bottom section) ---
        ctk.CTkLabel(self.gran_content, text="Arcane Weights (AI Models)",
                     font=ctk.CTkFont(family="Inter", weight="bold", size=18),
                     text_color=self.accent_hover).pack(anchor="w", pady=(30, 10))

        for fkey, feat in self.manifest["features"].items():
            if "models" not in feat: continue

            for cat, arr in feat["models"].items():
                if cat == "note" or not isinstance(arr, list): continue

                cat_lbl = ctk.CTkLabel(self.gran_content,
                                       text=f"{feat['label']} \u2014 {cat.capitalize()}",
                                       font=ctk.CTkFont(family="Inter", weight="bold", size=14),
                                       text_color="#AFFF00")
                cat_lbl.pack(anchor="w", pady=(15, 5), padx=5)

                for idx, model in enumerate(arr):
                    mkey = f"{fkey}::{cat}::{idx}"
                    var = ctk.BooleanVar(value=not model.get("optional", True))
                    self.model_vars[mkey] = {"var": var, "data": model, "feature": fkey}
                    var.trace_add("write", lambda *args: self._update_size())

                    req_text = "" if model.get("optional", True) else "[CORE] "
                    text = f"{req_text}{model['path'].split('/')[-1]} ({model.get('size_mb', 0)} MB)"
                    if model.get('note'):
                        text += f" - {model['note']}"

                    row = ctk.CTkFrame(self.gran_content, fg_color=self.sidebar_color, corner_radius=6)
                    row.pack(fill="x", padx=15, pady=4)

                    thumb_label = ctk.CTkLabel(row, text="[No Preview]", width=80, height=80,
                                               anchor="center", text_color="#4F4466")
                    thumb_label.pack(side="left", padx=5, pady=5)
                    page_url = model.get("page_url", "")
                    if "civitai.com" in page_url:
                        thumb_label.configure(text="[Loading...]")
                        def fetch_img(lbl, purl):
                            t_url = fetch_civitai_thumb(purl)
                            if t_url: load_image_async(t_url, lbl, size=(80,80))
                            else: lbl.after(0, lambda: lbl.configure(text="[No Preview]"))
                        threading.Thread(target=fetch_img, args=(thumb_label, page_url), daemon=True).start()

                    cb = ctk.CTkCheckBox(row, text=text, variable=var, width=500,
                                         font=ctk.CTkFont(family="Inter", size=13),
                                         fg_color=self.accent_color, hover_color=self.accent_hover)
                    cb.pack(side="left", padx=15)
                    self.model_vars[mkey]["widget"] = cb
                    core_label = "This is a CORE model required by its parent profile and cannot be unchecked while that profile is active." if not model.get("optional", True) else "This is an optional model — enable it for extra capability, or skip it to save disk space."
                    size_mb = model.get('size_mb', 0)
                    size_info = f"{size_mb/1024:.1f} GB" if size_mb > 1024 else f"{size_mb} MB"
                    note_info = f" {model['note']}" if model.get('note') else ""
                    _ToolTip(cb, f"Model: {model['path'].split('/')[-1]} ({size_info}).{note_info} {core_label}")

        # Trigger initial sync for pre-selected features
        for key in self.feature_vars:
            if self.feature_vars[key].get():
                self._on_feature_toggle(key)

        self._update_size()

    # ------------------------------------------------------------------
    # Feature <-> granular synchronisation
    # ------------------------------------------------------------------

    def _on_feature_toggle(self, fkey):
        """Sync the Advanced tab when a Quick Feature checkbox changes."""
        is_on = self.feature_vars[fkey].get()
        feat = self.manifest["features"][fkey]

        for node in feat.get("custom_nodes", []):
            if node in self.node_vars:
                if is_on:
                    self.node_vars[node].set(True)
                    self.node_vars[node]._widget.configure(state="disabled")
                else:
                    # Only unlock if no other enabled feature requires this node
                    still_needed = any(
                        self.feature_vars.get(k, ctk.BooleanVar(value=False)).get()
                        and node in self.manifest["features"][k].get("custom_nodes", [])
                        for k in self.feature_vars if k != fkey
                    )
                    if not still_needed:
                        self.node_vars[node]._widget.configure(state="normal")
                        self.node_vars[node].set(False)

        for mkey, mdata in self.model_vars.items():
            if mdata["feature"] == fkey:
                model = mdata["data"]
                if is_on:
                    if not model.get("optional", True):
                        mdata["var"].set(True)
                        mdata["widget"].configure(state="disabled")
                else:
                    if not model.get("optional", True):
                        mdata["widget"].configure(state="normal")
                        mdata["var"].set(False)

        self._update_size()

    # ------------------------------------------------------------------
    # Download-size estimate
    # ------------------------------------------------------------------

    def _update_size(self):
        """Recalculate total download size, feature count, and refresh the Step 4 summary."""
        total_mb = 0
        model_count = 0
        for mdata in self.model_vars.values():
            if mdata["var"].get():
                total_mb += mdata["data"].get("size_mb", 0)
                model_count += 1

        size_str = f"{total_mb/1024:.2f} GB" if total_mb > 1024 else f"{total_mb} MB"
        self.size_label.configure(text=f"Payload: {size_str}")

        feat_count = sum(1 for v in self.feature_vars.values() if v.get())
        self.feat_count_label.configure(text=f"{feat_count} feature{'s' if feat_count != 1 else ''} selected")

        # Update Step 4 summary panel
        try:
            self.summary_features_label.configure(text=f"Features: {feat_count}")
            self.summary_models_label.configure(text=f"Models: {model_count}")
            self.summary_size_label.configure(text=f"Download: {size_str}")

            # Build summary details text
            lines = []
            selected_features = [k for k, v in self.feature_vars.items() if v.get()]
            if selected_features:
                lines.append("SELECTED FEATURES:")
                for fkey in selected_features:
                    feat = self.manifest["features"].get(fkey, {})
                    label = feat.get("label", fkey)
                    vram = feat.get("vram_min_gb", 0)
                    vram_str = f" ({vram} GB VRAM)" if vram > 0 else ""
                    lines.append(f"  + {label}{vram_str}")
            else:
                lines.append("No features selected. Go to Step 2 to choose what to install.")

            lines.append("")

            # Count nodes
            node_count = sum(1 for v in self.node_vars.values() if v.get())
            lines.append(f"CUSTOM NODES: {node_count}")
            lines.append(f"MODEL FILES:  {model_count}")
            lines.append(f"TOTAL SIZE:   {size_str}")

            if total_mb > 10240:
                lines.append("")
                lines.append("NOTE: This is a large download. Make sure you have enough")
                lines.append("disk space and a stable internet connection.")

            self.summary_details.configure(state="normal")
            self.summary_details.delete("1.0", "end")
            self.summary_details.insert("1.0", "\n".join(lines))
            self.summary_details.configure(state="disabled")
        except AttributeError:
            pass  # Summary widgets may not exist yet during init

    # ------------------------------------------------------------------
    # Frame navigation
    # ------------------------------------------------------------------

    def select_frame(self, name):
        """Show the frame for *name* and highlight its sidebar button."""
        self.btn_paths.configure(fg_color="#21153B" if name == "paths" else "transparent")
        self.btn_features.configure(fg_color="#21153B" if name == "features" else "transparent")
        self.btn_granular.configure(fg_color="#21153B" if name == "granular" else "transparent")
        self.btn_install.configure(fg_color="#21153B" if name == "install" else "transparent")

        for k, f in self.frames.items():
            if k == name:
                f.grid(row=0, column=1, sticky="nsew")
            else:
                f.grid_forget()

        # Refresh summary whenever the user navigates to Step 4
        if name == "install":
            self._update_size()

    # ------------------------------------------------------------------
    # Logging helper
    # ------------------------------------------------------------------

    def log(self, text):
        """Append *text* to the install console and auto-scroll to the end."""
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.update_idletasks()

    def _set_file_progress(self, text):
        """Update the per-file progress label above the progress bar."""
        self.file_progress_label.configure(text=text)
        self.update_idletasks()

    def _set_progress(self, fraction):
        """Update progress bar and percentage label."""
        self.progress_bar.set(fraction)
        self.progress_pct_label.configure(text=f"{fraction*100:.0f}%")
        self.update_idletasks()

    # ------------------------------------------------------------------
    # Installation pipeline
    # ------------------------------------------------------------------

    def start_installation(self):
        """Kick off the install in a daemon thread so the UI stays responsive."""
        self.start_btn.configure(state="disabled", text="Deploying...")
        threading.Thread(target=self._run_install_thread, daemon=True).start()

    def _run_install_thread(self):
        """Background worker — three-phase installation with retry logic:

        1. Host plugins — copy GIMP/Darktable connector + config
        2. Custom nodes — git clone + pip requirements
        3. Model downloads — stream with progress, retry failures once
        """
        t_start = time.time()
        stats = {"plugins": 0, "nodes": 0, "models_ok": 0, "models_skip": 0, "models_fail": 0}

        self.log("Starting deployment pipeline...")
        if self._vram_mb > 0:
            self.log(f"  GPU: {self._gpu_name}  |  VRAM: {self._vram_mb/1024:.0f} GB  |  Tier: {self._vram_tier}")
        self.log("")
        comfy_path = Path(self.comfyui_path.get()) if self.comfyui_path.get() else Path("")

        # Detect remote-only mode: no local ComfyUI, just install plugins with remote server URL
        _remote_only = not comfy_path.is_dir()
        if _remote_only:
            srv = self.server_url.get()
            self.log("=" * 56)
            self.log("  REMOTE SERVER MODE")
            self.log(f"  ComfyUI server: {srv}")
            self.log("")
            self.log("  No local ComfyUI directory found.")
            self.log("  Plugins will be installed and configured to connect")
            self.log(f"  to the remote server at {srv}.")
            self.log("")
            self.log("  Custom nodes and models must be installed on the")
            self.log("  remote machine separately.")
            self.log("=" * 56)
            self.log("")

        # ---- Phase 1: Host Plugin Configuration ----
        self._set_file_progress("Phase 1/3: Installing host plugins...")

        if self.gimp_path.get():
            self.log(f"Installing GIMP plugin to {self.gimp_path.get()}...")
            gimp_plugins_dir = Path(self.gimp_path.get())
            gimp_plugins_dir.mkdir(parents=True, exist_ok=True)
            gimp_dest = gimp_plugins_dir / "comfyui-connector"

            gimp_src = builder._find_gimp_plugin_src()
            if gimp_src:
                builder.copy_plugin(gimp_src, gimp_dest)
            else:
                src_dir = Path("plugins/gimp/comfyui-connector")
                if src_dir.is_dir():
                    builder.copy_plugin(src_dir, gimp_dest)
                else:
                    self.log("WARNING: GIMP plugin source directory not found")

            import json
            conf = {"server_url": self.server_url.get()}
            if gimp_dest.is_dir():
                with open(gimp_dest / "config.json", "w", encoding="utf-8") as f:
                    json.dump(conf, f)

            expected = gimp_dest / "comfyui-connector.py"
            if expected.exists():
                self.log(f"  GIMP plugin installed successfully")
                if os.name != "nt":
                    expected.chmod(0o755)
                stats["plugins"] += 1
            else:
                self.log(f"  WARNING: Plugin script not found at {expected}")

        if self.darktable_path.get():
            dt_dir = Path(self.darktable_path.get())
            if dt_dir.is_dir():
                self.log(f"Installing Darktable plugin to {dt_dir}...")
                dt_src = builder._find_darktable_plugin_src()
                if dt_src:
                    import shutil
                    shutil.copy2(dt_src, dt_dir / dt_src.name)
                    # Also copy auxiliary files
                    for aux in ["splash.py", "spellcaster_steg.py", "installer_background.png", "darktable_splash.jpg"]:
                        aux_src = dt_src.parent / aux
                        if aux_src.exists():
                            shutil.copy2(aux_src, dt_dir / aux)
                    conf_path = dt_dir / "config.json"
                    import json
                    with open(conf_path, "w", encoding="utf-8") as f:
                        json.dump({"server_url": self.server_url.get()}, f)
                    builder.patch_plugin_server_url(dt_dir / dt_src.name, self.server_url.get())
                    self.log(f"  Darktable plugin installed successfully")
                    stats["plugins"] += 1

        # ---- Phase 1b: LUT Import ----
        if self.lut_path.get():
            import shutil as _shutil
            lut_src = Path(self.lut_path.get())
            if lut_src.is_dir():
                self._set_file_progress("Phase 1b: Importing LUT files...")
                self.log(f"\nImporting LUT files from {lut_src}...")
                lut_exts = {".cube", ".3dl", ".lut", ".als", ".clf"}
                found_luts = []
                for ext in lut_exts:
                    found_luts.extend(lut_src.rglob(f"*{ext}"))
                    found_luts.extend(lut_src.rglob(f"*{ext.upper()}"))
                found_luts = sorted(set(found_luts))
                if found_luts:
                    luts_dir = comfy_path / "models" / "luts"
                    luts_dir.mkdir(parents=True, exist_ok=True)
                    copied_luts = 0
                    for lut in found_luts:
                        dest_lut = luts_dir / lut.name
                        if not dest_lut.exists():
                            try:
                                _shutil.copy2(lut, dest_lut)
                                copied_luts += 1
                            except OSError as e:
                                self.log(f"  WARNING: Could not copy {lut.name}: {e}")
                    self.log(f"  ✓ Imported {copied_luts} LUT file(s) → {luts_dir}")
                else:
                    self.log(f"  No LUT files found in {lut_src}")
            else:
                self.log(f"  WARNING: LUT folder not found: {lut_src}")

        # ---- Phase 1c: Apply Spellcaster Visual Theme ----
        if self.apply_theme.get():
            self._set_file_progress("Applying Spellcaster visual theme...")
            self.log("\nApplying Spellcaster visual theme...")
            import shutil as _shutil

            # GIMP system splash
            if self.gimp_path.get():
                gimp_splash = builder._find_gimp_system_splash()
                gimp_src_dir = builder._find_gimp_plugin_src()
                if gimp_src_dir:
                    gimp_banner = gimp_src_dir.parent.parent / "gimp_banner.png"
                else:
                    gimp_banner = Path("plugins/gimp/gimp_banner.png")
                if gimp_splash and gimp_banner.exists():
                    backup = gimp_splash.with_suffix(".orig" + gimp_splash.suffix)
                    try:
                        if not backup.exists():
                            _shutil.copy2(gimp_splash, backup)
                        _shutil.copy2(gimp_banner, gimp_splash)
                        self.log(f"  ✓ GIMP splash replaced")
                    except PermissionError:
                        self.log(f"  ERROR: Permission denied — restart installer as Administrator")
                    except OSError as e:
                        self.log(f"  ERROR: {e}")
                elif not gimp_banner.exists():
                    self.log(f"  WARNING: gimp_banner.png not found — run generate_showcase.py --only splash first")
                else:
                    self.log(f"  WARNING: GIMP system splash not found")

            # Darktable system splash
            if self.darktable_path.get():
                dt_splash = builder._find_darktable_system_splash()
                dt_src_file = builder._find_darktable_plugin_src()
                dt_splash_src = (dt_src_file.parent / "darktable_splash.jpg"
                                 if dt_src_file else Path("plugins/darktable/darktable_splash.jpg"))
                if dt_splash and dt_splash_src.exists():
                    backup = dt_splash.with_suffix(".orig" + dt_splash.suffix)
                    try:
                        if not backup.exists():
                            _shutil.copy2(dt_splash, backup)
                        _shutil.copy2(dt_splash_src, dt_splash)
                        self.log(f"  ✓ Darktable splash replaced")
                    except PermissionError:
                        self.log(f"  ERROR: Permission denied — restart installer as Administrator")
                    except OSError as e:
                        self.log(f"  ERROR: {e}")
                elif not dt_splash_src.exists():
                    self.log(f"  WARNING: darktable_splash.jpg not found — run generate_showcase.py --only splash first")
                else:
                    self.log(f"  WARNING: Darktable system splash not found")

        # ---- Phase 2: Custom Nodes ----
        if _remote_only:
            self.log("Phase 2/3: Skipping custom nodes (remote server mode)")
            self.log("  Install nodes on the remote ComfyUI machine instead.\n")
        else:
            self._install_nodes(comfy_path, stats)

        # ---- Phase 3: Model Downloads ----
        if _remote_only:
            self.log("Phase 3/3: Skipping model downloads (remote server mode)")
            self.log("  Download models on the remote ComfyUI machine instead.\n")
        else:
            self._install_models(comfy_path, stats)

        # ---- Done ----
        elapsed = time.time() - t_start
        self._set_file_progress("Deployment complete!")
        self._set_progress(100)
        self.log(f"\n{'='*56}")
        self.log(f"  DEPLOYMENT COMPLETE in {elapsed:.0f}s")
        self.log(f"  Plugins: {stats['plugins']}  |  Nodes: {stats['nodes']}")
        self.log(f"  Models OK: {stats['models_ok']}  |  Skipped: {stats['models_skip']}  |  Failed: {stats['models_fail']}")
        if _remote_only:
            self.log(f"\n  Plugins configured for remote server: {self.server_url.get()}")
            self.log(f"  Remember to install nodes & models on the remote machine.")
        self.log(f"{'='*56}")
        self.start_btn.configure(state="normal", text="Completed")
        return

    def _install_nodes(self, comfy_path, stats):
        """Phase 2: Clone custom nodes into ComfyUI."""
        self._set_file_progress("Phase 2/3: Installing custom nodes...")
        self.log("\nInstalling Custom Nodes...")
        import shutil
        has_git = shutil.which("git") is not None

        custom_nodes_dir = comfy_path / "custom_nodes"
        node_count = sum(1 for v in self.node_vars.values() if v.get())
        node_idx = 0

        for nkey, var in self.node_vars.items():
            if var.get():
                node_idx += 1
                if not has_git:
                    self.log(f"  ERROR: 'git' not in PATH! Skipping: {nkey}")
                    continue
                node = self.manifest["custom_nodes"][nkey]
                dest = custom_nodes_dir / nkey
                self._set_file_progress(f"Phase 2/3: Node {node_idx}/{node_count} - {nkey}")
                self.log(f"  Cloning node: {nkey}...")
                if builder.git_clone(node["repo"], dest):
                    builder.install_node_requirements(dest, comfy_path)
                    stats["nodes"] += 1
                elif "alt_repo" in node:
                    self.log(f"  Trying fallback repo for {nkey}...")
                    if builder.git_clone(node["alt_repo"], dest):
                        builder.install_node_requirements(dest, comfy_path)
                        stats["nodes"] += 1

    def _install_models(self, comfy_path, stats):
        """Phase 3: Download selected models into ComfyUI."""
        self.log("\nDownloading selected models...")
        models_to_dl = [m["data"] for m in self.model_vars.values()
                        if m["var"].get() and m["data"].get("url")]

        if not models_to_dl:
            self.log("  No models requested for download.")
            return

        total_models = len(models_to_dl)

        for i, m in enumerate(models_to_dl, 1):
            dest = comfy_path / "models" / m["path"]
            fname = m['path'].split('/')[-1]
            size_mb = m.get('size_mb', 0)

            self._set_file_progress(f"Phase 3/3: Model {i}/{total_models} - {fname}")
            self._set_progress(i / max(total_models, 1))

            if dest.exists() and dest.stat().st_size > 0:
                self.log(f"  [{i}/{total_models}] Skipping {fname} (already exists)")
                stats["models_skip"] += 1
                continue

            self.log(f"  [{i}/{total_models}] Downloading {fname} ({size_mb} MB)...")
            dest.parent.mkdir(parents=True, exist_ok=True)
            import urllib.request

            success = False
            for attempt in range(1, 3):
                try:
                    urllib.request.urlretrieve(m["url"], dest)
                    success = True
                    break
                except Exception as e:
                    if attempt == 1:
                        self.log(f"    Attempt 1 failed: {e}")
                        self.log(f"    Retrying in 3 seconds...")
                        time.sleep(3)
                    else:
                        self.log(f"    Attempt 2 failed: {e}")

            if success:
                self.log(f"    Downloaded successfully")
                stats["models_ok"] += 1
            else:
                self.log(f"    FAILED after 2 attempts: {fname}")
                stats["models_fail"] += 1
                if dest.exists():
                    dest.unlink()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_gui(args, manifest):
    """Create and run the installer window (blocking until closed)."""
    app = InstallerApp(args, manifest)
    app.mainloop()
