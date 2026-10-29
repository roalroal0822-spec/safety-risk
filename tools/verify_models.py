"""모델 교체 검증: 같은 기능을 여러 모델로 돌려 정상 동작하는지 확인하고 보고서를 남긴다.

예)
  python tools/verify_models.py --base-url http://localhost:11434/v1 --models gemma3:4b exaone3.5:2.4b
  python tools/verify_models.py --base-url https://.../v1 --models 모델A 모델B   (키는 환경변수 LLM_API_KEY)
  python tools/verify_models.py --mock      (가짜 모델 서버로 연결 경로만 시험)

결과: verify_report.md
'통과'는 오류 없이 응답했다는 뜻만이 아니라 결과가 모의자료의 정답과 맞는다는 뜻이다.
  - 설명 보조: 낱말 목록에 없는 '냉각탑 팬 날개' 작업에서 끼임(H04)을 찾고, 근거 문구가 설명에 실제로 있어야 통과
  - 사진 판독: 시연용 그림에서 떨어짐(H01)을 찾아야 통과. 사진을 받지 못하는 모델은 '지원 안 함'으로 따로 표시(실패로 세지 않음)
"""
import argparse
import base64
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def make_llm(provider, base, model):
    from core.llm import LLM
    return LLM({"provider": provider, "base_url": base, "model": model, "api_key_env": "LLM_API_KEY",
                "temperature": 0.1, "timeout": 300})


def checks(llm, kb):
    import assess
    res = []
    t = time.time()
    a = assess.make(kb, "본부 청사", "", "옥상 냉각탑 점검", "냉각탑 팬 날개 청소, 2인 1조", llm=llm)
    model_items = [i for i in a["items"] if i["by"] == "모델"]
    dropped = [n for n in a["notes"] if "제외" in n]
    if llm.cfg.get("model") == "mock-b":  # 근거 없는 제안을 일부러 섞는 가짜 모델: 앱이 모두 걸러 내면 통과
        ok, name = not model_items and len(dropped) >= 2, "설명 보조: 근거 없는 제안 차단"
    else:
        ok, name = any(i["code"] == "H04" for i in model_items), "설명 보조: 낱말로 못 찾는 위험요인(근거 문구 대조)"
    res.append((name, ok, time.time() - t,
                f"모델이 더한 위험요인 {[i['code'] for i in model_items]}, 걸러진 제안 {len(dropped)}개" + (f": {dropped[0]}" if dropped else "")))
    t = time.time()
    img = base64.b64encode((ROOT / "sample_data" / "사진" / "조명교체_사다리.png").read_bytes()).decode()
    a = assess.make(kb, "종합체육센터", "", "체육관 조명 교체", "등기구 교체", llm=llm, photos=[img], photo_names=["x.png"])
    failed = [n for n in a["notes"] if "사진을 읽지 못함" in n]
    if failed:
        res.append(("사진 판독(현장 확인 필요로 표시)", None, time.time() - t, failed[0][:90]))
    else:
        seen = [i["code"] for i in a["items"] if i.get("photo")]
        dropped = [n for n in a["notes"] if "제외" in n]
        res.append(("사진 판독(현장 확인 필요로 표시)", "H01" in seen, time.time() - t,
                    f"사진에서 본 위험요인 {seen}, 걸러진 제안 {len(dropped)}개"))
    return res


def main():
    ap = argparse.ArgumentParser(description="여러 모델로 주요 기능을 돌려 보는 검증 도구")
    ap.add_argument("--provider", default="openai", choices=["openai", "ollama"])
    ap.add_argument("--base-url", default="http://localhost:11434/v1")
    ap.add_argument("--models", nargs="+", default=[])
    ap.add_argument("--mock", action="store_true", help="가짜 모델 서버로 연결 경로만 시험")
    ap.add_argument("--out", default=str(ROOT / "verify_report.md"))
    a = ap.parse_args()
    proc = None
    if a.mock:
        port = 18080
        proc = subprocess.Popen([sys.executable, str(ROOT / "tools" / "mock_llm.py"), "--port", str(port)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.0)
        a.base_url, a.models = f"http://127.0.0.1:{port}/v1", ["mock-a", "mock-b"]
    if not a.models:
        ap.error("--models 로 시험할 모델 이름을 2개 이상 주세요 (또는 --mock)")
    from kb import KB
    kb = KB(ROOT / "sample_data").load()
    rows = []
    try:
        for m in a.models:
            llm = make_llm(a.provider, a.base_url, m)
            h = llm.health()
            rows.append((m, "연결 확인" + (f" [{h['family']}]" if h.get("family") else ""), h["ok"], h.get("seconds", 0), h.get("detail", "")))
            if not h["ok"]:
                continue
            try:
                for name, ok, sec, note in checks(llm, kb):
                    rows.append((m, name, ok, sec, note))
            except Exception as e:
                rows.append((m, "기능 시험", False, 0, f"{type(e).__name__}: {e}"))
    finally:
        if proc:
            proc.terminate()
    lines = ["# 모델 교체 검증 보고서 (현장 위험성평가 AI)", "",
             f"- 실행 시각: {time.strftime('%Y-%m-%d %H:%M')}",
             f"- 연결 방식: {a.provider} / 주소: {a.base_url}",
             f"- 모델: {', '.join(a.models)}" + (" (가짜 모델 서버: 연결 경로 시험용이며 실제 모델 성능과 무관. mock-b는 목록에 없는 코드·설명에 없는 근거 문구를 일부러 섞으며, 앱이 그것을 걸러 내면 통과)" if a.mock else ""), "",
             "| 모델 | 기능 | 결과 | 시간(초) | 비고 |", "|---|---|---|---|---|"]
    for m, name, ok, sec, note in rows:
        lines.append(f"| {m} | {name} | {'지원 안 함' if ok is None else '통과' if ok else '실패'} | {sec:.1f} | {str(note).replace('|', '/')} |")
    rows = [r for r in rows if r[2] is not None]
    passed = sum(1 for r in rows if r[2])
    lines += ["", f"통과 {passed} / {len(rows)}"]
    Path(a.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    # 화면 머리·'서비스 구조·검증'에 보일 요약(모델별 통과 수). 가짜 모델 시험은 실측으로 표시하지 않는다
    import json
    per = {}
    for m, name, ok, sec, note in rows:
        d = per.setdefault(m, {"model": m, "passed": 0, "total": 0, "items": []})
        if ok is not None:  # 사진을 받지 못하는 모델의 '지원 안 함'은 통과·실패로 세지 않음
            d["total"] += 1
            d["passed"] += 1 if ok else 0
        d["items"].append({"name": name + (" (지원 안 함)" if ok is None else ""), "ok": bool(ok), "seconds": round(sec, 1), "note": str(note)[:200]})
    out = ROOT / "검증결과" / ("model_check_mock.json" if a.mock else "model_check.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"date": time.strftime("%Y-%m-%d"), "provider": a.provider, "mock": bool(a.mock),
                               "models": list(per.values())}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n".join(lines))
    print(f"\n보고서: {a.out}")
    sys.exit(0 if passed == len(rows) else 1)


if __name__ == "__main__":
    main()
