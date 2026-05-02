# Evaluation — Wizard Guild Upgrades: LangGraph & "ComfyInject"

**Date:** 2026-04-30
**Scope:** Tavern (`tavern/server.py`, `scaffold/`, `comfyui-spellcaster/spellcaster_core/`)
**Status:** Decision document — recommendations only, no code changes yet.

---

## TL;DR

| Candidate | Verdict | Reason |
|-----------|---------|--------|
| **"ComfyInject"** | **Misnomer — the right tool is `ComfyScript` (Chaoses-Ib)** | No project named "ComfyInject" exists on GitHub. The closest fit and the tool already evaluated in `RESEARCH_EXISTING_TOOLS.md` is `ComfyScript`. |
| **`ComfyScript`** | ⚖️ **DEFER** (already gated as 🔎 EVAL there) | Replaces ~2,469 LOC of `node_factory.py` and parts of `workflows.py` (8,276 LOC) — but mid-refactor (88 staged files renaming `spellcaster_core` imports to relative). Land the in-flight refactor first. Adopt opportunistically when the next ComfyUI node-family is added. |
| **`LangGraph`** | ❌ **SKIP for the tavern wizards** | Heavy LangChain dependency, online/cloud-leaning ecosystem, and architectural mismatch with the existing **LLM-as-orchestrator** design (`scaffold/spellcaster_wizard.py:18` — *"States form a loose graph — the scaffold is conversational, not rigid."*). Could be reconsidered narrowly for one specific pipeline (Studio 5-act) but cost > benefit today. |

---

## 1. What the user message claimed vs. ground truth

| Claim | Reality |
|-------|---------|
| Project at `D:\AI\spellcaster` | Project lives in a sibling tree (D:\AI has no `spellcaster/`). |
| `tavern/wizard-guild.spec` is a feature spec | `wizard-guild.spec` is a **PyInstaller** build spec — `Analysis(['guild_launcher.py'], ...)` — not a design doc. |
| ComfyInject is a tool | No project of that name exists in PyPI / GitHub search. Likely confusion with `ComfyScript` or `comfyui-tooling-nodes`. |
| LangGraph already considered | No hits for "LangGraph" / "langgraph" anywhere in the tree. |
| ~80 staged files relate to this work | 88 files staged, but they are a **relative-import refactor** (`from spellcaster_core.X` → `from .X`) — unrelated prep work. |

The factual core that **is** correct: the tavern has multi-step orchestration (setup, spellcaster_wizard, Studio 5-act, Director's Chair WAN) and a hand-maintained ComfyUI node graph layer. Both are surfaces that *could* be replaced. The question is whether the proposed tools are a fit.

---

## 2. Current architecture (what would be replaced)

### 2.1 ComfyUI integration layer
- `comfyui-spellcaster/spellcaster_core/node_factory.py` — **2,469 LOC**, ~129 hand-rolled node constructors.
- `comfyui-spellcaster/spellcaster_core/workflows.py` — **8,276 LOC** of `build_*` graph assemblers.
- `comfyui-spellcaster/spellcaster_core/pipeline.py` — **701 LOC**, fluent pipeline class chaining stages (upload → build → preflight → optimize → submit → download).
- Dispatch path: `dispatch.py` → ComfyUI HTTP `/prompt` + polling `/history/<id>`.
- Image I/O: filesystem round-trip via `/upload/image` and `/view?filename=...`.

### 2.2 Multi-step "wizard" orchestration
- `scaffold/spellcaster_wizard.py` — 977 LOC. **LLM-driven**: phases (`GREETING` → `ASSESS` → `INTENT` → `RECOMMEND` → `QUOTE` → `INSTALL_LOOP` → …) are *hints in the system prompt*; the LLM picks transitions and emits `<ACTION>{...}</ACTION>` JSON blocks the server executes. Comment line 18: *"loose graph — conversational, not rigid."*
- `scaffold/studio_scaffold.py` — 437 LOC, the 5-act Magic Studios pipeline.
- `scaffold/video_wizard.py` — 774 LOC, the Director's Chair (chained WAN I2V).
- `scaffold/meta_wizard.py` — 162 LOC, top-level wizard router.
- `tavern/server.py` (line 2264) — first-run setup state machine (`_setup_state_*`, `_run_avatar_setup_in_background`).

The pattern is uniform: **persistent JSON state on disk, LLM emits actions, server executes side-effects, user sees one streamed turn at a time.** No deterministic FSM library. Recovery is via re-reading the state snapshot, not via checkpointed graph nodes.

---

## 3. Evaluating ComfyScript (the actual "ComfyInject" candidate)

### What it offers
- Auto-generates typed Python constructors from `/object_info` — covers every custom node the user has installed without hand-porting.
- `with Workflow(): ...` context manager builds the prompt JSON.
- Bidirectional transpiler (Python ↔ workflow JSON), MIT licensed, active (v0.6.1 Nov 2025).

### What it would replace
- All of `node_factory.py` (~2,469 LOC).
- The graph-assembly half of `workflows.py` — the `build_*` functions become `with Workflow():` blocks (the prompt-text / negative / model-selection logic stays).

### Why DEFER, not adopt now
1. **Mid-refactor.** 88 staged files are converting absolute `spellcaster_core.X` imports to relative `.X`. Layering a new external dep on top of an unfinished package-shape refactor multiplies merge pain.
2. **Test coverage gap.** `test_quality_boost.py`, `test_model_coverage.py`, `test_klein_enhancer.py` are the regression net. They need to pass on the ComfyScript path before flipping. That's a 2–3 week migration with full A/B in CI.
3. **Per-workflow migration is the correct shape.** The research doc already prescribes this: migrate one builder at a time, both paths coexist, decision trigger = "next time we need a new ComfyUI node family."
4. **Downstream bundling.** ComfyScript needs to install cleanly into `python_embedded/`. Validate it has no native deps that break on the embedded distribution before committing.

### Adopt-now alternative that ships ~80% of the value
The research doc lists three tools that improve the **ComfyUI transport** without touching the graph DSL:
- `python-websockets` — kill the `/history` poll race (DEFERRED in research doc, but easier than ComfyScript).
- `Acly/comfyui-tooling-nodes` — eliminate filesystem round-trip on image I/O (PARTIAL today; finish wiring `ETN_LoadImageBase64` / `ETN_SendImageWebSocket`).
- `huggingface_hub` — already DONE 2026-04-20.

Recommendation: ship the websockets + ETN inline-transport pair before touching the node DSL.

---

## 4. Evaluating LangGraph

### What LangGraph offers
- Stateful graph runtime over LangChain primitives.
- Checkpointed nodes, conditional edges, human-in-the-loop interrupts, persistence backends.
- Designed for agentic LLM apps with deterministic step boundaries.

### Why it's a poor fit for the tavern wizards
1. **Architectural conflict.** The wizards are *deliberately* not deterministic graphs — `spellcaster_wizard.py:18` explicitly says phases are LLM hints. LangGraph's value comes from making transitions *deterministic* (conditional edges from inspectable state). Replacing the conversational prompt with a hard graph is a regression in flexibility for the install/calibration/build flows where users veer freely.
2. **Dependency weight.** LangGraph drags in LangChain core (langchain-core, langsmith optional, pydantic v2) — adds tens of MB to `python_embedded/`. The token-discipline rule in CLAUDE.md says defer to local LLMs; adopting LangChain pulls the project toward cloud-LLM idioms even if you don't use them.
3. **Local-LLM coverage.** LangGraph works with local LLMs, but the LangChain-native local adapters lag behind direct calls to KoboldCpp / LM Studio. Today the tavern calls KoboldCpp via plain HTTP (`DEFAULT_KOBOLD_URL = http://127.0.0.1:5001`); adding a LangChain wrapper is overhead, not leverage.
4. **No real persistence problem to solve.** State already persists as JSON snapshots (`_load_*`/`_save_*` helpers everywhere). LangGraph's checkpointers (SQLite/Postgres/Redis) are heavier than the existing `scaffold_overrides.json`/`anim_queue.json` files and don't fit the bundled-app posture.
5. **Shotboard / video pipelines.** `video_wizard.py` (Director's Chair) IS the closest thing to a true DAG — chain of WAN I2V + frame extract + assemble. *Even there*, the chain is short and linear; a 50-line dispatcher beats a graph runtime.

### When you would reconsider
- If a wizard grows to ≥10 hard-deterministic steps with branching/retry/HITL gates and the JSON-state pattern visibly bends. Studio 5-act could approach this — measure first.
- If you ship a cloud-mode tier where checkpointed long-running agents matter. Not on the roadmap today.

### Lighter-weight orchestration options worth keeping in mind
- `prefect` / `dagster` — same overweight problem; skip.
- Plain `asyncio` + a small per-wizard FSM module — already de-facto present; formalize in 50–100 LOC if you want stricter graphs (e.g. `transitions` lib, MIT, ~500 KB).
- **`pytransitions/transitions`** — only if you decide the LLM-as-orchestrator pattern is wrong for one specific wizard. Tiny, MIT, no LangChain footprint.

---

## 5. Risks specific to this codebase

- **Bundled-app constraint.** Wizard Guild ships as a PyInstaller exe (`wizard-guild.spec`). Every new dep is bytes the user downloads. LangChain alone is >50 MB once dependencies resolve; ComfyScript is leaner but pulls a typed-stub generator at runtime — verify it works under `_MEIPASS`.
- **Cross-process boundary.** `comfyui-spellcaster/` is a **ComfyUI custom-node pack** (sibling install), `tavern/` is the **Guild server**, GIMP plug-in is a **third process**. Anything stateful added to the orchestration layer must respect the existing event-bus + mailbox + SSE topology, not assume one process.
- **License hygiene.** Research doc flags GPL-3 (tooling-nodes, Manager) as use-as-sibling-only to keep MIT. ComfyScript is MIT — safe to vendor. LangGraph is MIT — safe.
- **In-flight import refactor.** Don't introduce *anything* until the 88-file `from .X` refactor lands and the relative-import pattern is the new convention.

---

## 6. Recommendation

### Implement
1. **Finish the 88-file relative-import refactor.** Land cleanly first.
2. **Pair-ship `python-websockets` + `ETN_LoadImageBase64`/`ETN_SendImageWebSocket`** (finish the PARTIAL item from research doc Sprint 2). Real wins for the tavern: faster ComfyUI completion signal, no filesystem round-trip for images, privacy improvement.
3. **Document the LLM-as-orchestrator pattern** in `_dev_docs/` so future contributors don't try to "fix" it with FSM libraries. One page.

### Defer
4. **`ComfyScript`** — wait for the next ComfyUI node-family addition trigger. Keep `RESEARCH_EXISTING_TOOLS.md` § 6 as the source of truth.

### Skip
5. **`LangGraph`** — architectural mismatch + dependency weight. If a specific wizard (Studio 5-act, Director's Chair) becomes brittle, formalize *that one* with `transitions` (MIT, tiny) instead of a graph runtime.

### Open question for the user
- Is "ComfyInject" actually a different tool you've seen elsewhere (private repo, blog post, internal name)? If yes, drop a link or a short description and this section gets re-evaluated. If no, this evaluation closes the loop.

---

## 7. Implementation order if you proceed

```
Now (blocked on refactor)
└── Land 88-file relative-import refactor
    └── Sprint A (1–2 days)
        ├── python-websockets client in dispatch.py + GIMP _spellcaster_main.py
        └── Wire ETN_LoadImageBase64 / ETN_SendImageWebSocket via use_inline_transport flag
    └── Sprint B (gated on need)
        └── ComfyScript pilot on ONE build_* (suggest: build_txt2img — smallest, well-tested)
            └── If pilot wins, migrate next-most-changed builders incrementally
    └── Skip / re-evaluate annually
        └── LangGraph
```

---

## Appendix A — Files inspected

- `tavern/server.py` (17,010 LOC; sampled by section grep)
- `tavern/wizard-guild.spec` (PyInstaller spec, 39 LOC)
- `tavern/guild_common.py`
- `scaffold/spellcaster_wizard.py` (lines 1–120)
- `_dev_docs/RESEARCH_EXISTING_TOOLS.md` (full)
- Staged-changes survey via `git diff --cached --stat`
- Web search for ComfyInject — no result

## Appendix B — What "ComfyInject" probably means

Given the user's verbal description ("ComfyInject for the purpose of improving the wizard tavern"), the closest match in the public ecosystem is **`comfyui-tooling-nodes`** by Acly (inline base64 image transport via `ETN_LoadImageBase64`) or **`ComfyScript`** by Chaoses-Ib (Python DSL injecting node graphs). Both already evaluated in `RESEARCH_EXISTING_TOOLS.md`. If a third project exists by this exact name it's not surfaced via standard search and should be linked explicitly before any further evaluation.
