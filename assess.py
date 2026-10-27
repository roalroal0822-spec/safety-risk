"""위험성평가: 작업 설명(+사진) → 위험요인·가능성·중대성·감소대책·개선 후 위험성.

1) 낱말: 위험요인 목록의 '찾는 낱말'이 작업 설명에 있으면 그 위험요인을 넣는다(근거 문구 표시).
2) 조건: 설명에서 높이·인원(1인 작업)·체감온도·운영 중 여부를 읽어 가능성·중대성을 조정한다(조정 이유 표시).
3) 아차사고: 같은 시설·위험요인의 최근 아차사고가 있으면 가능성을 1 올리고 그 기록을 근거로 단다.
4) 모델(선택): 설명에서 낱말로 못 찾은 위험요인을 제안받되, 목록에 있는 코드이고 근거 문구가 설명에 실제로 있어야 넣는다.
   사진은 모델이 본 위험요인을 '현장 확인 필요'로만 넣고, 담당자가 확인해야 평가표에 들어간다.
판단 기준(위험성 6 이상·3 이상)은 기관 규정 조문에서 읽는다.
"""
import re
import uuid
from datetime import date

from core.llm import LLMError
from kb import PERMIT, REG_TOPIC

RX_HEIGHT = re.compile(r"(\d+(?:\.\d+)?)\s*(?:m|미터|M)(?![a-zA-Z²㎡])")
RX_TEMP = re.compile(r"(?:체감온도|기온|온도)\s*(\d{2}(?:\.\d)?)\s*(?:℃|도)|(\d{2}(?:\.\d)?)\s*℃")
RX_NOBODY = re.compile(r"(?:이용객|회원|관람객|수강생)\s*(?:이|은|는)?\s*없")  # '관람객 없음'은 운영 중이 아님
RX_ALONE = re.compile(r"혼자|단독|(?<!\d)1인\s*작업|(?<!\d)1명|한\s*명(?:이|만|이서)|나\s*혼자")


def conditions(text, temp=None):
    c = {}
    hs = [float(x) for x in RX_HEIGHT.findall(text or "")]
    if hs:
        c["height"] = max(hs)
    m = RX_TEMP.search(text or "")
    if temp not in (None, ""):
        c["temp"] = float(temp)
    elif m:
        c["temp"] = float(m.group(1) or m.group(2))
    if RX_ALONE.search(text or ""):
        c["alone"] = True
    m = re.search(r"(\d+)\s*(?:인\s*1조|명이서|명이|명\s*작업|인\s*작업)", text or "")
    if m and int(m.group(1)) >= 2:
        c["people"] = int(m.group(1))
        c.pop("alone", None)
    if re.search(r"운영\s*중|이용객|회원|관람객|수강생", text or "") and not RX_NOBODY.search(text or ""):
        c["open"] = True
    if re.search(r"실외|옥외|옥상|주차장 진출입|야외|땡볕", text or ""):
        c["outdoor"] = True
    return c


def _quote(text, words):
    """낱말이 들어 있는 구절(쉼표·마침표로 나눈 한 토막)을 근거 문구로 돌려준다."""
    parts = [p.strip() for p in re.split(r"[.,\n;]|(?<=다)\s", text or "") if p.strip()]
    for w in words:
        for p in parts:
            if w in p:
                return p[:60], w
    return "", ""


def level(kb, r):
    if r >= kb.values["high"]:
        return "bad", "작업 전 감소대책 완료"
    if r >= kb.values["mid"]:
        return "warn", "작업 중 관리"
    return "ok", "현재 조치 유지"


def _item(kb, code, by, quote="", word=""):
    h = kb.hazards[code]
    return {"code": code, "name": h["name"], "type": h["type"], "L0": h["L"], "S0": h["S"], "L": h["L"], "S": h["S"],
            "reasons": [], "by": by, "quote": quote, "word": word, "confirmed": by != "사진(모델)",
            "measures": [{"text": m, "done": False, "owner": "", "due": "", "completed": ""} for m in h["measures"]],
            "law": h["law"], "basis": kb.cite_topic(REG_TOPIC[code]) if code in REG_TOPIC else None, "src": h["src"]}


def rate(kb, it, cond, fac, work, on):
    """가능성·중대성 조정. 조정마다 이유를 남긴다(같은 이유를 두 번 넣지 않음)."""
    L, S = it["L0"], it["S0"]
    reasons = []
    code = it["code"]
    hmin = kb.values["height"]
    if code == "H01" and "height" in cond:
        if cond["height"] >= hmin:
            S = 3
            reasons.append({"text": f"작업 높이 {cond['height']:g}m(기준 {hmin}m 이상) → 중대성 3", "src": None})
        else:
            S = 2
            reasons.append({"text": f"작업 높이 {cond['height']:g}m(기준 {hmin}m 미만) → 중대성 2", "src": None})
    if cond.get("alone") and code in ("H01", "H03", "H04", "H05"):
        L += 1
        reasons.append({"text": "1인 작업 → 가능성 +1", "src": None})
    if code == "H01" and "H02" in on:
        L += 1
        reasons.append({"text": "미끄러운 바닥 위 사다리 작업 → 가능성 +1", "src": None})
    if code == "H07" and "temp" in cond:
        if cond["temp"] >= kb.values["heat_stop"]:
            L = 3
            reasons.append({"text": f"체감온도 {cond['temp']:g}℃(작업 단축 기준 {kb.values['heat_stop']}℃ 이상) → 가능성 3", "src": None})
        elif cond["temp"] >= kb.values["heat_rest"]:
            reasons.append({"text": f"체감온도 {cond['temp']:g}℃(휴식 기준 {kb.values['heat_rest']}℃ 이상)", "src": None})
    if code == "H12" and cond.get("open"):
        reasons.append({"text": "운영 중(이용객 있음) 작업", "src": None})
    # 최근 아차사고
    for inc in recent_incidents(kb, fac, work, code, on):
        L += 1
        reasons.append({"text": f"최근 아차사고({inc['date']} {inc['fac']}): {inc['text'][:60]} → 가능성 +1", "src": inc["src"], "incident": inc["id"]})
        break
    it["L"], it["S"] = max(1, min(3, L)), max(1, min(3, S))
    it["reasons"] = reasons
    _score(kb, it)


def _score(kb, it):
    it["R"] = it["L"] * it["S"]
    it["level"], it["level_label"] = level(kb, it["R"])
    # 감소대책을 모두 하면 가능성이 1로 내려간다고 보고 개선 후 위험성을 계산(중대성은 그대로)
    done = all(m["done"] for m in it["measures"]) if it["measures"] else False
    it["R_after"] = 1 * it["S"]
    it["after_level"], it["after_label"] = level(kb, it["R_after"])
    it["all_done"] = done


def recent_incidents(kb, fac, work, code, on):
    look = kb.values["lookback"]
    today = date.today()
    out = []
    for inc in kb.incidents:
        try:
            d = date.fromisoformat(inc["date"])
        except ValueError:
            continue
        if (today - d).days > look * 31:
            continue
        if code not in inc.get("codes", []):
            continue
        # 같은 작업(작업 이름이 겹침)이고, 시설이 둘 다 적혀 있으면 같은 시설이어야 한다
        if not (work and inc["work"] and _overlap(work, inc["work"])):
            continue
        if fac and inc["fac"] and not (inc["fac"] in fac or fac in inc["fac"]):
            continue
        out.append(inc)
    return sorted(out, key=lambda x: x["date"], reverse=True)


def _overlap(a, b):
    stop = {"점검", "작업", "관리", "정기", "청소", "측정", "설치", "교체"}  # 흔한 낱말만 겹치는 것은 같은 작업으로 보지 않음
    wa = {w for w in re.findall(r"[가-힣A-Za-z]{2,}", a)} - stop
    wb = {w for w in re.findall(r"[가-힣A-Za-z]{2,}", b)} - stop
    return len(wa & wb) >= 1


# ------------------------------------------------------------ 모델 보조

def model_hazards(kb, text, llm, have):
    """설명에서 모델이 찾은 위험요인. 코드가 목록에 있고 근거 문구가 설명에 그대로 있어야 받는다."""
    lib = "\n".join(f"{c}: {h['name']} ({h['type']})" for c, h in kb.hazards.items())
    got = llm.json("공공시설 현장 작업 설명을 읽고 해당하는 위험요인 코드를 고르세요. 목록에 있는 코드만 쓰고, 각 코드마다 그렇게 판단한 근거가 되는 작업 설명 속 문구를 그대로 옮기세요.",
                   f"위험요인 목록:\n{lib}\n\n작업 설명: {text}\n\n출력 형식: {{\"hazards\": [{{\"code\": \"H01\", \"quote\": \"작업 설명 속 문구\"}}]}}")
    out, dropped = [], []
    norm = lambda s: re.sub(r"\s+", "", s or "")  # noqa: E731
    for h in (got.get("hazards") or []) if isinstance(got, dict) else []:
        code, q = str(h.get("code", "")).strip(), str(h.get("quote", "")).strip()
        if code in have:
            continue
        if code not in kb.hazards:
            dropped.append(f"목록에 없는 코드 {code}")
        elif not q or norm(q) not in norm(text):
            dropped.append(f"{code}: 근거 문구가 설명에 없음")
        else:
            out.append((code, q))
            have.add(code)
    return out, dropped


def photo_hazards(kb, photos_b64, llm):
    lib = "\n".join(f"{c}: {h['name']}" for c, h in kb.hazards.items())
    got = llm.vision_json("공공시설 작업 현장 사진을 보고 보이는 위험요인을 목록의 코드로만 고르세요. 사진에서 실제로 보이는 것만 쓰세요.",
                          f"위험요인 목록:\n{lib}\n\n출력 형식: {{\"hazards\": [{{\"code\": \"H01\", \"what\": \"사진에서 본 것\"}}]}}", photos_b64)
    out, dropped = [], []
    for h in (got.get("hazards") or []) if isinstance(got, dict) else []:
        code = str(h.get("code", "")).strip()
        if code in kb.hazards:
            out.append((code, str(h.get("what", "")).strip()[:80]))
        else:
            dropped.append(f"목록에 없는 코드 {code}")
    return out, dropped


# ------------------------------------------------------------ 평가 만들기

def make(kb, fac, dept, work, text, temp=None, llm=None, photos=None, photo_names=None):
    full = ". ".join(x for x in (work, text) if x)
    cond = conditions(full, temp)
    items, have = [], set()
    for code, h in kb.hazards.items():
        q, w = _quote(full, h["words"])
        if code == "H07" and not w and cond.get("outdoor") and cond.get("temp", 0) >= kb.values["heat_rest"]:
            q, w = f"실외 작업, 체감온도 {cond['temp']:g}℃", "체감온도"
        if code == "H12" and w and RX_NOBODY.search(full):
            continue
        if w:
            items.append(_item(kb, code, "낱말", q, w))
            have.add(code)
    notes = []
    engine = "규칙"
    if llm is not None and llm.enabled:
        try:
            got, dropped = model_hazards(kb, full, llm, have)
            for code, q in got:
                items.append(_item(kb, code, "모델", q))
            if got:
                engine = "규칙+모델"
            notes += [f"모델 제안 제외: {d}" for d in dropped]
        except LLMError as e:
            notes.append(f"모델 응답 실패로 규칙 결과만 씁니다({e})")
        if photos:
            try:
                got, dropped = photo_hazards(kb, photos, llm)
                for code, what in got:
                    ex = next((i for i in items if i["code"] == code), None)
                    if ex:
                        ex["photo"] = what
                    else:
                        it = _item(kb, code, "사진(모델)", what)
                        it["photo"] = what
                        items.append(it)
                        have.add(code)
                if got:
                    engine += "+사진(모델)"
                notes += [f"사진 판독 제외: {d}" for d in dropped]
            except LLMError as e:
                notes.append(f"사진은 첨부만 했습니다(모델이 사진을 읽지 못함: {e})")
    elif photos:
        notes.append("모델이 연결되지 않아 사진은 평가표에 첨부만 합니다. 사진에서 본 위험은 '위험요인 추가'로 넣으세요.")
    on = {i["code"] for i in items}
    for it in items:
        rate(kb, it, cond, fac, work, on)
    items.sort(key=lambda i: (-i["R"], i["code"]))
    questions = []
    if "H01" in on and "height" not in cond:
        questions.append("작업 높이가 몇 m인가요? (2m 이상이면 작업발판·안전대가 필요합니다)")
    if cond.get("height", 0) >= kb.values["height"] and "H01" not in on and "H01" in kb.hazards:
        questions.append(f"높이 {cond['height']:g}m 작업인데 목록의 낱말로 '{kb.hazards['H01']['name']}'을 찾지 못했습니다. "
                         "아래 '위험요인 추가'로 넣고 이 작업을 가리키는 말을 적어 두면 다음부터 자동으로 찾습니다.")
    if cond.get("outdoor") and "temp" not in cond:
        questions.append("실외 작업입니다. 작업 시간대의 체감온도를 넣으면 폭염 기준으로 다시 판단합니다.")
    if not items:
        questions.append("위험요인을 찾지 못했습니다. 장소·장비·약품·높이처럼 작업 모습을 더 자세히 적어 주세요.")
    permits = [{"name": PERMIT[c], "basis": kb.cite_topic(REG_TOPIC.get(c, PERMIT[c][:2]))} for c in on if c in PERMIT]
    return {
        "id": "R" + uuid.uuid4().hex[:6], "created": date.today().isoformat(), "fac": fac, "dept": dept, "work": work,
        "text": text, "conditions": cond, "items": items, "questions": questions, "permits": permits,
        "photos": photo_names or [], "engine": engine, "notes": notes, "reassess": [], "status": "작성 중",
        "rules": {"high": kb.values["high"], "mid": kb.values["mid"]},
    }


def rescore(kb, a):
    for it in a["items"]:
        _score(kb, it)
    a["items"].sort(key=lambda i: (-i["R"], i["code"]))
    return a


def add_item(kb, a, code, word=""):
    if code not in kb.hazards or any(i["code"] == code for i in a["items"]):
        return a
    q, w = _quote(". ".join(x for x in (a["work"], a["text"]) if x), [word]) if word else ("", "")
    it = _item(kb, code, "직접 추가", q, w)
    rate(kb, it, a["conditions"], a["fac"], a["work"], {i["code"] for i in a["items"]} | {code})
    a["items"].append(it)
    return rescore(kb, a)


def stats(a):
    items = [i for i in a["items"] if i["confirmed"]]
    open_ = [(i, m) for i in items for m in i["measures"] if not m["done"]]
    high = [i for i in items if i["level"] == "bad"]
    today = date.today().isoformat()
    overdue = [(i, m) for i, m in open_ if m["due"] and m["due"] < today]
    blocked = [i for i in high if not i["all_done"]]
    return {"items": len(items), "high": len(high), "open": len(open_), "overdue": len(overdue),
            "ready": bool(items) and not blocked, "empty": not items, "blocked": [i["name"] for i in blocked],
            "unconfirmed": sum(1 for i in a["items"] if not i["confirmed"])}


def reassess_hits(kb, assessments, inc):
    """새 아차사고가 기존 평가에 해당하면 수시평가 필요 표시."""
    hits = []
    basis = kb.cite_topic(r"수시평가")
    for a in assessments:
        codes = {i["code"] for i in a["items"]}
        other_fac = inc["fac"] and a["fac"] and not (inc["fac"] in a["fac"] or a["fac"] in inc["fac"])
        if set(inc.get("codes", [])) & codes and not other_fac and _overlap(a["work"], inc["work"]):
            if not any(r["incident"] == inc["id"] for r in a["reassess"]):
                a["reassess"].append({"incident": inc["id"], "date": inc["date"], "text": inc["text"][:80], "src": inc.get("src"), "basis": basis})
                hits.append(a["id"])
    return hits


def task_status(kb, task, assessments, year):
    """정기 평가 대상 작업 하나의 올해 평가 상태. 같은 시설이고 작업 이름이 겹치는 평가 중 가장 최근 것을 본다."""
    mine = [a for a in assessments if _overlap(task["work"], a["work"])
            and not (task["fac"] and a["fac"] and not (task["fac"] in a["fac"] or a["fac"] in task["fac"]))]
    last = max(mine, key=lambda a: a["created"], default=None)
    if not last:
        return {"state": "평가 없음", "level": "bad", "aid": None, "date": ""}
    st = stats(last)
    if last["reassess"]:
        state, lv = "수시평가 필요", "warn"
    elif last["created"][:4] != year:
        state, lv = "올해 평가 안 함", "bad"
    elif not st["ready"]:
        state, lv = "작업 전 조치 남음", "warn"
    else:
        state, lv = "올해 평가함", "ok"
    return {"state": state, "level": lv, "aid": last["id"], "date": last["created"], "count": len(mine)}
