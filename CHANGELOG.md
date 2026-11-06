# Changelog

## 0.1.1 — 2026-11-06

- Retained the portable Fish Gallery HTML download with chronological and visual-similarity grouping, track views and species review controls from desktop openfish.
- Saved similarity groups alongside cloud outputs. Configure a local DINOv2 bundle to enable appearance groups; missing models are clearly reported without inventing groups.

## 0.1.0 — 2026-11-06

- Created the shared openfishGPU video-analysis web workspace.
- Added Google Drive library browsing and direct resumable uploads.
- Added authenticated job history, durable submission claims, RunPod status/cancellation and protected result streaming.
- Adapted openfish 0.7.3 CFD YOLO/BoT-SORT tracking for CUDA; preserved stable raw track IDs across outputs.
- Added multi-view track species scoring, threshold/margin abstention, gallery search and CSV/video downloads.
- Added model checksum verification, explicit model-unavailable results, run manifests and version provenance.
- Added separate web/worker container recipes, CI tests, deployment/cost/recovery documentation.
- Configured the test import path explicitly for both console and module invocation in CI.
- Architectural difference from OpenReefGPU: a single-replica Python API and persistent SQLite index replace the Cloudflare control API; Drive/RunPod boundaries are retained.

Validation status: 19 passing mock-cloud API/worker and species tests, syntax checks, API dependency audit, and a three-frame local CPU detector/encoding smoke; live provider acceptance and GPU model validation remain deployment requirements. This version does not include audio, a pretrained species model, per-user workspaces, automatic deployment, or automatic cleanup.
