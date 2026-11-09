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

import ai
import assess
import feeds
import laws
from kb import KB

VERSION = "1.1.0"
HERE = Path(__file__).resolve().parent
SAMPLE = HERE / "sample_data"
IMG = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}

cfg = Config(HERE, {"app_title": "무사히(현장 위험성평가 AI)", "port": 8105})
llm = LLM(cfg["llm"])
store = Store(cfg.data_dir)
KB_ROOT = store.path("kb")
PHOTOS = store.path("photos")
app = App(HERE / "static")
webcommon.register(app, cfg, llm, "무사히(현장 위험성평가 AI)", VERSION)
ABOUT = {
    "lead": "위험요인 찾기·가능성·중대성·작업 시작 판정은 규칙과 기관 규정으로 하고, 모델은 낱말로 못 찾은 위험을 '제안'만 합니다. 모델이 없어도 같은 결과가 나옵니다.",
    "pipeline": [("작업 설명 읽기", "높이·인원·체감온도·운영 중·실외 여부를 읽고, 개인정보는 먼저 가림"),
                 ("위험요인 찾기", "기관 위험요인 목록의 '찾는 낱말'로 찾고 근거 문구를 붙임"),
                 ("가능성·중대성", "조건과 최근 같은 작업의 아차사고로 조정, 조정마다 이유와 원본 행"),
                 ("규정 기준 판정", "위험성 6 이상은 작업 전 감소대책 완료(규정 조문에서 읽은 값)"),
                 ("모델 제안(선택)", "목록에 있는 코드이고 근거 문구가 설명에 그대로 있어야 받음, 사진은 '현장 확인 필요'"),
                 ("법령 원문(공공데이터)", "위험요인의 관련 기준(법령명·주제)으로 법제처 Open API에서 조문을 찾아 원문·시행일을 붙임, 평가표·해설·물어보기의 근거로 씀"),
                 ("날씨·재난문자", "기상청 체감온도·기상특보로 작업 시작 판정, 긴급재난문자와 겹치는 평가에 수시평가 표시"),
                 ("평가표·TBM", "평가표·TBM 문안·서명지, 아차사고가 나면 수시평가 표시"),
                 ("아차사고 조치·결과보고", "조치·담당·기한·조치 전후 사진을 기록하고 결과보고서를 미리 보며 고쳐 내려받음, 조치 완료는 같은 작업 평가의 감소대책에, 미완료 조치는 오늘 작업 브리핑에 반영"),
                 ("오늘 작업 브리핑", "기상청 체감온도·특보, 재난문자, 아차사고, 미완료 조치를 평가마다 엮어 작업 중지·시작 전 조치·주의·시작 가능을 규칙으로 판정, AI는 우선순위 문장만"),
                 ("생성형 AI 문장(선택)", "물어보기(이어 묻기)·위험요인 해설·종합 의견·TBM 문안·문단 다듬기. 근거 사실에 없는 숫자·위험요인 코드가 있으면 버리고 규칙 문장")],
    "guards": ["가능성·중대성 조정과 작업 시작 판정은 모델이 하지 않고 규칙으로만 합니다.",
               "모델이 제안한 위험요인은 기관 목록에 있는 코드여야 하고, 근거 문구가 작업 설명에 그대로 있어야 받습니다.",
               "사진에서 모델이 본 위험은 '현장 확인 필요'로 두고, 담당자가 확인해야 평가표에 들어갑니다.",
               "판단 기준값(6 이상·3 이상, 폭염 33℃·35℃, 높이 2m)은 기관 규정 조문에서 읽고, 없으면 '기본값'으로 표시합니다.",
               "위험요인을 하나도 찾지 못하면 '작업 시작 가능'이 아니라 '평가가 끝나지 않음'으로 막습니다.",
               "높이 2m 이상 작업인데 떨어짐을 찾지 못하면 지어내지 않고 먼저 묻습니다.",
               "현장에서 보탠 낱말은 작업 설명에 실제로 있던 말만 받고, 따로 표시하며 뺄 수 있습니다.",
               "관련 기준은 법령 이름과 주제까지만 적고, 조문 번호와 본문은 법제처 Open API에서 받은 원문만 씁니다. 받지 못하면 조문을 지어내지 않고 국가법령정보센터 링크만 둡니다.",
               "기상특보에 따른 작업 중지는 특보 종류와 작업 조건(실외·높은 곳)으로 규칙만으로 판정하고, 체감온도는 기상청 공개 식으로 계산합니다.",
               "작업 설명·아차사고에 적은 개인정보(전화·주민번호·계좌 등)는 저장·모델 전달 전에 ○○○로 가립니다.",
               "AI가 쓴 문장(답변·해설·종합 의견·TBM 문안·브리핑)에 근거 사실에 없는 숫자나 위험요인 코드가 하나라도 있으면 버리고 규칙 문장을 쓰며, 이유를 화면에 표시합니다.",
               "아차사고는 조치를 하나도 적지 않았거나 끝나지 않은 조치가 있으면 '완료'로 바꿀 수 없고, 결과보고서에는 산업재해조사표(법정 서식)를 대신하지 않는다는 안내를 넣습니다.",
               "공개 시연판은 화면에서 모델 설정을 바꿀 수 없고(키 유출 방지), 모델 호출은 1분에 40번으로 묶습니다."],
    "data": ["시연 자료(위험요인 목록·규정·작업·아차사고)는 모두 지어낸 모의자료입니다. 기관 자료로 바꾸면 그대로 동작합니다.",
             "날씨(기상청 단기예보·기상특보)와 긴급재난문자(행정안전부)는 키를 넣으면 실제 자료를, 키가 없거나 연결이 안 되면 예시 자료를 쓰고 화면에 출처를 표시합니다.",
             "관련 법령 조문은 법제처 국가법령정보 공동활용 Open API(인증값 LAW_OC)에서 받고, 인증값이 없으면 국가법령정보센터 링크만 보여 줍니다.",
             "시연용 사진은 그림이며, 실제 비전 모델의 정확도는 기관 PC에서 실측해야 합니다.",
             "자료는 이 PC의 작업 폴더(data)에만 저장되고, 화면은 이 PC에서만 열립니다."],
}
webcommon.register_about(app, HERE, ABOUT)

STATE = {"kb": None, "brief_ai": None}


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

def _fu_brief(fu):
    fu = fu or {}
    acts = fu.get("actions", [])
    return {"status": fu.get("status", "접수"), "actions": len(acts), "open": sum(1 for m in acts if not m.get("done")), "photos": len(fu.get("photos", []))}


@app.get("/api/state")
def state(req):
    k = kb()
    today = date.today().isoformat()
    items = assessments()
    fus = followups()
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
        "kb": k.summary(), "tasks": k.tasks, "incidents": sorted([dict(i, fu=_fu_brief(fus.get(i["id"]))) for i in k.incidents], key=lambda x: x["date"], reverse=True),
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


def sheet_blocks(a):
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
                 _mlist(it), it["R_after"], _law_cell(it)]
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
    law_arts = [(it["name"], x) for it in items for x in laws.articles_for(it["law"])["items"]]
    if law_arts:
        blocks += [("h2", f"관련 법령 조문(출처: {laws.SRC})")] + [
            ("bullet", f"{n}: {laws.cite(x)}" + (f", 시행 {x['date']}" if x["date"] else "") + f" — {x['text'][:300]}") for n, x in law_arts]
    if a["permits"]:
        blocks += [("h2", "작업 전 필요한 허가")] + [("bullet", p["name"] + (f" (근거: {p['basis']['reg']} {p['basis']['label']})" if p.get("basis") else "")) for p in a["permits"]]
    if a["reassess"]:
        blocks += [("h2", "수시평가 사유")] + [("bullet", f"{r['date']} {r.get('kind', '아차사고')}: {r['text']}") for r in a["reassess"]]
    blocks += [("h2", "평가 참여자 확인"), ("table", ["구분", "성명", "서명"], [["작업 책임자", "", ""], ["작업자", "", ""], ["작업자", "", ""], ["안전 담당", "", ""]], [2, 3, 3]),
               ("note", f"※ 작성: 무사히(현장 위험성평가 AI, {a['engine']}). 위험요인·가능성·중대성은 담당자가 현장에서 확인해 고친 값입니다. 기록은 규정에 따라 보존합니다.")]
    pics = []
    for n in a.get("photos") or []:
        p = PHOTOS / n
        if p.exists():
            pics.append(("image", f"data:{IMG[p.suffix]};base64," + base64.b64encode(p.read_bytes()).decode(), "작업 현장 사진"))
    if pics:
        at = next(i for i, b in enumerate(blocks) if b[0] == "h2" and b[1] == "평가 참여자 확인")
        blocks[at:at] = [("h2", "현장 사진")] + pics
    return blocks


REPORT_KINDS = {"title", "h1", "h2", "h3", "p", "bullet", "note", "summary", "table", "image"}


def _clean_blocks(raw):
    """화면에서 고친 블록 목록을 검사해 내보내기 형식(튜플)으로 바꾼다."""
    from core.export import image_info
    out = []
    for b in raw if isinstance(raw, list) else []:
        if not isinstance(b, list) or not b or b[0] not in REPORT_KINDS:
            raise HttpError(400, "평가표 내용 형식이 올바르지 않습니다")
        k = b[0]
        if k == "table":
            out.append(("table", [str(x) for x in b[1]], [[str(c) for c in r] for r in b[2]], b[3] if len(b) > 3 else None))
        elif k == "summary":
            out.append(("summary", [str(x) for x in b[1] if str(x).strip()]))
        elif k == "image":
            try:
                image_info(b[1])
            except Exception as e:
                raise HttpError(400, f"그림을 읽지 못했습니다: {e}")
            out.append(("image", b[1], str(b[2]) if len(b) > 2 else ""))
        else:
            out.append((k, str(b[1])))
    if not out:
        raise HttpError(400, "평가표 내용이 비어 있습니다")
    return out


@app.get("/api/assess/<aid>/preview")
def sheet_preview(req):
    """화면 미리보기·수정용 평가표 블록(내려받기와 같은 내용, 첨부 사진 포함)."""
    return {"blocks": [list(b) for b in sheet_blocks(get_a(req.params["aid"]))]}


@app.post("/api/assess/<aid>/export")
def export_sheet(req):
    a = get_a(req.params["aid"])
    b = req.json or {}
    blocks = _clean_blocks(b["blocks"]) if b.get("blocks") else sheet_blocks(a)
    fmt = req.query.get("fmt", "hwpx")
    data, ctype = export(blocks, fmt)
    log("위험성평가표 내보내기", a["work"] + (" (화면에서 고침)" if b.get("blocks") else ""))
    return file_response(data, f"위험성평가표_{a['fac']}_{a['work'][:20]}.{fmt}", ctype)


@app.post("/api/assess/<aid>/xlsx")
def export_xlsx(req):
    a = get_a(req.params["aid"])
    items = [i for i in a["items"] if i["confirmed"]]
    rows = [[n, i["name"], i["type"], i["L"], i["S"], i["R"], i["level_label"], _mlist(i), i["R_after"],
             "; ".join(r["text"] for r in i["reasons"]), _law_cell(i)]
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
                    note=f"무사히(현장 위험성평가 AI) {VERSION} · 작성일 {s['today']}")
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


def _law_cell(it):
    arts = laws.articles_for(it["law"])["items"]
    s = "; ".join(laws.cite(x) for x in arts) or it["law"]
    return s + (f" / {it['basis']['reg']} {it['basis']['label']}" if it.get("basis") else "")


@app.get("/api/laws/<code>")
def law_articles(req):
    """위험요인의 관련 법령 조문 원문(법제처 Open API). 키가 없으면 링크만."""
    h = kb().hazards.get(req.params["code"])
    if not h:
        raise HttpError(404, "위험요인을 찾지 못했습니다")
    return dict(laws.articles_for(h["law"]), code=h["code"], law_text=h["law"])


# ------------------------------------------------------------ 생성형 AI(사실 대조)

def _item_facts(a, it):
    f = [f"작업: {a['fac']} {a['work']}. 작업 설명: {a['text']}",
         f"위험요인 {it['code']} {it['name']}({it['type']}): 가능성 {it['L']} × 중대성 {it['S']} = 위험성 {it['R']}, 판단 {it['level_label']}, 감소대책 후 위험성 {it['R_after']}"]
    f += [f"판단 이유: {r['text']}" for r in it["reasons"]]
    f += [f"감소대책: {m['text']}" + (" (완료)" if m["done"] else "") for m in it["measures"]]
    if it.get("law"):
        f.append(f"관련 기준: {it['law']}")
        f += [f"법령 원문 {laws.cite(x)}: {x['text'][:500]}" for x in laws.articles_for(it["law"])["items"]]
    if it.get("basis"):
        f.append(f"기관 규정: {it['basis']['reg']} {it['basis']['label']}({it['basis']['title']})")
    return f


@app.post("/api/assess/<aid>/explain")
def explain_item(req):
    """위험요인 하나를 작업자가 이해하기 쉽게 풀어 쓴다(왜 위험한지, 대책 순서)."""
    a = get_a(req.params["aid"])
    code = (req.json or {}).get("code")
    it = next((i for i in a["items"] if i["code"] == code), None)
    if not it:
        raise HttpError(404, "위험요인을 찾지 못했습니다")
    rule = f"{it['name']} 위험은 가능성 {it['L']}, 중대성 {it['S']}로 위험성 {it['R']}({it['level_label']})임. 먼저 " + ", ".join(m["text"] for m in it["measures"][:2]) + "을(를) 함."
    res = ai.guard(llm, "위험성평가표에 들어갈 '해설' 문단을 한국어 2~3문장 공문체(~함, ~임)로 쓰세요. 이 작업에서 왜 위험한지와 감소대책을 어떤 순서로 하면 좋은지 말하세요.",
                   _item_facts(a, it), rule)
    log("위험요인 해설", f"{a['work']} {code} {res['mode']}")
    return dict(res, code=code)


@app.post("/api/assess/<aid>/opinion")
def opinion(req):
    """평가표 끝의 '종합 의견'. 판정·위험성·날씨·수시평가 사실에서만 쓴다."""
    a = get_a(req.params["aid"])
    st = assess.stats(a)
    items = [i for i in a["items"] if i["confirmed"]]
    facts = [f"작업: {a['fac']} {a['work']}, 상태 {a['status']}, 판정 {'작업 시작 가능' if st['ready'] else '작업 전 조치 필요'}"]
    facts += [f"{i['code']} {i['name']}: 위험성 {i['R']}({i['level_label']}), 미완료 대책 {sum(1 for m in i['measures'] if not m['done'])}건" for i in items]
    wx = a.get("weather")
    if wx:
        facts.append(f"작업 당일 체감온도 {wx['feel']:g}℃, 특보 {', '.join(w['kind'] + w['level'] for w in wx['warnings']) or '없음'}, 작업 중지 {'; '.join(wx['stops']) or '없음'}")
    facts += [f"수시평가 사유: {r['text']}" for r in a["reassess"]]
    rule = []
    if st["blocked"]:
        rule.append("작업 전에 " + ", ".join(st["blocked"]) + "의 감소대책을 마쳐야 작업을 시작할 수 있음.")
    if st["weather_stops"]:
        rule.append("기상특보로 " + "; ".join(st["weather_stops"]) + ".")
    if a["reassess"]:
        rule.append(f"수시평가 사유 {len(a['reassess'])}건이 있어 작업 책임자가 현장을 다시 확인해야 함.")
    if st["ready"]:
        rule.append("확인한 위험요인의 작업 전 대책이 끝나 작업을 시작할 수 있음. 작업 중 관리 대상은 작업 책임자가 수시로 확인함.")
    rule.append("작업 전 안전점검회의(TBM)에서 위 내용을 전달하고 참석자 서명을 받음.")
    res = ai.guard(llm, "위험성평가표 끝의 '종합 의견'을 공문체(~함, ~임)로 3~4개 항목으로 쓰세요. 한 줄에 한 항목, 앞에 기호를 붙이지 마세요. 작업 시작 판정을 그대로 따르고 먼저 할 일부터 쓰세요.",
                   facts, "\n".join(rule), max_tokens=800)
    res["lines"] = [x.strip(" -·•*\t") for x in res["text"].splitlines() if x.strip(" -·•*\t")]
    log("평가 종합 의견", res["mode"])
    return res


@app.post("/api/report/polish")
def polish(req):
    text = ((req.json or {}).get("text") or "").strip()
    if not text:
        raise HttpError(400, "다듬을 문장이 없습니다")
    text = mask(text[:3000])[0]
    if not llm.enabled:
        return {"text": text, "mode": "규칙 기반", "dropped": "모델이 연결되지 않아 원문을 그대로 둡니다"}
    res = ai.guard(llm, "아래 사실은 위험성평가표의 한 문단입니다. 뜻과 숫자를 바꾸지 말고 공문체(~함, ~임)로 간결하게 다듬어 한 문단으로만 출력하세요. 제목·설명은 붙이지 마세요.",
                   [text], text, max_tokens=900)
    res["dropped"] = res["dropped"].replace("규칙 문장", "원문")
    return res


@app.post("/api/assess/<aid>/tbm/ai")
def tbm_ai(req):
    """TBM 낭독 문안을 현장에서 말하기 쉬운 말로. 규칙 문안의 사실(위험요인·대책·날씨·재난문자) 밖의 내용은 쓰지 않는다."""
    a = get_a(req.params["aid"])
    lines = tbm_script(a, kb())
    facts = lines + [x for it in a["items"] if it["confirmed"] for x in _item_facts(a, it)[1:3]]
    res = ai.guard(llm, "작업 전 안전점검회의(TBM)에서 작업 책임자가 소리 내어 읽을 문안을 쓰세요. 존댓말, 짧은 문장, 6~9줄, 한 줄에 한 문장, 앞에 기호를 붙이지 마세요. "
                        "작업 중지 권리와 서명 안내는 꼭 넣으세요.", facts, "\n".join(lines), max_tokens=900)
    res["lines"] = [x.strip(" -·•*\t") for x in res["text"].splitlines() if x.strip(" -·•*\t")]
    log("TBM 문안 AI", res["mode"])
    return res


@app.post("/api/ask")
def ask(req):
    b = req.json or {}
    q = (b.get("q") or "").strip()
    if not q:
        raise HttpError(400, "질문을 입력하세요")
    q, hidden = mask(q)
    hist = [{"q": mask(str(h.get("q") or ""))[0][:300], "a": str(h.get("a") or "")[:1200]}
            for h in (b.get("history") or [])[-4:] if isinstance(h, dict)]
    r = ai.ask(kb(), q, assessments(), llm, hist)
    r["masked"] = hidden
    log("질문", q)
    return r


@app.get("/api/briefing")
def get_briefing(req):
    r = ai.briefing(kb(), assessments(), feeds.weather(), feeds.messages(), followups())
    r["ai"] = STATE.get("brief_ai")
    return r


@app.post("/api/briefing/ai")
def briefing_ai(req):
    r = ai.briefing(kb(), assessments(), feeds.weather(), feeds.messages(), followups())
    res = ai.guard(llm, "공공시설 안전 담당자에게 '오늘 작업 브리핑'을 공문체(~함, ~임) 4~6문장으로 쓰세요. 작업마다 정해진 판정(작업 중지·시작 전 조치·주의·시작 가능)을 그대로 따르고, "
                        "먼저 멈추거나 조치할 작업과 이유, 오늘 날씨·재난문자에서 챙길 점을 말하세요.", r["facts"], r["rule"], max_tokens=900)
    STATE["brief_ai"] = res
    log("오늘 작업 브리핑", res["mode"])
    return res


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


# ------------------------------------------------------------ 아차사고 조치·결과보고

FU_STATES = ("접수", "조치 중", "완료")


def followups():
    return store.read("followups.json", {"items": {}})["items"]


def get_inc(iid):
    for i in kb().incidents:
        if i["id"] == iid:
            return i
    raise HttpError(404, "아차사고를 찾지 못했습니다")


def get_fu(iid):
    fu = followups().get(iid) or {}
    return {"status": fu.get("status", "접수"), "cause": fu.get("cause", ""), "prevent": fu.get("prevent", []),
            "actions": fu.get("actions", []), "photos": fu.get("photos", []), "applied": fu.get("applied", []), "updated": fu.get("updated", "")}


def put_fu(iid, fu):
    items = followups()
    items[iid] = dict(fu, updated=date.today().isoformat())
    store.write("followups.json", {"items": items})


def _inc_hazards(inc):
    k = kb()
    return [k.hazards[c] for c in inc.get("codes", []) if c in k.hazards]


def _inc_view(inc):
    fu = get_fu(inc["id"])
    rel = assess.related(inc, assessments())
    return {"incident": inc, "followup": fu,
            "hazards": [{"code": h["code"], "name": h["name"], "type": h["type"], "measures": h["measures"], "law": h["law"]} for h in _inc_hazards(inc)],
            "related": [{"id": a["id"], "fac": a["fac"], "work": a["work"], "status": a["status"]} for a in rel],
            "basis": kb().cite_topic(r"수시평가")}


def _inc_facts(inc, fu):
    f = [f"아차사고 {inc['date']} {inc['fac']} {inc['work']}: {inc['text']}" + (f" (결과: {inc['result']})" if inc.get("result") else "")]
    for h in _inc_hazards(inc):
        f.append(f"{h['code']} {h['name']}({h['type']}): 감소대책 {'; '.join(h['measures'])}" + (f", 관련 기준: {h['law']}" if h["law"] else ""))
    f += [f"조치: {m['text']}" + (f" (담당 {m['owner']})" if m.get("owner") else "") + (" 완료" if m.get("done") else " 미완료") for m in fu["actions"]]
    if fu["cause"]:
        f.append(f"담당자가 적은 원인: {fu['cause']}")
    f += [f"관련 위험성평가: {a['fac']} {a['work']}" for a in assess.related(inc, assessments())]
    return f


def _rule_cause(inc):
    hz = _inc_hazards(inc)
    names = ", ".join(h["name"] for h in hz) or "분류되지 않은 위험"
    ms = [m for h in hz for m in h["measures"][:2]]
    return (f"'{inc['work'] or '해당 작업'}'에서 {names} 위험이 드러난 사례임. 기록된 경위는 '{inc['text']}'임."
            + (f" 위험요인 목록의 감소대책({'; '.join(ms)}) 중 지켜지지 않은 것이 있었는지 현장에서 확인해야 함." if ms else " 현장에서 원인을 확인해야 함."))


def _rule_prevent(inc, fu):
    done = {m["text"] for m in fu["actions"]}
    out = [m["text"] + (" (완료)" if m.get("done") else " (진행 중)") for m in fu["actions"]]
    out += [m for h in _inc_hazards(inc) for m in h["measures"][:3] if m not in done][:4]
    out.append("같은 작업의 위험성평가를 수시평가로 다시 하고, 작업 전 안전점검회의(TBM)에서 이 사례를 공유함.")
    return out


def inc_blocks(inc):
    fu = get_fu(inc["id"])
    hz = _inc_hazards(inc)
    rel = assess.related(inc, assessments())
    blocks = [("title", "아차사고 조치 결과보고"),
              ("table", ["발생일", "시설", "작업", "결과(피해)", "처리 상태"], [[inc["date"], inc["fac"], inc["work"], inc.get("result") or "", fu["status"]]], [2, 2, 4, 3, 1]),
              ("h2", "1. 발생 경위"), ("p", inc["text"]),
              ("h2", "2. 위험요인 분류")]
    blocks += [("bullet", f"{h['name']}({h['type']})" + (f" · 관련 기준: {h['law']}" if h["law"] else "")) for h in hz] or [("bullet", "분류된 위험요인 없음(위험요인 목록의 찾는 낱말에 걸리지 않음)")]
    if inc.get("src"):
        blocks.append(("note", f"※ 원본 기록: {inc['src']['file']} {inc['src']['loc']}"))
    blocks += [("h2", "3. 원인"), ("p", fu["cause"] or _rule_cause(inc)),
               ("h2", "4. 조치 내용")]
    if fu["actions"]:
        blocks.append(("table", ["번호", "조치", "담당", "기한", "완료일", "상태"],
                       [[str(n), m["text"], m.get("owner", ""), m.get("due", ""), m.get("completed", ""), "완료" if m.get("done") else "진행 중"]
                        for n, m in enumerate(fu["actions"], 1)], [1, 7, 2, 2, 2, 1]))
    else:
        blocks.append(("p", "기록된 조치가 없습니다."))
    pics = []
    for ph in fu["photos"]:
        p = PHOTOS / ph["name"]
        if p.exists():
            pics.append(("image", f"data:{IMG[p.suffix]};base64," + base64.b64encode(p.read_bytes()).decode(),
                         f"조치 {'전' if ph.get('stage') == 'before' else '후'}" + (f" · {ph['caption']}" if ph.get("caption") else "")))
    if pics:
        blocks += [("h2", "5. 조치 전·후 사진")] + pics
    n = 6 if pics else 5
    blocks += [("h2", f"{n}. 재발 방지 대책")] + [("bullet", x) for x in (fu["prevent"] or _rule_prevent(inc, fu))]
    blocks += [("h2", f"{n + 1}. 위험성평가 반영")]
    blocks += [("bullet", f"{a['fac']} {a['work']}: " + ("완료한 조치를 감소대책에 반영함" if a["id"] in fu["applied"] else "수시평가 필요로 표시됨, 조치 완료 뒤 감소대책에 반영 예정"))
               for a in rel] or [("bullet", "같은 작업의 위험성평가가 없습니다. 이 작업을 새로 평가하세요.")]
    blocks += [("h2", "보고자 확인"), ("table", ["구분", "부서", "성명", "서명"], [["작성자", "", "", ""], ["확인자(안전 담당)", "", "", ""]], [2, 3, 3, 3]),
               ("note", "※ 이 보고서는 기관 내부 결과보고용입니다. 근로자가 다치는 산업재해가 발생한 경우에는 산업안전보건법령에 따른 산업재해조사표를 별도로 작성·제출해야 합니다."),
               ("note", f"※ 작성: 무사히(현장 위험성평가 AI). 경위·조치는 담당자가 입력한 내용이며, 원인·재발 방지 문장은 {'AI 초안을 담당자가 확인한 것' if llm.enabled else '규칙으로 만든 초안'}입니다.")]
    return blocks


@app.get("/api/incidents/<iid>")
def inc_one(req):
    return _inc_view(get_inc(req.params["iid"]))


def _apply_actions(inc, fu):
    """완료한 조치를 같은 작업 평가의 해당 위험요인 감소대책에 '완료'로 넣는다(이미 있으면 건너뜀)."""
    done = [m for m in fu["actions"] if m.get("done")]
    if not done:
        return []
    alls = assessments()
    hit = []
    words = lambda t: set(re.findall(r"[가-힣A-Za-z]{2,}", t))  # noqa: E731
    k = kb()
    for a in assess.related(inc, alls):
        cand = [i for i in a["items"] if i["code"] in inc.get("codes", [])] or a["items"]
        if not cand:
            continue
        for m in done:
            # 조치 낱말과 위험요인 이름·감소대책 낱말이 가장 많이 겹치는 위험요인에 넣는다
            it = max(cand, key=lambda i: len(words(m["text"]) & words(i["name"] + " " + " ".join(k.hazards.get(i["code"], {}).get("measures", [])))))
            t = f"{m['text']} (아차사고 {inc['date']} 조치)"
            if t not in {x["text"] for x in it["measures"]}:
                it["measures"].append({"text": t, "done": True, "owner": m.get("owner", ""), "due": m.get("due", ""), "completed": m.get("completed") or date.today().isoformat()})
        assess.rescore(kb(), a)
        hit.append(a["id"])
    save_all(alls)
    return hit


@app.post("/api/incidents/<iid>/followup")
def inc_followup(req):
    inc = get_inc(req.params["iid"])
    b = req.json or {}
    fu = get_fu(inc["id"])
    if "status" in b:
        if b["status"] not in FU_STATES:
            raise HttpError(400, "상태는 접수·조치 중·완료 중 하나입니다")
        fu["status"] = b["status"]
    if "cause" in b:
        fu["cause"] = mask(str(b["cause"] or "").strip())[0][:2000]
    if "prevent" in b:
        fu["prevent"] = [mask(str(x).strip())[0][:300] for x in b["prevent"] or [] if str(x).strip()][:12]
    if "actions" in b:
        old = {m["text"]: m for m in fu["actions"]}
        acts = []
        for m in b["actions"] or []:
            t = mask(str(m.get("text") or "").strip())[0][:200]
            if not t:
                continue
            d = bool(m.get("done"))
            acts.append({"text": t, "owner": str(m.get("owner") or "")[:40], "due": str(m.get("due") or "")[:10], "done": d,
                         "completed": (old.get(t, {}).get("completed") or date.today().isoformat()) if d else ""})
        fu["actions"] = acts[:20]
    if "photos" in b:  # 사진 빼기·설명 고치기(이미 올린 사진만)
        have = {p["name"]: p for p in fu["photos"]}
        fu["photos"] = [dict(have[p["name"]], caption=str(p.get("caption") or "")[:60], stage="before" if p.get("stage") == "before" else "after")
                        for p in b["photos"] or [] if p.get("name") in have]
    if fu["status"] == "완료":
        if not fu["actions"]:
            raise HttpError(400, "조치를 하나 이상 적어야 완료로 바꿀 수 있습니다")
        if not all(m["done"] for m in fu["actions"]):
            raise HttpError(400, "끝나지 않은 조치가 있어 완료로 바꿀 수 없습니다")
        fu["applied"] = sorted(set(fu["applied"]) | set(_apply_actions(inc, fu)))
    elif fu["actions"] and fu["status"] == "접수":
        fu["status"] = "조치 중"
    put_fu(inc["id"], fu)
    log("아차사고 조치", f"{inc['fac']} {inc['text'][:24]} → {fu['status']}" + (f", 평가 {len(fu['applied'])}건 감소대책 반영" if fu["status"] == "완료" else ""))
    return _inc_view(inc)


@app.post("/api/incidents/<iid>/photo")
def inc_photo(req):
    inc = get_inc(req.params["iid"])
    b = req.json or {}
    fu = get_fu(inc["id"])
    if len(fu["photos"]) >= 8:
        raise HttpError(400, "사진은 8장까지 넣을 수 있습니다")
    ext = Path(b.get("name") or "x.jpg").suffix.lower()
    if ext not in IMG:
        raise HttpError(400, "PNG·JPG 사진만 넣을 수 있습니다")
    raw = base64.b64decode(b.get("b64") or "")
    if not raw or len(raw) > 8 * 1024 * 1024:
        raise HttpError(400, "사진은 8MB까지 넣을 수 있습니다")
    name = uuid.uuid4().hex[:10] + (".jpg" if ext == ".jpeg" else ext)
    PHOTOS.mkdir(parents=True, exist_ok=True)
    (PHOTOS / name).write_bytes(raw)
    fu["photos"].append({"name": name, "stage": "before" if b.get("stage") == "before" else "after", "caption": str(b.get("caption") or "")[:60]})
    put_fu(inc["id"], fu)
    log("아차사고 사진", f"{inc['fac']} {'조치 전' if b.get('stage') == 'before' else '조치 후'}")
    return _inc_view(inc)


@app.post("/api/incidents/<iid>/ai")
def inc_ai(req):
    """원인(cause)·재발 방지(prevent) 초안. 등록 내용·조치·위험요인 목록 사실에서만 쓰고 대조한다."""
    inc = get_inc(req.params["iid"])
    part = (req.json or {}).get("part")
    fu = get_fu(inc["id"])
    facts = _inc_facts(inc, fu)
    if part == "cause":
        res = ai.guard(llm, "아차사고 결과보고서의 '원인' 문단을 공문체(~함, ~임) 2~3문장으로 쓰세요. 기록된 경위와 위험요인 목록의 감소대책 중 지켜지지 않았을 수 있는 것을 짚되, "
                            "사실에 없는 원인을 단정하지 말고 '확인 필요'로 쓰세요.", facts, _rule_cause(inc))
    elif part == "prevent":
        rule = _rule_prevent(inc, fu)
        res = ai.guard(llm, "아차사고 결과보고서의 '재발 방지 대책'을 공문체(~함)로 3~5개 항목으로 쓰세요. 한 줄에 한 항목, 앞에 기호를 붙이지 마세요. 이미 한 조치와 위험요인 목록의 감소대책 안에서만 쓰세요.",
                       facts, "\n".join(rule), max_tokens=800)
        res["lines"] = [x.strip(" -·•*\t") for x in res["text"].splitlines() if x.strip(" -·•*\t")]
    else:
        raise HttpError(400, "part는 cause 또는 prevent입니다")
    log("아차사고 보고 AI", f"{part} {res['mode']}")
    return res


@app.get("/api/incidents/<iid>/preview")
def inc_preview(req):
    return {"blocks": [list(b) for b in inc_blocks(get_inc(req.params["iid"]))]}


@app.post("/api/incidents/<iid>/export")
def inc_export(req):
    inc = get_inc(req.params["iid"])
    b = req.json or {}
    blocks = _clean_blocks(b["blocks"]) if b.get("blocks") else inc_blocks(inc)
    fmt = req.query.get("fmt", "hwpx")
    data, ctype = export(blocks, fmt)
    log("아차사고 결과보고 내보내기", f"{inc['fac']} {inc['work']}" + (" (화면에서 고침)" if b.get("blocks") else ""))
    return file_response(data, f"아차사고_결과보고_{inc['fac']}_{inc['date']}.{fmt}", ctype)


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
    ap = argparse.ArgumentParser(description="무사히(현장 위험성평가 AI) 실행")
    ap.add_argument("--port", type=int, default=cfg["port"])
    ap.add_argument("--host", default=cfg["host"])
    ap.add_argument("--no-browser", action="store_true")
    ar = ap.parse_args()
    kb()
    app.run(ar.host, ar.port, not ar.no_browser, "무사히(현장 위험성평가 AI)")


if __name__ == "__main__":
    main()
