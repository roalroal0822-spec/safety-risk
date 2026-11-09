"""시연영상 값 검증: 새 작업 폴더에서 시연용 모의자료로 앱을 띄워, 영상에 나오는 숫자·판정이 그대로 나오는지 확인한다.

실행: python tools/check_demo.py   (모델·인터넷·외부 키 없이, 결과는 검증결과/시연값_검증.md)
두 번 새로 띄워 두 번 모두 같은 값이 나오는지도 본다. 처리 시간(ms)은 PC마다 달라 여기서 보지 않는다(tools/measure.py).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from smoke_test import Client, free_port  # noqa: E402

WORK = {"fac": "종합체육센터", "dept": "체육사업팀", "work": "체육관 천장 조명(등기구) 교체",
        "text": "이동식 일자 사다리로 높이 4m 등기구 안정기 교체. 혼자 작업, 바닥 왁스 청소 직후", "use_weather": True}


def run_once():
    tmp = tempfile.mkdtemp(prefix="demo-check-")
    port = free_port()
    env = dict(os.environ, APP_DATA_DIR=tmp, LLM_PROVIDER="none")
    for k in ("DATA_GO_KR_KEY", "SAFETYDATA_KEY", "KMA_APIHUB_KEY", "LAW_OC"):
        env.pop(k, None)
    proc = subprocess.Popen([sys.executable, "run.py", "--no-browser", "--port", str(port)], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    got = []
    try:
        c = Client(port)
        for _ in range(100):
            try:
                c.call("GET", "/api/info")
                break
            except Exception:
                time.sleep(0.2)
        w = c.call("GET", "/api/feeds/weather")
        got.append(("1. 새 위험성평가 · 기상청", "체감온도(예시 자료)", "33.6℃", f"{w['feel']:g}℃"))
        got.append(("1. 새 위험성평가 · 기상청", "발표 중인 특보(예시 자료)", "폭염경보, 강풍주의보", ", ".join(x["kind"] + x["level"] for x in w["active"])))
        mt = c.call("POST", "/api/catalog/match", {"work": WORK["work"], "text": WORK["text"]})
        main = next(w for w in mt["works"] if w["primary"])
        got.append(("새 기능 · 작업 고르기", "설명으로 미리 고른 작업·단계", "조명(등기구) 교체 · 4단계", f"{main['work']} · {len(main['steps'])}단계"))
        a = c.call("POST", "/api/assess", dict(WORK, steps=main["steps"]))
        by = {i["code"]: i for i in a["items"]}
        tb = c.call("GET", f"/api/assess/{a['id']}/tbm")["sheet"]
        got.append(("새 기능 · TBM 일지", "오늘 작업 단계·위험요인 줄", "4단계·5줄", f"{len(tb['steps'])}단계·{len(tb['rows'])}줄"))
        got.append(("2. 위험성평가", "찾은 위험요인", "5개", f"{len(a['items'])}개"))
        got.append(("2. 위험성평가", "판정", "작업 전 조치 필요", "작업 시작 가능" if a["stats"]["ready"] else "작업 전 조치 필요"))
        got.append(("3. 판단 이유", "떨어짐 위험성(가능성×중대성)", "3×3=9", f"{by['H01']['L']}×{by['H01']['S']}={by['H01']['R']}"))
        got.append(("3. 판단 이유", "떨어짐 판단 이유(높이·혼자·젖은 바닥·아차사고)", "4건", f"{len(by['H01']['reasons'])}건"))
        got.append(("3. 판단 이유", "판단 이유가 원본 기록(파일·행)으로 이어짐", "있음", "있음" if any(r.get("src") for r in by["H01"]["reasons"]) else "없음"))
        lw = c.call("GET", "/api/laws/H01")
        got.append(("새 기능 · 법령 근거", "인증값 없을 때 조문을 지어내지 않고 링크만", "원문 0건·링크 있음", f"원문 {len(lw['items'])}건·링크 {'있음' if lw['refs'] else '없음'}"))
        q = c.call("POST", "/api/ask", {"q": "사다리 작업 안전 기준은?"})
        got.append(("새 기능 · 물어보기", "사다리 질문 근거 건수", "규정 1·위험요인 1·아차사고 1", "규정 {기관 규정}·위험요인 {위험요인 목록}·아차사고 {아차사고}".format(**{k: q["grounds"].get(k, 0) for k in ("기관 규정", "위험요인 목록", "아차사고")})))
        q2 = c.call("POST", "/api/ask", {"q": "점심 메뉴 추천해줘", "history": [{"q": "사다리 작업 안전 기준은?", "a": q["answer"]}]})
        got.append(("새 기능 · 물어보기", "근거 없는 질문", "답하지 않음", "답하지 않음" if not q2["grounded"] else "답함"))
        r = c.call("POST", "/api/incidents", {"fac": "종합체육센터", "work": "체육관 천장 조명 교체", "text": "사다리 위에서 안정기를 떼다 손에 전기가 찌릿함. 차단기를 내리지 않은 회로였음"})
        got.append(("4. 아차사고", "같은 작업 평가에 수시평가 필요", "1건", f"{len(r['hits'])}건"))
        iid = r["incident"]["id"]
        v = c.call("GET", f"/api/incidents/{iid}")
        got.append(("아차사고 조치·결과보고", "분류한 위험요인", "떨어짐, 감전", ", ".join(h["name"].split()[-1] for h in v["hazards"])))
        pv = c.call("GET", f"/api/incidents/{iid}/preview")["blocks"]
        got.append(("아차사고 조치·결과보고", "산업재해조사표 대체 아님 안내", "있음", "있음" if any("산업재해조사표" in str(b[1]) for b in pv) else "없음"))
        import base64
        pic = (ROOT / "sample_data" / "사진" / "수영장_풀사이드.jpg").read_bytes()
        rp = c.call("POST", "/api/reports", {"photo": {"name": "수영장_풀사이드.jpg", "b64": base64.b64encode(pic).decode()},
                                             "text": "풀사이드 배수구 주변 물이 고여 미끄러움. 청소 호스가 바닥에 둔 채 있음"})
        got.append(("새 기능 · 사진 제보", "사진 위치로 찾은 시설·촬영 시각", "종합체육센터 · 2026-11-09 07:42", f"{rp['fac']} · {rp['shot']}"))
        got.append(("새 기능 · 사진 제보", "위험요인 후보(사진 속 이용객 포함)", "미끄러운 바닥, 이용객 부상, 걸려 넘어짐", ", ".join({"H02": "미끄러운 바닥", "H12": "이용객 부상", "H13": "걸려 넘어짐"}.get(h["code"], h["code"]) for h in rp["hazards"])))
        ap = c.call("GET", f"/api/assess/{a['id']}")["approval"]
        got.append(("새 기능 · 결재(영상 미수록)", "조명 교체 결재선(전기설비 담당)", "작성 김도현 → 검토 오세린 → 합의 강태윤 → 승인 서경민",
                    " → ".join(f"{x['step']} {x['name']}" for x in ap["line"])))
        vd = c.call("POST", "/api/vendors/sample")
        got.append(("새 기능 · 협력업체 DB(영상 미수록)", "시연 보고서 3개에서 읽은 업체·작업", "7곳·11건", f"{vd['total']['vendors']}곳·{vd['total']['jobs']}건"))
        got.append(("새 기능 · 협력업체 DB(영상 미수록)", "위험 작업이 있는 업체(협의 대상)", "7곳", f"{vd['total']['risky']}곳"))
        py = c.call("GET", "/api/performance?unit=year&anchor=2026-11-09")
        led = c.call("POST", "/api/activities/sample")["added"][0]["rows"]
        got.append(("새 기능 · 안전 성과(영상 미수록)", "시연 실적 대장에서 가져온 활동", "260건", f"{led}건"))
        got.append(("새 기능 · 안전 성과(영상 미수록)", "2026년 아차사고 등록(모의 4건 + 시연 1건)", "5건", f"{py['by_kind']['아차사고 등록']}건"))
        m = c.call("GET", "/api/feeds/messages")
        got.append(("5. 긴급재난문자", "재난문자(예시 자료)", "2건", f"{len(m['items'])}건"))
        br = c.call("GET", "/api/briefing")
        row = next(x for x in br["rows"] if x["work"] == WORK["work"])
        got.append(("오늘 작업 브리핑", "조명 교체 작업 판정", "시작 전 조치", row["label"]))
        sc = json.loads((ROOT / "검증결과" / "scorecard.json").read_text(encoding="utf-8"))
        b = next(x for x in sc["areas"] if x["name"] == "위험요인 찾기(개선에 쓰지 않은 문항)")
        got.append(("끝 화면", "위험요인 찾기(보지 않은 문항)", "27/30", f"{b['passed']}/{b['total']}"))
    finally:
        proc.terminate()
        shutil.rmtree(tmp, ignore_errors=True)
    return got


def main():
    subprocess.run([sys.executable, "tools/eval.py"], cwd=ROOT, stdout=subprocess.DEVNULL, check=True)
    r1, r2 = run_once(), run_once()
    ok = sum(1 for g in r1 if g[2] == g[3])
    same = all(a[3] == b[3] for a, b in zip(r1, r2))
    rows = "\n".join(f"| {s} | {n} | {e} | {g} | {'일치' if e == g else '**다름**'} |" for s, n, e, g in r1)
    md = f"""# 무사히 시연영상 값 검증

- 측정일: {date.today().isoformat()} · 재현: `python tools/check_demo.py` (모델·인터넷·외부 키 불필요)
- 방법: 빈 작업 폴더에서 시연용 모의자료로 앱을 새로 띄워, 영상과 같은 순서로 화면과 같은 API를 불러 영상에 나오는 값과 비교. 두 번 새로 띄워 같은 값이 나오는지도 확인.
- 결과: **{ok}/{len(r1)} 일치**, 두 번 실행 결과 {'같음' if same else '**다름**'}

| 영상 장면 | 항목 | 영상에 나온 값 | 다시 돌린 값 | 비교 |
|---|---|---|---|---|
{rows}

- 날씨·재난문자는 이 영상이 외부 키 없이 찍혀 '예시 자료'입니다. 키를 넣으면 기상청·행정안전부의 실시간 값으로 바뀌므로 이 표의 날씨 값과 달라집니다.
- 처리 시간(평가 1건 ms, 한글 평가표 초)은 PC마다 다르므로 `python tools/measure.py`(검증결과/실측.md)로 따로 잽니다.
"""
    (ROOT / "검증결과" / "시연값_검증.md").write_text(md, encoding="utf-8")
    print(md)
    sys.exit(0 if ok == len(r1) and same else 1)


if __name__ == "__main__":
    main()
