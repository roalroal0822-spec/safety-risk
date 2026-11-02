"""현장 위험성평가 AI 웹 서버."""
import base64
import re
import shutil
import uuid
from datetime import date
from pathlib import Path

from core import webcommon
from core.config import Config
from core.export import export
from core.llm import LLM
from core.server import App, HttpError, Response, file_response
from core.sources import safe_parts
from core.pii import mask
from core.store import Store
from core.xlsx import CTYPE as XLSX, workbook

import assess
import feeds
from kb import KB

VERSION = "1.1.0"
HERE = Path(__file__).resolve().parent
SAMPLE = HERE / "sample_data"
IMG = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}

cfg = Config(HERE, {"app_title": "현장 위험성평가 AI", "port": 8105})
llm = LLM(cfg["llm"])
store = Store(cfg.data_dir)
KB_ROOT = store.path("kb")
PHOTOS = store.path("photos")
app = App(HERE / "static")
webcommon.register(app, cfg, llm, "현장 위험성평가 AI", VERSION)
ABOUT = {
    "lead": "위험요인 찾기·가능성·중대성·작업 시작 판정은 규칙과 기관 규정으로 하고, 모델은 낱말로 못 찾은 위험을 '제안'만 합니다. 모델이 없어도 같은 결과가 나옵니다.",
    "pipeline": [("작업 설명 읽기", "높이·인원·체감온도·운영 중·실외 여부를 읽고, 개인정보는 먼저 가림"),
                 ("위험요인 찾기", "기관 위험요인 목록의 '찾는 낱말'로 찾고 근거 문구를 붙임"),
                 ("가능성·중대성", "조건과 최근 같은 작업의 아차사고로 조정, 조정마다 이유와 원본 행"),
                 ("규정 기준 판정", "위험성 6 이상은 작업 전 감소대책 완료(규정 조문에서 읽은 값)"),
                 ("모델 제안(선택)", "목록에 있는 코드이고 근거 문구가 설명에 그대로 있어야 받음, 사진은 '현장 확인 필요'"),
                 ("날씨·재난문자", "기상청 체감온도·기상특보로 작업 시작 판정, 긴급재난문자와 겹치는 평가에 수시평가 표시"),
                 ("평가표·TBM", "평가표·TBM 문안·서명지, 아차사고가 나면 수시평가 표시")],
    "guards": ["가능성·중대성 조정과 작업 시작 판정은 모델이 하지 않고 규칙으로만 합니다.",
               "모델이 제안한 위험요인은 기관 목록에 있는 코드여야 하고, 근거 문구가 작업 설명에 그대로 있어야 받습니다.",
               "사진에서 모델이 본 위험은 '현장 확인 필요'로 두고, 담당자가 확인해야 평가표에 들어갑니다.",
               "판단 기준값(6 이상·3 이상, 폭염 33℃·35℃, 높이 2m)은 기관 규정 조문에서 읽고, 없으면 '기본값'으로 표시합니다.",
               "위험요인을 하나도 찾지 못하면 '작업 시작 가능'이 아니라 '평가가 끝나지 않음'으로 막습니다.",
               "높이 2m 이상 작업인데 떨어짐을 찾지 못하면 지어내지 않고 먼저 묻습니다.",
               "현장에서 보탠 낱말은 작업 설명에 실제로 있던 말만 받고, 따로 표시하며 뺄 수 있습니다.",
               "관련 기준은 법령 이름과 주제까지만 적고, 조문 번호를 지어내지 않습니다.",
               "기상특보에 따른 작업 중지는 특보 종류와 작업 조건(실외·높은 곳)으로 규칙만으로 판정하고, 체감온도는 기상청 공개 식으로 계산합니다.",
               "작업 설명·아차사고에 적은 개인정보(전화·주민번호·계좌 등)는 저장·모델 전달 전에 ○○○로 가립니다."],
    "data": ["시연 자료(위험요인 목록·규정·작업·아차사고)는 모두 지어낸 모의자료입니다. 기관 자료로 바꾸면 그대로 동작합니다.",
             "날씨(기상청 단기예보·기상특보)와 긴급재난문자(행정안전부)는 키를 넣으면 실제 자료를, 키가 없거나 연결이 안 되면 예시 자료를 쓰고 화면에 출처를 표시합니다.",
             "관련 기준의 세부 조문은 국가법령정보센터에서 확인하도록 했습니다.",
             "시연용 사진은 그림이며, 실제 비전 모델의 정확도는 기관 PC에서 실측해야 합니다.",
             "자료는 이 PC의 작업 폴더(data)에만 저장되고, 화면은 이 PC에서만 열립니다."],
}
webcommon.register_about(app, HERE, ABOUT)

STATE = {"kb": None}


def log(action, detail=""):
    store.append_log("history.jsonl", {"action": action, "detail": detail})


def kb():
    if STATE["kb"] is None:
        if not KB_ROOT.exists() or not any(KB_ROOT.rglob("*")):
            _copy_sample()
        reload()
    return STATE["kb"]


def _copy_sample():
    for p in SAMPLE.rglob("*"):
        if p.is_file() and "사진" not in p.parts:
            dst = KB_ROOT / p.relative_to(SAMPLE)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst)


def learned():
    return store.read("learned.json", {"items": []})["items"]


def reload():
    k = KB(KB_ROOT).load().learn(learned())
    k.incidents += [dict(i, codes=k.codes_in(i["text"])) for i in user_incidents()]
    STATE["kb"] = k
    return k


def user_incidents():
    return store.read("incidents.json", {"items": []})["items"]


def assessments():
    return store.read("assessments.json", {"items": []})["items"]


def save_all(items):
    store.write("assessments.json", {"items": items})


def get_a(aid):
    for a in assessments():
        if a["id"] == aid:
            return a
    raise HttpError(404, "평가를 찾지 못했습니다")


def put_a(a):
    items = assessments()
    for i, x in enumerate(items):
        if x["id"] == a["id"]:
            items[i] = a
            break
    else:
        items.insert(0, a)
    save_all(items)
    return dict(a, stats=assess.stats(a))


# ------------------------------------------------------------ 상태

@app.get("/api/state")
def state(req):
    k = kb()
    today = date.today().isoformat()
    items = assessments()
    rows = []
    for a in items:
        st = assess.stats(a)
        rows.append({"id": a["id"], "created": a["created"], "fac": a["fac"], "dept": a["dept"], "work": a["work"],
                     "status": a["status"], "top": max((i["R"] for i in a["items"] if i["confirmed"]), default=0),
                     "reassess": len(a["reassess"]), "stats": st})
    open_high = [{"aid": a["id"], "work": a["work"], "fac": a["fac"], "item": i["name"], "R": i["R"], "measure": m["text"],
                  "owner": m["owner"], "due": m["due"]}
                 for a in items for i in a["items"] if i["confirmed"] and i["level"] == "bad" for m in i["measures"] if not m["done"]]
    return {
        "kb": k.summary(), "tasks": k.tasks, "incidents": sorted(k.incidents, key=lambda x: x["date"], reverse=True),
        "periodic": {"basis": k.basis["periodic"], "year": today[:4],
                     "tasks": [dict(t, **assess.task_status(k, t, items, today[:4])) for t in k.tasks]},
        "learned": learned(),
        "hazards": [{"code": h["code"], "name": h["name"], "type": h["type"], "L": h["L"], "S": h["S"], "words": h["words"], "learned": h.get("learned", []),
                     "measures": h["measures"], "law": h["law"], "src": h["src"]} for h in k.hazards.values()],
        "assessments": rows,
        "dash": {"assessments": len(items), "open_high": open_high[:30], "n_open_high": len(open_high),
                 "overdue": [x for x in open_high if x["due"] and x["due"] < today],
                 "reassess": [r for r in rows if r["reassess"]], "unconfirmed": sum(r["stats"]["unconfirmed"] for r in rows)},
        "llm": llm.enabled, "today": today,
    }


# ------------------------------------------------------------ 평가

@app.post("/api/assess")
def create(req):
    b = req.json or {}
    work, k1 = mask((b.get("work") or "").strip())
    text, k2 = mask((b.get("text") or "").strip())
    if not work and not text:
        raise HttpError(400, "작업 이름이나 작업 설명을 입력하세요")
    photos, names = [], []
    for i, p in enumerate((b.get("photos") or [])[:4]):
        ext = Path(p.get("name") or "").suffix.lower()
        if ext not in IMG:
            raise HttpError(400, "사진은 png, jpg 파일만 넣을 수 있습니다")
        raw = base64.b64decode(p["b64"])
        if len(raw) > 8 * 1024 * 1024:
            raise HttpError(400, "사진 한 장은 8MB 이하로 넣어 주세요")
        name = f"{uuid.uuid4().hex[:10]}{ext}"
        PHOTOS.mkdir(parents=True, exist_ok=True)
        (PHOTOS / name).write_bytes(raw)
        photos.append(p["b64"])
        names.append(name)
    temp = b.get("temp")
    if temp not in (None, ""):
        try:
            temp = float(temp)
        except ValueError:
            raise HttpError(400, "체감온도는 숫자로 입력하세요")
    wx = feeds.weather() if b.get("use_weather") else None
    if wx and temp in (None, ""):
        temp = wx["feel"]
    a = assess.make(kb(), (b.get("fac") or "").strip(), (b.get("dept") or "").strip(), work, text, temp,
                    llm if llm.enabled else None, photos, names)
    if wx:
        set_weather(a, wx)
    if k1 or k2:
        a["notes"].insert(0, f"작업 설명의 개인정보({', '.join(dict.fromkeys(k1 + k2))})를 ○○○로 가린 뒤 평가했습니다.")
    log("위험성평가 작성", f"{a['fac']} {a['work']}")
    return put_a(a)


@app.get("/api/assess/<aid>")
def get_one(req):
    a = get_a(req.params["aid"])
    return dict(a, stats=assess.stats(a))


@app.post("/api/assess/<aid>/update")
def update(req):
    a = get_a(req.params["aid"])
    b = req.json or {}
    by = {i["code"]: i for i in a["items"]}
    for u in b.get("items") or []:
        it = by.get(u.get("code"))
        if not it:
            continue
        for k in ("L", "S"):
            if u.get(k) is not None:
                v = int(u[k])
                if not 1 <= v <= 3:
                    raise HttpError(400, "가능성·중대성은 1~3입니다")
                if v != it[k]:
                    it["reasons"].append({"text": f"담당자 조정: {'가능성' if k == 'L' else '중대성'} {it[k]} → {v}", "src": None})
                    it[k] = v
        if "confirmed" in u:
            it["confirmed"] = bool(u["confirmed"])
        for i, mu in enumerate(u.get("measures") or []):
            if i < len(it["measures"]):
                m = it["measures"][i]
                if "done" in mu:
                    m["done"] = bool(mu["done"])
                    m["completed"] = date.today().isoformat() if m["done"] else ""
                for k in ("owner", "due"):
                    if k in mu:
                        m[k] = str(mu[k] or "")[:40]
    if b.get("status") in ("작성 중", "확정"):
        a["status"] = b["status"]
    if b.get("clear_reassess"):
        a["reassess"] = []
    assess.rescore(kb(), a)
    log("평가 수정", a["work"])
    return put_a(a)


@app.post("/api/assess/<aid>/add")
def add(req):
    a = get_a(req.params["aid"])
    b = req.json or {}
    code, word = b.get("code"), (b.get("word") or "").strip()
    k = kb()
    if code not in k.hazards:
        raise HttpError(400, "위험요인 목록에 없는 코드입니다")
    if word:
        # 보탤 낱말은 이 작업 설명에 실제로 있는 말이어야 한다(지어낸 낱말로 목록이 넓어지지 않게)
        if not 2 <= len(word) <= 20 or word not in f"{a['work']} {a['text']}":
            raise HttpError(400, "작업 이름이나 설명에 실제로 있는 말(2~20자)을 적어 주세요")
        if word not in k.hazards[code]["words"]:
            items = learned()
            items.append({"code": code, "word": word, "aid": a["id"], "work": a["work"], "at": date.today().isoformat()})
            store.write("learned.json", {"items": items})
            log("찾는 낱말 보태기", f"{code} {k.hazards[code]['name']} ← '{word}'")
            k = reload()
    assess.add_item(k, a, code, word)
    log("위험요인 추가", f"{a['work']} {code}")
    return put_a(a)


@app.post("/api/learned/remove")
def learned_remove(req):
    b = req.json or {}
    items = [x for x in learned() if not (x["code"] == b.get("code") and x["word"] == b.get("word"))]
    store.write("learned.json", {"items": items})
    log("보탠 낱말 빼기", f"{b.get('code')} '{b.get('word')}'")
    reload()
    return state(req)


@app.post("/api/assess/<aid>/remove")
def remove(req):
    a = get_a(req.params["aid"])
    code = (req.json or {}).get("code")
    a["items"] = [i for i in a["items"] if i["code"] != code]
    log("위험요인 삭제", f"{a['work']} {code}")
    return put_a(a)


@app.delete("/api/assess/<aid>")
def delete(req):
    save_all([a for a in assessments() if a["id"] != req.params["aid"]])
    return {"ok": True}


@app.get("/api/photo/<name>")
def photo(req):
    name = req.params["name"]
    if not re.fullmatch(r"[0-9a-f]{10}\.(png|jpg|jpeg)", name):
        raise HttpError(404, "없는 사진입니다")
    p = PHOTOS / name
    if not p.exists():
        raise HttpError(404, "없는 사진입니다")
    return Response(p.read_bytes(), 200, IMG[p.suffix])


@app.get("/api/sample-photo")
def sample_photo(req):
    p = SAMPLE / "사진" / "조명교체_사다리.png"
    return {"name": p.name, "b64": base64.b64encode(p.read_bytes()).decode()}


# ------------------------------------------------------------ 문서

def _mlist(it):
    return "\n".join(("[완료] " if m["done"] else "") + m["text"] + (f" ({m['owner']}" + (f", ~{m['due']}" if m["due"] else "") + ")" if m["owner"] else "")
                     for m in it["measures"])


@app.post("/api/assess/<aid>/export")
def export_sheet(req):
    a = get_a(req.params["aid"])
    k = kb()
    items = [i for i in a["items"] if i["confirmed"]]
    cond = a["conditions"]
    cd = ", ".join(x for x in [f"높이 {cond['height']:g}m" if "height" in cond else "", "1인 작업" if cond.get("alone") else "",
                               f"{cond['people']}인 작업" if cond.get("people") else "", f"체감온도 {cond['temp']:g}℃" if "temp" in cond else "",
                               "운영 중" if cond.get("open") else "", "실외" if cond.get("outdoor") else ""] if x)
    blocks = [("title", "위험성평가표"),
              ("table", ["시설", "부서", "작업", "평가일", "상태"], [[a["fac"], a["dept"], a["work"], a["created"], a["status"]]], [2, 2, 4, 2, 1]),
              ("p", f"작업 설명: {a['text']}"), ("p", f"읽은 작업 조건: {cd or '없음'}"),
              ("p", f"판단 기준: 위험성 = 가능성(1~3) × 중대성(1~3). {a['rules']['high']} 이상은 작업 전 감소대책 완료, {a['rules']['mid']} 이상은 작업 중 관리."),
              ("table", ["번호", "유해·위험요인", "재해 형태", "가능성", "중대성", "위험성", "판단", "감소대책(담당·기한)", "개선 후", "관련 기준"],
               [[str(n), it["name"] + (" (사진 확인)" if it.get("photo") else ""), it["type"], it["L"], it["S"], it["R"], it["level_label"],
                 _mlist(it), it["R_after"], it["law"] + (f" / {it['basis']['reg']} {it['basis']['label']}" if it.get("basis") else "")]
                for n, it in enumerate(items, 1)], [1, 4, 2, 1, 1, 1, 2, 7, 1, 4])]
    reasons = [(it["name"], r) for it in items for r in it["reasons"]]
    if reasons:
        blocks += [("h2", "가능성·중대성 판단 이유")] + [("bullet", f"{n}: {r['text']}" + (f" [{r['src']['file']} {r['src']['loc']}]" if r.get("src") else "")) for n, r in reasons]
    wx = a.get("weather")
    if wx:
        blocks += [("h2", "작업 당일 기상(공공데이터)"),
                   ("bullet", f"{wx['region']} {wx['time']}: 기온 {wx['ta']:g}℃, 습도 {wx['rh']:g}%, 체감온도 {wx['feel']:g}℃ (출처: {wx['source']})"),
                   ("bullet", "발표 중인 특보: " + (", ".join(w["kind"] + w["level"] for w in wx["warnings"]) or "없음"))] + [
                   ("bullet", "작업 중지: " + t + " (관련 기준: 산업안전보건기준에 관한 규칙, 악천후·강풍 시 작업 중지)") for t in wx["stops"]]
    if a["permits"]:
        blocks += [("h2", "작업 전 필요한 허가")] + [("bullet", p["name"] + (f" (근거: {p['basis']['reg']} {p['basis']['label']})" if p.get("basis") else "")) for p in a["permits"]]
    if a["reassess"]:
        blocks += [("h2", "수시평가 사유")] + [("bullet", f"{r['date']} {r.get('kind', '아차사고')}: {r['text']}") for r in a["reassess"]]
    blocks += [("h2", "평가 참여자 확인"), ("table", ["구분", "성명", "서명"], [["작업 책임자", "", ""], ["작업자", "", ""], ["작업자", "", ""], ["안전 담당", "", ""]], [2, 3, 3]),
               ("note", f"※ 작성: 현장 위험성평가 AI({a['engine']}). 위험요인·가능성·중대성은 담당자가 현장에서 확인해 고친 값입니다. 기록은 규정에 따라 보존합니다.")]
    fmt = req.query.get("fmt", "hwpx")
    data, ctype = export(blocks, fmt)
    log("위험성평가표 내보내기", a["work"])
    return file_response(data, f"위험성평가표_{a['fac']}_{a['work'][:20]}.{fmt}", ctype)


@app.post("/api/assess/<aid>/xlsx")
def export_xlsx(req):
    a = get_a(req.params["aid"])
    items = [i for i in a["items"] if i["confirmed"]]
    rows = [[n, i["name"], i["type"], i["L"], i["S"], i["R"], i["level_label"], _mlist(i), i["R_after"],
             "; ".join(r["text"] for r in i["reasons"]), i["law"] + (f" / {i['basis']['reg']} {i['basis']['label']}" if i.get("basis") else "")]
            for n, i in enumerate(items, 1)]
    data = workbook([("위험성평가표", ["번호", "유해·위험요인", "재해 형태", "가능성", "중대성", "위험성", "판단", "감소대책(담당·기한)", "개선 후", "판단 이유", "관련 기준"],
                      rows, [6, 30, 12, 8, 8, 8, 16, 50, 8, 50, 40])],
                    note=f"{a['fac']} · {a['work']} · 평가일 {a['created']} · {a['status']} · 작업 설명: {a['text']}")
    log("위험성평가표 엑셀", a["work"])
    return file_response(data, f"위험성평가표_{a['fac']}_{a['work'][:20]}.xlsx", XLSX)


@app.post("/api/ledger-xlsx")
def ledger_xlsx(req):
    """위험성평가 대장: 모든 평가의 위험요인 한 줄씩 + 정기 평가 대상 작업 현황."""
    s = state(req)
    rows = []
    for a in assessments():
        st = assess.stats(a)
        for i in a["items"]:
            if i["confirmed"]:
                rows.append([a["created"], a["fac"], a["dept"], a["work"], a["status"], "작업 시작 가능" if st["ready"] else "작업 전 조치 필요",
                             i["name"], i["L"], i["S"], i["R"], i["level_label"], sum(1 for m in i["measures"] if not m["done"]),
                             "수시평가 필요" if a["reassess"] else ""])
    tasks = [[t["dept"], t["fac"], t["work"], t["cycle"], t["state"], t["date"]] for t in s["periodic"]["tasks"]]
    data = workbook([("평가 대장", ["평가일", "시설", "부서", "작업", "상태", "판정", "위험요인", "가능성", "중대성", "위험성", "판단", "미완료 조치", "수시평가"],
                      rows, [11, 12, 12, 30, 8, 16, 30, 8, 8, 8, 16, 10, 12]),
                     ("정기 평가 대상 작업", ["부서", "시설", "작업", "작업 주기", f"{s['today'][:4]}년 평가 상태", "마지막 평가일"], tasks, [12, 12, 30, 10, 18, 12])],
                    note=f"현장 위험성평가 AI {VERSION} · 작성일 {s['today']}")
    log("위험성평가 대장 엑셀")
    return file_response(data, f"위험성평가대장_{s['today']}.xlsx", XLSX)


def tbm_script(a, k):
    items = [i for i in a["items"] if i["confirmed"]][:3]
    stop = k.cite_topic(r"작업중지")
    lines = [f"오늘 작업은 {a['fac']} '{a['work']}'입니다."]
    if items:
        lines.append("오늘 특히 조심할 위험은 " + ", ".join(f"{n}번 {i['name']}" for n, i in enumerate(items, 1)) + "입니다.")
        for n, i in enumerate(items, 1):
            todo = [m["text"] for m in i["measures"]][:2]
            lines.append(f"{n}번을 막으려면 " + " 그리고 ".join(todo) + ".")
    wx = a.get("weather")
    if wx:
        lines.append(f"오늘 날씨: 체감온도 {wx['feel']:g}℃" + (", 발표 중인 특보: " + ", ".join(w["kind"] + w["level"] for w in wx["warnings"]) if wx["warnings"] else "")
                     + ("" if wx["live"] else " (예시 자료)") + ".")
        for t in wx["stops"]:
            lines.append(t + ".")
    msgs = [r for r in a["reassess"] if r.get("kind") == "재난문자" and r["date"] == date.today().isoformat()]
    for r in msgs[:2]:
        lines.append("오늘 받은 재난문자를 함께 확인합니다: " + r["text"].split(" → ")[0].split(": ", 1)[-1])
    if a["permits"]:
        lines.append("작업 전에 " + ", ".join(p["name"] for p in a["permits"]) + "를 받았는지 확인합니다.")
    blocked = assess.stats(a)["blocked"]
    if blocked:
        lines.append("아직 끝나지 않은 작업 전 조치가 있습니다: " + ", ".join(blocked) + ". 이 조치를 마치기 전에는 작업을 시작하지 않습니다.")
    lines.append("작업 중 위험하다고 느끼면 누구든 작업을 멈추고 대피할 수 있습니다" + (f"({stop['label']})." if stop else "."))
    lines.append("모두 이해했으면 서명해 주세요.")
    return lines


@app.get("/api/assess/<aid>/tbm")
def tbm(req):
    a = get_a(req.params["aid"])
    return {"lines": tbm_script(a, kb()), "basis": kb().cite_topic(r"안전점검회의")}


@app.post("/api/assess/<aid>/tbm")
def tbm_doc(req):
    a = get_a(req.params["aid"])
    blocks = [("title", "작업 전 안전점검회의(TBM) 기록"),
              ("table", ["일시", "시설", "작업", "작업 책임자"], [[date.today().isoformat() + "  :", a["fac"], a["work"], ""]], [2, 2, 4, 2]),
              ("h2", "전달 내용")] + [("bullet", l) for l in tbm_script(a, kb())] + [
              ("h2", "참석자 확인"), ("table", ["번", "성명", "건강 상태", "보호구", "서명"], [[str(n), "", "양호 / 이상", "착용 / 미착용", ""] for n in range(1, 9)], [1, 3, 2, 2, 2])]
    b = kb().cite_topic(r"안전점검회의")
    if b:
        blocks.append(("note", f"※ 근거: {b['reg']} {b['label']}({b['title']})"))
    fmt = req.query.get("fmt", "hwpx")
    data, ctype = export(blocks, fmt)
    log("TBM 기록지 만들기", a["work"])
    return file_response(data, f"TBM기록_{a['work'][:20]}.{fmt}", ctype)


# ------------------------------------------------------------ 공공데이터: 날씨·재난문자

def set_weather(a, wx):
    codes = {i["code"] for i in a["items"] if i["confirmed"]}
    a["weather"] = {k: wx[k] for k in ("source", "live", "region", "time", "ta", "rh", "feel", "note")}
    a["weather"]["warnings"] = feeds.active_warnings(wx)
    a["weather"]["stops"] = feeds.weather_stops(wx, a["conditions"], codes)
    a["weather"]["checked"] = date.today().isoformat()


@app.get("/api/feeds/weather")
def feed_weather(req):
    wx = feeds.weather()
    return dict(wx, active=feeds.active_warnings(wx), formula="기상청 여름철 체감온도 식(기온·습도)")


@app.post("/api/assess/<aid>/weather")
def recheck_weather(req):
    a = get_a(req.params["aid"])
    set_weather(a, feeds.weather())
    log("기상특보 다시 확인", a["work"])
    return put_a(a)


def _msg_hits(m, items):
    return [{"id": a["id"], "fac": a["fac"], "work": a["work"], "hazards": h,
             "done": any(r.get("incident") == "MSG-" + m["sn"] for r in a["reassess"])}
            for a in items for h in [feeds.message_hits(m, a)] if h]


@app.get("/api/feeds/messages")
def feed_messages(req):
    r = feeds.messages()
    items = assessments()
    for m in r["items"]:
        m["hits"] = _msg_hits(m, items)
    return r


@app.post("/api/feeds/messages/apply")
def apply_messages(req):
    r = feeds.messages()
    items = assessments()
    n = 0
    for m in r["items"]:
        for a in items:
            h = feeds.message_hits(m, a)
            if h and not any(x.get("incident") == "MSG-" + m["sn"] for x in a["reassess"]):
                a["reassess"].append({"incident": "MSG-" + m["sn"], "kind": "재난문자", "date": date.today().isoformat(),
                                      "text": f"긴급재난문자({m['kind'] or '안내'}): {m['text'][:80]} → 다시 볼 위험요인: {', '.join(h)}",
                                      "src": None, "basis": None, "source": r["source"]})
                n += 1
    save_all(items)
    log("긴급재난문자 반영", f"수시 확인 표시 {n}건 ({r['source']})")
    return {"added": n, "source": r["source"]}


# ------------------------------------------------------------ 아차사고

@app.post("/api/incidents")
def add_incident(req):
    b = req.json or {}
    text, hidden = mask((b.get("text") or "").strip())
    d = (b.get("date") or date.today().isoformat()).strip()
    if not text:
        raise HttpError(400, "무슨 일이 있었는지 적어 주세요")
    try:
        date.fromisoformat(d)
    except ValueError:
        raise HttpError(400, "날짜는 2026-10-27 형식으로 입력하세요")
    items = user_incidents()
    inc = {"id": "U" + uuid.uuid4().hex[:6], "date": d, "fac": (b.get("fac") or "").strip(), "work": (b.get("work") or "").strip(),
           "text": text, "result": mask((b.get("result") or "").strip())[0], "origin": "user", "src": None}
    items.append(inc)
    store.write("incidents.json", {"items": items})
    k = reload()
    inc = dict(inc, codes=k.codes_in(text))
    alls = assessments()
    hits = assess.reassess_hits(k, alls, inc)
    save_all(alls)
    log("아차사고 등록", f"{inc['fac']} {text[:30]}" + (f" → 수시평가 필요 {len(hits)}건" if hits else ""))
    return {"incident": inc, "hits": [{"id": a["id"], "work": a["work"], "fac": a["fac"]} for a in alls if a["id"] in hits],
            "codes": [{"code": c, "name": k.hazards[c]["name"]} for c in inc["codes"]], "basis": k.cite_topic(r"수시평가"), "masked": hidden}


# ------------------------------------------------------------ 기관 자료

@app.post("/api/kb/upload")
def kb_upload(req):
    files = (req.json or {}).get("files") or []
    if not files:
        raise HttpError(400, "올릴 파일이 없습니다")
    for f in files:
        try:
            parts = safe_parts(f.get("path") or "")
        except ValueError:
            continue
        if Path(parts[-1]).suffix.lower() not in (".xlsx", ".hwpx", ".docx", ".txt", ".pdf", ".csv"):
            raise HttpError(400, f"읽을 수 없는 형식입니다: {parts[-1]}")
        dst = KB_ROOT.joinpath("올린 자료", *parts)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(base64.b64decode(f["b64"]))
    log("기관 자료 올리기", ", ".join(f.get("path", "") for f in files))
    reload()
    return state(req)


@app.post("/api/kb/sample")
def kb_sample(req):
    store.remove_tree("kb")
    _copy_sample()
    reload()
    log("기관 자료를 모의자료로 되돌림")
    return state(req)


@app.get("/api/log")
def get_log(req):
    return {"items": list(reversed(store.read_log("history.jsonl")))[:200]}


def main():
    import argparse
    ap = argparse.ArgumentParser(description="현장 위험성평가 AI 실행")
    ap.add_argument("--port", type=int, default=cfg["port"])
    ap.add_argument("--host", default=cfg["host"])
    ap.add_argument("--no-browser", action="store_true")
    ar = ap.parse_args()
    kb()
    app.run(ar.host, ar.port, not ar.no_browser, "현장 위험성평가 AI")


if __name__ == "__main__":
    main()
