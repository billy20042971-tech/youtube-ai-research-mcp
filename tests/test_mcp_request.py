import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from scripts.mcp_request import McpRequestError, request_tool, retryable_http_status
from scripts.mcp_sse import parse_mcp_response_text

class Response:
    def __init__(self,status,body=b""): self.status,self.body=status,body
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def read(self): return self.body

def good():
    return json.dumps({"jsonrpc":"2.0","id":3,"result":{"structuredContent":{"videos":[{"video_id":"v1"}]}}}).encode()

class McpRequestTests(unittest.TestCase):
    def call(self,queue):
        seen,pauses=[],[]; items=iter(queue)
        def opener(req,timeout):
            seen.append(req); item=next(items)
            if isinstance(item,BaseException): raise item
            return item
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/"response.body"
            attempts=request_tool("https://mcp.invalid","session-test",{"queries":["fixture"]},output,
                                  opener=opener,sleeper=pauses.append,timeout=2)
            return attempts,seen,pauses,output.read_bytes()

    def test_http_200_json(self):
        attempts,seen,pauses,body=self.call([Response(200,good())])
        self.assertEqual((attempts,len(seen),pauses),(1,1,[]))
        self.assertEqual(parse_mcp_response_text(body.decode())["videos"][0]["video_id"],"v1")

    def test_http_200_sse(self):
        attempts,seen,_,body=self.call([Response(200,("data: "+good().decode()+"\n\n").encode())])
        self.assertEqual((attempts,len(seen)),(1,1))
        self.assertEqual(parse_mcp_response_text(body.decode())["videos"][0]["video_id"],"v1")

    def test_empty_body_then_success_reuses_request_id_and_is_bounded(self):
        attempts,seen,pauses,_=self.call([Response(200,b" \t"),Response(200,good())])
        self.assertEqual((attempts,len(seen),pauses),(2,2,[5]))
        self.assertEqual(json.loads(seen[0].data)["id"],json.loads(seen[1].data)["id"])

    def test_5xx_then_success(self):
        attempts,seen,pauses,_=self.call([Response(503,b"secret"),Response(200,good())])
        self.assertEqual((attempts,len(seen),pauses),(2,2,[5]))

    def test_timeout_then_success(self):
        attempts,seen,pauses,_=self.call([TimeoutError("secret token"),Response(200,good())])
        self.assertEqual((attempts,len(seen),pauses),(2,2,[5]))

    def test_nonretryable_4xx_fails_without_logging_body(self):
        error=HTTPError("https://mcp.invalid",401,"SECRET_BODY",{},None); seen=[]
        def opener(req,timeout): seen.append(req); raise error
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(McpRequestError,"non-retryable HTTP status 401") as caught:
                request_tool("https://mcp.invalid","s",{},Path(tmp)/"body",opener=opener,sleeper=lambda _:None)
        self.assertEqual(len(seen),1); self.assertNotIn("SECRET_BODY",str(caught.exception))

    def test_empty_response_exhaustion_fails_closed_after_two_tries(self):
        seen=[]
        def opener(req,timeout): seen.append(req); return Response(200,b" \n")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(McpRequestError,"failed after 2 attempts"):
                request_tool("https://mcp.invalid","s",{},Path(tmp)/"body",opener=opener,sleeper=lambda _:None)
        self.assertEqual(len(seen),2)

    def test_retry_classification(self):
        for code in (408,425,429,500,503,599): self.assertTrue(retryable_http_status(code))
        for code in (200,400,401,403,404): self.assertFalse(retryable_http_status(code))

    def test_invalid_json_is_not_retried(self):
        attempts,seen,_,body=self.call([Response(200,b"{not-json}")])
        self.assertEqual((attempts,len(seen)),(1,1))
        with self.assertRaisesRegex(RuntimeError,"Invalid JSON"): parse_mcp_response_text(body.decode())

    def test_sse_without_data_event_is_not_retried(self):
        attempts,seen,_,body=self.call([Response(200,b"event: message\n\n")])
        self.assertEqual((attempts,len(seen)),(1,1))
        with self.assertRaisesRegex(RuntimeError,"no data events"): parse_mcp_response_text(body.decode())

    def test_json_rpc_error_is_not_retried(self):
        body=json.dumps({"jsonrpc":"2.0","id":3,"error":{"code":-32603,"message":"private"}}).encode()
        attempts,seen,_,saved=self.call([Response(200,body)])
        self.assertEqual((attempts,len(seen)),(1,1))
        with self.assertRaisesRegex(RuntimeError,"JSON-RPC error"): parse_mcp_response_text(saved.decode())

    def test_session_header_and_sensitive_content_not_exposed(self):
        error=HTTPError("https://mcp.invalid",400,"DO_NOT_LOG",{},None); seen=[]
        def opener(req,timeout): seen.append(req); raise error
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(McpRequestError) as caught:
                request_tool("https://mcp.invalid","session-x",{},Path(tmp)/"body",opener=opener,sleeper=lambda _:None)
        self.assertEqual(seen[0].get_header("Mcp-session-id"),"session-x")
        self.assertNotIn("DO_NOT_LOG",str(caught.exception))

if __name__ == "__main__":
    unittest.main()
