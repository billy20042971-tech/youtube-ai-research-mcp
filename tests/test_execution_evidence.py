import json
import tempfile
import unittest
from pathlib import Path

from scripts.execution_evidence import ensure_failure_audit, record_execution_state, validate_success_evidence


class ExecutionEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "data").mkdir()
        (self.root / "reports").mkdir()
        self.execution_id = "gh-100-attempt-1"
        self.state = {
            "execution_id": self.execution_id,
            "github_run_id": "100",
            "trigger": "schedule",
            "recovery_attempt": False,
            "status": "SUCCESS",
            "data": "PASS",
            "reports": "PASS",
            "verification": "PASS",
        }
        self.data = {
            "execution_id": self.execution_id,
            "generated_at": "2026-10-21T00:00:00Z",
            "verification": {"fresh_videos": 3, "stale_or_invalid_videos": 0, "verified_72h": True},
        }
        self.summary = {"execution_id": self.execution_id, "sample_count": 3, "generated_at": "2026-10-21T00:00:00Z", "recent_72h_sample": {}}
        self.manifest = {"execution_id": self.execution_id, "sample_count": 3, "generated_at": "2026-10-21T00:00:01Z"}
        self.audit = {
            "execution_id": self.execution_id, "status": "PASS", "writeback_verified": True,
            "readback_verified": True, "page_id": "page-1", "comment_id": "comment-1",
            "readback_content_sha256": "abc123",
        }

    def tearDown(self):
        self.temp.cleanup()

    def write_evidence(self, data=None, summary=None, manifest=None, audit=None):
        for path, value in (
            ("data/latest.json", data or self.data),
            ("data/recent-summary.json", summary or self.summary),
            ("reports/latest-manifest.json", manifest or self.manifest),
            ("data/notion-writeback-audit.json", audit or self.audit),
        ):
            (self.root / path).write_text(json.dumps(value), encoding="utf-8")

    def test_complete_matching_evidence_passes(self):
        validate_success_evidence(self.state, self.data, self.summary, self.manifest, self.audit)

    def test_data_execution_id_mismatch_fails(self):
        data = {**self.data, "execution_id": "gh-old-attempt-1"}
        with self.assertRaisesRegex(ValueError, "execution IDs do not match"):
            validate_success_evidence(self.state, data, self.summary, self.manifest, self.audit)

    def test_summary_execution_id_mismatch_fails(self):
        summary = {**self.summary, "execution_id": "gh-old-attempt-1"}
        with self.assertRaisesRegex(ValueError, "execution IDs do not match"):
            validate_success_evidence(self.state, self.data, summary, self.manifest, self.audit)

    def test_summary_timestamp_mismatch_fails(self):
        summary = {**self.summary, "generated_at": "2026-10-21T02:00:00Z"}
        with self.assertRaisesRegex(ValueError, "timestamps do not match"):
            validate_success_evidence(self.state, self.data, summary, self.manifest, self.audit)

    def test_summary_sample_count_mismatch_fails(self):
        summary = {**self.summary, "sample_count": 2}
        with self.assertRaisesRegex(ValueError, "sample_count do not match"):
            validate_success_evidence(self.state, self.data, summary, self.manifest, self.audit)

    def test_manifest_execution_id_mismatch_fails(self):
        manifest = {**self.manifest, "execution_id": "gh-old-attempt-1"}
        with self.assertRaisesRegex(ValueError, "execution IDs do not match"):
            validate_success_evidence(self.state, self.data, self.summary, manifest, self.audit)

    def test_audit_execution_id_mismatch_fails(self):
        audit = {**self.audit, "execution_id": "gh-other-attempt-1"}
        with self.assertRaisesRegex(ValueError, "execution IDs do not match"):
            validate_success_evidence(self.state, self.data, self.summary, self.manifest, audit)

    def test_manifest_timestamp_mismatch_fails(self):
        manifest = {**self.manifest, "generated_at": "2026-10-21T02:00:00Z"}
        with self.assertRaisesRegex(ValueError, "timestamps differ"):
            validate_success_evidence(self.state, self.data, self.summary, manifest, self.audit)

    def test_recovery_success_keeps_recovery_trigger_distinct(self):
        self.write_evidence()
        recovery = {**self.state, "execution_id": "gh-105-attempt-1",
                    "trigger": "workflow_dispatch", "recovery_attempt": True}
        self.write_evidence(
            data={**self.data, "execution_id": "gh-105-attempt-1"},
            summary={**self.summary, "execution_id": "gh-105-attempt-1"},
            manifest={**self.manifest, "execution_id": "gh-105-attempt-1"},
            audit={**self.audit, "execution_id": "gh-105-attempt-1"},
        )
        record_execution_state(recovery, root=self.root)
        saved = json.loads((self.root / "data/latest-successful-execution.json").read_text())
        self.assertEqual(saved["trigger"], "workflow_dispatch")
        self.assertTrue(saved["recovery_attempt"])

    def test_audit_readback_false_fails(self):
        audit = {**self.audit, "readback_verified": False}
        with self.assertRaisesRegex(ValueError, "Audit is not PASS"):
            validate_success_evidence(self.state, self.data, self.summary, self.manifest, audit)

    def test_audit_without_comment_identity_or_hash_fails(self):
        audit = {**self.audit, "comment_id": "", "readback_content_sha256": ""}
        with self.assertRaisesRegex(ValueError, "identity/content evidence"):
            validate_success_evidence(self.state, self.data, self.summary, self.manifest, audit)

    def test_stale_or_invalid_data_fails(self):
        data = {**self.data, "verification": {"fresh_videos": 3, "stale_or_invalid_videos": 1, "verified_72h": False}}
        with self.assertRaisesRegex(ValueError, "Freshness Data Gate"):
            validate_success_evidence(self.state, data, self.summary, self.manifest, self.audit)

    def test_success_writes_last_success_and_history(self):
        self.write_evidence()
        record_execution_state(self.state, root=self.root)
        saved = json.loads((self.root / "data/latest-successful-execution.json").read_text())
        history = json.loads((self.root / "data/execution-history.json").read_text())
        self.assertEqual(saved["execution_id"], self.execution_id)
        self.assertEqual(len(history["executions"]), 1)

    def test_failed_recovery_does_not_overwrite_last_success(self):
        self.write_evidence()
        record_execution_state(self.state, root=self.root)
        failed = {
            **self.state, "execution_id": "gh-101-attempt-1", "github_run_id": "101",
            "trigger": "workflow_dispatch", "recovery_attempt": True, "status": "FAILED",
            "data": "UNKNOWN", "reports": "UNKNOWN", "verification": "FAIL",
        }
        record_execution_state(failed, root=self.root)
        saved = json.loads((self.root / "data/latest-successful-execution.json").read_text())
        history = json.loads((self.root / "data/execution-history.json").read_text())
        current = json.loads((self.root / "data/execution-state.json").read_text())
        self.assertEqual(saved["execution_id"], self.execution_id)
        self.assertEqual(current["execution_id"], "gh-101-attempt-1")
        self.assertEqual([x["status"] for x in history["executions"]], ["SUCCESS", "FAILED"])

    def test_old_data_cannot_make_failed_execution_pass(self):
        self.write_evidence()
        failed = {**self.state, "execution_id": "gh-102-attempt-1", "status": "FAILED", "data": "UNKNOWN"}
        record_execution_state(failed, root=self.root)
        self.assertFalse((self.root / "data/latest-successful-execution.json").exists())
        current = json.loads((self.root / "data/execution-state.json").read_text())
        self.assertEqual(current["status"], "FAILED")

    def test_multiple_runs_keep_latest_success_separate_from_latest_failure(self):
        self.write_evidence()
        record_execution_state(self.state, root=self.root)
        failed = {**self.state, "execution_id": "gh-103-attempt-1", "status": "FAILED", "data": "UNKNOWN"}
        record_execution_state(failed, root=self.root)
        successful = {**self.state, "execution_id": "gh-104-attempt-1"}
        self.write_evidence(
            data={**self.data, "execution_id": "gh-104-attempt-1"},
            summary={**self.summary, "execution_id": "gh-104-attempt-1"},
            manifest={**self.manifest, "execution_id": "gh-104-attempt-1"},
            audit={**self.audit, "execution_id": "gh-104-attempt-1"},
        )
        record_execution_state(successful, root=self.root)
        latest_success = json.loads((self.root / "data/latest-successful-execution.json").read_text())
        history = json.loads((self.root / "data/execution-history.json").read_text())
        self.assertEqual(latest_success["execution_id"], "gh-104-attempt-1")
        self.assertEqual([x["execution_id"] for x in history["executions"]], [
            "gh-100-attempt-1", "gh-103-attempt-1", "gh-104-attempt-1"
        ])

    def test_failure_before_notion_writeback_does_not_leave_previous_pass_audit(self):
        old_audit = {**self.audit, "execution_id": "gh-old-attempt-1"}
        (self.root / "data/notion-writeback-audit.json").write_text(json.dumps(old_audit), encoding="utf-8")
        changed = ensure_failure_audit(root=self.root, execution_id="gh-106-attempt-1",
                                       reason="MCP initialize failed", run_id="106")
        saved = json.loads((self.root / "data/notion-writeback-audit.json").read_text())
        self.assertTrue(changed)
        self.assertEqual(saved["execution_id"], "gh-106-attempt-1")
        self.assertEqual(saved["status"], "NOT_RUN")
        self.assertFalse(saved["writeback_verified"])
        self.assertFalse(saved["readback_verified"])
        history = json.loads((self.root / "data/notion-writeback-audit-history.json").read_text())
        self.assertEqual(history["audits"][-1]["execution_id"], "gh-106-attempt-1")
        self.assertEqual(history["audits"][-1]["status"], "NOT_RUN")

    def test_failure_does_not_overwrite_same_execution_notion_audit(self):
        self.write_evidence()
        changed = ensure_failure_audit(root=self.root, execution_id=self.execution_id,
                                       reason="later evidence gate failed", run_id="100")
        saved = json.loads((self.root / "data/notion-writeback-audit.json").read_text())
        self.assertFalse(changed)
        self.assertEqual(saved["status"], "PASS")
        self.assertEqual(saved["execution_id"], self.execution_id)

    def test_history_is_bounded(self):
        history_path = self.root / "data/execution-history.json"
        history_path.write_text(json.dumps({"executions": [{"execution_id": f"old-{i}"} for i in range(5)]}))
        failed = {**self.state, "execution_id": "gh-new-attempt-1", "status": "FAILED"}
        record_execution_state(failed, root=self.root, history_limit=3)
        history = json.loads(history_path.read_text())
        self.assertEqual(len(history["executions"]), 3)
        self.assertEqual(history["executions"][-1]["execution_id"], "gh-new-attempt-1")


if __name__ == "__main__":
    unittest.main()
