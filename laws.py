"""법제처 국가법령정보 공동활용 Open API로 위험요인의 관련 법령 조문 원문을 받는다.

- 키: 환경변수 LAW_OC (open.law.go.kr에서 신청한 API 인증값). 주소 전체를 넣어도 OC= 값만 쓴다.
- 목록: {BASE}/lawSearch.do?OC=&target=law&type=JSON&query=법령명
- 본문: {BASE}/lawService.do?OC=&target=law&type=JSON&MST=법령일련번호
- 응답의 정확한 JSON 중첩은 가이드에 없어서, 필드 이름(법령일련번호·조문내용 등)으로 어디에 있든 찾는다.
- 키가 없거나 연결이 안 되면 조문을 지어내지 않고 법령 이름과 국가법령정보센터 링크만 돌려준다.
"""
import json
import os
import re
import time
import urllib.parse
import urllib.request

BASE = os.environ.get("LAW_API_BASE", "http://www.law.go.kr/DRF").rstrip("/")
TIMEOUT = 10
TTL = 24 * 3600
SRC = "법제처 국가법령정보 공동활용 Open API"
_CACHE = {}   # 법령명 -> (받은 시각, 법령 dict 또는 오류 문장)

STOP = {"위험", "방지", "예방", "등", "관한", "인한", "의한", "작업"}
# 관련 기준 괄호 속 주제어를 조문 제목에서 찾기 쉬운 말로 넓힌다(검색어일 뿐, 조문 내용은 법제처 원문만 쓴다).
SYN = {"추락": ["추락", "작업발판", "개구부"], "전기": ["감전", "전기"], "온열질환": ["온열", "폭염", "휴식"],
       "근골격계부담작업": ["근골격계", "중량물"], "낙하물": ["낙하물", "낙하"], "화재": ["화재", "용접", "화기"],
       "기계": ["기계", "원동기", "회전"], "기구": ["방호"], "바닥": ["바닥", "통로"], "밀폐공간": ["밀폐공간", "산소"],
       "차량계": ["차량계", "하역운반"]}


def oc():
    v = os.environ.get("LAW_OC", "").strip()
    m = re.search(r"OC=([^&\s]+)", v)
    return urllib.parse.unquote(m.group(1) if m else v)


def parse_refs(law_text):
    """'산업안전보건기준에 관한 규칙(추락 위험 방지)' -> [(법령명, [검색어...])]. 법령이 아닌 기관 규정은 뺀다."""
    out = []
    for part in re.split(r"\s*[/;]\s*", law_text or ""):
        m = re.match(r"\s*([^()]+?)\s*(?:\(([^)]*)\))?\s*$", part)
        if not m:
            continue
        name, topic = m.group(1).strip(), (m.group(2) or "").strip()
        if not re.search(r"(법|법률|령|규칙)$", name) or name.startswith("기관"):
            continue
        words = []
        for w in re.split(r"[\s·ㆍ,]+", topic):
            w = re.sub(r"(으로|로|의|에)$", "", w)
            if len(w) >= 2 and w not in STOP:
                words += SYN.get(w, [w])
        out.append((name, list(dict.fromkeys(words))))
    return out


def link(name, no=""):
    return "https://www.law.go.kr/법령/" + urllib.parse.quote(name.replace(" ", "")) + ("/" + urllib.parse.quote(no) if no else "")


def _get(path, params):
    q = urllib.parse.urlencode(dict(params, OC=oc(), target="law", type="JSON"), quote_via=urllib.parse.quote)
    with urllib.request.urlopen(f"{BASE}/{path}?{q}", timeout=TIMEOUT) as r:
        raw = r.read().decode("utf-8", "replace")
    try:
        return json.loads(raw)
    except ValueError:
        m = re.search(r"<(?:msg|errMsg|message)>(.*?)<", raw)
        raise RuntimeError(m.group(1) if m else "JSON이 아닌 응답(인증값·등록 서버 확인 필요)")


def _dicts(d, key):
    """중첩 JSON 안에서 key를 가진 dict를 모두 찾는다."""
    if isinstance(d, dict):
        if key in d:
            yield d
        for v in d.values():
            yield from _dicts(v, key)
    elif isinstance(d, list):
        for v in d:
            yield from _dicts(v, key)


def _flat(v):
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, list):
        return "\n".join(x for x in (_flat(i) for i in v) if x)
    return ""


def _article_text(u):
    lines = [_flat(u.get("조문내용"))]
    hangs = u.get("항") or []
    for h in hangs if isinstance(hangs, list) else [hangs]:
        if not isinstance(h, dict):
            continue
        lines.append(_flat(h.get("항내용")))
        hos = h.get("호") or []
        for ho in hos if isinstance(hos, list) else [hos]:
            if isinstance(ho, dict):
                lines.append(_flat(ho.get("호내용")))
    return re.sub(r"[ \t]+", " ", "\n".join(x for x in lines if x)).strip()


def fetch(name):
    """법령 하나의 조문 목록. 실패하면 RuntimeError."""
    hit = _CACHE.get(name)
    if hit and time.time() - hit[0] < TTL:
        if isinstance(hit[1], str):
            raise RuntimeError(hit[1])
        return hit[1]
    try:
        s = _get("lawSearch.do", {"query": name, "display": 20})
        cands = list(_dicts(s, "법령일련번호"))
        key = name.replace(" ", "")
        pick = next((c for c in cands if str(c.get("법령명한글", "")).replace(" ", "") == key), None) \
            or next((c for c in cands if str(c.get("법령약칭명", "")).replace(" ", "") == key), None)
        if not pick:
            raise RuntimeError(f"'{name}'을(를) 법령 목록에서 찾지 못함")
        b = _get("lawService.do", {"MST": pick["법령일련번호"]})
        info = next(_dicts(b, "법령명_한글"), {})
        arts = []
        for u in _dicts(b, "조문번호"):
            if str(u.get("조문여부", "조문")) != "조문":
                continue
            no = f"제{u['조문번호']}조" + (f"의{u['조문가지번호']}" if str(u.get("조문가지번호") or "").strip() not in ("", "0") else "")
            text = re.sub(r"^제\s*\d+\s*조(?:\s*의\s*\d+)?\s*(?:\([^)]*\))?\s*", "", _article_text(u)).strip()
            if text:
                arts.append({"no": no, "title": str(u.get("조문제목") or "").strip(), "text": text,
                             "date": str(u.get("조문시행일자") or "")})
        if not arts:
            raise RuntimeError("본문에서 조문을 읽지 못함")
        law = {"name": str(info.get("법령명_한글") or name), "date": str(info.get("시행일자") or pick.get("시행일자") or ""),
               "articles": arts}
        _CACHE[name] = (time.time(), law)
        return law
    except Exception as e:
        msg = str(e)[:100]
        _CACHE[name] = (time.time() - TTL + 300, msg)   # 실패는 5분만 기억
        raise RuntimeError(msg)


def _ymd(s):
    s = re.sub(r"\D", "", s or "")
    return f"{s[:4]}.{s[4:6]}.{s[6:8]}" if len(s) == 8 else ""


def articles_for(law_text, n=2):
    """관련 기준 문장 -> {"live", "items":[{law, no, title, text, date, url}], "refs":[{law,url}], "note"}."""
    refs = parse_refs(law_text)
    out = {"live": False, "source": SRC, "items": [], "refs": [{"law": nm, "url": link(nm)} for nm, _ in refs], "note": ""}
    if not refs:
        return out
    if not oc():
        out["note"] = "법제처 인증값(LAW_OC)이 없어 조문 원문 대신 법령 이름과 국가법령정보센터 링크만 보여 줍니다."
        return out
    errs = []
    for name, words in refs:
        try:
            law = fetch(name)
        except RuntimeError as e:
            errs.append(f"{name}: {e}")
            continue
        out["live"] = True
        scored = []
        for a in law["articles"]:
            s = sum(3 * (w in a["title"]) + (w in a["text"]) for w in words)
            if s:
                scored.append((s, a))
        scored.sort(key=lambda x: -x[0])
        for _, a in scored[:n]:
            out["items"].append({"law": law["name"], "no": a["no"], "title": a["title"], "text": a["text"][:1200],
                                 "date": _ymd(a["date"]) or _ymd(law["date"]), "url": link(law["name"], a["no"])})
    if errs:
        out["note"] = "법령 원문을 받지 못했습니다(" + "; ".join(errs)[:160] + ")."
    elif out["live"] and not out["items"]:
        out["note"] = "법령은 받았지만 주제에 맞는 조문을 찾지 못했습니다. 링크에서 확인하세요."
    return out


# 물어보기: 질문에 법령 이름·조문 번호가 있으면 법제처에서 그 조문을 받는다.
ALIAS = {"중대재해처벌법": "중대재해 처벌 등에 관한 법률", "중대재해법": "중대재해 처벌 등에 관한 법률",
         "재난안전법": "재난 및 안전관리 기본법", "재난안전관리기본법": "재난 및 안전관리 기본법",
         "시설물안전법": "시설물의 안전 및 유지관리에 관한 특별법", "산안법": "산업안전보건법",
         "안전보건규칙": "산업안전보건기준에 관한 규칙", "산업안전보건규칙": "산업안전보건기준에 관한 규칙",
         "산업안전보건기준규칙": "산업안전보건기준에 관한 규칙"}
KNOWN = ["산업안전보건기준에 관한 규칙", "산업안전보건법 시행규칙", "산업안전보건법 시행령", "산업안전보건법",
         "중대재해 처벌 등에 관한 법률 시행령", "중대재해 처벌 등에 관한 법률", "재난 및 안전관리 기본법",
         "시설물의 안전 및 유지관리에 관한 특별법"]
RX_LAWQ = re.compile(r"법|법령|조문|규칙|시행령|조항|제\s*\d+\s*조|\d+\s*조")
DEFAULT = ["산업안전보건기준에 관한 규칙", "산업안전보건법"]


def laws_in(q):
    """질문에 나온 법령 이름(정식 이름). 긴 이름부터 맞춰 겹치지 않게."""
    z = re.sub(r"\s+", "", q)
    out = []
    for nm in KNOWN:
        if nm.replace(" ", "") in z and not any(nm.replace(" ", "") in o.replace(" ", "") for o in out):
            out.append(nm)
    for al, nm in ALIAS.items():
        if al in z and nm not in out:
            out.append(nm)
    return out


def ask_articles(q, words, n=3):
    """법령 질문이면 조문을 받는다. 법령명이 없으면 산업안전보건 기본 두 법령에서 질문 낱말로 찾는다.
    {"asked": 법령 질문인지, "live", "items", "refs", "note"}"""
    named = laws_in(q)
    out = {"asked": bool(named or RX_LAWQ.search(re.sub(r"(방|해|용|수|기|문|작|요)법", "", q))), "live": False, "source": SRC, "items": [], "refs": [], "note": ""}
    if not out["asked"]:
        return out
    names = named or DEFAULT
    out["refs"] = [{"law": nm, "url": link(nm)} for nm in names]
    m = re.search(r"제?\s*(\d+)\s*조(?:\s*의\s*(\d+))?", q)
    want = (f"제{m.group(1)}조" + (f"의{m.group(2)}" if m.group(2) else "")) if m else ""
    if not oc():
        out["note"] = "법제처 인증값(LAW_OC)이 없어 법령 원문을 가져오지 못했습니다. 국가법령정보센터 링크에서 확인하세요."
        return out
    ws = [w for w in words if not any(w in nm.replace(" ", "") for nm in names) and not re.match(r"^(법령|법률|조문|규칙|시행령|조항|내용|기준|뭐야|알려줘)$", w)]
    errs = []
    for nm in names:
        try:
            law = fetch(nm)
        except RuntimeError as e:
            errs.append(f"{nm}: {e}")
            continue
        out["live"] = True
        if want and named:
            picks = [a for a in law["articles"] if a["no"] == want][:1]
        else:
            sc = sorted(((sum(3 * (w in a["title"]) + (w in a["text"]) for w in ws), a) for a in law["articles"]), key=lambda x: -x[0])
            picks = [a for s_, a in sc if s_][:n]
        for a in picks:
            out["items"].append({"law": law["name"], "no": a["no"], "title": a["title"], "text": a["text"][:1200],
                                 "date": _ymd(a["date"]) or _ymd(law["date"]), "url": link(law["name"], a["no"])})
    out["items"] = out["items"][:n]
    if errs:
        out["note"] = "법령 원문을 받지 못했습니다(" + "; ".join(errs)[:160] + ")."
    elif out["live"] and not out["items"]:
        out["note"] = (f"{want}을(를) 찾지 못했습니다." if want and named else "질문에 맞는 조문을 찾지 못했습니다.") + " 링크에서 확인하세요."
    return out


def cite(a):
    """평가표·사실 목록용 짧은 표기."""
    return f"{a['law']} {a['no']}" + (f"({a['title']})" if a["title"] else "")
