"""Local mock of the OpenAI Chat Completions and Anthropic Messages APIs (port 8765), answering with the
scripted test responses. Lets you exercise the live-provider code paths without an API key:

  python tests/mock_llm_server.py &
  OPENAI_API_KEY=x OPENAI_BASE_URL=http://127.0.0.1:8765/v1 PROMOFINDER_MODEL=mock python -m promofinder.cli run --zip sample_data/synthetic_show.zip --out runs/mock --provider openai
  ANTHROPIC_API_KEY=x ANTHROPIC_BASE_URL=http://127.0.0.1:8765 PROMOFINDER_MODEL=mock python -m promofinder.cli run --zip sample_data/synthetic_show.zip --out runs/mock2 --provider anthropic
"""
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from test_promofinder import Scripted
S = Scripted(__import__("tempfile").mkdtemp())
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        prompt = body['messages'][-1]['content']
        text, _ = S._call(prompt)
        if self.path.endswith('/chat/completions'):
            out = {"id": "x", "object": "chat.completion", "created": 0, "model": body['model'],
                   "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
                   "usage": {"prompt_tokens": len(prompt)//4, "completion_tokens": len(text)//4, "total_tokens": 1}}
        else:
            out = {"id": "msg", "type": "message", "role": "assistant", "model": body['model'],
                   "content": [{"type": "text", "text": text}], "stop_reason": "end_turn", "stop_sequence": None,
                   "usage": {"input_tokens": len(prompt)//4, "output_tokens": len(text)//4}}
        b = json.dumps(out).encode(); self.send_response(200); self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(b))); self.end_headers(); self.wfile.write(b)
HTTPServer(('127.0.0.1', 8765), H).serve_forever()
