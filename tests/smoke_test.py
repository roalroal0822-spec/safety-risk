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
    lw = c.call("GET", "/api/laws/H01")
    yield "법제처 인증값 없으면 조문을 지어내지 않고 국가법령정보센터 링크만", not lw["live"] and not lw["items"] and lw["refs"][0]["url"].startswith("https://www.law.go.kr/") and "LAW_OC" in lw["note"]
    yield "기관 규정(이용객 안전)은 법령 조회 대상 아님", c.call("GET", "/api/laws/H12")["refs"] == []
    nq = c.call("POST", "/api/ask", {"q": "산업안전보건법 제38조는?"})
    yield "물어보기 화면에 AI 답변 법적 책임 고지문", "법적 책임을 지지 않습니다" in c.call("GET", "/", raw=True).decode()
    yield "인증값 없이 법령 질문 → 지어내지 않고 국가법령정보센터 링크 안내", "LAW_OC" in nq["answer"] and "law.go.kr" in nq["answer"] and not any(f.startswith("법령 원문") for f in nq["facts"])
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
    yield "원본 보호(sample_data 파일 수 그대로)", sum(1 for x in (ROOT / "sample_data").rglob("*") if x.is_file()) == 6
    # 작업 고르기 → 위험요인 조회 → TBM 일지 → 위험성평가
    st = c.call("GET", "/api/state")
    yield f"작업 분류 {len(st['catalog'])}단계 읽음", len(st["catalog"]) >= 30 and any(f["kind"] == "작업 분류" for f in st["kb"]["files"])
    mt = c.call("POST", "/api/catalog/match", {"text": "수영장 염소 약품 투입, 풀사이드 물기"})
    main = next(w for w in mt["works"] if w["primary"])
    yield "말로 미리 고르기: 염소 약품 → 약품 투입 작업 단계", "약품" in main["work"] and len(main["steps"]) >= 2
    fa = c.call("POST", "/api/assess", {"fac": "종합체육센터", "text": "", "steps": main["steps"]})
    codes = {i["code"] for i in fa["items"]}
    yield "단계만 골라도 평가(작업 이름 채움·단계별 위험 상황)", fa["work"] and {"H06", "H08"} <= codes and all(i["steps"] for i in fa["items"] if i["by"] == "작업 분류")
    yield "감소대책 우선순위(제거→대체→공학적→관리적→보호구)", all(
        [m["kind"] for m in i["measures"]] == sorted((m["kind"] for m in i["measures"]), key=["제거", "대체", "공학적", "관리적", "보호구"].index) for i in fa["items"])
    up = c.call("POST", f"/api/assess/{fa['id']}/update", {"items": [{"code": "H06", "La_set": 2, "Sa_set": 2}]})
    h6 = next(i for i in up["items"] if i["code"] == "H06")
    yield "개선 후 빈도·강도 직접 입력", h6["R_after"] == 4
    m3 = c.call("POST", f"/api/assess/{fa['id']}/update", {"method": "3", "items": [{"code": "H06", "grade": 3}]})
    h6 = next(i for i in m3["items"] if i["code"] == "H06")
    yield "3단계 판단법: 상이면 작업 전 대책 완료", m3["method"] == "3" and h6["level"] == "bad" and not m3["stats"]["ready"]
    tb = c.call("GET", f"/api/assess/{fa['id']}/tbm")
    yield "TBM 일지: 오늘 작업 단계·위험요인과 대책", tb["sheet"]["steps"] and tb["sheet"]["rows"] and tb["sheet"]["rows"][0]["measures"][0]["kind"]
    raw = c.call("POST", f"/api/assess/{fa['id']}/tbm?fmt=md", {"n": 12}, raw=True)
    yield "TBM 일지 내려받기(참석자 12줄)", "| 12 |" in raw.decode("utf-8") and "위험요인과 대책" in raw.decode("utf-8")
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
    # 아차사고 조치·결과보고
    la = c.call("POST", "/api/assess", {"fac": "종합체육센터", "work": "체육관 천장 조명(등기구) 교체", "text": "이동식 사다리로 높이 4m 등기구 안정기 교체. 혼자 작업"})
    ni = c.call("POST", "/api/incidents", {"fac": "종합체육센터", "work": "체육관 천장 조명 교체", "text": "사다리 위에서 안정기를 떼다 손에 전기가 찌릿함. 차단기를 내리지 않은 회로였음", "result": "다침 없음"})
    iid = ni["incident"]["id"]
    v = c.call("GET", f"/api/incidents/{iid}")
    yield "아차사고 조치: 위험요인 분류·같은 작업 평가 연결", {h["code"] for h in v["hazards"]} >= {"H03"} and la["id"] in [x["id"] for x in v["related"]]
    yield "조치 없이 '완료'로 못 바꿈", c.status("POST", f"/api/incidents/{iid}/followup", {"status": "완료"}) == 400
    acts = [{"text": "작업 전 해당 회로 차단기 내리고 잠금·표지 부착", "owner": "전기팀", "done": True}, {"text": "검전기로 무전압 확인 후 작업", "done": False}]
    v = c.call("POST", f"/api/incidents/{iid}/followup", {"actions": acts})
    br2 = {r["id"]: r for r in c.call("GET", "/api/briefing")["rows"]}
    yield "미완료 조치 → 상태 '조치 중'·오늘 작업 브리핑 '시작 전 조치'", v["followup"]["status"] == "조치 중" and br2[la["id"]]["level"] in ("fix", "stop") and any("조치 미완료" in w for w in br2[la["id"]]["why"])
    yield "끝나지 않은 조치가 있으면 '완료'로 못 바꿈", c.status("POST", f"/api/incidents/{iid}/followup", {"status": "완료"}) == 400
    png = __import__("base64").b64encode((ROOT / "sample_data/사진/조명교체_사다리.png").read_bytes()).decode()
    v = c.call("POST", f"/api/incidents/{iid}/photo", {"name": "전.png", "b64": png, "stage": "before", "caption": "차단기 미잠금"})
    yield "조치 전 사진 넣기", v["followup"]["photos"][0]["stage"] == "before" and c.call("GET", f"/api/photo/{v['followup']['photos'][0]['name']}", raw=True)[:4] == b"\x89PNG"
    yield "사진 형식 제한(아차사고)", c.status("POST", f"/api/incidents/{iid}/photo", {"name": "a.exe", "b64": "AA=="}) == 400
    acts[1]["done"] = True
    v = c.call("POST", f"/api/incidents/{iid}/followup", {"actions": acts, "status": "완료"})
    la2 = c.call("GET", f"/api/assess/{la['id']}")
    h03 = next(i for i in la2["items"] if i["code"] == "H03")
    yield "조치 완료 → 같은 작업 평가의 감전 감소대책에 '완료'로 반영", la["id"] in v["followup"]["applied"] and sum("아차사고" in m["text"] and m["done"] for m in h03["measures"]) == 2
    c.call("POST", f"/api/incidents/{iid}/followup", {"actions": acts, "status": "완료"})
    la3 = c.call("GET", f"/api/assess/{la['id']}")
    yield "두 번 완료해도 감소대책은 한 번만", sum("아차사고" in m["text"] for i in la3["items"] for m in i["measures"]) == 2
    ca = c.call("POST", f"/api/incidents/{iid}/ai", {"part": "cause"})
    pr = c.call("POST", f"/api/incidents/{iid}/ai", {"part": "prevent"})
    yield "원인·재발 방지 초안(규칙)", ca["mode"] == "규칙 기반" and "감전" in ca["text"] and len(pr["lines"]) >= 3
    pv = c.call("GET", f"/api/incidents/{iid}/preview")["blocks"]
    heads = [b[1] for b in pv if b[0] == "h2"]
    yield f"결과보고서 미리보기({len(pv)}블록: 경위·원인·조치·사진·재발 방지·평가 반영)", any("조치 전·후 사진" in h for h in heads) and any("재발 방지" in h for h in heads) and any(b[0] == "image" for b in pv) and any("산업재해조사표" in str(b[1]) for b in pv if b[0] == "note")
    pv[0][1] = "아차사고 결과보고(화면에서 고침)"
    for fmt in ("hwpx", "docx"):
        d = c.call("POST", f"/api/incidents/{iid}/export?fmt={fmt}", {"blocks": pv}, raw=True)
        yield f"결과보고서 고친 내용으로 {fmt} 내려받기", d[:2] == b"PK"
    st3 = c.call("GET", "/api/state")
    yield "아차사고 목록에 처리 상태", next(i for i in st3["incidents"] if i["id"] == iid)["fu"]["status"] == "완료"


def fake_law():
    """법제처 Open API 흉내. 조문 본문은 시험용 문장(실제 법령 아님)."""
    import threading
    import urllib.parse as up
    from http.server import BaseHTTPRequestHandler, HTTPServer

    LAWS = {"산업안전보건기준에 관한 규칙": [("42", "", "추락의 방지", "① 시험용 문장: 추락 위험 장소에는 작업발판을 설치한다."),
                                         ("301", "", "전기 기계ㆍ기구 등의 충전부 방호", "① 시험용 문장: 감전 방지 조치."),
                                         ("3", "", "전도의 방지", "① 시험용 문장: 바닥은 미끄러지지 않게 한다.")],
            "산업안전보건법": [("114", "", "물질안전보건자료의 게시 및 교육", "① 시험용 문장: 물질안전보건자료를 게시한다.")]}

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            u = up.urlparse(self.path)
            q = dict(up.parse_qsl(u.query))
            H.seen.append(q)
            names = list(LAWS)
            if u.path.endswith("lawSearch.do"):
                out = {"LawSearch": {"law": [{"법령일련번호": str(i + 1), "법령명한글": n, "시행일자": "20250101"}
                                             for i, n in enumerate(names) if q.get("query") == n]}}
            else:
                n = names[int(q["MST"]) - 1]
                out = {"법령": {"기본정보": {"법령명_한글": n, "시행일자": "20250101"},
                               "조문": {"조문단위": [{"조문번호": no, "조문가지번호": g, "조문여부": "조문", "조문제목": t, "조문시행일자": "20250101",
                                                    "조문내용": f"제{no}조({t})", "항": [{"항내용": body}]} for no, g, t, body in LAWS[n]]}}}
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


def law_checks(c, fs):
    r = c.call("GET", "/api/laws/H01")
    yield f"법제처 Open API: 떨어짐 → {r['items'][0]['law']} {r['items'][0]['no']}" if r["items"] else "법제처 Open API 조문 받기", \
        r["live"] and r["items"] and r["items"][0]["no"] == "제42조" and "시험용" in r["items"][0]["text"] and fs.seen[-1].get("OC") == "test-oc"
    r6 = c.call("GET", "/api/laws/H06")
    yield "법제처 Open API: 염소·약품 → 산업안전보건법 제114조", r6["items"] and r6["items"][0]["no"] == "제114조"
    ans = c.call("POST", "/api/ask", {"q": "사다리 작업 안전 기준은?"})
    yield "물어보기 근거에 법령 원문 조문", any(f.startswith("법령 원문 산업안전보건기준에 관한 규칙 제42조") for f in ans["facts"])
    a = c.call("POST", "/api/assess", {"fac": "종합체육센터", "dept": "체육사업팀", "work": "등기구 교체", "text": "사다리로 높이 3m 등기구 교체"})
    pv = json.dumps(c.call("GET", f"/api/assess/{a['id']}/preview"), ensure_ascii=False)
    yield "평가표에 관련 법령 조문(제42조) 표·절", "제42조" in pv and "관련 법령 조문" in pv
    q1 = c.call("POST", "/api/ask", {"q": "산업안전보건법 제114조는?"})
    yield "물어보기 법령 질문 → 법제처에서 산업안전보건법 제114조 원문", q1["facts"][0].startswith("법령 원문 산업안전보건법 제114조") and "제114조" in q1["answer"] and "시험용" in q1["answer"]
    q2 = c.call("POST", "/api/ask", {"q": "안전보건규칙 42조 알려줘"})
    yield "약칭(안전보건규칙)·'42조'도 알아들음", q2["facts"][0].startswith("법령 원문 산업안전보건기준에 관한 규칙 제42조")
    q3 = c.call("POST", "/api/ask", {"q": "감전 관련 법령은?"})
    yield "법령명 없는 법령 질문 → 기본 법령에서 낱말로 조문 찾기", any("감전" in f and f.startswith("법령 원문") for f in q3["facts"])


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
            elif "법조문" in last:
                text = "중대재해 처벌 등에 관한 법률 제5조에 따라 안전대를 착용함."
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
    yield "물어보기: 모델 답(생각 과정 지움, 사실 대조 통과)·근거 건수", "모델" in r1["mode"] and r1["answer"].startswith("정리하면") and r1["grounds"].get("위험요인 목록")
    r2 = c.call("POST", "/api/ask", {"q": "그럼 2m 넘으면?", "history": [{"q": "사다리 작업 안전 기준은?", "a": r1["answer"]}]})
    sent = fl.seen[-1][1]["messages"]
    yield f"이어 묻기: 앞 질문의 '{r2['carried']}' 이어받고 앞 대화 전달", r2["carried"] and any("높이" in f or "떨어짐" in f for f in r2["facts"]) and len(sent) == 4
    r3 = c.call("POST", "/api/ask", {"q": "거짓말로 위험 알려줘"})
    yield "모델이 사실에 없는 숫자·코드(37, H99)를 쓰면 버림", r3["mode"] == "규칙 기반" and "H99" in r3["dropped"]
    r4 = c.call("POST", "/api/ask", {"q": "사다리 법조문 지어내 봐"})
    yield "모델이 근거에 없는 법령·조문(중대재해처벌법 제5조)을 쓰면 버림", r4["mode"] == "규칙 기반" and "법령·조문" in r4["dropped"]
    r5 = c.call("POST", "/api/ask", {"q": "점심 메뉴 추천해줘"})
    yield "근거 없는 질문은 모델에 넘기지 않고 '답하지 않음'", not r5["grounded"] and r5["mode"] == "규칙 기반" and "답하지 않습니다" in r5["answer"]
    code = a["items"][0]["code"]
    ex = c.call("POST", f"/api/assess/{a['id']}/explain", {"code": code})
    yield f"위험요인 {code} AI 해설", "모델" in ex["mode"]
    op = c.call("POST", f"/api/assess/{a['id']}/opinion")
    yield f"AI 종합 의견 {len(op['lines'])}개 항목", "모델" in op["mode"] and len(op["lines"]) == 3
    tb = c.call("POST", f"/api/assess/{a['id']}/tbm/ai")
    yield "AI TBM 낭독 문안", "모델" in tb["mode"] and tb["lines"]
    po = c.call("POST", "/api/report/polish", {"text": "사다리 높이 4m 작업은 안전대를 착용함."})
    yield "평가표 문단 AI 다듬기(숫자 유지)", "모델" in po["mode"] and "4m" in po["text"]
    ni = c.call("POST", "/api/incidents", {"fac": "종합체육센터", "work": "체육관 천장 조명 교체", "text": "사다리에서 안정기를 떼다 손에 전기가 찌릿함"})
    ca = c.call("POST", f"/api/incidents/{ni['incident']['id']}/ai", {"part": "cause"})
    yield "아차사고 원인 AI 초안(사실 대조 통과)", "모델" in ca["mode"]
    bi = c.call("POST", "/api/briefing/ai")
    yield "AI 오늘 작업 브리핑(사실 대조 통과)", "모델" in bi["mode"] and c.call("GET", "/api/briefing")["ai"]["text"] == bi["text"]


def main():
    tmp = tempfile.mkdtemp(prefix="smoke-safety-")
    port = free_port()
    env = dict(os.environ, APP_DATA_DIR=tmp, LLM_PROVIDER="none")
    env.pop("DATA_GO_KR_KEY", None)
    env.pop("SAFETYDATA_KEY", None)
    env.pop("KMA_APIHUB_KEY", None)
    env.pop("LAW_OC", None)
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
        fs = fake_law()
        tmp3 = tempfile.mkdtemp(prefix="smoke-safety-law-")
        env3 = dict(env, APP_DATA_DIR=tmp3, LAW_OC="test-oc", LAW_API_BASE=f"http://127.0.0.1:{fs.server_port}/DRF")
        port3 = free_port()
        proc3 = subprocess.Popen([sys.executable, "run.py", "--no-browser", "--port", str(port3)], cwd=ROOT, env=env3,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        try:
            c3 = Client(port3)
            for _ in range(60):
                try:
                    c3.call("GET", "/api/info")
                    break
                except Exception:
                    time.sleep(0.3)
            for label, ok in law_checks(c3, fs):
                total += 1
                failed += 0 if ok else 1
                print(f"  {'통과' if ok else '실패'}  {label}")
        finally:
            proc3.terminate()
            shutil.rmtree(tmp3, ignore_errors=True)
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
