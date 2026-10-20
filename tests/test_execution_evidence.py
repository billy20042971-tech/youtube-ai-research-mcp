import json
import tempfile
import unittest
from pathlib import Path
from scripts.execution_evidence import schedule_deadline_status, validate_execution_artifacts, write_execution_state

def seed(root, eid, *, data_id=None, summary_id=None, manifest_id=None, audit_id=None,
         counts=(3,3,3), data_time="2026-10-20T01:00:00+00:00",
         summary_time="2026-10-20T01:00:00+00:00", manifest_data_time="2026-10-20T01:00:00+00:00"):
    data_id, summary_id, manifest_id, audit_id = data_id or eid, summary_id or eid, manifest_id or eid, audit_id or eid
    folder = Path("reports/2026-10-20/executions") / eid
    (root / folder).mkdir(parents=True, exist_ok=True)
    for name in ("report.docx","slides.pptx","chart.png"):
        (root / folder / name).write_bytes(b"fixture")
    data={"execution_id":data_id,"generated_at":data_time,"sample_count":counts[0],
          "verification":{"fresh_videos":counts[0],"stale_or_invalid_videos":0,"verified_72h":True}}
    summary={"execution_id":summary_id,"generated_at":summary_time,"sample_count":counts[1]}
    manifest={"execution_id":manifest_id,"generated_at":"2026-10-20T01:01:00+00:00",
              "data_generated_at":manifest_data_time,"sample_count":counts[2],
              "word":str(folder/"report.docx"),"pptx":str(folder/"slides.pptx"),"chart":str(folder/"chart.png")}
    audit={"execution_id":audit_id,"status":"PASS","page_id":"page","comment_id":"comment",
           "writeback_verified":True,"readback_verified":True,"content_verified":True,"sample_count":counts[2],
           "data_execution_id":data_id,"summary_execution_id":summary_id,"manifest_execution_id":manifest_id,
           "data_generated_at":data_time,"summary_generated_at":summary_time,"manifest_data_generated_at":manifest_data_time}
    for path,value in (("data/latest.json",data),("data/recent-summary.json",summary),
                       ("reports/latest-manifest.json",manifest),("data/notion-writeback-audit.json",audit)):
        target=root/path; target.parent.mkdir(parents=True,exist_ok=True); target.write_text(json.dumps(value),encoding="utf-8")

def save_state(root,eid,status,trigger="workflow_dispatch",started="2026-10-20T01:00:00+00:00"):
    return write_execution_state(root,execution_id=eid,started_at=started,github_run_id=eid.split("-")[1],
        github_run_attempt="1",trigger=trigger,recovery_attempt=trigger=="workflow_dispatch",
        requested_status=status,failure_reason="MCP response body is empty." if status!="SUCCESS" else "",
        mcp_endpoint="https://mcp.invalid")

class ExecutionEvidenceTests(unittest.TestCase):
    def test_success_requires_bound_data_reports_and_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); seed(root,"gh-101-attempt-1")
            state,ok=save_state(root,"gh-101-attempt-1","SUCCESS","schedule","2026-10-20T06:00:00+08:00")
            self.assertTrue(ok); self.assertEqual(state["status"],"SUCCESS"); self.assertEqual(state["artifact_gate_status"],"PASS")
            self.assertEqual(state["schedule_deadline_status"],"ON_TIME"); self.assertTrue((root/"data/last-successful-execution.json").is_file())

    def test_recovery_success_never_proves_schedule_was_on_time(self):
        self.assertEqual(schedule_deadline_status("workflow_dispatch","2026-10-20T09:00:00+08:00"),"NOT_APPLICABLE_RECOVERY_OR_NON_SCHEDULE")
        self.assertEqual(schedule_deadline_status("schedule","2026-10-20T06:16:00+08:00"),"MISSED_DEADLINE")

    def test_success_then_failed_recovery_preserves_last_success_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); first,second="gh-101-attempt-1","gh-102-attempt-1"; seed(root,first)
            save_state(root,first,"SUCCESS"); pointer=(root/"data/last-successful-execution.json").read_text()
            state,ok=save_state(root,second,"FAILED")
            self.assertFalse(ok); self.assertEqual(state["status"],"FAILED")
            self.assertEqual((root/"data/last-successful-execution.json").read_text(),pointer)
            self.assertTrue((root/"data/execution-history"/(first+".json")).is_file())
            self.assertTrue((root/"data/execution-history"/(second+".json")).is_file())

    def test_failed_research_never_reuses_old_data_as_current_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); seed(root,"gh-201-attempt-1"); save_state(root,"gh-201-attempt-1","SUCCESS")
            state,ok=save_state(root,"gh-202-attempt-1","FAILED")
            self.assertFalse(ok); self.assertEqual(state["status"],"FAILED"); self.assertFalse(state["data_execution_match"])
            self.assertIsNone(state["data_generated_at"]); self.assertEqual(state["data"],"UNKNOWN")

    def test_data_manifest_execution_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); seed(root,"gh-301-attempt-1",manifest_id="gh-old-attempt-1")
            result=validate_execution_artifacts(root,"gh-301-attempt-1")
            self.assertEqual(result["status"],"FAIL"); self.assertIn("manifest_execution_id_mismatch",result["errors"])

    def test_timestamp_and_sample_count_mismatch_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); seed(root,"gh-401-attempt-1",summary_time="2026-10-20T01:02:00+00:00",counts=(3,2,3))
            errors=validate_execution_artifacts(root,"gh-401-attempt-1")["errors"]
            self.assertIn("summary_data_timestamp_mismatch",errors); self.assertIn("sample_count_mismatch",errors)

    def test_audit_must_match_same_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); seed(root,"gh-501-attempt-1",audit_id="gh-old-attempt-1")
            self.assertIn("audit_execution_id_mismatch",validate_execution_artifacts(root,"gh-501-attempt-1")["errors"])

    def test_partial_new_data_and_old_manifest_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); seed(root,"gh-601-attempt-1",manifest_id="gh-600-attempt-1")
            self.assertEqual(validate_execution_artifacts(root,"gh-601-attempt-1")["status"],"FAIL")

    def test_new_success_preserves_prior_history_and_advances_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); first,second="gh-801-attempt-1","gh-802-attempt-1"; seed(root,first)
            save_state(root,first,"SUCCESS"); history=(root/"data/execution-history"/(first+".json")).read_text()
            seed(root,second); state,ok=save_state(root,second,"SUCCESS")
            self.assertTrue(ok); self.assertEqual(state["status"],"SUCCESS")
            self.assertEqual((root/"data/execution-history"/(first+".json")).read_text(),history)
            self.assertEqual(json.loads((root/"data/last-successful-execution.json").read_text())["execution_id"],second)

if __name__ == "__main__":
    unittest.main()
