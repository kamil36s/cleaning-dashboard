"""B2 shared-infrastructure evidence, drift and unified routing regressions."""

import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from kermit_grounding import ground
from kermit_index.builder import CORE_NAMES
from kermit_index.coverage import coverage_check
from kermit_retrieval import retrieve
from kermit_service.app import KermitService
from kermit_service.config import ServiceConfig
from kermit_service.routing import GENERAL, PROJECT, route


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "kermit_index/admission.json"
INDEX = ROOT / "data/generated/kermit-index"


def ask(question):
    return retrieve({"contractVersion": 1, "question": question})


def draft(answer, evidence):
    return {"answer": answer, "citedEvidenceIds": [item["evidenceId"] for item in evidence], "uncertainty": []}


class B2RetrievalTests(unittest.TestCase):
    def test_questions_select_reviewed_boundary_packs(self):
        cases = (
            ("How are dashboard widgets loaded?", "dashboard", "dashboard.md"),
            ("How does Kermit know whether a widget is active?", "dashboard", "dashboard.md"),
            ("Where is widget order stored?", "dashboard", "dashboard.md"),
            ("What happens when a widget module fails to load?", "dashboard", "dashboard.md"),
            ("Which settings are server-backed?", "settings", "settings.md"),
            ("Which settings can exist only in localStorage?", "settings", "settings.md"),
            ("How does /api/settings work?", "settings", "settings.md"),
            ("Which process owns Live Workout?", "central-api", "central-api.md"),
            ("Which process owns Network Monitor?", "central-api", "central-api.md"),
            ("Which process owns Kermit?", "central-api", "central-api.md"),
            ("Does restarting server.py stop an active workout?", "central-api", "central-api.md"),
            ("Can Kermit mutate dashboard settings?", "dashboard", "dashboard.md"),
            ("How are private Finance paths protected?", "central-api", "central-api.md"),
        )
        for question, subsystem, filename in cases:
            with self.subTest(question=question):
                result = ask(question)
                self.assertTrue(any(item["subsystem"] == subsystem and item["layer"] == "L1"
                                    and item["path"].endswith(filename) for item in result["selectedEvidence"]))
                self.assertTrue(all(not item["path"].startswith("data/") for item in result["selectedEvidence"]))

    def test_ownership_and_failure_evidence_is_specific(self):
        for question, expected in (
            ("How does Kermit know whether a widget is active?", "34 distinct keys"),
            ("What happens when a widget module fails to load?", "Promise.allSettled"),
            ("Which settings can exist only in localStorage?", "BROWSER-ONLY PREFERENCE"),
            ("Which process owns Live Workout?", "8766"),
            ("Which process owns Network Monitor?", "8765"),
            ("Which process owns Kermit?", "8767"),
            ("Does restarting server.py stop an active workout?", "does not stop"),
            ("How are private Finance paths protected?", "404"),
        ):
            with self.subTest(question=question):
                self.assertTrue(any(expected.casefold() in item.get("excerpt", "").casefold()
                                    for item in ask(question)["selectedEvidence"]))

    def test_false_boundary_claims_are_not_retained(self):
        cases = (
            ("How does Kermit know whether a widget is active?", "Every widget-*.js file is active."),
            ("Which settings are server-backed?", "All settings live in SQLite."),
            ("Where is dashboard setting stored?", "localStorage is canonical for all settings."),
            ("Which process owns Kermit?", "Kermit runs inside server.py."),
            ("Which process owns Live Workout?", "server.py owns Live Workout lifecycle."),
            ("Can Kermit mutate dashboard settings?", "Kermit can use dashboard write APIs."),
            ("How are private Finance paths protected?", "Private data/ paths are ordinary static files."),
            ("Which process owns Network Monitor?", "Network Monitor runs on port 8766."),
            ("Where is widget order stored?", "data/widget-order.json is the canonical saved user order."),
        )
        for question, false_claim in cases:
            with self.subTest(false_claim=false_claim):
                evidence = ask(question)
                result = ground(evidence, draft(false_claim, evidence["selectedEvidence"]))
                self.assertNotEqual(result["claims"][0]["supportStatus"], "supported")
                self.assertNotIn(false_claim, result["answer"])

    def test_four_turn_unified_chat_routes_and_read_only_explanation(self):
        history = []
        turns = ("hi", "How are dashboard widgets loaded?", "Can you change my widget order?",
                 "And where is that setting stored?")
        decisions = []
        for turn in turns:
            decisions.append(route(turn, history))
            history.append({"role": "user", "content": turn})
        self.assertEqual([item["route"] for item in decisions], [GENERAL, PROJECT, PROJECT, PROJECT])
        self.assertEqual(decisions[-1]["query"], "Where is the dashboard widget order setting stored?")
        capability = ask(decisions[2]["query"])
        result = ground(capability, draft("Kermit can use dashboard write APIs.", capability["selectedEvidence"]))
        self.assertNotIn("Kermit can use dashboard write APIs", result["answer"])
        self.assertIn("cannot mutate widget order", result["answer"])
        followup = ask(decisions[-1]["query"])
        self.assertTrue(any("data/settings/dashboard.json" in item.get("excerpt", "")
                            for item in followup["selectedEvidence"]))
        self.assertTrue(all(not item["path"].startswith("data/") for item in followup["selectedEvidence"]))
        verified_storage = ground(followup, draft(
            "The dashboard widget order setting is stored in canonical server JSON "
            "data/settings/dashboard.json when the API is available.", followup["selectedEvidence"]))
        self.assertEqual(verified_storage["claims"][0]["supportStatus"], "supported")

        def answerer(question, **_kwargs):
            evidence = ask(question)
            if "mutate dashboard settings" in question:
                proposed = "Kermit can use dashboard write APIs."
            elif "widget order setting stored" in question:
                proposed = ("The dashboard widget order setting is stored in canonical server JSON "
                            "data/settings/dashboard.json when the API is available.")
            else:
                proposed = "Visible dashboard widgets are loaded by js/dashboard-widget-loader.js."
            return {**ground(evidence, draft(proposed, evidence["selectedEvidence"])), "draftStatus": "draft"}

        service = KermitService(ServiceConfig(provider="fake"), answerer=answerer)
        conversation = []
        replies = []
        for turn in turns:
            status, reply = service.chat({"contractVersion": 1, "message": turn, "profile": "quick",
                                          "history": conversation})
            self.assertEqual(status, 200)
            replies.append(reply)
            conversation.extend(({"role": "user", "content": turn},
                                 {"role": "assistant", "content": reply["answer"]}))
        self.assertEqual([reply["route"] for reply in replies], [GENERAL, PROJECT, PROJECT, PROJECT])
        self.assertIn("Hey!", replies[0]["answer"])
        self.assertIn("cannot mutate widget order", replies[2]["answer"])
        self.assertIn("data/settings/dashboard.json", replies[3]["answer"])
        self.assertTrue(replies[3]["citations"])

    def test_queries_do_not_change_sources_index_or_runtime_state(self):
        files = [ROOT / "index.html", ROOT / "server.py", MANIFEST,
                 *(ROOT / "docs/kermit/knowledge/subsystems" / f"{slug}.md"
                   for slug in ("dashboard", "settings", "central-api")),
                 *(INDEX / name for name in (*CORE_NAMES, "build.json")),
                 *(ROOT / name for name in ("data/settings/dashboard.json", "data/finance.sqlite",
                                               "data/cleaning.sqlite"))]
        present = [path for path in files if path.is_file()]
        before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in present}
        for question in ("How are dashboard widgets loaded?", "How does /api/settings work?",
                         "Which process owns Kermit?"):
            ask(question)
        self.assertEqual(before, {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in present})


class B2CoverageCheckTests(unittest.TestCase):
    def check(self):
        return coverage_check(ROOT, MANIFEST, INDEX)

    def test_current_inventory_and_index_are_clean(self):
        result = self.check()
        self.assertEqual(result["findings"], [])
        self.assertEqual((result["widgetCount"], result["apiDomainCount"], result["admittedCount"]),
                         (34, 45, 201))

    def test_checker_reports_new_widget_and_new_api_without_writing(self):
        from kermit_index import coverage
        real_read = coverage._read
        def changed(root, relative):
            raw = real_read(root, relative)
            if relative == "index.html":
                return raw + b'\n<div data-widget="new-card"></div>\n'
            if relative == "js/dashboard-widget-loader.js":
                return raw.replace(b"const widgetLoaders = {", b"const widgetLoaders = {\n  \"new-card\": () => import(\"./new-card.js\"),", 1)
            return raw
        with patch.object(coverage, "_read", side_effect=changed), patch.object(
                coverage, "_api_domains", return_value=coverage._api_domains(ROOT) | {"new-domain"}):
            result = self.check()
        codes = {(item["code"], item["subject"]) for item in result["findings"]}
        self.assertIn(("widget_missing_coverage", "new-card"), codes)
        self.assertIn(("api_domain_missing_coverage", "new-domain"), codes)

    def test_checker_reports_missing_reference_marker_and_changed_fingerprint(self):
        from kermit_index import coverage
        real_read = coverage._read
        def changed(root, relative):
            if relative == "js/dashboard-widget-visibility.js":
                return real_read(root, relative).replace(b"filterVisibleWidgetKeys", b"renamedFilter")
            return real_read(root, relative)
        with patch.object(coverage, "_read", side_effect=changed):
            result = self.check()
        codes = {item["code"] for item in result["findings"]}
        self.assertIn("pack_reference_missing_marker", codes)
        # A real source edit is checked against the index snapshot, not the mock read.
        self.assertEqual(result["status"], "stale")

    def test_checker_reports_missing_source_and_validated_pack_drift(self):
        from kermit_index import coverage
        real_read = coverage._read
        real_safe_path = coverage.safe_path
        def missing(root, relative):
            if relative == "js/dashboard-widget-visibility.js":
                raise OSError("test missing")
            return real_read(root, relative)
        def missing_admission(root, relative, group, max_bytes):
            if relative == "js/dashboard-widget-visibility.js":
                raise OSError("test missing")
            return real_safe_path(root, relative, group, max_bytes)
        with patch.object(coverage, "_read", side_effect=missing), patch.object(
                coverage, "safe_path", side_effect=missing_admission):
            result = self.check()
        self.assertTrue(any(item["code"] == "referenced_source_missing" for item in result["findings"]))
        self.assertTrue(any(item["code"] == "validated_pack_source_changed" for item in result["findings"]))
        self.assertTrue(any(item["code"] == "admitted_source_missing" for item in result["findings"]))

    def test_checker_reports_changed_admitted_source_and_pack_fingerprint(self):
        from kermit_index import coverage
        real_safe_path = coverage.safe_path
        with tempfile.TemporaryDirectory() as temporary:
            substitute = Path(temporary) / "visibility.js"
            substitute.write_bytes((ROOT / "js/dashboard-widget-visibility.js").read_bytes() + b"\n// test drift\n")
            def changed(root, relative, group, max_bytes):
                if relative == "js/dashboard-widget-visibility.js":
                    return substitute
                return real_safe_path(root, relative, group, max_bytes)
            with patch.object(coverage, "safe_path", side_effect=changed):
                result = self.check()
        codes = {item["code"] for item in result["findings"]}
        self.assertIn("admitted_source_changed", codes)
        self.assertIn("validated_pack_source_changed", codes)


if __name__ == "__main__":
    unittest.main()
