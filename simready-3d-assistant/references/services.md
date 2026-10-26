# Services and command reference

Verified against public endpoints on 2026-10-26. Service behavior can change; old success is not an availability guarantee.

## Sources

- Central UI: https://huggingface.co/spaces/nvidia/simready-central
- Public service: https://nvidia-simready-central.hf.space
- OpenAPI: https://nvidia-simready-central.hf.space/openapi.json
- NVIDIA availability-only fallback (when Central cannot be reached): https://huggingface.co/datasets/nvidia/simready-assets
- Scenario supplementary collection: https://huggingface.co/datasets/scenario-labs/3d-collection (see [scenario.md](scenario.md))
- Publishing, licenses and use: https://docs.omniverse.nvidia.com/simready/latest/simready-central.html
- Registered packages: https://github.com/NVIDIA-Omniverse/simready-central/tree/main/submissions
- ZIP implementation: https://huggingface.co/spaces/nvidia/simready-central/blob/main/pipeline/package_download/app.py

No account, cookie or API key is added by the scripts. A future 401/403 is a service failure; do not copy frontend credentials to bypass it.

## Current routes

`POST /search_hybrid` maps to recommended v3 hybrid search. The script combines `hybrid_text_query` with a SigLIP2 text vector query and includes `file_extension_include=usd*`. Asset URLs come from each hit's source, not fabricated filenames.

`GET /images?asset_url=<encoded-source-url>&img_offset=0` provides a preview. When that fails, the script can use an original preview in the owner's package BOM. `return_images=true` does not guarantee inline image bytes.

`GET /download/asset?asset_url=<encoded-source-url>&scope=package` provides a Central ZIP. Treat it as a remote service link, not a verified local download. The local downloader obtains all files under the owner's package folder at a fixed Hugging Face commit.

Root USD files may only reference larger payloads and textures. `source.size` is not package size. The script estimates size from a paginated recursive listing and checks hashes supplied by the package BOM. It does not verify the aggregate `package_hash` algorithm or certify assets.

## CLI

Every subcommand accepts `--cache-dir`, `--timeout` and `--retries`. Search, inspect and download support `--offline`. Only Python's standard library is needed.

```text
python scripts/simready.py search --query "robot gripper" --limit 5 --out ./candidates
python scripts/simready.py search --query "cart" --source nvidia --out ./fallback
python scripts/simready.py search --query "cart" --offline --out ./offline-results
python scripts/simready.py search --query "robot arm" --license-policy any --out ./research
python scripts/simready.py search --source scenario --query "cart" --scenario-keyword trolley --scenario-keyword handcart --style low-poly --out ./supplement
python scripts/simready.py search --source scenario --query "chair" --scenario-exclude room --out ./standalone-props
python scripts/simready.py inspect --asset-url "<returned-source-url>" --out ./plan.json
python scripts/simready.py download --asset-url "<source-url>" --out ./downloads --zip --max-mb 512
python scripts/simready.py handoff --manifest ./downloads/PACKAGE/download-manifest.json --idea "Make it a repair robot" --target Blender --out ./handoff.md
```

Replace example paths with returned values. JSON summaries go to stdout; progress/errors go to stderr. Summary paths are absolute; paths inside a download manifest are relative so an extracted ZIP remains usable on another machine. A nonzero exit means the operation did not finish.

## Output contract

Search writes `results.json`, `gallery.html`, `candidates.md` and available images in `previews/`. Results include pinned dataset/revision, source/package URLs, declared license and license-file URL, entrypoints, estimated bytes, image state and warnings. `retrieval_mode` identifies caches or fallback name search. Unknown/restricted licenses are never silently presented as unrestricted.

Automatic routing distinguishes catalogue misses from service outages:

- Central responds normally: use its candidates; if suitable candidates are missing or below `--limit`, supplement directly from Scenario. Zero matches, license exclusions or unusable asset metadata do not trigger NVIDIA repository search.
- Central is unreachable: reuse cached Central candidates, then consult NVIDIA's repository only if more candidates are needed. Scenario can fill remaining gaps.
- Explicit `--source nvidia` is a manual/diagnostic override. Offline mode can use cached Central/NVIDIA metadata without attempting network access.

Lower-priority additions do not replace or outrank primary results. `central_status` records live availability versus outage/offline cache use. If an optional source fails, valid primary results are retained. Scenario results include `source_family=scenario`, `is_simready=false`, per-format `direct_downloads`, matched keywords, style/context clues and metadata coverage counts.

Inspect writes a download plan. Download writes the source folder plus a manifest/attribution draft and optional ZIP. A complete manifest records file checks and textual USD references needing review. Failed downloads write an incomplete manifest and exit nonzero; partial files can be reused on retry.

Handoff requires a complete manifest and writes a modeling brief with the idea, local files, sources, license, checks and unverified items. It does not operate a 3D application itself.
