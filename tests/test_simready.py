"""Behavioral checks for anonymous discovery, package integrity and failure states."""
import argparse
import hashlib
import importlib.util
import io
import http.client
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib import error
import zipfile

SCRIPT = Path(__file__).resolve().parents[1] / "simready-3d-assistant" / "scripts" / "simready.py"
spec = importlib.util.spec_from_file_location("simready", SCRIPT)
s = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = s
spec.loader.exec_module(s)
REV = "a" * 40
ROOT = "cart_mobile_a01"


def encoded(value):
    return json.dumps(value).encode()


class Response(io.BytesIO):
    def __init__(self, data, headers=None):
        super().__init__(data)
        self.headers = headers or {}


class Fixture:
    def __init__(self, license_id="CC-BY-4.0", license_file=True):
        self.asset = s.Asset(s.NVIDIA, REV, ROOT + "/simready_usd/root.usda")
        self.payloads = {
            "simready_usd/root.usda": b'#usda 1.0\n( subLayers = [@payloads/body.usda@] )\n',
            "simready_usd/payloads/body.usda": b'#usda 1.0\ndef Xform "Body" {}\n',
            s.ROOTS: encoded({"entries": ["simready_usd/root.usda"]}),
        }
        if license_file:
            self.payloads[s.LICENSE] = b"Test license text: CC-BY-4.0; Creator Example."
        items = [{"relative_path": name, "size": len(data), "hash": {"sha256": hashlib.sha256(data).hexdigest()}}
                 for name, data in self.payloads.items()]
        self.payloads[s.BOM] = encoded({"format_version": "1.0", "items": items})
        self.payloads[s.DESCRIPTOR] = encoded({"license": license_id, "package_id": "fixture.package",
            "metadata": [{"name": s.PurePosixPath(s.BOM).name, "hash": {"sha256": hashlib.sha256(self.payloads[s.BOM]).hexdigest()}}]})
        self.rows = [{"type": "file", "path": ROOT + "/" + name, "size": len(data)} for name, data in self.payloads.items()]
        self.request_headers = []
        self.central_fails = False
        self.corrupt_file = None
        self.calls = []

    def open(self, req, timeout=None):
        url = req.full_url
        self.calls.append(url)
        self.request_headers.append(dict(req.header_items()))
        if url == s.CENTRAL + "/search_hybrid":
            if self.central_fails:
                raise error.URLError("fixture unavailable")
            body = json.loads(req.data)
            assert body["vector_queries"][0]["query"] == body["hybrid_text_query"]
            return Response(encoded({"hits": [{"source": {"base_key": self.asset.url(kind="blob")}}], "total": 1, "corpus_total": 99}))
        if url == s.HF + "/api/datasets/" + s.NVIDIA:
            return Response(encoded({"sha": REV}))
        if "/tree/" + REV + "/" + ROOT + "?" in url:
            return Response(encoded(self.rows))
        if "/tree/" + REV + "?" in url:
            if "cursor=" not in url:
                return Response(encoded([{"type": "directory", "path": "other_object"}]),
                    {"Link": f'<{s.HF}/api/datasets/{s.NVIDIA}/tree/{REV}?recursive=false&limit=1000&cursor=next>; rel="next"'})
            return Response(encoded([{"type": "directory", "path": ROOT}]))
        prefix = self.asset.url(ROOT + "/")
        if url.startswith(prefix):
            name = url[len(prefix):]
            if name in self.payloads:
                return Response(b"corrupted" if name == self.corrupt_file else self.payloads[name])
        raise error.HTTPError(url, 404, "fixture not found", {}, None)


class SimReadyTests(unittest.TestCase):
    def setUp(self):
        self.test_root = SCRIPT.parents[2] / ".test-tmp"
        self.test_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=self.test_root)
        self.work = Path(self.temp.name)
        self.http = s.HTTP(self.work / "cache", timeout=0.1, retries=0)
        self.fixture = Fixture()
        self.opener = patch.object(s.request, "urlopen", self.fixture.open)
        self.opener.start()

    def tearDown(self):
        self.opener.stop()
        self.assertTrue(Path(self.temp.name).resolve().is_relative_to(self.test_root.resolve()))
        self.temp.cleanup()

    def plan(self):
        return s.inspect_asset(self.http, self.fixture.asset.url(kind="blob"))

    def test_central_search_is_anonymous_and_pins_package(self):
        urls, mode, counts = s.central_search(self.http, "mobile cart", 3)
        plan = s.inspect_asset(self.http, urls[0])
        self.assertEqual(mode, "central_live")
        self.assertEqual(counts["corpus_total"], 99)
        self.assertEqual(plan["revision"], REV)
        self.assertTrue(plan["bom_hash_verified"])
        self.assertEqual(plan["license_status"], "permissive_declared")
        self.assertTrue(all(not {k.lower() for k in h} & {"authorization", "cookie", "x-api-key"} for h in self.fixture.request_headers))

    def test_network_failure_uses_cached_central_response(self):
        s.central_search(self.http, "mobile cart", 3)
        self.fixture.central_fails = True
        _, mode, _ = s.central_search(self.http, "mobile cart", 3)
        self.assertEqual(mode, "central_cache_after_failure")
        self.assertTrue(self.http.warnings)

    def test_offline_reads_cached_metadata_without_network(self):
        s.central_search(self.http, "mobile cart", 3)
        self.plan()
        count = len(self.fixture.calls)
        self.http.offline = True
        urls, mode, _ = s.central_search(self.http, "mobile cart", 3)
        self.assertEqual(mode, "central_cache")
        self.assertEqual(s.inspect_asset(self.http, urls[0])["license"], "CC-BY-4.0")
        self.assertEqual(len(self.fixture.calls), count)

    def test_fallback_reads_all_pages_and_matches_names(self):
        urls, mode, counts = s.nvidia_search(self.http, "mobile cart", 1)
        self.assertEqual(mode, "nvidia_name_search")
        self.assertEqual(counts["folder_count"], 2)
        self.assertEqual(len(urls), 1)
        self.assertIn(ROOT, urls[0])

    def test_auto_falls_back_when_central_is_unavailable(self):
        self.fixture.central_fails = True
        args = argparse.Namespace(source="auto", query="mobile cart", limit=1, license_policy="permissive", intent="repair cart", out=self.work / "gallery", offline=False)
        with patch.object(s, "preview", lambda *a, **kw: None):
            summary = s.search_command(args, self.http)
        self.assertEqual(summary["results"], 1)
        self.assertEqual(summary["retrieval_mode"], "nvidia_name_search")

    def test_sufficient_primary_results_never_consult_scenario(self):
        args = argparse.Namespace(source="auto", query="mobile cart", limit=1, license_policy="permissive", intent="repair cart", out=self.work / "primary", offline=False)
        with patch.object(s, "scenario_module") as secondary, patch.object(s, "preview", lambda *a, **kw: None):
            result = s.search_command(args, self.http)
        secondary.assert_not_called()
        self.assertEqual(result["results"], 1)

    def test_scenario_only_fills_missing_slots_and_cannot_outrank_primary(self):
        secondary = dict(self.plan())
        secondary.pop("files")
        secondary.update(dataset=s.SCENARIO, source_family="scenario", is_simready=False, package_root="assets/secondary", name="secondary")
        mock_search = unittest.mock.Mock(return_value=([secondary], [], {"keyword_matches": 1}))
        args = argparse.Namespace(source="auto", query="mobile cart", limit=2, license_policy="permissive", intent="repair cart", out=self.work / "mixed", offline=False)
        with patch.object(s, "nvidia_search") as nvidia, patch.object(s, "scenario_module", return_value=SimpleNamespace(search=mock_search)), patch.object(s, "preview", lambda *a, **kw: None):
            summary = s.search_command(args, self.http)
        nvidia.assert_not_called()
        self.assertEqual(mock_search.call_args.args[2], 1)
        report = json.loads(Path(summary["report"]).read_text(encoding="utf-8"))
        self.assertEqual([r["dataset"] for r in report["results"]], [s.NVIDIA, s.SCENARIO])

    def test_successful_zero_match_central_goes_directly_to_scenario(self):
        args = argparse.Namespace(source="auto", query="unknown prop", limit=2, license_policy="permissive", intent="", out=self.work / "zero-matches", offline=False)
        secondary_search = unittest.mock.Mock(return_value=([], [], {"keyword_matches": 0}))
        with patch.object(s, "central_search", return_value=([], "central_live", {"total": 0})), patch.object(s, "nvidia_search") as nvidia, patch.object(s, "scenario_module", return_value=SimpleNamespace(search=secondary_search)):
            summary = s.search_command(args, self.http)
        nvidia.assert_not_called()
        secondary_search.assert_called_once()
        report = json.loads(Path(summary["report"]).read_text(encoding="utf-8"))
        self.assertEqual(report["central_status"], "available")

    def test_primary_license_exclusions_do_not_trigger_nvidia(self):
        args = argparse.Namespace(source="auto", query="cart", limit=1, license_policy="permissive", intent="", out=self.work / "excluded-primary", offline=False)
        secondary_search = unittest.mock.Mock(return_value=([], [], {}))
        with patch.object(s, "hydrate", return_value=([], [{"reason": "license_policy"}])), patch.object(s, "nvidia_search") as nvidia, patch.object(s, "scenario_module", return_value=SimpleNamespace(search=secondary_search)):
            s.search_command(args, self.http)
        nvidia.assert_not_called()
        secondary_search.assert_called_once()

    def test_outage_with_partial_cached_central_can_use_nvidia_backup(self):
        s.central_search(self.http, "mobile cart", 2)
        self.fixture.central_fails = True
        args = argparse.Namespace(source="auto", query="mobile cart", limit=2, license_policy="permissive", intent="", out=self.work / "cached-outage", offline=False)
        secondary = SimpleNamespace(search=unittest.mock.Mock(return_value=([], [], {})))
        with patch.object(s, "nvidia_search", return_value=([], "nvidia_name_search", {})) as nvidia, patch.object(s, "scenario_module", return_value=secondary), patch.object(s, "preview", lambda *a, **kw: None):
            summary = s.search_command(args, self.http)
        nvidia.assert_called_once()
        report = json.loads(Path(summary["report"]).read_text(encoding="utf-8"))
        self.assertEqual(report["central_status"], "unavailable_using_cache")
        self.assertEqual(summary["results"], 1)

    def test_optional_source_failure_preserves_valid_primary_results(self):
        args = argparse.Namespace(source="auto", query="mobile cart", limit=2, license_policy="permissive", intent="repair cart", out=self.work / "partial", offline=False)
        module = SimpleNamespace(search=unittest.mock.Mock(side_effect=s.NetworkError("optional source offline")))
        with patch.object(s, "nvidia_search", side_effect=s.NetworkError("fallback offline")), patch.object(s, "scenario_module", return_value=module), patch.object(s, "preview", lambda *a, **kw: None):
            summary = s.search_command(args, self.http)
        self.assertEqual(summary["results"], 1)
        self.assertTrue(any("Scenario" in warning for warning in summary["warnings"]))

    def test_unknown_or_noncommercial_license_is_not_silently_allowed(self):
        self.fixture = Fixture("CC-BY-NC-4.0")
        self.opener.stop()
        self.opener = patch.object(s.request, "urlopen", self.fixture.open)
        self.opener.start()
        results, excluded = s.hydrate(self.http, [self.fixture.asset.url(kind="blob")], 1, "permissive")
        self.assertEqual(results, [])
        self.assertEqual(excluded[0]["license"], "CC-BY-NC-4.0")
        results, _ = s.hydrate(self.http, [self.fixture.asset.url(kind="blob")], 1, "any")
        self.assertEqual(results[0]["license_status"], "needs_review")

    def test_missing_license_text_requires_review(self):
        self.fixture = Fixture(license_file=False)
        self.opener.stop()
        self.opener = patch.object(s.request, "urlopen", self.fixture.open)
        self.opener.start()
        self.assertEqual(self.plan()["license_status"], "needs_review")

    def test_lowercase_permissive_license_is_recognized(self):
        self.fixture = Fixture("cc-by-4.0")
        self.opener.stop()
        self.opener = patch.object(s.request, "urlopen", self.fixture.open)
        self.opener.start()
        plan = self.plan()
        self.assertEqual(plan["license"], "CC-BY-4.0")
        self.assertEqual(plan["license_status"], "permissive_declared")

    def test_complete_download_keeps_dependencies_license_and_zip(self):
        plan = self.plan()
        result = s.download_package(self.http, plan, self.work / "downloads", 1024 * 1024, True)
        self.assertTrue(result["complete"])
        source = Path(result["source_directory"])
        self.assertEqual((source / "simready_usd/payloads/body.usda").read_bytes(), self.fixture.payloads["simready_usd/payloads/body.usda"])
        self.assertTrue((source / s.LICENSE).is_file())
        self.assertGreater(result["sha256_verified_files"], 0)
        with zipfile.ZipFile(result["zip"]) as bundle:
            self.assertTrue(any(n.endswith("source/" + s.LICENSE) for n in bundle.namelist()))
        again = s.download_package(self.http, plan, self.work / "downloads", 1024 * 1024)
        manifest = json.loads(Path(again["manifest"]).read_text())
        self.assertTrue(all(f["state"] == "reused" for f in manifest["files"]))

    def test_corrupt_payload_does_not_become_a_successful_package(self):
        plan = self.plan()
        self.fixture.corrupt_file = "simready_usd/payloads/body.usda"
        with self.assertRaises(s.SkillError):
            s.download_package(self.http, plan, self.work / "broken", 1024 * 1024, True)
        manifests = list((self.work / "broken").rglob("download-manifest.json"))
        self.assertEqual(len(manifests), 1)
        manifest = json.loads(manifests[0].read_text())
        self.assertFalse(manifest["complete"])
        self.assertFalse(list((self.work / "broken").glob("*.zip")))
        self.assertFalse((manifests[0].parent / manifest["source_directory"] / self.fixture.corrupt_file).exists())

    def test_existing_user_changes_are_preserved_and_handoff_detects_them(self):
        plan = self.plan()
        result = s.download_package(self.http, plan, self.work / "downloads", 1024 * 1024)
        altered = Path(result["source_directory"]) / "simready_usd/payloads/body.usda"
        altered.write_text("user changes")
        with self.assertRaises(s.SkillError):
            s.download_package(self.http, plan, self.work / "downloads", 1024 * 1024)
        self.assertEqual(altered.read_text(), "user changes")

    def test_handoff_rechecks_files_and_does_not_claim_execution(self):
        result = s.download_package(self.http, self.plan(), self.work / "downloads", 1024 * 1024)
        args = argparse.Namespace(manifest=result["manifest"], idea="A repair cart", target="Blender", out=self.work / "handoff.md")
        summary = s.handoff_command(args)
        self.assertFalse(summary["editing_executed"])
        altered = Path(result["source_directory"]) / "simready_usd/payloads/body.usda"
        altered.write_text("changed")
        with self.assertRaises(s.SkillError):
            s.handoff_command(args)

    def test_archive_does_not_include_unrelated_files_added_locally(self):
        plan = self.plan()
        result = s.download_package(self.http, plan, self.work / "downloads", 1024 * 1024)
        extra = Path(result["source_directory"]) / "local-notes.txt"
        extra.write_text("Not part of the upstream package")
        result = s.download_package(self.http, plan, self.work / "downloads", 1024 * 1024, True)
        with zipfile.ZipFile(result["zip"]) as bundle:
            self.assertFalse(any(n.endswith("local-notes.txt") for n in bundle.namelist()))

    def test_incomplete_http_response_is_reported_as_network_failure(self):
        with patch.object(s.request, "urlopen", side_effect=http.client.IncompleteRead(b"partial", 10)):
            with self.assertRaises(s.NetworkError):
                s.central_search(self.http, "mobile cart", 1)

    def test_untrusted_paths_and_urls_are_rejected(self):
        for value in ("../outside", "/absolute", "C:/temp", "safe/../../out", "a\\b", "a/NUL.txt", "a:stream", "a/thing."):
            with self.subTest(value=value), self.assertRaises(s.SkillError):
                s.safe_rel(value)
        with self.assertRaises(s.SkillError):
            s.asset_from_url("https://evil.example/datasets/x/y/blob/main/model.usd", self.http)

    def test_size_budget_is_checked_before_payload_download(self):
        plan = self.plan()
        count = len(self.fixture.calls)
        with self.assertRaises(s.SkillError):
            s.download_package(self.http, plan, self.work / "budget", 1)
        self.assertEqual(len(self.fixture.calls), count)

    def test_gallery_escapes_untrusted_text(self):
        item = self.plan()
        item["name"] = '<script>alert("x")</script>'
        item["preview_path"] = None
        report = {"query": "cart", "intent": '<img src=x onerror="bad">', "results": [item], "warnings": []}
        s.render_results(report, self.work / "escaped")
        page = (self.work / "escaped/gallery.html").read_text(encoding="utf-8")
        self.assertNotIn('<script>alert', page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("Content-Security-Policy", page)


class ScenarioTests(unittest.TestCase):
    def setUp(self):
        self.module = s.scenario_module()

    def test_keywords_match_synonyms_and_plurals_without_prefix_false_positives(self):
        rows = [{"id": "a", "prompt": "Two wooden trolleys."}, {"id": "b", "prompt": "A cartoon cat."}]
        matches = self.module.rank_rows(rows, "cart")
        self.assertEqual([r["row"]["id"] for r in matches], ["a"])

    def test_explicit_compound_keywords_do_not_broaden_to_unrelated_objects(self):
        rows = [{"id": "a", "prompt": "A robot cat."}, {"id": "b", "prompt": "A cat."}, {"id": "c", "prompt": "A robot."}]
        matches = self.module.rank_rows(rows, "robot cat", ["robotic cat"])
        self.assertEqual([r["row"]["id"] for r in matches], ["a"])
        robot_terms = self.module.keyword_plan("robot")
        self.assertNotIn(("gripper",), robot_terms)

    def test_missing_prompt_does_not_guess_meaning_from_model_or_file_ids(self):
        row = {"id": "robot", "model": "robot-generator", "outputs": [{"path": "robot.glb"}], "prompt": None}
        self.assertEqual(self.module.rank_rows([row], "robot"), [])

    def test_style_matching_is_separate_and_standalone_objects_rank_above_scene_mentions(self):
        rows = [{"id": "a", "prompt": "A futuristic room with an old chair."}, {"id": "b", "prompt": "A low-poly chair."}]
        matches = self.module.rank_rows(rows, "chair", style="low poly")
        self.assertEqual(matches[0]["row"]["id"], "b")
        self.assertEqual(matches[0]["style_match"], "text_match")
        self.assertEqual(matches[1]["text_match_context"], "scene_context")

    def test_exclusions_use_word_boundaries_and_do_not_remove_other_candidates(self):
        rows = [{"id": "a", "prompt": "A chair in a room."}, {"id": "b", "prompt": "A chair with roomier seating."}]
        matches = self.module.rank_rows(rows, "chair", exclude=["room"])
        self.assertEqual([r["row"]["id"] for r in matches], ["b"])

    def test_viewer_revision_mismatch_is_rejected(self):
        root = SCRIPT.parents[2] / ".test-tmp"
        with tempfile.TemporaryDirectory(dir=root) as folder:
            http = s.HTTP(folder, retries=0)
            with patch.object(s.request, "urlopen", return_value=Response(encoded({"rows": []}), {"x-revision": "b" * 40})):
                with self.assertRaises(s.SkillError):
                    http.json_page("https://datasets-server.huggingface.co/rows", expected_revision=REV)

    def test_scenario_plan_preserves_formats_hashes_and_required_attribution(self):
        row = {"id": "example", "prompt": "A wooden cart.", "license": "cc-by-4.0", "inputs": {"assets": []},
               "outputs": [{"path": "assets/example/output.glb", "format": "glb", "sha256": "1" * 64}],
               "preview_file": {"path": "assets/example/preview.jpg", "sha256": "2" * 64}}
        listing = [{"type": "file", "path": p, "size": 10} for p in ["LICENSE", "README.md", "assets/example/output.glb", "assets/example/preview.jpg"]]
        plan = self.module.inspect_row(None, row, REV, s, listing)
        self.assertFalse(plan["is_simready"])
        self.assertEqual(plan["required_attribution"], "Scenario")
        self.assertIsNone(plan["package_download_url"])
        self.assertEqual(plan["direct_downloads"][0]["format"], "glb")
        self.assertTrue(all(REV in item["url"] for item in plan["files"]))


if __name__ == "__main__":
    unittest.main()
