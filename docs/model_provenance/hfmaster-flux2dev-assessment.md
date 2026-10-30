# hfmaster/flux2dev Assessment - t_40578d16

**Assessment Date:** 2026-10-30
**Assignee:** default
**Task ID:** t_40578d16
**Source Repository:** `hfmaster/flux2dev` (Hugging Face, https://hf.co/hfmaster/flux2dev)
**Verification Method:** Hugging Face Hub API (hub_repo_details / hub_repo_search / hf_fs), not `git clone` — the repo's two LFS files (43 GB combined) are not retrievable via a plain git clone, consistent with the capability block recorded on this card's prior runs (#84, #86, #87, #312).

---

## Executive Summary

**RATING: LOW**

`hfmaster/flux2dev` is an undocumented, unlicensed two-file Hugging Face upload (zero downloads, zero likes, zero engagement since its single commit on 2026-09-30) that has no README, no `metadata.json`, no `license.md`, no tests/CI, and no verifiable provenance tying it to Black Forest Labs' official FLUX.2-dev. Its file naming (a proprietary-looking `.tsmodel` plus a `safetensors` file that cross-references an unrelated model family, "mistral") is inconsistent with standard FLUX.2-dev releases and cannot be verified as a legitimate or safe artifact. It has no relationship to this fleet's Klein-family objectives (official, Apache-2.0, small/fast, distilled BFL models) — if anything it is the structural opposite: two unverified, oversized (24.9 GB + 18.0 GB), non-Apache, no-license binary blobs — so there is no basis to invest further fleet effort in it.

---

## Detailed Findings

| Aspect | Status | Notes |
|--------|--------|-------|
| Repository exists | **Yes** | `hfmaster/flux2dev`, created 2026-09-30, last updated 2026-09-30 (one commit) |
| `metadata.json` | **Missing** | Not present in the repo (confirmed via `hf_fs stat`) |
| `license.md` | **Missing** | Not present in the repo (confirmed via `hf_fs stat`) |
| `README.md` | **Missing** | No model card at all (confirmed via `hf_fs stat`) |
| License (Hub tag) | **None** | Repo card carries only the `region:us` tag — no license tag, no pipeline/library tag |
| Most recent commit (default branch) | **2026-09-30** | Single commit since creation; no activity in the 30 days since |
| Issue / PR activity (30d) | **None observable** | HF model repos use a Discussions tab, not GitHub issues/PRs; 0 downloads / 0 likes / trending score 0 is the only engagement signal the Hub API exposes, and it is flat |
| Automated tests / CI config / status badges | **None** | No README, no `.github/`, no CI manifest of any kind — the repo is exactly 3 files |
| User-facing documentation | **None** | No README, no docs folder, no model card prose |
| Files present | 3 total | `.gitattributes` (1.58 KB, stock LFS boilerplate) + `Artius-Flux2-Dev-v1.tsmodel` (24.88 GB, LFS) + `mistral_3_small_flux2_int8_convrot.safetensors` (18.04 GB, LFS) |
| Author profile | **Unverified** | `hfmaster` — no org page content surfaced, no other identifying signal |

---

## Klein-Family Objectives Alignment

Per this fleet's own prior provenance review (`docs/model_provenance/flux2_dev_fp8_verification.md`), the Klein-family objective is explicitly the official Black Forest Labs `FLUX.2-klein-4B` lineage: small, fast, Apache-2.0-licensed, distilled models (the same family backing the fleet's spark2 FLUX.3-klein NVFP4 library work). `hfmaster/flux2dev` has:
- no stated base model or lineage to `black-forest-labs/FLUX.2-dev` or any klein variant,
- no license at all (klein's defining trait is Apache-2.0),
- two oversized files (43 GB combined) that run directly counter to the "small/fast" klein objective,
- a filename (`Artius-Flux2-Dev-v1.tsmodel`) that does not match any known BFL or community FLUX.2-dev release pattern, and a second file name that cross-contaminates a `mistral` (LLM) naming convention into a FLUX (image) artifact — a strong signal of mislabeling, a scraped/renamed upload, or an unrelated/unverifiable conversion.

**Alignment: none established.** There is no evidence this repo serves, or could safely be made to serve, the Klein-family objective.

---

## License Compliance

**FAIL.** No `license.md`, no README, and no Hub license tag exist anywhere in the repository. Per this board's standing policy (every model adopted onto the fleet must carry a verifiable, attributable license — see the Klein-family Apache-2.0 precedent and the `CaaretAI/FLUX.2-dev-FP8` review's `flux-non-commercial-license` precedent), an artifact with **zero** license information cannot be adopted or redistributed under any current board policy. Default copyright applies with no grant of rights.

---

## Recommendation

**Action: DO NOT USE / ARCHIVE.** This repository offers no documentation, no license, no provenance, no community validation, and no alignment with the Klein-family objective it was presumably checked against. There is nothing here worth a second look unless `hfmaster` later republishes with a model card, a license, and a verifiable lineage statement.

---

## Verification Notes

- Checked via the Hugging Face Hub MCP connector (`hub_repo_details`, `hub_repo_search`, `hf_fs`) rather than `git clone`, per the capability gap this card's prior runs (#84/#86/#87/#312) correctly identified — `git clone` of an HF model repo does not reliably materialize LFS-tracked files without `git-lfs`/the Hub API, and is not required for a documentation/license/provenance review in any case.
- `hf_fs stat` was run directly against `metadata.json`, `license.md`, and `README.md` inside the repo; all three returned `exists: false`.
- This board's spellcaster git repository (`C:\Users\legui\spellcaster`, the board's actual `default_workdir` per `board.json`) is the commit target for this assessment — the earlier block reasoning on this card ("no git repository exists at the board root") conflated the kanban storage directory with the board's working repo; the working repo exists, is active, and already holds the sibling assessments this file follows the format of (e.g. `docs/model_provenance/bosch-sdxl-lora-assessment.md`, `docs/license_compliance/bosch-sdxl-lora.md`).

---

## Completion Metadata

| Field | Value |
|-------|-------|
| Commit SHA | (set by kanban_complete metadata['commit']) |
| Verified By | Claude (daddy/supervisor session, owner-approved unblock) |
| Verification Time | 2026-10-30 |
