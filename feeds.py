"""공공데이터 연동: 기상청 날씨(체감온도·기상특보)와 행정안전부 긴급재난문자.

키가 없거나 인터넷이 막히면 '예시 자료'로 같은 흐름을 보여 준다(화면에 출처를 항상 표시).
- 체감온도: 기상청 단기예보 조회서비스(초단기실황)의 기온·습도로 기상청 여름철 체감온도 식을 써서 계산
  (식 출처: 기상자료개방포털 체감온도 안내 data.kma.go.kr/climate/windChill/selectWindChillChart.do)
- 기상특보: 기상청 기상특보 조회서비스(getWthrWrnList) 최근 발표 제목
- 긴급재난문자: 재난안전데이터공유플랫폼 긴급재난문자 API
키는 환경변수로만 받는다: DATA_GO_KR_KEY(공공데이터포털), SAFETYDATA_KEY(재난안전데이터공유플랫폼).
"""
import json
import math
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

TIMEOUT = 6
KMA_NCST = "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtNcst"
KMA_WRN = "http://apis.data.go.kr/1360000/WthrWrnInfoService/getWthrWrnList"
# 기상청 API허브(apihub.kma.go.kr)의 공공데이터포털 형식(typ02) 주소. 키 이름은 authKey
HUB = os.environ.get("KMA_HUB_TYP02", "https://apihub.kma.go.kr/api/typ02/openApi")
HUB_NCST = HUB + "/VilageFcstInfoService_2.0/getUltraSrtNcst"
HUB_WRN = HUB + "/WthrWrnInfoService/getWthrWrnList"  # 특보 목록: API허브 주소 형식은 미확인(실패하면 특보 없이 기온만)
DSSP_MSG = "https://www.safetydata.go.kr/V2/api/DSSP-IF-00247"

# 기관 위치(환경변수로 바꿈). 격자 nx·ny는 기상청 단기예보 격자, stn은 기상특보 지점 번호.
REGION = os.environ.get("DISASTER_REGION", "서울특별시 도봉구")
NX, NY = os.environ.get("WEATHER_NX", "61"), os.environ.get("WEATHER_NY", "129")
STN = os.environ.get("WEATHER_STN", "109")

WARN_KINDS = ["폭염", "한파", "강풍", "풍랑", "호우", "대설", "태풍", "건조", "황사", "폭풍해일"]
STOP_HIGH = {"강풍", "호우", "대설", "태풍"}  # 실외 높은 곳 작업을 멈출 특보
OUTDOOR_ONLY = {"폭염", "강풍", "태풍", "호우", "대설", "한파", "홍수"}  # 실외 작업에만 해당하는 재난
# 재난문자 종류 → 다시 볼 위험요인 코드(기관 위험요인 목록의 코드)
MSG_CODES = {"폭염": ["H07"], "강풍": ["H01", "H11"], "태풍": ["H01", "H11"], "호우": ["H02", "H03", "H05"],
             "홍수": ["H03", "H05"], "대설": ["H01", "H02"], "한파": ["H02"], "지진": ["H11"], "화재": ["H09"], "산불": ["H09"]}


def feels_like(ta, rh):
    """기상청 여름철 체감온도(℃). Tw는 Stull(2011) 습구온도 추정식."""
    tw = (ta * math.atan(0.151977 * math.sqrt(rh + 8.313659)) + math.atan(ta + rh) - math.atan(rh - 1.67633)
          + 0.00391838 * rh ** 1.5 * math.atan(0.023101 * rh) - 4.686035)
    return round(-0.2442 + 0.55399 * tw + 0.45535 * ta - 0.0022 * tw * tw + 0.00278 * tw * ta + 3.0, 1)


def _get(url, params):
    q = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    with urllib.request.urlopen(url + "?" + q, timeout=TIMEOUT) as r:
        raw = r.read().decode("utf-8", "replace")
    try:
        return json.loads(raw)
    except ValueError:
        m = re.search(r"<returnAuthMsg>(.*?)</returnAuthMsg>|<errMsg>(.*?)</errMsg>", raw)
        raise RuntimeError(m.group(1) or m.group(2) if m else "JSON이 아닌 응답")


def _items(d):
    """응답 JSON 안에서 항목(dict) 목록을 찾는다."""
    if isinstance(d, list):
        return d if d and isinstance(d[0], dict) else []
    if isinstance(d, dict):
        for k in ("item", "items", "body", "response", "data"):
            if k in d:
                got = _items(d[k])
                if got:
                    return got
    return []


def warn_kind(title):
    kind = next((k for k in WARN_KINDS if k in title), "")
    level = "경보" if "경보" in title else "주의보" if "주의보" in title else ""
    return kind, level, ("해제" in title)


# ------------------------------------------------------------ 날씨

def sample_weather():
    ta, rh = 33.0, 62.0
    return {"source": "예시 자료", "live": False, "region": REGION, "time": "예시: 8월 오후 2시",
            "ta": ta, "rh": rh, "feel": feels_like(ta, rh),
            "warnings": [{"title": "[특보] 서울 동북권 폭염경보 발표(예시)", "kind": "폭염", "level": "경보", "off": False},
                         {"title": "[특보] 서울 동북권 강풍주의보 발표(예시)", "kind": "강풍", "level": "주의보", "off": False}],
            "note": "공공데이터포털 키(DATA_GO_KR_KEY)가 없거나 연결되지 않아 예시 자료를 보여 줍니다."}


def _hub_key():
    """기상청 API허브 키. 주소째 넣어도 authKey= 뒤만 쓴다."""
    k = os.environ.get("KMA_APIHUB_KEY", "").strip()
    m = re.search(r"authKey=([^&\s]+)", k)
    return urllib.parse.unquote(m.group(1) if m else k)


def weather():
    key = urllib.parse.unquote(os.environ.get("DATA_GO_KR_KEY", "").strip())  # 인코딩 키를 넣어도 디코딩 키로
    hub = _hub_key()
    if not key and not hub:
        return sample_weather()
    if key:
        auth, ncst_url, wrn_url, src = {"serviceKey": key}, KMA_NCST, KMA_WRN, "기상청 단기예보·기상특보(공공데이터포털)"
    else:
        auth, ncst_url, wrn_url, src = {"authKey": hub}, HUB_NCST, HUB_WRN, "기상청 초단기실황·기상특보(기상청 API허브)"
    now = datetime.now() - timedelta(minutes=40)  # 초단기실황은 매시 정각 자료가 40분 뒤 나옴
    try:
        d = _get(ncst_url, dict(auth, pageNo=1, numOfRows=20, dataType="JSON",
                                base_date=now.strftime("%Y%m%d"), base_time=now.strftime("%H00"), nx=NX, ny=NY))
        obs = {i.get("category"): i.get("obsrValue") for i in _items(d)}
        ta, rh = float(obs["T1H"]), float(obs["REH"])
    except Exception as e:  # 키 오류·승인 전·연결 실패
        s = sample_weather()
        s["note"] = f"기상청 자료를 받지 못해 예시 자료를 보여 줍니다({str(e)[:80]})."
        return s
    warns, note = [], ""
    try:
        today = datetime.now()
        w = _get(wrn_url, dict(auth, pageNo=1, numOfRows=20, dataType="JSON", stnId=STN,
                               fromTmFc=(today - timedelta(days=1)).strftime("%Y%m%d"), toTmFc=today.strftime("%Y%m%d")))
        for i in _items(w):
            t = str(i.get("title") or "")
            k, lv, off = warn_kind(t)
            if k:
                warns.append({"title": t, "kind": k, "level": lv, "off": off})
    except Exception as e:
        note = f"기상특보는 받지 못했습니다({str(e)[:60]}). 기온·습도·체감온도만 실제 자료입니다."
    return {"source": src, "live": True, "region": REGION, "time": now.strftime("%Y-%m-%d %H:00 관측"), "ta": ta, "rh": rh,
            "feel": feels_like(ta, rh), "warnings": warns, "note": note}


def active_warnings(wx):
    """해제되지 않은 특보 종류(같은 종류가 발표 뒤 해제되면 뺌, 목록은 최근 발표 순서라고 보지 않고 전부 확인)."""
    on = {}
    for w in wx.get("warnings", []):
        if w["kind"]:
            on[w["kind"]] = None if w["off"] else w
    return [w for w in on.values() if w]


def weather_stops(wx, cond, codes):
    """작업 시작 전에 멈춰야 할 이유(규칙). 실외에서 높은 곳 작업이면 강풍·호우·대설·태풍 특보 중 작업 중지."""
    stops = []
    outdoor_high = cond.get("outdoor") and "H01" in codes
    for w in active_warnings(wx):
        if w["kind"] in STOP_HIGH and outdoor_high:
            stops.append(f"{w['kind']}{w['level']} 중: 실외 높은 곳 작업은 특보가 풀린 뒤 시작")
    return stops


# ------------------------------------------------------------ 긴급재난문자

def sample_messages():
    d = datetime.now().strftime("%Y/%m/%d")
    return {"source": "예시 자료", "live": False, "region": REGION, "items": [
        {"sn": "EX1", "time": f"{d} 11:02", "region": REGION, "kind": "폭염", "step": "안전안내",
         "text": "[도봉구] 오늘 폭염경보 발효 중. 낮 시간 야외활동과 실외 작업을 자제하고 물을 자주 드세요.(예시)"},
        {"sn": "EX2", "time": f"{d} 07:40", "region": REGION, "kind": "강풍", "step": "안전안내",
         "text": "[서울시] 강풍주의보 발효. 간판·공사장 자재 등 날림에 주의하고 옥외 시설물 점검 바랍니다.(예시)"}],
        "note": "재난안전데이터공유플랫폼 키(SAFETYDATA_KEY)가 없거나 연결되지 않아 예시 자료를 보여 줍니다."}


def msg_kind(text, given=""):
    for k in MSG_CODES:
        if k in (given or "") or k in text:
            return k
    return given or ""


def messages():
    key = urllib.parse.unquote(os.environ.get("SAFETYDATA_KEY", "").strip())
    if not key:
        return sample_messages()
    try:
        d = _get(DSSP_MSG, {"serviceKey": key, "returnType": "json", "pageNo": 1, "numOfRows": 50,
                            "crtDt": datetime.now().strftime("%Y%m%d"), "rgnNm": REGION.split()[0]})
        items = []
        for i in _items(d):
            text = str(i.get("MSG_CN") or "")
            region = str(i.get("RCPTN_RGN_NM") or "")
            if REGION.split()[-1] not in region and REGION.split()[0] not in region:
                continue
            items.append({"sn": str(i.get("SN") or ""), "time": str(i.get("CRT_DT") or ""), "region": region,
                          "kind": msg_kind(text, str(i.get("DST_SE_NM") or "")), "step": str(i.get("EMRG_STEP_NM") or ""), "text": text})
        return {"source": "행정안전부 긴급재난문자(재난안전데이터공유플랫폼)", "live": True, "region": REGION, "items": items[:20], "note": ""}
    except Exception as e:
        s = sample_messages()
        s["note"] = f"재난문자를 받지 못해 예시 자료를 보여 줍니다({str(e)[:80]})."
        return s


def message_hits(msg, assessment):
    """재난문자 하나가 이 평가의 위험요인과 겹치면 겹친 위험요인 이름 목록."""
    codes = MSG_CODES.get(msg["kind"], [])
    if msg["kind"] in OUTDOOR_ONLY and not assessment["conditions"].get("outdoor"):
        return []
    return [i["name"] for i in assessment["items"] if i["code"] in codes and i["confirmed"]]
