# Cost planning

No cloud resources are provisioned or billable jobs submitted by local tests.

RunPod charges depend on selected GPU, worker mode and actual billed worker time. Use the rate displayed in your RunPod console; this document does not claim a current price. Scale-to-zero minimizes idle workers, while image/model loading, source download, encoding and uploading may still consume billed runtime. A network volume adds storage charges, and keeping minimum workers above zero adds idle charges.

Estimate a job with:

`estimated GPU charge = billed seconds × selected GPU price per second`

For illustration only, a hypothetical rate of $0.0003/second and a 20-minute billed job would cost $0.36. This is arithmetic, not a RunPod quote or performance promise. A video's runtime can exceed its playback duration; benchmark the actual detector, batch size, resolution and GPU. High-resolution inference, many tracks, video encoding, cold starts and Drive transfer latency all affect cost.

Additional costs include the API container host, persistent API disk/backups, Google Drive account storage, a RunPod model volume, registry storage and any provider transfer charges. Drive retains source uploads, annotated video, sampled crops and exports. Do not assume storage/API usage is unlimited. Monitor actual usage in each provider dashboard.

Start with one maximum GPU worker, zero minimum workers, a short test video, a conservative file limit and an execution timeout. The default two-hour timeout limits an individual attempt, not total monthly spend. TTL covers queue plus run duration; it is not a billing budget. Set provider-level budgets/alerts, manually clean abandoned uploads and failed attempts, and avoid starting replacements until ambiguous submissions are reconciled.

References: [RunPod serverless pricing](https://www.runpod.io/serverless-gpu) and [Google Drive API limits](https://developers.google.com/workspace/drive/api/guides/limits). Verify current rates and quotas in your account before deployment.
