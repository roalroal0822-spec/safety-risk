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
