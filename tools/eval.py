"""정확도 성적표: 모델·인터넷 없이 같은 결과가 나오는 시험을 돌려 검증결과/에 남긴다.

  python tools/eval.py [--note "무엇을 고친 뒤 쟀는지"]   → 검증결과/scorecard.json, 정확도_성적표.md

시험
  1. 위험요인 찾기(개선에 쓴 문항 30개 / 쓰지 않은 문항 30개): 작업 설명마다 정답 위험요인 코드를 미리 적어 두고,
     앱이 찾은 코드와 정확히 같은지 본다(빠짐·덧붙임 모두 오답). 코드 단위 재현율·정밀도도 적는다.
  2. 조건 읽기: 높이·인원·체감온도·운영 중·실외 25문장.
  3. 작업 시작 판정: 무작위 평가 300건에서 '위험성 6 이상 감소대책이 남으면 막고, 모두 끝나면 연다'가 지켜지는지.
  4. 모델 제안 거르기: 가짜 모델이 목록에 없는 코드·설명에 없는 근거를 섞으면 버리고, 바른 제안은 받는지.
  5. 개인정보 가림: 개인정보 문장 30개는 가리고, 시험 문장·평가 이유 문장은 건드리지 않는지.
문항과 정답은 이 파일에 있고(개발자 작성, 위험요인 목록의 낱말을 아는 사람이 씀), 틀린 문항은 고치지 않고 공개한다.
"""
import json
import random
import re
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import assess  # noqa: E402
from core.pii import mask  # noqa: E402
from kb import KB  # noqa: E402

# (작업, 설명, 정답 코드) — H01 떨어짐 H02 넘어짐 H03 감전 H04 끼임 H05 질식 H06 약품 H07 온열 H08 근골격 H09 화재 H10 차량 H11 맞음 H12 이용객
SET_A = [
    ("분전반 점검", "분전반 차단기 교체", {"H03"}),
    ("저수조 청소", "지하 저수조 내부 청소", {"H05"}),
    ("냉각탑 점검", "옥상 냉각탑 필터 교체, 체감온도 34도", {"H01", "H07"}),
    ("수영장 청소", "수영장 바닥 물청소", {"H02"}),
    ("약품 보충", "차아염소산나트륨 약품 보충", {"H06"}),
    ("차선 도색", "주차장 진출입로 차선 도색", {"H10"}),
    ("물품 정리", "후원 물품 박스 30개 옮기기", {"H08"}),
    ("배관 보수", "배관 용접 보수", {"H09"}),
    ("로비 조명", "운영 중 로비 천장 등기구 교체, 사다리 사용", {"H01", "H03", "H11", "H12"}),
    ("펌프 정비", "펌프 모터 베어링 교체", {"H04"}),
    ("정화조 점검", "정화조 내부 점검", {"H05"}),
    ("샤워실 보수", "샤워실 타일 보수", {"H02"}),
    ("공조기 정비", "공조기 벨트 교체", {"H04"}),
    ("에스컬레이터 점검", "에스컬레이터 점검, 이용객 통제", {"H04", "H12"}),
    ("화단 정비", "폭염 속 실외 화단 정비", {"H07"}),
    ("자재 운반", "무거운 자재 운반, 20kg", {"H08"}),
    ("난간 절단", "그라인더로 철제 난간 절단", {"H09"}),
    ("하역", "지게차로 자재 하역", {"H08", "H10"}),
    ("콘센트 교체", "어린이 수강생 있는 강의실 콘센트 교체", {"H03", "H12"}),
    ("맨홀 확인", "맨홀 뚜껑 열고 내부 확인", {"H05"}),
    ("창고 정리", "선반 위 물품 정리", {"H11"}),
    ("복도 작업", "왁스 청소 직후 복도 사다리 작업", {"H01", "H02"}),
    ("배선 정리", "전기 배선 정리", {"H03"}),
    ("옥상 방수", "옥상 방수 작업, 한낮", {"H01", "H07"}),
    ("소독제", "소독제 희석", {"H06"}),
    ("송풍기", "송풍기 점검", {"H04"}),
    ("물탱크", "물탱크 청소", {"H05"}),
    ("잔디 깎기", "실외 작업, 체감온도 36도, 잔디 깎기", {"H07"}),
    ("홈통 청소", "지붕 홈통 청소", {"H01"}),
    ("차량 유도", "후진하는 차량 유도", {"H10"}),
]
# 개선에 쓰지 않은 문항(2026-10-29 SET_A와 함께 작성, 한 번만 잼). 틀려도 이 문항에 맞춰 앱을 고치지 않는다
SET_B = [
    ("보일러 점검", "기계실 보일러 버너 점검", {"H04"}),
    ("외벽 도장", "높이 3m 비계 위에서 도장", {"H01"}),
    ("조명 교체", "전원 끄지 않고 조명 교체", {"H03"}),
    ("수처리", "수처리제 투입", {"H06"}),
    ("집수정 청소", "집수정 펌프 청소", {"H04", "H05"}),
    ("제설", "빙판길 제설", {"H02"}),
    ("무대 조명", "강당 무대 트러스에 조명 매달기, 높이 7m", {"H01", "H11"}),
    ("바닥 왁스", "체육관 바닥 왁스 작업", {"H02"}),
    ("간판 점검", "고소작업대로 외벽 간판 점검", {"H01"}),
    ("펜스 수리", "용접기로 펜스 수리, 땡볕", {"H09", "H07"}),
    ("승강기 점검", "엘리베이터 기계실 점검", {"H04"}),
    ("차단기 수리", "주차 차단기 수리, 차량 통행 중", {"H10", "H03"}),
    ("청소", "락스와 세제 섞어 청소", {"H06"}),
    ("배수", "피트 내부 배수 작업", {"H05"}),
    ("의자 정리", "의자 100개 옮기기", {"H08"}),
    ("풀사이드 보수", "회원 이용 중 수영장 풀사이드 보수", {"H02", "H12"}),
    ("케이블", "케이블 포설", {"H03"}),
    ("천장 보수", "천장 텍스 교체", {"H01", "H11"}),
    ("배관 절단", "화기 작업 허가 후 배관 절단", {"H09"}),
    ("여과기", "여과기 역세척", {"H04"}),
    ("정산기 점검", "땡볕 아래 주차장 정산기 점검", {"H07", "H10"}),
    ("태양광", "옥상 태양광 패널 청소", {"H01"}),
    ("탱크 도장", "탱크 내부 도장", {"H05"}),
    ("열화상", "분전반 열화상 측정", {"H03"}),
    ("적재", "박스 적재", {"H08"}),
    ("펌프 점검", "물기 많은 기계실 바닥에서 펌프 점검", {"H02", "H04"}),
    ("로비 청소", "민원인 있는 로비 바닥 청소", {"H12"}),
    ("현수막", "사다리로 현수막 설치", {"H01"}),
    ("모터 교체", "모터 교체 작업, 혼자", {"H04"}),
    ("무대 리프트", "공연장 무대 리프트 점검", {"H04"}),
]

# (설명, 있어야 할 조건, 없어야 할 조건)
CONDS = [
    ("높이 4m 사다리 작업", {"height": 4.0}, []), ("3.5미터 높이", {"height": 3.5}, []), ("혼자 작업", {"alone": True}, []),
    ("1인 작업으로 진행", {"alone": True}, []), ("2인 1조", {"people": 2}, ["alone"]), ("3명이 작업", {"people": 3}, ["alone"]),
    ("체감온도 34도", {"temp": 34.0}, []), ("기온 35℃ 실외", {"temp": 35.0, "outdoor": True}, []), ("운영 중 작업", {"open": True}, []),
    ("관람객 없음", {}, ["open"]), ("이용객 없는 시간", {}, ["open"]), ("옥상 작업", {"outdoor": True}, []),
    ("땡볕 아래 점검", {"outdoor": True}, []), ("수강생 있는 강의실", {"open": True}, []), ("한 명이 작업", {"alone": True}, []),
    ("높이 2m 작업대", {"height": 2.0}, []), ("조명기 12대 설치", {}, ["people", "height"]), ("면적 200㎡ 바닥", {}, ["height"]),
    ("나 혼자 해요", {"alone": True}, []), ("야외 행사장 설치, 체감온도 33도", {"outdoor": True, "temp": 33.0}, []),
    ("회원 이용 중", {"open": True}, []), ("5명 작업", {"people": 5}, []), ("단독 작업", {"alone": True}, []),
    ("2026-08-19 작업", {}, ["height", "temp"]), ("20kg 박스 운반", {}, ["height"]),
]


def eval_sets(kb):
    out = []
    for name, cases, desc in (("위험요인 찾기(개선에 쓴 문항)", SET_A, "개발자가 미리 정답을 적은 작업 30개. 이 문항으로 앱을 고칠 수 있으므로 참고용"),
                              ("위험요인 찾기(개선에 쓰지 않은 문항)", SET_B, "같은 날 따로 적어 한 번만 잰 작업 30개(목록에 없는 표현 포함). 틀린 것을 보고 앱을 고치지 않음")):
        ok, fails, tp, fp, fn = 0, [], 0, 0, 0
        for work, text, want in cases:
            a = assess.make(kb, "", "", work, text)
            got = {i["code"] for i in a["items"]}
            tp += len(got & want)
            fp += len(got - want)
            fn += len(want - got)
            if got == want:
                ok += 1
            else:
                fails.append(f"'{text}' → 찾음 {sorted(got) or '없음'} / 정답 {sorted(want)}")
        rec = tp / (tp + fn) * 100 if tp + fn else 0
        pre = tp / (tp + fp) * 100 if tp + fp else 0
        out.append({"name": name, "passed": ok, "total": len(cases), "failures": fails,
                    "desc": f"{desc}. 정답과 정확히 같아야 통과(코드 단위 재현율 {rec:.0f}%, 정밀도 {pre:.0f}%)"})
    return out


def eval_conds():
    ok, fails = 0, []
    for text, want, absent in CONDS:
        c = assess.conditions(text)
        bad = [f"{k}={c.get(k)}(정답 {v})" for k, v in want.items() if c.get(k) != v] + [f"{k}가 잘못 읽힘({c[k]})" for k in absent if k in c]
        if bad:
            fails.append(f"'{text}': " + ", ".join(bad))
        else:
            ok += 1
    return [{"name": "조건 읽기", "passed": ok, "total": len(CONDS), "failures": fails,
             "desc": "높이·1인 작업·인원·체감온도·운영 중(부정 표현 포함)·실외를 읽어 내는지"}]


def eval_verdict(kb, n=300):
    rnd = random.Random(5)
    ok, fails = 0, []
    codes = list(kb.hazards)
    for i in range(n):
        a = assess.make(kb, "", "", "작업", "설명")
        a["items"] = []
        for c in rnd.sample(codes, rnd.randint(1, 4)):
            it = assess._item(kb, c, "낱말")
            it["L"], it["S"] = rnd.randint(1, 3), rnd.randint(1, 3)
            for m in it["measures"]:
                m["done"] = rnd.random() < 0.5
            a["items"].append(it)
        assess.rescore(kb, a)
        st = assess.stats(a)
        should = all(all(m["done"] for m in it["measures"]) for it in a["items"] if it["L"] * it["S"] >= kb.values["high"])
        if st["ready"] == should:
            ok += 1
        else:
            fails.append(f"평가 {i + 1}: 판정 {st['ready']} / 규칙상 {should}")
    return [{"name": "작업 시작 판정", "passed": ok, "total": n, "failures": fails,
             "desc": f"무작위 평가 {n}건에서 '위험성 {kb.values['high']} 이상(규정 조문 값)의 감소대책이 남으면 막고, 모두 끝나면 연다'를 지키는지"}]


class FakeLLM:
    enabled = True

    def __init__(self, reply):
        self.reply = reply
        self.cfg = {"model": "fake"}

    def json(self, system, user, **kw):
        return self.reply


def eval_model_guard(kb, n=100):
    rnd = random.Random(9)
    texts = [t for _, t, _ in SET_A + SET_B]
    blocked, fails, good_ok, good_fail = 0, [], 0, []
    for i in range(n):
        text = rnd.choice(texts)
        kind = rnd.choice(["code", "quote"])
        if kind == "code":
            bad = {"code": rnd.choice(["H99", "H13", "X01", "H0", "위험"]), "quote": text[:6]}
        else:
            bad = {"code": rnd.choice(list(kb.hazards)), "quote": rnd.choice(["안전모 미착용", "고압 전류 노출", "추락 위험이 큼", "가스 누출 의심"])}
        got, dropped = assess.model_hazards(kb, text, FakeLLM({"hazards": [bad]}), set())
        if not got and dropped:
            blocked += 1
        else:
            fails.append(f"'{text}'에 섞은 {bad} 를 받아들임")
    for text in texts[:30]:
        have = {i["code"] for i in assess.make(kb, "", "", "", text)["items"]}
        free = [c for c in kb.hazards if c not in have]
        c = rnd.choice(free)
        q = text.split(",")[0][:8].strip()
        got, dropped = assess.model_hazards(kb, text, FakeLLM({"hazards": [{"code": c, "quote": q}]}), set(have))
        if got == [(c, q)]:
            good_ok += 1
        else:
            good_fail.append(f"'{text}': 바른 형식의 제안({c}, '{q}')을 버림 {dropped}")
    return [{"name": "모델 제안 거르기", "passed": blocked, "total": n, "failures": fails,
             "desc": "가짜 모델이 목록에 없는 코드나 설명에 없는 근거 문구를 냈을 때 버린 비율"},
            {"name": "바른 제안은 받음", "passed": good_ok, "total": 30, "failures": good_fail,
             "desc": "목록에 있는 코드 + 설명에 그대로 있는 근거 문구인 제안을 받아들인 비율(내용이 맞는지는 담당자 확인 몫)"}]


PII_POS = ["담당 김○○ 010-2345-6789로 연락 바람", "주민번호 850315-2345678 확인", "계좌 110-234-567890 입금", "메일 manager@agency.go.kr",
           "카드 4321-8765-1234-5678 결제", "사무실 02-345-6789", "지역번호 031-456-7890", "외국인등록번호 900101-5123456",
           "여권번호 M12345678 사본", "휴대폰 01098765432", "010.1111.2222 문자", "국민은행 123456-12-345678", "신한 110-12-345678",
           "정산 담당 042-123-4567", "개인 메일 abc.def@example.com 회신", "주민 9001011234567", "농협 301-1234-5678-91",
           "번호 010 3333 4444", "팩스 02-777-8888", "주민등록 760505 1234567", "a_b@test.co.kr로 보내 줘", "070-1234-5678 인터넷전화",
           "카드번호 1111 2222 3333 4444", "우리 1002-345-678901", "051-234-5678 부산", "연락 011-234-5678", "여권 S98765432",
           "메일주소: hong.gildong@agency.kr", "공단 담당 053-230-1234", "계좌 3333-01-1234567"]


def eval_pii(kb):
    ok_pos, pos_fail = 0, []
    for t in PII_POS:
        out, kinds = mask(t)
        if kinds and "@" not in out and not re.search(r"\d{3,}", out.replace(" ", "")):
            ok_pos += 1
        else:
            pos_fail.append(f"'{t}' → '{out}'")
    neg = {t for _, t, _ in SET_A + SET_B} | {t for t, _, _ in CONDS}
    for _, t, _ in SET_A:
        a = assess.make(kb, "종합체육센터", "", "체육관 조명 교체", t)
        neg |= {r["text"] for it in a["items"] for r in it["reasons"]} | {m["text"] for it in a["items"] for m in it["measures"]}
    neg |= {i["text"] for i in kb.incidents}
    neg = sorted(neg)
    ok_neg, neg_fail = 0, []
    for t in neg:
        _, kinds = mask(t)
        if kinds:
            neg_fail.append(f"잘못 가림({', '.join(kinds)}): {t[:60]}")
        else:
            ok_neg += 1
    return [{"name": "개인정보 가림", "passed": ok_pos, "total": len(PII_POS), "failures": pos_fail,
             "desc": "주민번호·전화·계좌·카드·이메일·여권이 든 문장 30개를 가린 비율"},
            {"name": "개인정보 오탐 없음", "passed": ok_neg, "total": len(neg), "failures": neg_fail,
             "desc": "작업 설명·판단 이유·감소대책·아차사고 문장(날짜·높이·℃·kg 포함)을 잘못 가리지 않은 비율"}]


def main():
    import argparse
    ap = argparse.ArgumentParser(description="정확도 성적표 만들기")
    ap.add_argument("--note", default="", help="측정 이력에 남길 한 줄")
    note = ap.parse_args().note
    t0 = time.time()
    kb = KB(ROOT / "sample_data").load()
    areas = eval_sets(kb) + eval_conds() + eval_verdict(kb) + eval_model_guard(kb) + eval_pii(kb)
    out = ROOT / "검증결과"
    out.mkdir(exist_ok=True)
    prev = None
    try:
        prev = json.loads((out / "scorecard.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    summary = ", ".join(f"{a['name']} {a['passed']}/{a['total']}" for a in areas)
    hist = (prev or {}).get("history", [])
    if not hist or hist[-1]["summary"] != summary or note:
        hist.append({"date": date.today().isoformat(), "summary": summary, "note": note})
    sc = {"app": "현장 위험성평가 AI", "date": date.today().isoformat(), "command": "python tools/eval.py",
          "author": "개발자 작성(블라인드 아님, 위험요인 목록 낱말을 아는 사람이 씀)", "seconds": round(time.time() - t0, 1),
          "areas": areas, "history": hist[-10:]}
    (out / "scorecard.json").write_text(json.dumps(sc, ensure_ascii=False, indent=1), encoding="utf-8")
    md = ["# 정확도 성적표 (현장 위험성평가 AI)", "", f"- 측정일: {sc['date']} · 재현: `{sc['command']}` (모델·인터넷 불필요, {sc['seconds']}초)",
          f"- 문항: {sc['author']}", "", "| 시험 | 결과 | 무엇을 쟀나 |", "|---|---|---|"]
    for a in areas:
        md.append(f"| {a['name']} | {a['passed']}/{a['total']} ({a['passed'] / a['total'] * 100:.1f}%) | {a['desc']} |")
    fails = [(a["name"], f) for a in areas for f in a["failures"]]
    md += ["", "## 틀린 문항 (고치지 않고 공개)", ""] + ([f"- [{n}] {f}" for n, f in fails] or ["- 없음"])
    md += ["", "## 측정 이력", ""] + [f"- {i}차 {h['date']}" + (f" ({h['note']})" if h.get("note") else "") + f": {h['summary']}" for i, h in enumerate(hist[-10:], 1)]
    (out / "정확도_성적표.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md[:7 + len(areas)]))
    print(f"\n틀린 문항 {len(fails)}건")


if __name__ == "__main__":
    main()
