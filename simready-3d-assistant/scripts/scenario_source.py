"""Lower-priority lexical discovery for Scenario's public 3D collection.

Receives the parent script's API module to share its HTTP/cache/download machinery.
No optional packages, model execution, semantic embeddings or authenticated sources.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import re
from urllib import parse

REPO = "scenario-labs/3d-collection"
VIEWER = "https://datasets-server.huggingface.co/rows"
ALIASES = {
    "cart": ("cart", "trolley", "handcart", "pushcart"),
    "chair": ("chair", "armchair", "stool"),
    "sofa": ("sofa", "couch", "settee"),
    "car": ("car", "automobile", "sedan"),
    "truck": ("truck", "lorry", "pickup"),
    "airplane": ("airplane", "aeroplane", "aircraft"),
    "robot": ("robot", "android", "robotic"),
    "gripper": ("gripper", "robot hand", "robotic hand"),
    "cabinet": ("cabinet", "cupboard", "locker"),
    "shelf": ("shelf", "shelves", "shelving", "bookcase"),
    "cat": ("cat", "kitten", "feline"),
    "dog": ("dog", "puppy", "canine"),
    "tree": ("tree", "oak", "pine", "palm tree"),
    "sword": ("sword", "blade", "saber", "sabre"),
}
def tokens(text):
    text = re.sub(r"\bsci[\s-]*fi\b", "scifi", (text or "").lower())
    text = re.sub(r"\blow[\s-]*poly\b", "lowpoly", text)
    words = re.findall(r"[a-z0-9]+", text)
    normalized = []
    for word in words:
        if len(word) > 4 and word.endswith("ies"):
            word = word[:-3] + "y"
        elif len(word) > 4 and word.endswith(("ches", "shes", "xes", "zes", "sses")):
            word = word[:-2]
        elif len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
            word = word[:-1]
        normalized.append(word)
    return normalized


def text_of(row):
    # Hashed filenames, generator names and input asset IDs contain no reliable
    # object meaning. Do not let those manufacture apparent keyword matches.
    values = [row.get("prompt"), (row.get("inputs") or {}).get("prompt")]
    return " ".join(dict.fromkeys(v for v in values if isinstance(v, str) and v.strip()))


def keyword_plan(query, extra=()):
    terms = [query, *extra]
    query_tokens = tokens(query)
    if not extra:
        matched = []
        for aliases in ALIASES.values():
            lengths = [len(tokens(phrase)) for phrase in aliases if contains_phrase(query_tokens, tokens(phrase))]
            if lengths:
                matched.append((max(lengths), aliases))
        if matched:
            longest = max(length for length, _ in matched)
            best = [aliases for length, aliases in matched if length == longest]
            # Preserve a multi-object compound rather than broadening it to
            # unrelated objects. Explicit phrases let the agent control recall.
            if len(best) == 1:
                terms.extend(best[0])
    groups = list(dict.fromkeys(tuple(tokens(t)) for t in terms if tokens(t)))
    # When an explicit synonym exists, the simple subject can match without all
    # material/style modifiers. Otherwise preserve the supplied compound phrase.
    return groups


def contains_phrase(haystack, needle):
    return any(tuple(haystack[i:i + len(needle)]) == tuple(needle) for i in range(len(haystack) - len(needle) + 1))


def rank_rows(rows, query, extra=(), style="", exclude=()):
    groups, desired_style = keyword_plan(query, extra), tokens(style)
    ranked = []
    for row in rows:
        text = text_of(row)
        words = tokens(text)
        if any(contains_phrase(words, tokens(term)) for term in exclude if tokens(term)):
            continue
        matched = [" ".join(group) for group in groups if contains_phrase(words, group)]
        if not matched:
            continue
        exact = contains_phrase(words, tokens(query))
        style_match = contains_phrase(words, desired_style) if desired_style else None
        score = (20 if exact else 0) + 6 * len(matched) + len(set(words) & set(tokens(query)))
        positions = [i for group in groups for i in range(len(words)) if tuple(words[i:i + len(group)]) == group]
        first_position = min(positions)
        score += max(0, 14 - first_position)
        scene_words = {"room", "scene", "interior", "environment", "village", "diorama"}
        scene_context = bool(set(words[:10]) & scene_words - set(tokens(query)))
        context = "scene_context" if scene_context else "near_subject" if first_position < 12 else "mentioned_later"
        if scene_context:
            score -= 8
        if words and words[0] == "change" and "preserve" in words:
            score -= 6
        if style_match:
            score += 10
        # Do not turn a high lexical score into a claim of visual/style fit.
        ranked.append({"row": row, "score": score, "matched_keywords": matched, "text_match_context": context,
                       "style_match": "text_match" if style_match else "not_found_in_text" if desired_style else "not_requested"})
    return sorted(ranked, key=lambda r: (-r["score"], r["row"].get("id", "")))


def load_index(http, api, revision=None):
    if revision is None:
        revision = http.json(api.HF + "/api/datasets/" + REPO).get("sha", "")
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise api.SkillError("Scenario did not return a valid immutable revision")
    index_path = http.cache_dir / "scenario-index" / (revision + ".json")
    if index_path.exists():
        index = json.loads(index_path.read_text(encoding="utf-8"))
        if index.get("revision") == revision and index.get("complete") is True:
            return index
    def page(offset):
        url = VIEWER + "?" + parse.urlencode({"dataset": REPO, "config": "default", "split": "train", "offset": offset, "length": 100, "revision": revision})
        data = http.json_page(url, expected_revision=revision)[0]
        if data.get("partial") or not isinstance(data.get("rows"), list):
            raise api.SkillError("Scenario viewer returned partial or malformed metadata")
        return data
    first = page(0)
    total = first.get("num_rows_total")
    if not isinstance(total, int) or total < 0 or total > 100000:
        raise api.SkillError("Scenario metadata row count is invalid")
    step = len(first["rows"])
    if total and not step:
        raise api.SkillError("Scenario metadata has no first page")
    pages = [first]
    with ThreadPoolExecutor(max_workers=3) as executor:
        pages.extend(executor.map(page, range(step, total, step or 100)))
    indexed = {}
    for data in pages:
        if data.get("num_rows_total") != total:
            raise api.SkillError("Scenario row count changed during indexing")
        for item in data["rows"]:
            if item.get("truncated_cells"):
                raise api.SkillError("Scenario metadata contains truncated cells; keyword coverage is incomplete")
            position = item["row_idx"]
            if position in indexed:
                raise api.SkillError("Duplicate Scenario metadata row")
            row = dict(item["row"])
            # Viewer thumbnail URLs are signed and temporary. Use preview_file
            # at the pinned repository revision instead, including its hash.
            for transient in ("preview", "input_files", "output_files"):
                row.pop(transient, None)
            indexed[position] = row
    if set(indexed) != set(range(total)):
        raise api.SkillError("Scenario metadata pagination is incomplete")
    rows = [indexed[i] for i in range(total)]
    index = {"revision": revision, "complete": True, "created_at": api.now(), "rows": rows,
             "row_count": total, "searchable_rows": sum(bool(text_of(row)) for row in rows)}
    api.write_json(index_path, index)
    return index


def inspect_row(http, row, revision, api, listing=None):
    outputs = row.get("outputs") or []
    if not outputs:
        raise api.SkillError("Scenario example has no output files")
    output_paths = [api.safe_rel(item["path"]) for item in outputs]
    folders = {path.rsplit("/", 1)[0] for path in output_paths}
    if len(folders) != 1 or not all(path.startswith("assets/") for path in output_paths):
        raise api.SkillError("Unsupported Scenario output layout")
    root = next(iter(folders))
    asset = api.Asset(REPO, revision, output_paths[0])
    listing = listing if listing is not None else api.tree(http, asset, recursive=True)
    records = {item["path"]: item for item in listing if item.get("type") == "file"}
    wanted = {name for name in records if name.startswith(root + "/")}
    originals = (row.get("inputs") or {}).get("assets") or []
    preview = row.get("preview_file") or {}
    hash_items = [*outputs, *originals, preview]
    for item in hash_items:
        if item.get("path"):
            wanted.add(api.safe_rel(item["path"]))
    wanted.update({"LICENSE", "README.md"})
    hashes = {}
    for item in hash_items:
        if item.get("path"):
            sha = item.get("sha256")
            if not re.fullmatch(r"[0-9a-f]{64}", sha or ""):
                raise api.SkillError("Scenario file metadata lacks a valid SHA-256")
            hashes[api.safe_rel(item["path"])] = sha
    files = []
    for path in sorted(wanted):
        api.safe_rel(path)
        if path not in records:
            raise api.SkillError("Scenario metadata refers to a missing pinned file: " + path)
        entry = records[path]
        upstream = (entry.get("lfs") or {}).get("oid")
        sha = hashes.get(path) or (upstream if re.fullmatch(r"[0-9a-f]{64}", upstream or "") else None)
        if path in hashes and upstream and hashes[path] != upstream:
            raise api.SkillError("Scenario metadata and repository file hashes disagree")
        files.append({"path": path, "size": entry.get("size"), "sha256": sha, "url": asset.url(path)})
    license_id = str(row.get("license") or "UNKNOWN").upper()
    title = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(row.get("id") or root.rsplit("/", 1)[-1]))[:80]
    direct = [{"format": str(item.get("format") or path.rsplit(".", 1)[-1]), "url": asset.url(path), "path": path}
              for item, path in zip(outputs, output_paths)]
    return {"name": title, "owner": "Scenario", "dataset": REPO, "revision": revision, "package_root": root,
            "package_id": row.get("id"), "source_family": "scenario", "is_simready": False, "ai_generated": True,
            "description": text_of(row), "required_attribution": "Scenario", "scenario_record": row,
            "source_url": asset.url(kind="blob"), "selected_source_url": asset.url(kind="blob"),
            "package_definition_url": None, "package_download_url": None, "direct_downloads": direct,
            "license": license_id, "license_file_url": asset.url("LICENSE"),
            "license_status": "permissive_declared" if license_id in api.PERMISSIVE else "needs_review",
            "entrypoints": output_paths, "file_count": len(files), "estimated_bytes": sum(item["size"] or 0 for item in files),
            "thumbnail_url": asset.url(preview["path"]) if preview.get("path") else None,
            "thumbnail_sha256": preview.get("sha256"), "central_thumbnail_url": None,
            "files": files, "bom_hash_verified": False, "style_review_required": True,
            "warnings": ["AI-generated Scenario example; style varies and needs visual review. No SimReady physics/profile validation is declared."]}


def inspect_source(http, asset, api):
    index = load_index(http, api, asset.revision)
    for row in index["rows"]:
        if asset.path in {item.get("path") for item in row.get("outputs") or []}:
            return inspect_row(http, row, asset.revision, api)
    raise api.SkillError("Selected Scenario model is not listed in the pinned metadata")


def search(http, query, limit, license_policy, keywords, style, api, exclude=()):
    index = load_index(http, api)
    ranked = rank_rows(index["rows"], query, keywords, style, exclude)
    listing = api.tree(http, api.Asset(REPO, index["revision"], "unused"), recursive=True) if ranked else []
    results, excluded = [], []
    for match in ranked[:max(limit * 3, 15)]:
        try:
            item = inspect_row(http, match["row"], index["revision"], api, listing)
            if license_policy == "permissive" and item["license_status"] != "permissive_declared":
                excluded.append({"id": item["package_id"], "reason": "license_policy", "license": item["license"]})
                continue
            item.pop("files")
            item.update(keyword_score=match["score"], matched_keywords=match["matched_keywords"], style_match=match["style_match"], text_match_context=match["text_match_context"])
            results.append(item)
            if len(results) >= limit:
                break
        except (api.SkillError, KeyError, TypeError, ValueError) as exc:
            excluded.append({"id": match["row"].get("id"), "reason": str(exc)})
    stats = {"row_count": index["row_count"], "searchable_rows": index["searchable_rows"],
             "unlabeled_rows": index["row_count"] - index["searchable_rows"], "keyword_matches": len(ranked),
             "expanded_keywords": [" ".join(group) for group in keyword_plan(query, keywords)], "revision": index["revision"]}
    stats["excluded_keywords"] = list(exclude)
    return results, excluded, stats
