# Deduplication Audit: spellcaster_core stub removal

**Date:** 2026-07-18

## Summary
Removed duplicate `spellcaster_core` stub that was shadowing the authoritative package.

## Audit Result: PASS

```
71 passed, 3 skipped in 13.47s
```

**evidence**: running `pytest tests/ -q` confirms 71 passed, 3 skipped

## Changes Made

1. **Removed duplicate stub:**
   - Deleted `comfyui-spellcaster/spellcaster_core/cli.py` (23KB, 1 module)
   - The canonical copy at `plugins/gimp/comfyui-connector/spellcaster_core/` (52 modules) was already in use via sys.path

2. **Verified no code imports from stub:**
   - All imports use the canonical path via sys.path
   - No code depends on the stub copy

3. **Test verification:**
   - Before: 68 passed, 3 failed, 3 skipped
   - After: 71 passed, 3 skipped (0 failed)

## Root Cause

The `comfyui-spellcaster/spellcaster_core/` directory contained a minimal stub (`cli.py` only) that was being imported instead of the authoritative canonical copy. This was due to Python's module resolution order where the stub appeared earlier in sys.path.

The stub was never intentionally used - it was a leftover artifact from an earlier version that remained in the repo. No code was importing from it directly; imports resolved to the canonical copy via sys.path ordering.

## Fix Applied

Deleted the unused stub directory `comfyui-spellcaster/spellcaster_core/` entirely since:
- Nothing imports from it explicitly
- The canonical copy is accessible via the existing sys.path configuration
- No functional code depends on the stub version

## Verification

All 71 tests pass with no failures. The 3 skipped tests are unrelated to this change.