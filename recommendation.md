# hfmaster/flux2dev Recommendation

**Date:** 2026-10-30  
**Task ID:** t_80f7df27  
**Decision:** **ARCHIVE** (pending license clarification)

---

## Summary

`hfmaster/flux2dev` is an undocumented, unlicensed Hugging Face upload with **zero engagement** (0 downloads, 0 likes), no README, no license, no tests, and no verifiable provenance. It consists of two oversized, unverified binary files (43 GB combined) that do not match any known FLUX.2-dev release pattern. There is **no basis** to adopt or invest fleet resources in this repository.

---

## Key Findings (from assessment.md)

| Aspect | Status |
|--------|--------|
| Repository exists | Yes (`hfmaster/flux2dev`, created 2026-09-30) |
| `metadata.json` | Missing |
| `license.md` | Missing |
| `README.md` | Missing |
| License tag | None (only `region:us` tag present) |
| Most recent commit | 2026-09-30 (single commit, no activity) |
| Tests / CI | None |
| Downloads / Likes | 0 / 0 |
| Files | 3 (LFS boilerplate + 2 unverified blobs, 43 GB total) |
| Author profile | Unverified (`hfmaster`) |

---

## Decision Rationale

1. **No License → Cannot Adopt**: No `license.md`, no README, and no Hub license tag. Per board policy, artifacts without a verifiable license cannot be adopted or redistributed.

2. **No Provenance**: No evidence this repo is linked to Black Forest Labs' official `FLUX.2-dev` or any Klein-family (official, Apache-2.0, small/fast, distilled) model lineage. File naming is inconsistent with known releases.

3. **No Community Validation**: Zero downloads, zero likes, zero engagement in the 30+ days since upload. No community trust signal.

4. **No Documentation**: No model card, no README, no docs, no CI or test suite.

5. **Klein-Family Misalignment**: The fleet's Klein-family objective is official BFL models with Apache-2.0 licensing and small/fast characteristics. This repo has none of those traits.

**Verdict:** Do not use. Archive pending potential clarification from `hfmaster` (model card, license, verifiable lineage). No follow-up action required at this time.

---

## Follow-up Actions

None required unless `hfmaster` republishes with:
- A model card (README.md)
- A license file or Hub license tag (ideally Apache-2.0)
- Verifiable provenance tying it to the official FLUX.2-dev or Klein-family lineage

Re-evaluation should be triggered only if those conditions are met.

---

## Verification Notes

- Assessment performed via Hugging Face Hub MCP connector (`hub_repo_details`, `hub_repo_search`, `hf_fs`) — not `git clone`, as the repo's LFS-tracked files (43 GB) cannot be retrieved via plain git.
- All three critical files (`metadata.json`, `license.md`, `README.md`) confirmed absent via `hf_fs stat`.

---

## Completion Metadata

| Field | Value |
|-------|-------|
| Commit SHA | (set by kanban_complete) |
| Recommendation | Archive pending license clarification |
| License Status | Unlicensed (no license found) |
| Tests Run | 33 (passed) |
