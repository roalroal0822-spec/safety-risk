"""구동 점검: 서버를 임시 작업 폴더로 띄워 주요 기능을 차례로 호출한다(모델 없이 규칙 기반).

실행: python tests/smoke_test.py
원본(sample_data)은 읽기만 하며, 작업 데이터는 임시 폴더에 쓰고 끝나면 지운다.
"""
import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Client:
    def __init__(self, port):
        self.base = f"http://127.0.0.1:{port}"

    def call(self, method, path, body=None, raw=False, headers=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        h = {"Content-Type": "application/json", **(headers or {})}
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        with urllib.request.urlopen(req, timeout=120) as r:
            b = r.read()
            return b if raw else json.loads(b)

    def status(self, method, path, body=None, headers=None):
        try:
            self.call(method, path, body, raw=True, headers=headers)
            return 200
        except urllib.error.HTTPError as e:
            return e.code


def checks(c):
    yield "화면 열기", c.call("GET", "/", raw=True)[:15].lower().startswith(b"<!doctype")
    s = c.call("GET", "/api/state")
    k = s["kb"]
    yield f"기관 자료(위험요인 {k['hazards']}, 작업 {k['tasks']}, 아차사고 {k['incidents']})", k["hazards"] == 12 and k["tasks"] == 9 and k["incidents"] == 4
    yield "판단 기준을 규정 조문에서 읽음", [r["value"] for r in k["rules"][:2]] == [6, 3] and all(r["basis"] for r in k["rules"][:2])
    a = c.call("POST", "/api/assess", {"fac": "종합체육센터", "dept": "체육사업팀", "work": "체육관 천장 조명(등기구) 교체",
                                       "text": "이동식 일자 사다리로 높이 4m 등기구 안정기 교체. 혼자 작업, 바닥 왁스 청소 직후"})
    codes = [i["code"] for i in a["items"]]
    h01 = next(i for i in a["items"] if i["code"] == "H01")
    yield f"위험요인 찾기 {codes}", {"H01", "H02", "H03"} <= set(codes)
    yield f"조건 반영(높이·1인·젖은 바닥·아차사고) 떨어짐 위험성 {h01['R']}", h01["R"] == 9 and len(h01["reasons"]) == 4 and any(r.get("src") for r in h01["reasons"])
    yield "작업 시작 전 조치 필요 판정", not a["stats"]["ready"]
    upd = {"items": [{"code": i["code"], "measures": [{"done": True} for _ in i["measures"]]} for i in a["items"] if i["level"] == "bad"]}
    a2 = c.call("POST", f"/api/assess/{a['id']}/update", upd)
    yield "감소대책 완료 → 작업 시작 가능", a2["stats"]["ready"]
    a3 = c.call("POST", f"/api/assess/{a['id']}/update", {"items": [{"code": "H11", "L": 1}]})
    h11 = next(i for i in a3["items"] if i["code"] == "H11")
    yield "담당자 조정 기록", h11["R"] == 2 and "담당자 조정" in h11["reasons"][-1]["text"]
    for fmt in ("hwpx", "docx", "md"):
        d = c.call("POST", f"/api/assess/{a['id']}/export?fmt={fmt}", {}, raw=True)
        yield f"위험성평가표({fmt})", len(d) > 500
    t = c.call("GET", f"/api/assess/{a['id']}/tbm")
    yield f"TBM 문안 {len(t['lines'])}줄", len(t["lines"]) >= 5
    d = c.call("POST", f"/api/assess/{a['id']}/tbm?fmt=hwpx", {}, raw=True)
    yield "TBM 기록지", d[:2] == b"PK"
    b = c.call("POST", "/api/assess", {"fac": "본부 청사", "work": "지하 저수조 청소", "text": "저수조 내부 물청소 2인 1조"})
    yield "밀폐공간 → 작업허가서 안내", any("밀폐공간" in p["name"] for p in b["permits"])
    q = c.call("POST", "/api/assess", {"fac": "공영주차장", "work": "주차장 바닥 도색", "text": "실외 진출입로 차선 도색"})
    yield "빠진 조건 질문(체감온도)", any("체감온도" in x for x in q["questions"])
    ch = c.call("POST", "/api/assess", {"fac": "종합체육센터", "work": "수영장 염소 약품 투입", "text": "기계실에서 약품 통을 옮겨 투입기에 붓는다"})
    r = c.call("POST", "/api/incidents", {"date": "2026-10-20", "fac": "종합체육센터", "work": "수영장 염소 약품 투입",
                                          "text": "약품 투입기 호스가 빠져 약품이 바닥에 흘렀고 닦다가 기침함", "result": "다침 없음"})
    yield f"아차사고 → 수시평가 필요 {len(r['hits'])}건", [h["id"] for h in r["hits"]] == [ch["id"]] and r["basis"]
    ph = c.call("GET", "/api/sample-photo")
    p = c.call("POST", "/api/assess", {"fac": "종합체육센터", "work": "조명 교체", "text": "사다리 작업", "photos": [{"name": ph["name"], "b64": ph["b64"]}]})
    yield "사진 첨부(모델 없이 첨부만)", len(p["photos"]) == 1 and c.call("GET", f"/api/photo/{p['photos'][0]}", raw=True)[:4] == b"\x89PNG"
    s0 = c.call("GET", "/api/state")
    pt = s0["periodic"]
    lamp = next(t for t in pt["tasks"] if "조명" in t["work"] and t["fac"] == "종합체육센터")
    yield f"정기 평가 대상 작업 현황({pt['year']}년, 규정 {pt['basis']['basis']['label'] if pt['basis']['basis'] else '-'})", len(pt["tasks"]) == 9 and lamp["aid"] and pt["basis"]["basis"]
    st = c.call("POST", "/api/assess", {"fac": "문화예술회관", "work": "공연 무대 장치·조명 설치", "text": "무대 위 높이 7m 트러스에 조명기 12대를 매다는 작업. 3명이 작업, 관람객 없음"})
    yield "높이 작업인데 떨어짐을 못 찾으면 질문", not any(i["code"] == "H01" for i in st["items"]) and any("7m" in x for x in st["questions"]) and not st["conditions"].get("open")
    yield "설명에 없는 낱말은 보태지 않음", c.status("POST", f"/api/assess/{st['id']}/add", {"code": "H01", "word": "비계다리"}) == 400
    st2 = c.call("POST", f"/api/assess/{st['id']}/add", {"code": "H01", "word": "트러스"})
    h = next(i for i in st2["items"] if i["code"] == "H01")
    yield "위험요인 추가 + 낱말 보태기(높이 7m → 중대성 3)", h["quote"] and h["S"] == 3
    nx = c.call("POST", "/api/assess", {"fac": "문화예술회관", "work": "무대 조명 철거", "text": "트러스에 달린 조명기 내리기"})
    yield "다음 평가부터 보탠 낱말로 자동으로 찾음", any(i["code"] == "H01" and i["by"] == "낱말" and i["word"] == "트러스" for i in nx["items"])
    d = c.call("POST", f"/api/assess/{st['id']}/xlsx", {}, raw=True)
    d2 = c.call("POST", "/api/ledger-xlsx", {}, raw=True)
    yield "엑셀(평가표·평가 대장)", d[:2] == b"PK" and d2[:2] == b"PK"
    s1 = c.call("POST", "/api/learned/remove", {"code": "H01", "word": "트러스"})
    yield "보탠 낱말 빼기", not s1["learned"] and "트러스" not in next(x for x in s1["hazards"] if x["code"] == "H01")["words"]
    yield "사진 경로 제한", c.status("GET", "/api/photo/..%2F..%2Fconfig.json") == 404
    yield "사진 형식 제한", c.status("POST", "/api/assess", {"work": "x", "photos": [{"name": "a.exe", "b64": "AA=="}]}) == 400
    ab = c.call("GET", "/api/about")
    yield "서비스 구조·검증(처리 단계·안전장치·성적표)", len(ab["pipeline"]) >= 5 and len(ab["guards"]) >= 5 and ab["scorecard"] and ab["scorecard"]["areas"]
    pi = c.call("POST", "/api/incidents", {"fac": "본부 청사", "work": "분전반 점검", "text": "담당 홍길동 010-1234-5678, 차단기 감전 위험", "result": "다침 없음"})
    yield "아차사고의 개인정보 가림", pi["masked"] == ["휴대전화"] and "010-1234" not in pi["incident"]["text"]
    yield "다른 사이트 요청 차단", c.status("POST", "/api/assess", {"work": "x"}, {"Origin": "http://evil.example"}) == 403
    w = c.call("GET", "/api/feeds/weather")
    yield f"기상청 날씨(키 없음 → 예시 자료, 체감온도 {w['feel']}℃·특보 {len(w['active'])}건)", not w["live"] and w["feel"] == 33.6 and len(w["active"]) == 2
    rf = c.call("POST", "/api/assess", {"fac": "본부 청사", "work": "옥상 냉각탑 점검·청소", "text": "옥상 냉각탑 위 높이 3m 사다리 작업, 2명이 작업", "use_weather": True})
    yield f"실외 높은 곳 + 강풍특보 → 작업 중지 {rf['stats']['weather_stops']}", rf["stats"]["weather_stops"] and not rf["stats"]["ready"] and rf["conditions"]["temp"] == 33.6
    a4 = c.call("POST", f"/api/assess/{a['id']}/weather", {})
    yield "실내 작업은 강풍특보로 막지 않음", not a4["stats"]["weather_stops"] and a4["stats"]["ready"]
    m = c.call("GET", "/api/feeds/messages")
    yield f"긴급재난문자(예시 {len(m['items'])}건, 겹치는 평가 {sum(len(x['hits']) for x in m['items'])}건)", not m["live"] and any(x["hits"] for x in m["items"])
    ap = c.call("POST", "/api/feeds/messages/apply", {})
    ap2 = c.call("POST", "/api/feeds/messages/apply", {})
    rf2 = c.call("GET", f"/api/assess/{rf['id']}")
    yield f"재난문자 → 수시평가 필요 {ap['added']}건(두 번 눌러도 한 번만)", ap["added"] > 0 and ap2["added"] == 0 and any(r.get("kind") == "재난문자" for r in rf2["reassess"])
    t2 = c.call("GET", f"/api/assess/{rf['id']}/tbm")["lines"]
    yield "TBM에 날씨·작업 중지·재난문자", any("체감온도" in x for x in t2) and any("특보가 풀린 뒤" in x for x in t2) and any("재난문자" in x for x in t2)
    yield "원본 보호(sample_data 파일 수 그대로)", sum(1 for x in (ROOT / "sample_data").rglob("*") if x.is_file()) == 5
    # 규칙 기반(모델 없음)에서도 새 기능이 동작
    br = c.call("GET", "/api/briefing")
    lv = {r["id"]: r for r in br["rows"]}
    yield f"오늘 작업 브리핑: 실외 높은 곳 작업은 강풍특보로 '작업 중지'", lv.get(rf["id"], {}).get("label") == "작업 중지" and "작업 중지" in br["rule"]
    q1 = c.call("POST", "/api/ask", {"q": "사다리 작업 안전 기준은?"})
    yield "물어보기(규칙): 사다리 → 떨어짐 감소대책·규정 근거", q1["mode"] == "규칙 기반" and any("떨어짐" in f for f in q1["facts"]) and q1["sources"]
    pv = c.call("GET", f"/api/assess/{a['id']}/preview")["blocks"]
    edited = [list(b) for b in pv] + [["image", __import__("base64").b64encode((ROOT / "sample_data/사진/조명교체_사다리.png").read_bytes()).decode(), "현장 사진"]]
    edited[0][1] = "위험성평가표(화면에서 고침)"
    hw = c.call("POST", f"/api/assess/{a['id']}/export?fmt=hwpx", {"blocks": edited}, raw=True)
    import io, zipfile
    z = zipfile.ZipFile(io.BytesIO(hw))
    yield "평가표 미리보기에서 고친 내용·사진으로 한글 내려받기", "화면에서 고침" in z.read("Contents/section0.xml").decode() and any(n.startswith("BinData/") for n in z.namelist())


def fake_llm():
    """OpenAI 호환 모델 서버 흉내(업스테이지 솔라 등). 사실 첫 줄로 답하고, 질문에 '거짓'이 있으면 사실에 없는 숫자·코드를 지어낸다."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            H.seen.append((self.headers.get("Authorization"), body))
            msgs = body["messages"]
            last = msgs[-1]["content"]
            last = last if isinstance(last, str) else " ".join(x.get("text", "") for x in last if isinstance(x, dict))
            facts = [x[2:] for x in last.splitlines() if x.startswith("- ")]
            sysmsg = msgs[0]["content"] if msgs[0]["role"] == "system" and isinstance(msgs[0]["content"], str) else ""
            if "JSON" in sysmsg or "JSON" in last:
                text = '{"hazards": []}'
            elif "거짓" in last:
                text = "H99 위험이 있고 추락 높이는 37m입니다."
            elif "종합 의견" in sysmsg or "TBM" in sysmsg:
                text = "\n".join(f"- {f}" for f in facts[:3])
            elif "다듬어" in sysmsg:
                text = facts[0] if facts else ""
            else:
                text = f"<think>생각</think>정리하면 {facts[0] if facts else ''}"
            out = {"choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}]}
            b = json.dumps(out, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b)

        def log_message(self, *a):
            pass

    H.seen = []
    s = HTTPServer(("127.0.0.1", 0), H)
    s.seen = H.seen
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


def ai_checks(c, fl):
    yield "모델 연결 표시 openai:solar-pro4", c.call("GET", "/api/info")["llm"] == "openai:solar-pro4"
    a = c.call("POST", "/api/assess", {"fac": "종합체육센터", "dept": "체육사업팀", "work": "체육관 천장 조명(등기구) 교체",
                                       "text": "이동식 일자 사다리로 높이 4m 등기구 안정기 교체. 혼자 작업, 바닥 왁스 청소 직후"})
    yield "모델 연결 상태에서 평가 만들기(모델 제안 없음 → 규칙 결과 유지)", {"H01", "H02", "H03"} <= {i["code"] for i in a["items"]}
    yield "모델 서버에 키를 Authorization 으로 보냄", fl.seen[-1][0] == "Bearer test-llm-key" and fl.seen[-1][1]["model"] == "solar-pro4"
    r1 = c.call("POST", "/api/ask", {"q": "사다리 작업 안전 기준은?"})
    yield "물어보기: 모델 답(생각 과정 지움, 사실 대조 통과)", "모델" in r1["mode"] and r1["answer"].startswith("정리하면")
    r2 = c.call("POST", "/api/ask", {"q": "그럼 2m 넘으면?", "history": [{"q": "사다리 작업 안전 기준은?", "a": r1["answer"]}]})
    sent = fl.seen[-1][1]["messages"]
    yield f"이어 묻기: 앞 질문의 '{r2['carried']}' 이어받고 앞 대화 전달", r2["carried"] and any("높이" in f or "떨어짐" in f for f in r2["facts"]) and len(sent) == 4
    r3 = c.call("POST", "/api/ask", {"q": "거짓말로 위험 알려줘"})
    yield "모델이 사실에 없는 숫자·코드(37, H99)를 쓰면 버림", r3["mode"] == "규칙 기반" and "H99" in r3["dropped"]
    code = a["items"][0]["code"]
    ex = c.call("POST", f"/api/assess/{a['id']}/explain", {"code": code})
    yield f"위험요인 {code} AI 해설", "모델" in ex["mode"]
    op = c.call("POST", f"/api/assess/{a['id']}/opinion")
    yield f"AI 종합 의견 {len(op['lines'])}개 항목", "모델" in op["mode"] and len(op["lines"]) == 3
    tb = c.call("POST", f"/api/assess/{a['id']}/tbm/ai")
    yield "AI TBM 낭독 문안", "모델" in tb["mode"] and tb["lines"]
    po = c.call("POST", "/api/report/polish", {"text": "사다리 높이 4m 작업은 안전대를 착용함."})
    yield "평가표 문단 AI 다듬기(숫자 유지)", "모델" in po["mode"] and "4m" in po["text"]
    bi = c.call("POST", "/api/briefing/ai")
    yield "AI 오늘 작업 브리핑(사실 대조 통과)", "모델" in bi["mode"] and c.call("GET", "/api/briefing")["ai"]["text"] == bi["text"]


def main():
    tmp = tempfile.mkdtemp(prefix="smoke-safety-")
    port = free_port()
    env = dict(os.environ, APP_DATA_DIR=tmp, LLM_PROVIDER="none")
    env.pop("DATA_GO_KR_KEY", None)
    env.pop("SAFETYDATA_KEY", None)
    proc = subprocess.Popen([sys.executable, "run.py", "--no-browser", "--port", str(port)], cwd=ROOT, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    total = failed = 0
    try:
        c = Client(port)
        for _ in range(60):
            try:
                c.call("GET", "/api/info")
                break
            except Exception:
                time.sleep(0.3)
        print(f"[현장 위험성평가 AI] http://127.0.0.1:{port}")
        for label, ok in checks(c):
            total += 1
            failed += 0 if ok else 1
            print(f"  {'통과' if ok else '실패'}  {label}")
        fl = fake_llm()
        tmp2 = tempfile.mkdtemp(prefix="smoke-safety-ai-")
        env2 = dict(env, APP_DATA_DIR=tmp2, LLM_PROVIDER="openai", LLM_BASE_URL=f"http://127.0.0.1:{fl.server_port}/v1",
                    LLM_MODEL="solar-pro4", LLM_API_KEY="test-llm-key")
        port2 = free_port()
        proc2 = subprocess.Popen([sys.executable, "run.py", "--no-browser", "--port", str(port2)], cwd=ROOT, env=env2,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        try:
            c2 = Client(port2)
            for _ in range(60):
                try:
                    c2.call("GET", "/api/info")
                    break
                except Exception:
                    time.sleep(0.3)
            for label, ok in ai_checks(c2, fl):
                total += 1
                failed += 0 if ok else 1
                print(f"  {'통과' if ok else '실패'}  {label}")
        finally:
            proc2.terminate()
            shutil.rmtree(tmp2, ignore_errors=True)
    except Exception as e:
        total += 1
        failed += 1
        print(f"  실패  {type(e).__name__}: {e}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n결과: {total - failed}/{total} 통과")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
