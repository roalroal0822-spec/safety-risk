"""시험용 가짜 모델 서버 (OpenAI 호환 /v1/chat/completions, Ollama /api/chat).

실제 모델이 아니다. 앱의 모델 연결 경로(글·사진 요청 형식, JSON 해석, 근거 대조)가 동작하는지 확인하려고
출력 습관이 다른 두 가지 응답 방식을 흉내 낸다.
  mock-a : 작업 설명에 실제로 있는 문구만 근거로 들고 JSON 을 깔끔하게 돌려준다.
  mock-b : ```json 코드블록·설명 문장을 섞고, 목록에 없는 코드와 설명에 없는 근거 문구를 일부러 섞는다(앱이 걸러야 함).
실행: python tools/mock_llm.py --port 18080
"""
import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _text(messages):
    out, imgs = [], 0
    for m in messages:
        c = m.get("content", "")
        if isinstance(c, list):
            for part in c:
                if part.get("type") == "text":
                    out.append(part["text"])
                else:
                    imgs += 1
        else:
            out.append(c)
        imgs += len(m.get("images") or [])
    return "\n".join(out), imgs


def reply(model, messages):
    user, imgs = _text(messages)
    bad = model.endswith("b")
    if imgs:
        obj = {"hazards": [{"code": "H01", "what": "사다리 위 작업자, 안전모 없음"}, {"code": "H02", "what": "바닥 물기"}]}
        if bad:
            obj["hazards"].append({"code": "H99", "what": "알 수 없는 위험"})
            return "사진을 보았습니다.\n```json\n" + json.dumps(obj, ensure_ascii=False) + "\n```"
        return json.dumps(obj, ensure_ascii=False)
    if "작업 설명:" in user:
        desc = user.split("작업 설명:")[-1].split("\n\n")[0]
        hz = []
        m = re.search(r"[^.,]*팬[^.,]*", desc)
        if m:
            hz.append({"code": "H04", "quote": m.group().strip() if not bad else "회전하는 팬 날개에 손이 닿을 수 있음"})
        if bad:
            hz.append({"code": "H99", "quote": desc[:10]})
        s = json.dumps({"hazards": hz}, ensure_ascii=False)
        return f"분석 결과입니다.\n```json\n{s}\n```" if bad else s
    return "확인"


class H(BaseHTTPRequestHandler):
    def _send(self, obj):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.endswith("/models"):
            return self._send({"data": [{"id": "mock-a"}, {"id": "mock-b"}]})
        return self._send({"models": [{"name": "mock-a"}, {"name": "mock-b"}]})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        req = json.loads(self.rfile.read(n) or b"{}")
        out = reply(req.get("model", "mock-a"), req.get("messages", []))
        if self.path.endswith("/api/chat"):
            return self._send({"message": {"role": "assistant", "content": out}, "done": True, "done_reason": "stop"})
        return self._send({"choices": [{"message": {"role": "assistant", "content": out}, "finish_reason": "stop"}]})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=18080)
    a = ap.parse_args()
    ThreadingHTTPServer(("127.0.0.1", a.port), H).serve_forever()
