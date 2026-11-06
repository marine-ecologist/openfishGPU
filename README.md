# openfishGPU

A shared web workspace for fish detection, BoT-SORT tracking, track-level species suggestions, and gallery review of underwater video. Videos and durable outputs live in Google Drive; RunPod Serverless runs the CUDA workload.

**Version 0.1.2 · implementation preview.** API lifecycle and species aggregation are tested with mocked cloud services. A live CUDA/Drive deployment must pass the acceptance procedure below before research use. Model weights and cloud credentials are not bundled.

## Workflow

1. Sign into the shared team workspace.
2. Upload a video directly to Drive, or browse the configured Drive video library.
3. Start a RunPod GPU job, follow its status, or request cancellation.
4. Review the annotated video and searchable track/species gallery. Choose **Group similar types** in the web gallery or download **Fish Gallery (HTML)** to retain chronological and visual-similarity grouping. Download detections, tracks, species scores and summaries.
5. Return to job history to retrieve previous results.

Tracks are provisional segments, **not unique individual fish**. Species suggestions average scores over up to four sampled views per track, apply confidence and margin thresholds, and retain unidentified results when evidence is weak or a classifier is unavailable. Scores are not calibrated accuracy. No trained Caribbean classifier is included.

## Start locally

Use Python 3.12+ and Node for the JavaScript syntax check. The web API needs no GPU.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env
# Fill .env with your own configuration, then load it through your process manager.
# Uvicorn's --env-file option needs python-dotenv if you choose that method.
.venv/bin/uvicorn server.app:app --host 127.0.0.1 --port 8000 --workers 1
```

Alternatively configure `.env` and run `docker compose up --build`. Open http://localhost:8000. Compose loads `.env` and persists the job index in its `jobs` volume. The Docker command is the simplest way to load configuration without putting secrets in a shell history.

[Setup and deployment](docs/DEPLOYMENT.md) covers OAuth, model preparation, RunPod, API hosting, acceptance tests and recovery. [Architecture](docs/ARCHITECTURE.md) explains the OpenReef reference and differences. [Costs](docs/COSTS.md) describes the billing model. [Changelog](CHANGELOG.md) records changes. [Validation report](docs/VALIDATION.md) records completed checks and limits.

The manually triggered `Build container images` GitHub Actions workflow can publish both images to GHCR without a local Docker installation. It does not deploy or start a GPU endpoint.

## Verify

```sh
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q server shared worker pipeline
node --check web/app.js
```

These checks do not submit GPU jobs or upload real video. Cloud end-to-end, container build and actual model compatibility require the configured deployment.

## Provenance

The fish-processing modules were adapted from the user's `marine-ecologist/openfish` version 0.7.3, commit `4227d09972254459554961507cd05cffe20f37d7`. OpenReefGPU 0.6.5-gpu.5's local cloud API/storage and worker implementation informed the architecture; no credentials or environment files were copied. See [third-party notices](THIRD_PARTY_NOTICES.md). Review upstream and model licenses before distribution or commercial deployment.
