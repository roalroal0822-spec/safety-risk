"""안전 활동 DB·결재·협력업체 DB.

1) 결재: 공종 담당(작성) → 안전팀(검토) → 협력부서(합의, 선택) → 승인권자(승인). 단계마다 처리자·시각·의견을 남긴다.
2) 안전 활동 DB: 평가 작성·승인, 감소대책 완료, TBM, 사진 제보·조치, 아차사고·조치를 한 줄씩 모은다(원본 기록에서 다시 계산).
   기간(연·월·주)별로 건수·완료율·처리 일수를 낸다.
3) 협력업체 DB: 협력부서·수선유지 보고서(엑셀 표, 한글·워드·PDF 글)에서 업체·공사명·금액·기간·시설을 읽어 업체별로 모은다.
   읽은 값마다 원문 위치를 붙이고, 공사명에 위험 작업 낱말이 있으면 도급 작업 안전보건 협의 대상으로 표시한다.
"""
import re
from datetime import date, datetime, timedelta

ROLES = [("작성", "공종 담당"), ("검토", "안전팀"), ("합의", "협력부서"), ("승인", "승인권자")]


# ------------------------------------------------------------ 결재

def owner_of(cfg, cat, dept=""):
    """공종 담당: 작업 분류(공종)가 같은 담당자, 없으면 부서가 같은 첫 담당자."""
    owners = cfg.get("owners", [])
    return (next((o for o in owners if cat and o["cat"] == cat and o.get("name")), None)
            or next((o for o in owners if dept and o.get("dept") == dept and o.get("name")), None))


def new_line(cfg, cat, dept=""):
    """결재선: 공종별 담당자 표와 결재 설정에서 이름을 채운다. 합의는 설정에 이름이 있을 때만."""
    own = owner_of(cfg, cat, dept)
    names = {"작성": own["name"] if own else "", "검토": cfg.get("reviewer", ""), "합의": cfg.get("agree", ""), "승인": cfg.get("approver", "")}
    return [{"step": s, "role": r, "name": names[s], "at": "", "result": "", "memo": ""}
            for s, r in ROLES if s != "합의" or names["합의"]]


def stage(ap):
    if not ap or not ap.get("line"):
        return "작성 중"
    if ap.get("rejected"):
        return "반려"
    done = [x for x in ap["line"] if x["result"] == "완료"]
    if len(done) == len(ap["line"]):
        return "승인"
    nxt = ap["line"][len(done)]["step"]
    return {"작성": "작성 중", "검토": "검토 대기", "합의": "합의 대기", "승인": "승인 대기"}[nxt]


def act(ap, action, name, memo, now):
    """action: next(현재 단계 처리) | reject(반려) | reset(다시 작성). 처리한 단계를 돌려준다."""
    line = ap["line"]
    if action == "reset":
        for x in line:
            x.update(at="", result="", memo="")
        ap["rejected"] = False
        ap.setdefault("history", []).append({"at": now, "name": name, "what": "다시 작성", "memo": memo})
        return "작성"
    cur = next((x for x in line if x["result"] != "완료"), None)
    if cur is None:
        raise ValueError("이미 승인된 평가입니다")
    if ap.get("rejected"):
        raise ValueError("반려된 평가입니다. '다시 작성'을 먼저 누르세요")
    if action == "reject":
        if cur["step"] == "작성":
            raise ValueError("작성 단계는 반려할 수 없습니다")
        ap["rejected"] = True
        cur.update(at=now, result="반려", memo=memo, name=name or cur["name"])
        ap.setdefault("history", []).append({"at": now, "name": name or cur["name"], "what": f"{cur['step']} 반려", "memo": memo})
        return cur["step"]
    cur.update(at=now, result="완료", memo=memo, name=name or cur["name"])
    ap.setdefault("history", []).append({"at": now, "name": cur["name"], "what": {"작성": "검토 요청", "검토": "검토 완료", "합의": "합의", "승인": "승인"}[cur["step"]], "memo": memo})
    return cur["step"]


# ------------------------------------------------------------ 안전 활동 DB

def activities(assessments, reports, incidents, followups, log):
    """원본 기록에서 안전 활동을 한 줄씩 모은다: {date, kind, fac, cat, who, title, ref}"""
    out = []

    def add(d, kind, fac, cat, who, title, ref):
        if d:
            out.append({"date": d[:10], "kind": kind, "fac": fac or "", "cat": cat or "", "who": who or "", "title": title, "ref": ref})
    for a in assessments:
        cat = cat_of(a)
        add(a["created"], "위험성평가 작성", a["fac"], cat, a.get("dept"), a["work"], a["id"])
        for h in (a.get("approval") or {}).get("history", []):
            if h["what"] == "승인":
                add(h["at"], "평가 승인", a["fac"], cat, h["name"], a["work"], a["id"])
        for it in a["items"]:
            for m in it["measures"]:
                if m.get("done") and m.get("completed"):
                    add(m["completed"], "감소대책 완료", a["fac"], cat, m.get("owner"), f"{a['work']} · {m['text']}", a["id"])
    for e in log:
        if e.get("action") in ("TBM 일지 만들기", "TBM 기록지 만들기"):
            add(e["at"], "TBM 실시", "", "", "", e.get("detail", ""), "")
    for r in reports:
        add(r["at"], "사진 제보", r["fac"], "", r["reporter"], r["text"] or "사진 제보", r["id"])
        if r["status"] == "완료":
            add(r.get("done_at") or r["at"], "제보 조치 완료", r["fac"], "", r.get("owner"), r.get("memo") or r["text"], r["id"])
    for i in incidents:
        add(i["date"], "아차사고 등록", i["fac"], "", "", i["text"][:60], i["id"])
        fu = followups.get(i["id"]) or {}
        for m in fu.get("actions", []):
            if m.get("done") and m.get("completed"):
                add(m["completed"], "아차사고 조치 완료", i["fac"], "", m.get("owner"), m["text"], i["id"])
    return sorted(out, key=lambda x: x["date"], reverse=True)


KINDS = ["위험성평가 작성", "평가 승인", "감소대책 완료", "TBM 실시", "안전점검·교육", "사진 제보", "제보 조치 완료", "아차사고 등록", "아차사고 조치 완료"]
# 도표용 4묶음: 평가·결재 / 조치 완료 / 점검·교육(TBM) / 제보·아차사고
GROUPS = {"평가·결재": ["위험성평가 작성", "평가 승인"], "안전조치 완료": ["감소대책 완료", "제보 조치 완료", "아차사고 조치 완료"],
          "TBM·점검·교육": ["TBM 실시", "안전점검·교육"], "제보·아차사고": ["사진 제보", "아차사고 등록"]}
GROUP_OF = {k: g for g, ks in GROUPS.items() for k in ks}


def kind_from_text(t):
    """기존 실적 대장의 '활동' 칸 → 활동 종류."""
    t = str(t or "")
    for pat, k in ((r"아차", "아차사고 등록"), (r"제보", "사진 제보"), (r"TBM|작업 ?전 ?(회의|점검회의)", "TBM 실시"),
                   (r"승인", "평가 승인"), (r"위험성 ?평가", "위험성평가 작성"),
                   (r"감소대책|개선|보수|교체|설치|조치", "감소대책 완료"), (r"점검|교육|훈련|순찰", "안전점검·교육")):
        if re.search(pat, t):
            return k
    return "안전점검·교육"


def parse_activity_ledger(doc):
    """기존 안전 활동 실적 대장(표) → 활동 줄. 날짜·활동 열이 있어야 한다."""
    out = []
    for t in doc.tables:
        h = t["header"]
        cd, ck = _col(h, r"날짜|일자|실시일"), _col(h, r"활동|구분|종류")
        if cd is None or ck is None:
            continue
        c = {k: _col(h, p) for k, p in (("fac", r"시설|장소"), ("cat", r"공종|분야"), ("who", r"담당|실시자|작성자"), ("title", r"내용|제목|비고"))}
        for row, loc in zip(t["rows"], t.get("row_locs") or [""] * len(t["rows"])):
            g = lambda i: str(row[i]).strip() if i is not None and i < len(row) else ""  # noqa: E731
            d = _date(g(cd)) or (g(cd)[:10] if re.match(r"20\d{2}-\d{2}-\d{2}", g(cd)) else "")
            if not d:
                continue
            out.append({"date": d, "kind": kind_from_text(g(ck)), "fac": g(c["fac"]), "cat": g(c["cat"]), "who": g(c["who"]),
                        "title": g(c["title"]) or g(ck), "ref": f"{doc.relpath} {loc}", "imported": True})
    return out


def period_range(unit, anchor):
    d = date.fromisoformat(anchor)
    if unit == "year":
        s, e = date(d.year, 1, 1), date(d.year, 12, 31)
        buckets = [(f"{m}월", date(d.year, m, 1), (date(d.year + (m == 12), m % 12 + 1, 1) - timedelta(days=1))) for m in range(1, 13)]
        label = f"{d.year}년"
    elif unit == "month":
        s = date(d.year, d.month, 1)
        e = date(d.year + (d.month == 12), d.month % 12 + 1, 1) - timedelta(days=1)
        buckets, w, cur = [], 1, s
        while cur <= e:
            end = min(e, cur + timedelta(days=6 - cur.weekday()))
            buckets.append((f"{w}주", cur, end))
            cur, w = end + timedelta(days=1), w + 1
        label = f"{d.year}년 {d.month}월"
    else:
        s = d - timedelta(days=d.weekday())
        e = s + timedelta(days=6)
        buckets = [("월화수목금토일"[k], s + timedelta(days=k), s + timedelta(days=k)) for k in range(7)]
        label = f"{s.isoformat()} ~ {e.isoformat()}"
    return s, e, buckets, label


def performance(acts, assessments, reports, unit, anchor):
    s, e, buckets, label = period_range(unit, anchor)
    inside = [x for x in acts if s.isoformat() <= x["date"] <= e.isoformat()]
    by_kind = {k: sum(1 for x in inside if x["kind"] == k) for k in KINDS}
    trend = [{"label": b, "from": f.isoformat(), "to": t.isoformat(),
              "counts": {k: sum(1 for x in inside if x["kind"] == k and f.isoformat() <= x["date"] <= t.isoformat()) for k in KINDS}}
             for b, f, t in buckets]
    by_fac, by_cat = {}, {}
    for x in inside:
        by_fac[x["fac"] or "시설 모름"] = by_fac.get(x["fac"] or "시설 모름", 0) + 1
        if x["cat"]:
            by_cat[x["cat"]] = by_cat.get(x["cat"], 0) + 1
    # 기간 안에 만든 평가의 감소대책 완료율, 기간 안 제보의 처리 일수
    ms = [m for a in assessments if s.isoformat() <= a["created"] <= e.isoformat() for it in a["items"] if it.get("confirmed", True) for m in it["measures"]]
    rp = [r for r in reports if s.isoformat() <= r["at"] <= e.isoformat()]
    days = [(date.fromisoformat(r["done_at"][:10]) - date.fromisoformat(r["at"])).days for r in rp if r["status"] == "완료" and r.get("done_at")]
    appr = [a for a in assessments if s.isoformat() <= a["created"] <= e.isoformat()]
    groups = {g: sum(by_kind[k] for k in ks) for g, ks in GROUPS.items()}
    run, cum = {g: 0 for g in GROUPS}, []
    for t in trend:
        for g, ks in GROUPS.items():
            run[g] += sum(t["counts"][k] for k in ks)
        cum.append(dict(run))
    daily = {}
    for x in inside:
        daily[x["date"]] = daily.get(x["date"], 0) + 1
    recent = [x for x in inside if GROUP_OF.get(x["kind"]) == "안전조치 완료"][:8]
    return {"unit": unit, "label": label, "groups": groups, "cum": cum, "daily": daily, "recent": recent,
            "imported": sum(1 for x in inside if x.get("imported")), "from": s.isoformat(), "to": e.isoformat(), "total": len(inside), "by_kind": by_kind, "trend": trend,
            "by_fac": sorted(by_fac.items(), key=lambda x: -x[1]), "by_cat": sorted(by_cat.items(), key=lambda x: -x[1]),
            "measures": {"total": len(ms), "done": sum(1 for m in ms if m["done"])},
            "reports": {"total": len(rp), "done": sum(1 for r in rp if r["status"] == "완료"), "avg_days": round(sum(days) / len(days), 1) if days else None},
            "approval": {"total": len(appr), "approved": sum(1 for a in appr if stage(a.get("approval")) == "승인"),
                         "waiting": sum(1 for a in appr if stage(a.get("approval")) in ("검토 대기", "합의 대기", "승인 대기"))},
            "people": len({x["who"] for x in inside if x["who"] and x["who"] != "익명"}),
            "rows": inside[:500]}


# ------------------------------------------------------------ 협력업체 DB

def _col(header, pat):
    for i, h in enumerate(header):
        if re.search(pat, str(h).replace(" ", "")):
            return i
    return None


RX_VENDOR = r"업체명?|시공사|계약상대자|수급인|협력업체|용역사|시공업체"
RX_CORP = re.compile(r"(?:\(주\)|㈜|주식회사)\s*[가-힣A-Za-z0-9]+|[가-힣A-Za-z0-9]+\s*(?:\(주\)|㈜|주식회사)")


def norm_vendor(n):
    n = re.sub(r"\(주\)|㈜|주식회사|\(유\)|유한회사|\s", "", n or "")
    return n.strip()


def _money(s):
    t = str(s or "").replace(",", "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*(억|천만|백만|만)?\s*원?", t)
    if not m:
        return 0
    v = float(m.group(1))
    return int(v * {"억": 1e8, "천만": 1e7, "백만": 1e6, "만": 1e4}.get(m.group(2), 1))


def _date(s):
    m = re.search(r"(20\d{2})[.\-/년\s]+(\d{1,2})[.\-/월\s]+(\d{1,2})", str(s or ""))
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else ""


def parse_vendor_doc(doc):
    """보고서 한 건 → 작업 기록 목록. 표가 있으면 열 이름으로, 없으면 '항목: 값' 글에서 읽는다."""
    jobs = []
    for t in doc.tables:
        h = t["header"]
        cv = _col(h, RX_VENDOR)
        cw = _col(h, r"공사명|용역명|건명|작업명|수선내용|작업내용|보수내용")
        if cv is None or cw is None:
            continue
        c = {k: _col(h, p) for k, p in (("amount", r"금액|공사비|용역비|계약액"), ("start", r"착공|시작|작업일|일자|계약일|시행일"),
                                         ("end", r"준공|완료|종료"), ("fac", r"시설|장소|현장"), ("dept", r"부서|담당|주관"),
                                         ("note", r"비고|안전|특이"))}
        locs = t.get("row_locs") or [""] * len(t["rows"])
        for row, loc in zip(t["rows"], locs):
            g = lambda i: str(row[i]).strip() if i is not None and i < len(row) else ""  # noqa: E731
            if not g(cv) or not g(cw):
                continue
            jobs.append({"vendor": g(cv), "work": g(cw), "amount": _money(g(c["amount"])), "start": _date(g(c["start"])), "end": _date(g(c["end"])),
                         "fac": g(c["fac"]), "dept": g(c["dept"]), "note": g(c["note"]), "src": {"file": doc.relpath, "loc": loc, "quote": f"{g(cv)} · {g(cw)}"}})
    if jobs:
        return jobs
    # 글 보고서: '업체명: ○○', '공사명: ○○' 같은 항목
    kv = {}
    first_loc = {}
    for b in doc.blocks:
        for m in re.finditer(r"([가-힣 ]{2,10})\s*[:：]\s*([^\n:：]{1,80}?)(?=\s{2,}|\s*[가-힣 ]{2,10}\s*[:：]|$)", b.text):
            k = m.group(1).replace(" ", "")
            kv.setdefault(k, m.group(2).strip())
            first_loc.setdefault(k, b.loc)

    def pick(pat):
        k = next((k for k in kv if re.search(pat, k)), None)
        return (kv[k], first_loc[k]) if k else ("", "")
    vendor, vloc = pick(RX_VENDOR)
    if not vendor:
        m = RX_CORP.search(doc.text)
        vendor, vloc = (m.group().strip(), "본문") if m else ("", "")
    work, _ = pick(r"공사명|용역명|건명|작업명|제목")
    if vendor and work:
        amount, _ = pick(r"금액|공사비|용역비|계약액")
        period, _ = pick(r"기간|공사기간|작업기간")
        start, _ = pick(r"착공|시작|작업일|일자")
        end, _ = pick(r"준공|완료")
        dates = re.findall(r"20\d{2}[.\-/년\s]+\d{1,2}[.\-/월\s]+\d{1,2}", period)
        fac, _ = pick(r"시설|장소|현장")
        dept, _ = pick(r"부서|담당|주관")
        note, _ = pick(r"안전|비고|특이")
        jobs.append({"vendor": vendor, "work": work, "amount": _money(amount), "start": _date(start or (dates[0] if dates else "")),
                     "end": _date(end or (dates[1] if len(dates) > 1 else "")), "fac": fac, "dept": dept, "note": note,
                     "src": {"file": doc.relpath, "loc": vloc, "quote": f"{vendor} · {work}"}})
    return jobs


def vendors(jobs, kb):
    """업체별 모음: 건수·금액·시설·최근 작업, 위험 작업(위험요인 낱말) 표시."""
    by = {}
    for j in jobs:
        key = norm_vendor(j["vendor"])
        v = by.setdefault(key, {"key": key, "name": j["vendor"], "jobs": [], "amount": 0, "facs": set(), "depts": set(), "risky": {}})
        v["jobs"].append(j)
        v["amount"] += j["amount"]
        if j["fac"]:
            v["facs"].add(j["fac"])
        if j["dept"]:
            v["depts"].add(j["dept"])
        for c in kb.codes_in(j["work"] + " " + j.get("note", "")):
            h = kb.hazards[c]
            if h["S"] >= 3:
                v["risky"][c] = h["name"]
        if len(j["vendor"]) > len(v["name"]):
            v["name"] = j["vendor"]
    out = []
    for v in by.values():
        last = max((j["end"] or j["start"] for j in v["jobs"]), default="")
        out.append({"key": v["key"], "name": v["name"], "count": len(v["jobs"]), "amount": v["amount"], "facs": sorted(v["facs"]), "depts": sorted(v["depts"]),
                    "last": last, "risky": [{"code": c, "name": n} for c, n in sorted(v["risky"].items())],
                    "jobs": sorted(v["jobs"], key=lambda j: j["start"] or "", reverse=True)})
    return sorted(out, key=lambda v: (-v["count"], -v["amount"]))


def cat_of(a):
    return (a.get("steps") or [{}])[0].get("cat", "") if a.get("steps") else a.get("cat", "")


def today_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M")
