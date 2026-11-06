# Third-party notices and provenance

`pipeline/` is adapted from the user's marine-ecologist/openfish repository, commit 4227d09972254459554961507cd05cffe20f37d7, version 0.7.3. The inspected checkout did not contain a top-level LICENSE; no broader license grant is asserted here. These modules are included to fulfill the repository owner's request. Confirm rights and select a repository license before third-party redistribution.

Changes include environment-based detector paths, CUDA tracking defaults, explicit FP16 CUDA / FP32 CPU inference selection, and GPU device selection for species inference. No model binaries are distributed. The original desktop application and its output directories remain untouched.

The available OpenReefGPU 0.6.5-gpu.5 cloud sources were used as an architecture reference. The new shared Python Drive adapter and API are original implementation; OpenReef's environment files, tokens, account IDs and model assets were not copied. OpenReef's MIT notice is preserved in `docs/OPENREEF-LICENSE.txt` as acknowledgment.

Ultralytics, CFD model weights, Fishial, PyTorch, Hugging Face models, BoT-SORT and other dependencies have their own license terms. In particular, review Ultralytics AGPL/commercial licensing and the detector/classifier model license before public or commercial hosting. Installing a dependency does not grant rights to distribute model weights.
