# Validation — 2026-11-06

Completed locally:

- 19 passing tests: authenticated sessions, origin restrictions, scoped Drive browsing, filename/size/resolution validation, upload completion, persistent and atomic submission claims, unknown submissions, progress and provider terminal states, cancellation confirmation, durable manifest recovery, worker output contract, schema/version validation, CPU rejection on the GPU endpoint, and real multi-view species aggregation/abstention.
- Python syntax compilation for API, storage, worker and pipeline; browser JavaScript syntax; verification that all 32 JavaScript element references exist in the HTML with no duplicate IDs.
- API dependency audit: zero known vulnerabilities reported by pip-audit at verification time.
- CPU smoke with the user's existing CFD fish weights and a three-frame clip generated locally from existing footage. Detection/tracking completed; three encoded output frames verified by ffprobe; species JSON, CSV and empty gallery generated. That very short clip produced zero established tracks, so this smoke does not validate detection accuracy or nonempty tracking on real footage. The nonempty gallery/manifest flow is covered by fixture tests.
- Published dependency metadata checked for the pinned Ultralytics, Transformers and RunPod versions; RunPod 2.1.0's `progress_update(job, progress)` signature verified from its distributed wheel.

Local test interpreter: Python 3.15.2. Container and CI target Python 3.12 (web) and the PyTorch base image's Python (worker). Tests use mocked Drive and RunPod; they do not send footage to external services or incur GPU charges. Test execution currently reports one upstream httpx/TestClient deprecation warning.

Not completed on this host:

- Browser visual/interaction QA: the provided browser tool failed during startup.
- Container builds: Docker is not installed. The manual `Build container images` GitHub workflow is supplied for a Linux builder; it has not been run here.
- CUDA inference, live Drive resumable upload/CORS, cloud deployment, GPU throughput, classifier bundle compatibility, and scientific accuracy validation. Follow the deployment acceptance procedure before live research work.

No production host, RunPod endpoint, Drive folder, billing resource, or model volume was provisioned during this implementation. No existing OpenReef endpoint or configuration was changed. No credentials or source footage were added to the repository.
