# spellcaster-antenna is RETIRED. DO NOT TOUCH.

The `antenna/` Python module in this repo has been superseded by
**prometheus-client** (a separate compiled binary maintained out of the
Prometheus hub). prometheus-client v0.11.79+ is what the fleet runs as
of 2026-06-20.

The retired code now lives at `antenna.RETIRED-2026-06-20-DO-NOT-TOUCH/`
so it remains readable for git history / forensic purposes but cannot
be imported by mistake.

## If you are Claude reading this
- Do NOT patch anything under `antenna.RETIRED-*/`. The user has
  explicitly archived it and gets angry every time it resurfaces.
- For ANY popup / heartbeat / fleet-visibility issue, the canonical
  code is **prometheus-client**, not this repo.
- See `~/.claude/projects/d--/memory/reference_fleet_antenna_topology.md`
  for the full fleet-antenna topology + how to tell which antenna a
  given host runs.

## Original deprecation commit
  e2ee79f0 deprecate(antenna): mark spellcaster-antenna as superseded
  by prometheus-client  (2026-06-14)
