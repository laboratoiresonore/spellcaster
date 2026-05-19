# Nightly scheduling for `llm_morning_briefing.py` + `night_maintenance.py` + `export_comfyui_workflows.py`

Run this once on the the dev host host (or any machine that should host the
nightly cycle). All scripts are best-effort — failures degrade
gracefully — so a missed run is recoverable.

## Windows Task Scheduler (the dev host)

Per `~/.claude/projects/c--Users-legui/memory/feedback_taskscheduler_redirection.md`:
Windows Task Scheduler does NOT shell-eval the Arguments field. Wrap
any `>>` / `2>&1` redirection inside `cmd.exe /c "..."` rather than
embedding it as a flag.

### night_maintenance.py — 03:00 local time

```cmd
schtasks /Create ^
    /TN "Spellcaster Night Maintenance" ^
    /TR "cmd.exe /c \"C:\Users\legui\AppData\Local\Programs\Python\Python311\python.exe C:\Users\legui\spellcaster\tests\night_maintenance.py >> C:\Users\legui\.voodoomaster\night_maintenance.log 2>&1\"" ^
    /SC DAILY ^
    /ST 03:00 ^
    /F
```

Writes `~/.voodoomaster/night_report_YYYYMMDD.md` (markdown report).
Also rotates an append-only log at `night_maintenance.log` for
audit history.

### export_comfyui_workflows.py — 03:30 local time

Refreshes the ComfyUI-GUI-visible spellcaster workflow snapshots at
`C:\Users\legui\ComfyUI\ComfyUI\user\default\workflows\spellcaster\`.
Each builder gets its own `.json` with a Note node containing docstring +
signature. Runs after night_maintenance so the exported file set
reflects the latest merged workflow changes (e.g. new opt-in kwargs
landed during the day).

```cmd
schtasks /Create ^
    /TN "Spellcaster ComfyUI Workflow Export" ^
    /TR "cmd.exe /c \"C:\Users\legui\AppData\Local\Programs\Python\Python311\python.exe C:\Users\legui\spellcaster\tools\export_comfyui_workflows.py >> C:\Users\legui\.voodoomaster\export_comfyui_workflows.log 2>&1\"" ^
    /SC DAILY ^
    /ST 03:30 ^
    /F
```

Outputs:

- 73+ `<builder>.json` files (ComfyUI GUI-loadable) under the spellcaster subfolder.
- `_INDEX.md` listing every export with its docstring summary.

Exit codes: 0 (full), 1 (partial — some failed), 2 (catastrophic). The
nightly task does not fail-stop on exit 1; a partial export is still
useful for the user.

### llm_morning_briefing.py — 04:00 local time

```cmd
schtasks /Create ^
    /TN "Spellcaster Morning Briefing" ^
    /TR "cmd.exe /c \"C:\Users\legui\AppData\Local\Programs\Python\Python311\python.exe C:\Users\legui\spellcaster\tools\llm_morning_briefing.py --model qwen2.5-coder-7b-instruct >> C:\Users\legui\.voodoomaster\morning_briefing.log 2>&1\"" ^
    /SC DAILY ^
    /ST 04:00 ^
    /F
```

Reads the 03:00 night_report + recent commits + open PRs + live caps
+ active sessions + log tails, sends the dump through LM Studio, and
writes `<repo>/_dev_docs/morning_briefing.md` for the next Claude
session to read at startup.

The 1-hour gap between the two jobs gives the dev host time to settle if the
maintenance run hits any restart.

### Verify

```cmd
schtasks /Query /TN "Spellcaster Night Maintenance"        /V /FO LIST
schtasks /Query /TN "Spellcaster ComfyUI Workflow Export"  /V /FO LIST
schtasks /Query /TN "Spellcaster Morning Briefing"         /V /FO LIST
```

### Delete

```cmd
schtasks /Delete /TN "Spellcaster Night Maintenance"        /F
schtasks /Delete /TN "Spellcaster ComfyUI Workflow Export"  /F
schtasks /Delete /TN "Spellcaster Morning Briefing"         /F
```

## Linux / macOS cron alternative

```cron
# m h  dom mon dow  command
0 3 * * *   /usr/bin/python3 /path/to/spellcaster/tests/night_maintenance.py        >> ~/.voodoomaster/night_maintenance.log 2>&1
30 3 * * *  /usr/bin/python3 /path/to/spellcaster/tools/export_comfyui_workflows.py >> ~/.voodoomaster/export_comfyui_workflows.log 2>&1
0 4 * * *   /usr/bin/python3 /path/to/spellcaster/tools/llm_morning_briefing.py     >> ~/.voodoomaster/morning_briefing.log 2>&1
```

## Model selection

`llm_morning_briefing.py --model <name>` accepts any model id LM Studio
exposes. Sensible defaults:

- `qwen2.5-coder-7b-instruct` — fast (under a minute), good for the
  structured briefing format. Recommended default.
- `qwen3-30b-a3b` — slower (~5+ minutes), nuanced output. Use if the
  briefing keeps surfacing the same blind spots.
- `deepseek-r1-0528-qwen3-8b` — reasoning-tuned; experimentally
  better when the briefing needs to PRIORITIZE among many concerns.

Anything that takes longer than the 300 s timeout falls back to
raw facts only (no LLM summary). The raw facts are still useful;
the LLM polish is an enhancement, not a requirement.
