================================================================
  SPELLCASTER STUDIO — portable bundle
  GIMP + ComfyUI + Spellcaster, pre-configured, no install needed.
================================================================

WHAT'S INSIDE
-------------
  gimp/        — GIMP 3.x (installed on first run; stays inside this
                 folder, does not touch your system).
  comfyui/     — ComfyUI backend with the ComfyUI-Spellcaster node
                 pack pre-installed and the canonical ControlNet
                 files pre-downloaded.
  plugin/      — The Spellcaster GIMP plug-in, pre-configured to
                 talk to the bundled ComfyUI at 127.0.0.1:8188.
  data/        — Your generated images, logs, and GIMP config.
                 This bundle writes NOTHING outside its own folder.


HOW TO USE
----------
  1. Double-click  SpellcasterStudio.bat
  2. First run installs GIMP locally (~1-3 min). Subsequent runs
     boot straight into the app (~10 s).
  3. When GIMP opens, look for the  Filters -> Spellcaster  menu.
     You should see 69 AI tools. ComfyUI is running invisibly in
     the background.
  4. Close GIMP normally when done — the launcher stops ComfyUI
     for you.


FIRST THINGS TO DO
------------------
  * GOD MODE  (optional): open  Filters -> Spellcaster -> Settings
                          and tick  "Apply Spellcaster premium
                          dark theme"  for the branded look.
  * MODELS:   the bundle ships with canonical ControlNet files,
                but NOT checkpoint models (they're 7+ GB each).
                Download a checkpoint (SDXL / Flux / Klein / etc.)
                into  comfyui\ComfyUI\models\checkpoints\  and
                restart ComfyUI (close GIMP, re-launch .bat).
  * LoRAs:    drop any .safetensors into
                comfyui\ComfyUI\models\loras\


TROUBLESHOOTING
---------------
  "ComfyUI did not become ready in 60 s"
      -> open  data\logs\comfyui.log  and scroll to the bottom.
         Most common: first launch takes longer on cold-cache Windows
         Defender scans — run the .bat once more.

  "Unable to write to this folder" on first run
      -> the bundle needs to be extracted somewhere the current
         Windows user can write. USB sticks work. OneDrive-synced
         folders can be flaky (move to a local path).

  GIMP opens but no Spellcaster menu
      -> check that  plugin\comfyui-connector\  exists next to
         SpellcasterStudio.bat. If it does, delete  data\gimp_config\
         and re-launch — GIMP will rebuild its plug-in cache.

  "Out of VRAM" during generation
      -> open  Filters -> Spellcaster -> Settings  and set "After
         generation" to "Delete temp uploads from ComfyUI", then
         restart ComfyUI. For truly low-VRAM GPUs, try the smaller
         checkpoint variants (Klein 4B instead of 9B, etc.).


UPDATING
--------
  * Plug-in updates happen automatically on GIMP launch (the bundled
    plug-in checks GitHub on startup; no bundle re-download needed).
  * ComfyUI updates: run  comfyui\update\update_comfyui.bat
  * Full bundle updates (new GIMP, new CNs): re-download the bundle
    when a new release is cut.


PRIVACY
-------
  * Nothing leaves your machine. Every generation runs on the
    ComfyUI bundled here. Spellcaster only hits external URLs for:
      - GitHub (plug-in updates)
      - Hugging Face (ControlNet auto-download, if missing)
      - Your own LLM (optional, prompt enhancement)
  * All temporary files on the bundled ComfyUI are cleaned after
    each generation (configurable in Settings).


WHERE'S MY DATA?
----------------
  Generated images (auto-copied):   data\output\
  GIMP saved files:                 wherever you saved them in GIMP
  ComfyUI logs:                     data\logs\comfyui.log
  Launcher logs:                    data\logs\launcher.log
  Plug-in config:                   plugin\comfyui-connector\config.json
  GIMP settings:                    data\gimp_config\


LICENCE + CREDITS
-----------------
  See LICENSE.txt for the full notice. Short version:
    * Spellcaster plug-in + spellcaster_core: MIT
    * GIMP (bundled): GPLv3 (redistributed per its licence)
    * ComfyUI (bundled): GPLv3 (same)
    * ControlNet files (bundled): each has its own HF licence —
      Xinsir Union (Apache 2.0), Shakker Labs Flux Union Pro
      (CreativeML OpenRAIL-M), lllyasviel v1.1 (OpenRAIL). All
      permit redistribution.

  "Spellcaster Studio" is not affiliated with or endorsed by the
  GIMP Project, who own the GIMP trademark. GIMP is bundled per
  its GPL redistribution terms; the "Studio" branding applies to
  the overall package of GIMP + ComfyUI + Spellcaster plug-in.


REPO
----
  https://github.com/laboratoiresonore/spellcaster
  https://github.com/laboratoiresonore/ComfyUI-Spellcaster

File bugs, request tools, or fork it:
  https://github.com/laboratoiresonore/spellcaster/issues
