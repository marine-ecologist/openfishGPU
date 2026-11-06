# Setup and deployment

## 1. Google Drive

Create a dedicated `openfishGPU` jobs folder and a separate video-library root. Do not point the job root at OpenReef's existing `jobs` directory. A shared drive is supported by the storage requests, provided the OAuth user can create folders and files there. A service account without Drive storage quota is not the default approach.

Enable Drive API in a Google Cloud project. Create an OAuth client and configure the consent screen, authorized redirect URI and an approved operator account. Obtain a refresh token through Google's OAuth authorization-code flow with offline access and consent. Use the `https://www.googleapis.com/auth/drive` scope when browsing existing videos; `drive.file` alone cannot browse arbitrary existing folders. This scope grants broad Drive access: use a dedicated account/library, and consider OAuth verification requirements for an externally distributed application. Testing-mode refresh tokens may expire; configure the consent screen appropriately for a durable deployment.

Store these only in the API host's secret settings and RunPod endpoint secret settings:

- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN`
- `GOOGLE_DRIVE_JOB_ROOT_ID`, `GOOGLE_DRIVE_SOURCE_ROOT_ID` (folder IDs, not URLs)

Never commit `.env`, `.dev.vars`, tokens, uploaded footage or model files. Do not paste upload-session URLs into logs. The browser receives a scoped resumable upload capability, never an access/refresh token. Uploads use 8 MiB chunks and query the session after network errors. The page must remain open during upload; after closing it, a new analysis is needed. The session URL is intentionally not persisted in browser storage.

Reference: [Google resumable upload documentation](https://developers.google.com/workspace/drive/api/guides/manage-uploads) and [Drive scopes](https://developers.google.com/workspace/drive/api/guides/api-specific-auth).

## 2. Models and RunPod

Build from the repository root:

```sh
docker build -f worker/Dockerfile -t YOUR_REGISTRY/openfishgpu-worker:0.1.0 .
docker push YOUR_REGISTRY/openfishgpu-worker:0.1.0
```

Create a **new queue-based Serverless endpoint** using that image, a CUDA 12.6-compatible GPU, enough disk for source + decoded/annotated intermediate + outputs, zero minimum workers and initially one maximum worker. Set execution timeout to fit the video length. Input requests also specify an execution timeout (default 2 hours) and a 24-hour TTL; queue time plus execution must fit TTL. Validate the effective policy in RunPod before long jobs. Do not repoint OpenReef's reconstruction endpoint at this image.

Mount a RunPod network volume and place the user's CFD YOLO weights at `/runpod-volume/openfish/models/cfd-complete.pt`. Compute its SHA-256 locally and set `DETECTOR_SHA256` to that exact hex digest. Set `OPENFISH_DETECTOR_MODEL` to the mounted path. The worker refuses to process missing or mismatched weights; it never falls back to a general object detector. The cloud release accepts only YOLO; RF-DETR is retained as upstream source but is not enabled in the cloud dependency set.

For species inference, mount a local Hugging Face image-classification bundle with `species_manifest.json` (ordered `labels`, `model_id`, pinned `revision`, and `catalog` mapping IDs to scientific-name entries). Include processor/config/weights. Alternatively use the openfish Fishial bundle with `backend: fishial_torchscript`, `model.pt`, embedded class mapping, `input_size`, labels and catalog. Set `OPENFISHID_SPECIES_MODEL` to the bundle folder. An absent/invalid classifier produces unidentified results with review reasons; it does not invent species. Review model scores and taxonomic coverage on representative footage. Thresholds are 0.8 mean score and 0.2 top-class margin in this release. The four sampled views use the desktop pipeline's bounded rotating temporal slots.

Set the Google variables above on the worker; also set `GPU_BATCH=4`, `MAX_VIDEO_BYTES` and detector variables. Copy the RunPod endpoint ID and an appropriately scoped RunPod API key to **API-host secrets only** as `RUNPOD_ENDPOINT_ID` and `RUNPOD_API_KEY`. RunPod automatically supplies its runtime credentials to its worker; do not manually embed API keys in the image.

Reference: [RunPod endpoint operations](https://docs.runpod.io/serverless/endpoints/send-requests) and [endpoint configuration](https://docs.runpod.io/serverless/endpoints/endpoint-configurations).

## 3. Web/API host

Build the root `Dockerfile` and deploy one replica, one Uvicorn worker, on a container host with persistent storage mounted at `/data`. Use `compose.yaml` locally or on a TLS reverse-proxy host. The web UI and API share one origin, avoiding credentialed cross-origin requests.

Set `PUBLIC_ORIGIN` to the exact external origin, such as `https://fish.example.org` (no trailing slash). Set an independent random `SESSION_SECRET` of at least 32 characters and `APP_PASSWORD` of at least 16 characters. Generate with a password manager. Use HTTPS in production. Configure the host's secret manager; `.env.example` documents all keys. `DATABASE_PATH=/data/jobs.sqlite3` inside the container.

The root image runs as a non-root user. Ensure `/data` is writable by that user on bind mounts. Put gateway-level sign-in throttling and team identity controls in front of the service if exposing it beyond a small trusted team. Do not enable multiple replicas against separate local databases. Back up the SQLite volume, including a consistent checkpoint rather than copying a live WAL database alone.

No production endpoint is created automatically by this repository. Deployment needs configured provider accounts, the model volume, secrets, and a host/domain. GitHub Pages alone cannot run the authenticated Python API.

## 4. Acceptance test before research use

1. Build both images and start the API under its final HTTPS origin. Confirm signed-out history and assets return 401; foreign-origin mutations return 403.
2. Submit a short, non-sensitive MP4 by upload. Confirm it appears in the dedicated Drive job folder before submission. Repeat using an existing Drive video; verify that original stays in place.
3. Confirm one RunPod job per submission, CUDA logs, correct model checksum, stage progress, and cancellation confirmation.
4. Confirm all frames are processed, source/tracked video durations match, and CSV track IDs match gallery crops and video labels. This initial worker does not retain audio.
5. Confirm `manifest.json` lists durable assets and checksums. Open video seeking, search the gallery, and download CSVs through the authenticated API.
6. Test one known species bundle and one missing/ambiguous model case. Confirm multi-view scoring and explicit unidentified results. Review species suggestions against manual labels.
7. Restart the API and confirm history persists; simulate a provider timeout and confirm the UI offers no automatic resubmission.
8. Inspect the built image, Git history and browser network requests for credentials. Browser requests must contain only the signed session cookie and temporary upload capability.

The automated tests cover mocked cloud lifecycle and real species aggregation; they do not certify live GPU throughput or model accuracy.

## Recovery and maintenance

Use `python -m server.recover scan` to rebuild missing SQLite history from Drive job records (server environment required). This does not dispatch jobs. Use `python -m server.recover reconcile JOB_UUID PROVIDER_JOB_ID` after checking RunPod's private console to attach an ambiguous submission to its existing provider job. Use `python -m server.recover manifest JOB_UUID MANIFEST_FILE_ID` to restore completed results after RunPod status retention expires. Recovery does not automatically start or retry work. Run these with the API stopped to avoid races.

Delete incomplete/failed job folders manually according to the team's retention policy; remove corresponding database rows only after backup. Drive history is shared across everyone with the workspace password. Rotate the workspace password and session secret to revoke existing sessions; rotating just the password does not invalidate signed cookies.

## Fish Gallery HTML and similar types

The results include a **Fish Gallery (HTML)** download (`fish_ID_gallery.html`). Open the downloaded file in a browser and select **Visual similarity** under Sort order to group similar-looking tracks, or return to **Chronological**. This preserves the desktop gallery workflow, including embedded crops and species review controls. Mount the local DINOv2 processor/config/weights bundle and set `OPENFISHID_SIMILARITY_MODEL` on the GPU worker. No model is downloaded at runtime. If that model is unavailable, the HTML explains why grouping is disabled. Appearance groups do not establish species or individual identity. Existing completed jobs need a gallery rebuild or reprocessing to gain this additional artifact.

The openfishGPU web gallery also offers **View tracks → Group similar types**. Search filters tracks within their appearance groups; tracks lacking embeddings stay in an ungrouped section. Existing v0.1.1 jobs load their saved `similarity.json` without reprocessing. Jobs without saved groups still need rebuilding or reprocessing. New worker/API deployments must both use version 0.1.2.
