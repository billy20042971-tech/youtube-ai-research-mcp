from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RecoveryDispatchHttpObservabilityTests(unittest.TestCase):
    def test_dispatch_captures_http_status_without_fail_with_body(self):
        workflow = (ROOT / ".github/workflows/youtube-research-self-healing.yml").read_text(encoding="utf-8")
        dispatch = workflow.split('echo "SELF_HEALING: dispatching a fresh verified production recovery run."', 1)[1]
        self.assertIn('DISPATCH_HTTP_STATUS="$(curl -sS', dispatch)
        self.assertNotIn('DISPATCH_HTTP_STATUS="$(curl --fail-with-body', dispatch)
        self.assertIn("CURL_EXIT_CODE=$?", dispatch)
        self.assertIn('set +e', dispatch)
        self.assertIn('set -e', dispatch)
        self.assertIn('http_status=${DISPATCH_HTTP_STATUS:-empty}', dispatch)
        self.assertIn('[ "$DISPATCH_HTTP_STATUS" != "204" ]', dispatch)
        self.assertIn("Recovery dispatch HTTP request failed at the transport/client layer.", dispatch)
        self.assertIn("Unexpected recovery dispatch HTTP status:", dispatch)


if __name__ == "__main__":
    unittest.main()
