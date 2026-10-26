# Scenario supplementary discovery

## Priority and fit

Source: https://huggingface.co/datasets/scenario-labs/3d-collection

Use this collection when Central has no suitable assets or does not provide enough similar candidates. If Central responds normally, `auto` supplements directly from Scenario without searching NVIDIA's overlapping repository. NVIDIA is an availability backup only when Central cannot be reached; Scenario can also fill remaining gaps in that outage path. If primary results are numerically sufficient but visually wrong, judge that from the images and request an explicit supplementary search. An explicit user request for Scenario also selects it directly.

Keep primary results before additions and mark each result's source family. Scenario styles vary and all assets are declared AI-generated. A relevant noun does not guarantee the desired silhouette, style, editable structure or simulation properties. Do not bulk-mix these examples into a consistent SimReady scene without checking and adapting them.

## Keyword strategy

1. Translate the core object into English; keep the full user idea in `--intent`.
2. Separate object names from style/material modifiers. Start with a concrete noun or meaningful compound phrase: `cart`, `dental chair`, `robot hand`.
3. Use `--scenario-keyword` for deliberate synonyms or alternate compounds, e.g. `trolley`, `handcart`; keep several specific queries when a compound has distinct meanings. Explicit variants take precedence over automatic broadening.
4. Use `--scenario-exclude` to remove misleading contexts, e.g. `room` when searching for a standalone prop. Exclusions are exact words/phrases, so do not overexclude useful examples.
5. Supply desired style separately with `--style`. Spelling/spacing variants of low-poly and sci-fi are normalized. A text match is still subject to visual verification.
6. Inspect the previews and explain what is reusable and what requires modification. If the style is unsuitable, return fewer candidates or try another precise phrase.

The local ranker uses original prompts, word boundaries, singular/plural normalization, a small synonym vocabulary, exact-phrase bonuses and subject-position/context weighting. It does not match `cart` inside `cartoon`, guess object meaning from hashes, or call an embedding service.

## Metadata and coverage

The upstream authoritative metadata is `data/train-00000-of-00001.parquet`. To keep the Skill dependency-free, it reads the Hugging Face dataset viewer's structured JSON rows in pages of 100, checks the `x-revision` header against a fixed repository commit, and checks complete/nonduplicated pagination before saving a lightweight local index. Mixed-version, partial or truncated metadata is rejected. Viewer signed preview URLs are discarded in favor of pinned `preview_file.path` URLs.

On 2026-10-26 the collection had 1,342 rows, of which 370 contained textual prompts. The other 972 cannot be found reliably through this keyword index. The script reports current `searchable_rows` and `unlabeled_rows`; it does not claim complete semantic coverage. The first Scenario query builds this index; later queries reuse it for the same commit.

Some prompts describe edits to existing objects or whole scenes. Rankings favor primary subject mentions and flag scene context, but final relevance remains an image-based judgment.

## Files, licenses and editing

The dataset card and LICENSE declare CC-BY-4.0 and require credit **Scenario**:

- https://huggingface.co/datasets/scenario-labs/3d-collection/blob/main/README.md
- https://huggingface.co/datasets/scenario-labs/3d-collection/blob/main/LICENSE

Examples offer varying combinations of GLB, Blender, FBX, PLY, SPZ or VOX. Search returns actual per-format URLs. These are original output-file links, not a dependency-complete ZIP. The local downloader additionally obtains the whole example folder, associated input files and license/README, retains the selected metadata in its manifest and verifies available SHA-256 values. It does not download the entire collection.

This source has no SimReady BOM or declared physics-profile validation. `.blend` files must be opened with automatic script execution disabled. Check packed and external textures and the chosen application's support for each format. Upstream structural checks do not establish visual, animation or physics quality.

The separately published Hunyuan companion has different licensing/access requirements and is outside this source integration.
