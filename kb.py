"""기관 자료 읽기: 위험요인 목록, 안전보건관리규정, 정기 평가 대상 작업, 아차사고 기록.

표는 열 이름으로 알아본다. 판단 기준값(위험성 6 이상·3 이상, 폭염 33℃·35℃ 등)은 규정 조문에서 읽고,
규정에 없으면 기본값을 쓴다. 모든 항목에 원문 위치를 붙인다.
"""
import re

from core import regparse
from core.loaders import load_folder

# 위험요인 코드 → 규정에서 관련 조문을 찾는 낱말
REG_TOPIC = {"H01": r"높은 곳", "H03": r"전기", "H05": r"밀폐", "H06": r"약품", "H07": r"폭염", "H09": r"화기"}
PERMIT = {"H05": "밀폐공간 작업허가서", "H09": "화기작업 허가서"}


def _col(header, *pats):
    for i, h in enumerate(header):
        hs = str(h).replace(" ", "")
        if any(re.search(p, hs) for p in pats):
            return i
    return None


def _num(s, default):
    m = re.search(r"\d+", str(s or ""))
    return int(m.group()) if m else default


class KB:
    def __init__(self, root):
        self.root = root
        self.hazards = {}  # 코드 → {...}
        self.tasks = []
        self.incidents = []
        self.reg = None
        self.reg_doc = None
        self.files = []
        self.warnings = []
        self.values, self.basis = {}, {}

    def load(self):
        docs, skipped = load_folder(self.root)
        for s in skipped:
            if not s["file"].lower().endswith((".png", ".jpg", ".jpeg")):
                self.warnings.append(f"{s['file']}: {s['reason']}")
        for doc in docs:
            for t in doc.tables:
                self._table(doc, t)
            if doc.ext in (".hwpx", ".hwp", ".docx", ".txt", ".pdf", ".md") and re.search(r"위험성", doc.text) and re.search(r"제\s*\d+\s*조", doc.text):
                reg = regparse.parse([(b.loc, b.text) for b in doc.blocks], source=doc.relpath)
                if reg.articles and (self.reg is None or len(reg.articles) > len(self.reg.articles)):
                    self.reg, self.reg_doc = reg, doc
        if self.reg:
            self.files.append({"file": self.reg_doc.relpath, "kind": "안전보건 규정", "rows": len(self.reg.articles)})
        self._values()
        for inc in self.incidents:
            inc["codes"] = self.codes_in(inc["text"])  # 무슨 일이 있었는지(내용)로만 분류
        return self

    def _table(self, doc, t):
        h = t["header"]
        locs = t.get("row_locs") or [""] * len(t["rows"])
        c_code, c_words, c_meas = _col(h, r"^코드$"), _col(h, r"찾는낱말|키워드"), _col(h, r"감소대책")
        if None not in (c_code, c_words, c_meas):
            c = {k: _col(h, p) for k, p in (("name", r"^위험요인$|위험요인명"), ("type", r"재해형태"), ("L", r"가능성"),
                                             ("S", r"중대성"), ("law", r"관련기준|근거"))}
            n = 0
            for row, loc in zip(t["rows"], locs):
                g = lambda i: row[i] if i is not None and i < len(row) else ""  # noqa: E731
                code = str(g(c_code)).strip()
                if not code:
                    continue
                self.hazards[code] = {
                    "code": code, "name": str(g(c["name"])).strip() or code, "type": str(g(c["type"])).strip(),
                    "words": [w.strip() for w in str(g(c_words)).split("|") if w.strip()],
                    "L": max(1, min(3, _num(g(c["L"]), 2))), "S": max(1, min(3, _num(g(c["S"]), 2))),
                    "measures": [m.strip() for m in str(g(c_meas)).split(";") if m.strip()],
                    "law": str(g(c["law"])).strip(),
                    "src": {"file": doc.relpath, "loc": loc, "quote": f"{code} {g(c['name'])}"}}
                n += 1
            self.files.append({"file": doc.relpath, "kind": "위험요인 목록", "rows": n})
            return
        c_date, c_text = _col(h, r"발생일|일자"), _col(h, r"^내용$|경위")
        if c_date is not None and c_text is not None:
            c_fac, c_work, c_res = _col(h, r"시설|장소"), _col(h, r"작업"), _col(h, r"결과|피해")
            n = 0
            for row, loc in zip(t["rows"], locs):
                g = lambda i: str(row[i]).strip() if i is not None and i < len(row) else ""  # noqa: E731
                d = re.search(r"20\d{2}-\d{2}-\d{2}", g(c_date))
                if not d:
                    continue
                self.incidents.append({"id": f"I{len(self.incidents) + 1}", "date": d.group(), "fac": g(c_fac), "work": g(c_work),
                                       "text": g(c_text), "result": g(c_res), "origin": "file",
                                       "src": {"file": doc.relpath, "loc": loc, "quote": g(c_text)[:160]}})
                n += 1
            self.files.append({"file": doc.relpath, "kind": "아차사고 기록", "rows": n})
            return
        c_work, c_cycle = _col(h, r"^작업$|작업명"), _col(h, r"주기")
        if c_work is not None and c_cycle is not None:
            c_dept, c_fac = _col(h, r"부서"), _col(h, r"시설|장소")
            n = 0
            for row, loc in zip(t["rows"], locs):
                g = lambda i: str(row[i]).strip() if i is not None and i < len(row) else ""  # noqa: E731
                if g(c_work):
                    self.tasks.append({"dept": g(c_dept), "fac": g(c_fac), "work": g(c_work), "cycle": g(c_cycle),
                                       "src": {"file": doc.relpath, "loc": loc, "quote": g(c_work)}})
                    n += 1
            self.files.append({"file": doc.relpath, "kind": "평가 대상 작업", "rows": n})

    # ------------------------------------------------------------ 규정
    def article(self, topic):
        if not self.reg:
            return None
        for a in self.reg.articles:
            if re.search(topic, a.title or ""):
                return a
        for a in self.reg.articles:
            if re.search(topic, a.plain):
                return a
        return None

    def cite(self, a):
        if not a:
            return None
        return {"reg": self.reg.title or self.reg_doc.name, "label": a.label, "title": a.title, "text": a.to_text(),
                "file": self.reg_doc.relpath, "loc": a.loc}

    def cite_topic(self, topic):
        return self.cite(self.article(topic))

    def _values(self):
        spec = [  # 키, 조문 낱말, 숫자 패턴, 기본값, 설명
            ("high", r"위험성 판단|판단 기준", r"(\d+)\s*이상이면\s*작업을\s*시작하기\s*전", 6, "작업 전 감소대책 완료 기준(위험성)"),
            ("mid", r"위험성 판단|판단 기준", r"(\d+)\s*이상이면\s*감소대책", 3, "작업 중 관리 기준(위험성)"),
            ("heat_rest", r"폭염", r"(\d+)\s*℃\s*이상이면\s*실외", 33, "폭염 휴식 기준(체감온도 ℃)"),
            ("heat_stop", r"폭염", r"(\d+)\s*℃\s*이상이면\s*오후", 35, "폭염 작업 단축 기준(체감온도 ℃)"),
            ("height", r"높은 곳", r"높이\s*(\d+)\s*(?:미터|m)", 2, "작업발판·안전대 기준 높이(m)"),
            ("lookback", r"수시평가", r"(\d+)\s*개월", 12, "아차사고 반영 기간(개월)"),
        ]
        for key, topic, rx, default, label in spec:
            a = self.article(topic)
            v, b = default, None
            if a:
                m = re.search(rx, a.plain)
                if m:
                    v, b = int(m.group(1)), self.cite(a)
            self.values[key] = v
            self.basis[key] = {"label": label, "value": v, "basis": b, "from": "규정" if b else "기본값"}

    # ------------------------------------------------------------ 낱말로 위험요인 찾기
    def codes_in(self, text):
        t = text or ""
        return [c for c, h in self.hazards.items() if any(w in t for w in h["words"])]

    def summary(self):
        return {"hazards": len(self.hazards), "tasks": len(self.tasks), "incidents": len(self.incidents),
                "reg": self.reg_doc.relpath if self.reg_doc else "", "files": self.files, "warnings": self.warnings,
                "rules": list(self.basis.values())}
