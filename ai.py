"""생성형 AI 쓰임새: 사실 대조 장치, 물어보기(이어 묻기), 오늘 작업 브리핑(외부 자료 종합 해석).

판정(위험성·작업 시작·작업 중지)은 규칙으로 하고, 모델은 사실 목록 안에서 문장만 쓴다.
모델 문장에 사실에 없는 숫자나 위험요인 코드가 있으면 버리고 규칙 문장을 쓴다.
"""
import re
import time
from collections import deque
from datetime import date

import assess
import laws
import feeds
from core.llm import LLMError

RX_NUM = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?")
RX_CODE = re.compile(r"\bH\d{2}\b")
RATE, RATE_MAX = deque(), 40  # 1분에 40번(공개 시연판에서 키가 빨리 닳지 않게)


def _nums(text):
    out = set()
    for m in RX_NUM.findall(text or ""):
        try:
            out.add(round(float(m.replace(",", "")), 1))
        except ValueError:
            pass
    return out


def guard(llm, system, facts, rule, user=None, extra="", history=None, max_tokens=700):
    """{"text","mode","dropped"}. 모델이 없거나 실패하거나 사실에 없는 숫자·코드를 쓰면 규칙 문장."""
    res = {"text": rule, "mode": "규칙 기반", "dropped": ""}
    if not (llm and llm.enabled and facts):
        return res
    now = time.time()
    while RATE and now - RATE[0] > 60:
        RATE.popleft()
    if len(RATE) >= RATE_MAX:
        res["dropped"] = "요청이 많아 잠시 규칙 문장을 씁니다(1분 뒤 다시 시도)"
        return res
    RATE.append(now)
    msgs = [{"role": "system", "content": system + " 아래 '사실'에 있는 숫자·위험요인·기준만 쓰고, 사실에 없는 숫자·조문 번호·원인은 지어내지 마세요."}]
    for h in history or []:
        msgs += [{"role": "user", "content": h["q"]}, {"role": "assistant", "content": h["a"]}]
    msgs.append({"role": "user", "content": "사실:\n" + "\n".join(f"- {f}" for f in facts) + (f"\n\n{user}" if user else "")})
    try:
        text = llm.chat(msgs, max_tokens=max_tokens).strip()
    except LLMError as e:
        res["dropped"] = f"모델 응답 실패로 규칙 문장을 씁니다({e})"
        return res
    if not text:
        res["dropped"] = "모델이 빈 답을 돌려줘 규칙 문장을 씁니다"
        return res
    src = "\n".join(facts) + " " + (user or "") + " " + rule + " " + extra + " " + " ".join(h["q"] + " " + h["a"] for h in history or [])
    allowed = _nums(src) | {float(i) for i in range(0, 13)}
    bad = sorted(n for n in _nums(text) if n not in allowed and round(n) not in allowed)
    codes = sorted(set(RX_CODE.findall(text)) - set(RX_CODE.findall(src)))
    if bad or codes:
        what = [f"{x:g}" for x in bad[:3]] + codes[:3]
        res["dropped"] = f"모델 문장에 사실에 없는 숫자·코드({', '.join(what)})가 있어 규칙 문장을 씁니다"
        return res
    res.update(text=text, mode="모델(사실 대조 통과)")
    return res


# ------------------------------------------------------------ 물어보기

STOP = {"작업", "어떻게", "무엇", "뭐야", "알려줘", "해야", "하나", "있어", "필요", "기준", "규정", "그럼", "그러면", "어때", "언제", "얼마"}
RX_FOLLOW = re.compile(r"^\s*(그럼|그러면|그리고|그건|그거|거기|그때|그 작업|만약|혹시)")


def _words(q):
    return [w for w in re.findall(r"[가-힣A-Za-z]{2,}", q) if w not in STOP]


def _articles(k, q, n=2):
    """질문 낱말이 많이 들어 있는 규정 조문(제목에 있으면 가중)."""
    if not k.reg:
        return []
    ws = _words(q)
    scored = []
    for a in k.reg.articles:
        s = sum(3 * (w in (a.title or "")) + (w in a.plain) for w in ws)
        if s:
            scored.append((s, a))
    scored.sort(key=lambda x: -x[0])
    return [a for _, a in scored[:n]]


def carry(k, q, history):
    """이어 묻는 질문이면 앞 질문의 위험요인 낱말을 붙인다. (질문, 붙인 말)"""
    if not history or not (RX_FOLLOW.search(q) or len(q.replace(" ", "")) <= 10):
        return q, ""
    if k.codes_in(q):
        return q, ""
    for h in reversed(history):
        codes = k.codes_in(h["q"])
        if codes:
            add = k.hazards[codes[0]]["name"]
            return add + " " + q, add
    return q, ""


def ask_facts(k, q, items, today):
    """질문에 맞는 사실 목록·출처·규칙 답."""
    facts, srcs, lines = [], [], []
    codes = k.codes_in(q)
    for c in codes[:3]:
        h = k.hazards[c]
        facts.append(f"{c} {h['name']}({h['type']}): 기본 가능성 {h['L']}, 중대성 {h['S']}, 감소대책: {'; '.join(h['measures'])}"
                     + (f", 관련 기준: {h['law']}" if h["law"] else ""))
        srcs.append(h["src"])
        lines.append(f"{h['name']}({h['type']}) 위험은 이렇게 줄입니다: " + "; ".join(h["measures"][:4]) + "."
                     + (f" 관련 기준: {h['law']}." if h["law"] else ""))
        for x in laws.articles_for(h["law"], 1)["items"]:
            facts.append(f"법령 원문 {laws.cite(x)}" + (f"(시행 {x['date']})" if x["date"] else "") + f": {x['text'][:500]}")
            srcs.append({"file": laws.SRC, "loc": laws.cite(x), "quote": x["text"][:160]})
            lines.append(f"법령 원문 {laws.cite(x)}: {x['text'][:200]}")
    for key, b in k.basis.items():
        if any(w in b["label"] for w in _words(q)) or (key == "height" and re.search(r"높|사다리|m\b|미터", q)) \
                or (key.startswith("heat") and re.search(r"폭염|더위|체감", q)):
            facts.append(f"판단 기준 {b['label']}: {b['value']} ({b['from']}" + (f", {b['basis']['reg']} {b['basis']['label']}" if b["basis"] else "") + ")")
            if b["basis"]:
                lines.append(f"{b['label']}은 {b['value']}입니다({b['basis']['reg']} {b['basis']['label']}).")
    for a in _articles(k, q):
        c = k.cite(a)
        facts.append(f"{c['reg']} {c['label']}({c['title']}): {a.plain[:400]}")
        srcs.append({"file": c["file"], "loc": c["loc"], "quote": a.plain[:160]})
        lines.append(f"{c['reg']} {c['label']}({c['title']}): {a.plain[:200]}")
    incs = [i for i in k.incidents if set(i.get("codes", [])) & set(codes)][:3] if codes else []
    for i in incs:
        facts.append(f"아차사고 {i['date']} {i['fac']} {i['work']}: {i['text'][:100]}")
        if i.get("src"):
            srcs.append(i["src"])
    if incs:
        lines.append("최근 같은 위험의 아차사고: " + "; ".join(f"{i['date']} {i['fac']} {i['work']}" for i in incs) + ".")
    if re.search(r"오늘|지금|시작|현황|남은|미완료", q):
        for a in items[:6]:
            st = assess.stats(a)
            facts.append(f"평가 {a['created']} {a['fac']} {a['work']}: " + ("작업 시작 가능" if st["ready"] else "작업 전 조치 필요(" + ", ".join(st["blocked"] + st["weather_stops"]) + ")"))
        if items:
            lines.append("평가 현황: " + "; ".join(f"{a['fac']} {a['work']} {'시작 가능' if assess.stats(a)['ready'] else '작업 전 조치 필요'}" for a in items[:4]) + ".")
    if not lines:
        lines.append('이렇게 물어보세요: "사다리 작업 안전 기준은?", "폭염 때 실외 작업은?", "밀폐공간 들어가기 전에 뭘 해야 해?", "오늘 시작 못 하는 작업 있어?"')
    return facts, srcs, "\n".join(lines)


def overview_facts(k, items):
    facts = [f"기관 위험요인 목록 {len(k.hazards)}종, 정기 평가 대상 작업 {len(k.tasks)}개, 아차사고 {len(k.incidents)}건"]
    facts += [f"{c} {h['name']}({h['type']}): 감소대책 {'; '.join(h['measures'][:2])}" for c, h in list(k.hazards.items())[:12]]
    facts += [f"판단 기준 {b['label']}: {b['value']}" for b in k.basis.values()]
    return facts


def ask(k, q, items, llm=None, history=None):
    history = [h for h in (history or []) if h.get("q") and h.get("a")][-4:]
    q2, carried = carry(k, q, history)
    facts, srcs, rule = ask_facts(k, q2, items, date.today().isoformat())
    general = False
    if not facts and llm and llm.enabled:
        facts, general = overview_facts(k, items), True
    g = guard(llm, "당신은 공공시설 현장 안전 담당자를 돕습니다. 질문에 한국어로 3~5문장으로 답하세요. 기관 규정과 위험요인 목록의 감소대책을 근거로 말하고, "
                   "법령은 이름과 주제까지만 쓰세요." + (" 사실만으로 답할 수 없으면 그렇다고 말하세요." if general else ""),
              facts, rule, user=f"질문: {q2}", extra=q, history=history)
    return {"answer": g["text"], "mode": g["mode"], "dropped": g["dropped"].replace("규칙 문장", "규칙 답"), "facts": facts,
            "sources": [s for s in srcs if s][:6], "carried": carried, "general": general}


# ------------------------------------------------------------ 오늘 작업 브리핑(외부 자료 종합 해석)

LEVEL = {"stop": 0, "fix": 1, "care": 2, "go": 3}
LABEL = {"stop": "작업 중지", "fix": "시작 전 조치", "care": "주의하며 진행", "go": "시작 가능"}


def briefing(k, items, wx, msgs):
    """작성 중·확정 평가마다 기상청 체감온도·특보, 긴급재난문자, 아차사고, 미완료 조치를 엮어 오늘 판정."""
    rows, facts = [], []
    act = feeds.active_warnings(wx)
    facts.append(f"기상({wx['source']}) {wx['time']}: 기온 {wx['ta']:g}℃, 습도 {wx['rh']:g}%, 체감온도 {wx['feel']:g}℃, "
                 f"발표 중인 특보: {', '.join(w['kind'] + w['level'] for w in act) or '없음'}")
    for m in msgs["items"][:5]:
        facts.append(f"긴급재난문자({msgs['source']}) {m['time']} {m['kind'] or '안내'}: {m['text'][:90]}")
    rest, stop_t = k.values["heat_rest"], k.values["heat_stop"]
    for a in items[:12]:
        codes = {i["code"] for i in a["items"] if i["confirmed"]}
        st = assess.stats(a)
        stops = feeds.weather_stops(wx, a["conditions"], codes)
        why, lv = [], "go"
        if stops:
            lv = "stop"
            why += stops
        outdoor = a["conditions"].get("outdoor")
        if outdoor and wx["feel"] >= stop_t:
            lv = min(lv, "fix", key=LEVEL.get)
            why.append(f"실외 작업, 체감온도 {wx['feel']:g}℃가 작업 단축 기준({stop_t}℃) 이상")
        elif outdoor and wx["feel"] >= rest:
            lv = min(lv, "care", key=LEVEL.get)
            why.append(f"실외 작업, 체감온도 {wx['feel']:g}℃가 휴식 기준({rest}℃) 이상")
        hit = [(m, feeds.message_hits(m, a)) for m in msgs["items"]]
        hit = [(m, h) for m, h in hit if h]
        if hit:
            lv = min(lv, "fix", key=LEVEL.get)
            why.append("재난문자 " + ", ".join(dict.fromkeys(m["kind"] or "안내" for m, _ in hit)) + "와 겹치는 위험: " + ", ".join(dict.fromkeys(x for _, h in hit for x in h)))
        if st["blocked"]:
            lv = min(lv, "fix", key=LEVEL.get)
            why.append("작업 전 끝낼 조치 남음: " + ", ".join(st["blocked"]))
        incs = [r for r in a["reassess"] if r.get("kind") != "재난문자"]
        if incs:
            lv = min(lv, "care", key=LEVEL.get)
            why.append(f"같은 작업 아차사고 {len(incs)}건(수시평가 필요)")
        if st["empty"]:
            lv = "fix"
            why.append("위험요인이 없어 평가가 끝나지 않음")
        top = max((i["R"] for i in a["items"] if i["confirmed"]), default=0)
        rows.append({"id": a["id"], "fac": a["fac"], "work": a["work"], "status": a["status"], "top": top, "outdoor": bool(outdoor),
                     "level": lv, "label": LABEL[lv], "why": why or ["걸리는 조건 없음"]})
        facts.append(f"{a['fac']} {a['work']}(최고 위험성 {top}{', 실외' if outdoor else ''}) → 판정: {LABEL[lv]}. 이유: {'; '.join(why) or '걸리는 조건 없음'}")
    rows.sort(key=lambda r: (LEVEL[r["level"]], -r["top"]))
    rule = []
    for lv in ("stop", "fix", "care"):
        x = [r for r in rows if r["level"] == lv]
        if x:
            rule.append(f"{LABEL[lv]}: " + "; ".join(f"{r['fac']} {r['work']}({r['why'][0]})" for r in x[:4]) + ".")
    ok = [r for r in rows if r["level"] == "go"]
    if ok:
        rule.append("시작 가능: " + ", ".join(f"{r['fac']} {r['work']}" for r in ok[:4]) + ".")
    if not rows:
        rule.append("오늘 볼 위험성평가가 없습니다. '새 위험성평가'에서 작업을 평가하세요.")
    rule.append(f"기상: 체감온도 {wx['feel']:g}℃, 특보 {', '.join(w['kind'] + w['level'] for w in act) or '없음'}"
                + ("" if wx["live"] else "(예시 자료)") + f". 재난문자 {len(msgs['items'])}건" + ("" if msgs["live"] else "(예시 자료)") + ".")
    return {"rows": rows, "facts": facts, "rule": "\n".join(rule), "weather": dict(wx, active=act), "messages": msgs,
            "src": {"weather": wx["live"], "messages": msgs["live"], "incidents": len(k.incidents)},
            "th": {"heat_rest": rest, "heat_stop": stop_t}}
