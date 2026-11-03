import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class RemainingSafetyTests(unittest.TestCase):
    def test_mcp_handshake_does_not_consume_youtube_api_quota(self):
        handshake = (ROOT / ".github/workflows/mcp-handshake-test.yml").read_text(encoding="utf-8")
        self.assertIn("tools/list", handshake)
        self.assertIn("tools.body", handshake)
        self.assertIn("without consuming YouTube API quota", handshake)
        self.assertNotIn('"method":"tools/call"', handshake)
        self.assertNotIn("name: Call YouTube research tool", handshake)
        self.assertNotIn("tool.body", handshake)

    def test_missing_notion_credentials_fail_closed_and_write_skipped_audit(self):
        script = ROOT / "scripts/notion_writeback.py"
        with tempfile.TemporaryDirectory() as temp_dir:
            env = os.environ.copy()
            env.pop("NOTION_API_KEY", None)
            env.pop("NOTION_DATABASE_ID", None)
            env["GITHUB_RUN_ID"] = "test-run"
            env["GITHUB_RUN_ATTEMPT"] = "1"
            result = subprocess.run(
                [sys.executable, str(script)],
                cwd=temp_dir,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            audit_path = Path(temp_dir) / "data/notion-writeback-audit.json"
            self.assertTrue(audit_path.is_file())
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            self.assertEqual(audit["status"], "SKIPPED_MISSING_CREDENTIALS")
            self.assertFalse(audit["writeback_verified"])
            self.assertFalse(audit["token_configured"])
            self.assertFalse(audit["database_id_configured"])

    def test_legacy_page_id_alone_does_not_enable_notion_writeback(self):
        script = ROOT / "scripts/notion_writeback.py"
        with tempfile.TemporaryDirectory() as temp_dir:
            env = os.environ.copy()
            env["NOTION_API_KEY"] = "test-token"
            env["NOTION_PAGE_ID"] = "8eeeca64-4e1f-4687-a361-1f5124a0c5c8"
            env.pop("NOTION_DATABASE_ID", None)
            env["GITHUB_RUN_ID"] = "legacy-only-test"
            env["GITHUB_RUN_ATTEMPT"] = "1"
            result = subprocess.run(
                [sys.executable, str(script)],
                cwd=temp_dir,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            audit = json.loads((Path(temp_dir) / "data/notion-writeback-audit.json").read_text(encoding="utf-8"))
            self.assertEqual(audit["status"], "SKIPPED_MISSING_CREDENTIALS")
            self.assertFalse(audit["database_id_configured"])
            self.assertFalse(audit["writeback_verified"])


if __name__ == "__main__":
    unittest.main()
