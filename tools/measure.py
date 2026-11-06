"""실측: 이 PC에서 앱을 띄워 평가 60건(eval.py 문항 A+B)을 실제 화면과 같은 API로 처리하며 시간과 산출량을 잰다.

실행: python tools/measure.py   (모델·인터넷 불필요, 결과는 검증결과/실측.md·measure.json)
사람이 손으로 평가표를 쓰는 시간은 이 스크립트가 잴 수 없으므로 적지 않는다(기관에서 따로 재야 함).
"""
import json
import os
import platform
import shutil
import statistics as st
import subprocess
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tools"))
from smoke_test import Client, free_port  # noqa: E402
from eval import SET_A, SET_B  # noqa: E402


def timed(fn):
    t = time.perf_counter()
    r = fn()
    return r, (time.perf_counter() - t) * 1000


def main():
    tmp = tempfile.mkdtemp(prefix="measure-safety-")
    port = free_port()
    env = dict(os.environ, APP_DATA_DIR=tmp, LLM_PROVIDER="none")
    for k in ("DATA_GO_KR_KEY", "SAFETYDATA_KEY", "KMA_APIHUB_KEY", "LAW_OC"):
        env.pop(k, None)
    proc = subprocess.Popen([sys.executable, "run.py", "--no-browser", "--port", str(port)], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        c = Client(port)
        for _ in range(100):
            try:
                c.call("GET", "/api/info")
                break
            except Exception:
                time.sleep(0.2)
        rows = []
        for work, text, _ in SET_A + SET_B:
            a, t_as = timed(lambda: c.call("POST", "/api/assess", {"fac": "종합체육센터", "dept": "시설팀", "work": work, "text": text}))
            _, t_hw = timed(lambda: c.call("POST", f"/api/assess/{a['id']}/export?fmt=hwpx", {}, raw=True))
            _, t_tb = timed(lambda: c.call("POST", f"/api/assess/{a['id']}/tbm?fmt=hwpx", {}, raw=True))
            items = [i for i in a["items"] if i["confirmed"]]
            rows.append({"work": work, "typed": len(work) + len(text), "assess_ms": t_as, "hwpx_ms": t_hw, "tbm_ms": t_tb,
                         "hazards": len(items), "measures": sum(len(i["measures"]) for i in items),
                         "reasons": sum(len(i["reasons"]) for i in items), "laws": sum(bool(i["law"]) for i in items)})
    finally:
        proc.terminate()
        shutil.rmtree(tmp, ignore_errors=True)

    def s(key):
        v = [r[key] for r in rows]
        return {"median": round(st.median(v), 1), "max": round(max(v), 1), "mean": round(st.mean(v), 1)}
    out = {"date": date.today().isoformat(), "n": len(rows), "machine": f"{platform.system()} {platform.machine()}, Python {platform.python_version()}",
           "assess_ms": s("assess_ms"), "hwpx_ms": s("hwpx_ms"), "tbm_ms": s("tbm_ms"), "typed": s("typed"),
           "hazards": s("hazards"), "measures": s("measures"), "reasons": s("reasons"), "laws": s("laws"), "rows": rows}
    (ROOT / "검증결과").mkdir(exist_ok=True)
    (ROOT / "검증결과" / "measure.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    md = f"""# 무사히 실측 결과

- 측정일: {out['date']} · 재현: `python tools/measure.py` (모델·인터넷 불필요)
- 측정 환경: {out['machine']} (개발용 리눅스 컨테이너, 기관 PC에서 다시 재면 숫자가 달라질 수 있음)
- 대상: 정확도 성적표와 같은 작업 {out['n']}건(A 30 + B 30)을 화면과 같은 API로 처리

| 항목 | 중앙값 | 최대 | 평균 |
|---|---|---|---|
| 위험성평가 1건 만들기(위험요인 찾기·가능성·중대성·작업 시작 판정) | {out['assess_ms']['median']}ms | {out['assess_ms']['max']}ms | {out['assess_ms']['mean']}ms |
| 위험성평가표 한글(HWPX) 만들기 | {out['hwpx_ms']['median']}ms | {out['hwpx_ms']['max']}ms | {out['hwpx_ms']['mean']}ms |
| TBM 기록지 한글(HWPX) 만들기 | {out['tbm_ms']['median']}ms | {out['tbm_ms']['max']}ms | {out['tbm_ms']['mean']}ms |
| 담당자가 입력한 글자 수(작업명+작업 설명) | {out['typed']['median']:g}자 | {out['typed']['max']:g}자 | {out['typed']['mean']}자 |
| 자동으로 채워진 위험요인 행 | {out['hazards']['median']:g}개 | {out['hazards']['max']:g}개 | {out['hazards']['mean']}개 |
| 자동으로 채워진 감소대책 | {out['measures']['median']:g}개 | {out['measures']['max']:g}개 | {out['measures']['mean']}개 |
| 자동으로 붙은 판단 이유(조건·아차사고) | {out['reasons']['median']:g}개 | {out['reasons']['max']:g}개 | {out['reasons']['mean']}개 |
| 관련 기준(법령명·주제)이 붙은 위험요인 | {out['laws']['median']:g}개 | {out['laws']['max']:g}개 | {out['laws']['mean']}개 |

- 처리 시간은 서버 응답까지 잰 값(화면 그리기 제외)입니다. 모델(솔라)을 켜면 AI 문장 기능은 모델 응답 시간만큼 더 걸립니다.
- **사람이 손으로 평가표를 쓰는 시간은 재지 않았습니다.** 비교하려면 같은 작업을 담당자가 기존 방식으로 쓸 때 걸린 시간을 기관에서 재야 합니다.
"""
    (ROOT / "검증결과" / "실측.md").write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
