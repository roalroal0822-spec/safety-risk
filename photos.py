"""사진 위험 제보: 사진 속 정보(촬영 시각·위치) 읽기, 위치 지우기, 가까운 시설 찾기, 사물 인식(선택).

- 촬영 시각·위치는 JPEG의 Exif(APP1)와 PNG의 eXIf 덩어리에서 읽는다(외부 라이브러리 없이).
- 위치는 가장 가까운 시설을 고르는 데만 쓰고, 저장하는 사진에서는 Exif를 지운다(좌표를 남기지 않음).
- 사물 인식은 YOLOX-Nano(Megvii, Apache-2.0, COCO 80종)를 onnxruntime으로 돌린다.
  numpy·onnxruntime·Pillow와 모델 파일(models/yolox_nano.onnx)이 있을 때만 쓰고, 없으면 건너뛴다.
  사람·차량·의자 같은 '물건'만 알아보며 물기·높이·전선 같은 위험 자체는 보지 못한다.
"""
import io
import math
import struct
from pathlib import Path

MODEL = Path(__file__).resolve().parent / "models" / "yolox_nano.onnx"

# ------------------------------------------------------------ Exif 읽기

def _tiff(buf):
    """Exif TIFF 덩어리 → {'time','lat','lon','make','model'}"""
    if len(buf) < 8 or buf[:2] not in (b"II", b"MM"):
        return {}
    e = "<" if buf[:2] == b"II" else ">"
    SZ = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8}

    def ifd(off):
        out = {}
        if off + 2 > len(buf):
            return out
        n = struct.unpack_from(e + "H", buf, off)[0]
        for i in range(n):
            p = off + 2 + i * 12
            if p + 12 > len(buf):
                break
            tag, typ, cnt = struct.unpack_from(e + "HHI", buf, p)
            size = SZ.get(typ, 1) * cnt
            vo = p + 8 if size <= 4 else struct.unpack_from(e + "I", buf, p + 8)[0]
            if vo + size > len(buf):
                continue
            if typ == 2:
                out[tag] = buf[vo:vo + cnt].split(b"\0")[0].decode("ascii", "replace").strip()
            elif typ in (3, 4):
                f = e + ("H" if typ == 3 else "I") * cnt
                v = struct.unpack_from(f, buf, vo)
                out[tag] = v[0] if cnt == 1 else v
            elif typ in (5, 10):
                v = struct.unpack_from(e + ("I" if typ == 5 else "i") * (2 * cnt), buf, vo)
                out[tag] = [v[k] / v[k + 1] if v[k + 1] else 0 for k in range(0, len(v), 2)]
        return out

    ifd0 = ifd(struct.unpack_from(e + "I", buf, 4)[0])
    sub = ifd(ifd0[0x8769]) if isinstance(ifd0.get(0x8769), int) else {}
    gps = ifd(ifd0[0x8825]) if isinstance(ifd0.get(0x8825), int) else {}
    r = {}
    if isinstance(ifd0.get(0x0112), int) and ifd0[0x0112] != 1:
        r["orient"] = ifd0[0x0112]
    t = sub.get(0x9003) or ifd0.get(0x0132)
    if isinstance(t, str) and len(t) >= 16:
        r["time"] = t[:10].replace(":", "-") + " " + t[11:16]
    if ifd0.get(0x010F) or ifd0.get(0x0110):
        r["device"] = " ".join(str(ifd0.get(k, "")) for k in (0x010F, 0x0110)).strip()
    try:
        lat, lon = gps[2], gps[4]
        la = lat[0] + lat[1] / 60 + lat[2] / 3600
        lo = lon[0] + lon[1] / 60 + lon[2] / 3600
        if str(gps.get(1, "N")).upper().startswith("S"):
            la = -la
        if str(gps.get(3, "E")).upper().startswith("W"):
            lo = -lo
        if la or lo:
            r["lat"], r["lon"] = round(la, 6), round(lo, 6)
    except (KeyError, IndexError, TypeError):
        pass
    return r


def _jpeg_segments(raw):
    """(표식, 시작, 끝) 목록. SOS 이후는 그대로 둔다."""
    out, p = [], 2
    while p + 4 <= len(raw) and raw[p] == 0xFF:
        m = raw[p + 1]
        if m == 0xDA:
            break
        n = struct.unpack_from(">H", raw, p + 2)[0]
        out.append((m, p, p + 2 + n))
        p += 2 + n
    return out


def _png_chunks(raw):
    p = 8
    while p + 12 <= len(raw):
        n = struct.unpack_from(">I", raw, p)[0]
        yield raw[p + 4:p + 8], p, p + 12 + n
        p += 12 + n


def exif(raw):
    """사진 바이트 → 촬영 시각·위치·기기. 정보가 없으면 빈 dict."""
    try:
        if raw[:2] == b"\xff\xd8":
            for m, a, b in _jpeg_segments(raw):
                if m == 0xE1 and raw[a + 4:a + 10] == b"Exif\0\0":
                    return _tiff(raw[a + 10:b])
        elif raw[:8] == b"\x89PNG\r\n\x1a\n":
            for typ, a, b in _png_chunks(raw):
                if typ == b"eXIf":
                    return _tiff(raw[a + 8:b - 4])
    except (struct.error, ValueError, IndexError):
        return {}
    return {}


def strip(raw):
    """사진에서 Exif(촬영 위치 등)를 지운 바이트. 그림 자체는 바꾸지 않는다."""
    if raw[:2] == b"\xff\xd8":
        segs = _jpeg_segments(raw)
        drop = [(a, b) for m, a, b in segs if m == 0xE1]
        if not drop:
            return raw
        o = exif(raw).get("orient")
        # 회전 정보만 남긴 최소 Exif(세로 사진이 눕지 않게). 위치·시각·기기 정보는 모두 지운다.
        keep = (b"\xff\xe1" + struct.pack(">H", 2 + 6 + 8 + 2 + 12 + 4) + b"Exif\0\0" + b"II*\0" + struct.pack("<I", 8)
                + struct.pack("<H", 1) + struct.pack("<HHIHH", 0x0112, 3, 1, o, 0) + struct.pack("<I", 0)) if o else b""
        out, p = bytearray(), 0
        for k, (a, b) in enumerate(drop):
            out += raw[p:a] + (keep if k == 0 else b"")
            p = b
        return bytes(out + raw[p:])
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        out, last = bytearray(raw[:8]), 8
        for typ, a, b in _png_chunks(raw):
            if typ != b"eXIf":
                out += raw[a:b]
            last = b
        return bytes(out + raw[last:])
    return raw


# ------------------------------------------------------------ 가까운 시설

def meters(la1, lo1, la2, lo2):
    r = 6371000
    p1, p2 = math.radians(la1), math.radians(la2)
    dp, dl = p2 - p1, math.radians(lo2 - lo1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def nearest(facilities, lat, lon):
    """반경 안에 드는 가장 가까운 시설. 없으면 None."""
    best = None
    for f in facilities:
        d = meters(lat, lon, f["lat"], f["lon"])
        if d <= f.get("radius", 300) and (best is None or d < best[1]):
            best = (f, d)
    return {"fac": best[0]["name"], "dist": round(best[1]), "src": best[0].get("src")} if best else None


# ------------------------------------------------------------ 사물 인식(YOLOX-Nano, 선택)

COCO = ["사람", "자전거", "승용차", "오토바이", "비행기", "버스", "기차", "트럭", "배", "신호등", "소화전", "정지 표지", "주차 요금기", "벤치", "새", "고양이", "개",
        "말", "양", "소", "코끼리", "곰", "얼룩말", "기린", "배낭", "우산", "핸드백", "넥타이", "여행가방", "원반", "스키", "스노보드", "공", "연", "야구 방망이",
        "야구 글러브", "스케이트보드", "서핑보드", "테니스 라켓", "병", "와인잔", "컵", "포크", "칼", "숟가락", "그릇", "바나나", "사과", "샌드위치", "오렌지",
        "브로콜리", "당근", "핫도그", "피자", "도넛", "케이크", "의자", "소파", "화분", "침대", "식탁", "변기", "TV", "노트북", "마우스", "리모컨", "키보드",
        "휴대전화", "전자레인지", "오븐", "토스터", "싱크대", "냉장고", "책", "시계", "꽃병", "가위", "곰인형", "헤어드라이어", "칫솔"]
VEHICLE = {"승용차", "버스", "트럭", "오토바이", "자전거"}
FLOOR = {"배낭", "핸드백", "여행가방", "공", "병", "컵", "의자", "벤치", "스케이트보드"}
_SESS = {}


def detector_status():
    if not MODEL.exists():
        return {"ok": False, "why": "모델 파일(models/yolox_nano.onnx)이 없습니다"}
    try:
        import numpy  # noqa: F401
        import onnxruntime  # noqa: F401
        from PIL import Image  # noqa: F401
    except Exception as e:  # ImportError, DLL 오류 등
        return {"ok": False, "why": f"사물 인식 부품이 설치되지 않았습니다({type(e).__name__})"}
    return {"ok": True, "name": "YOLOX-Nano(Apache-2.0, COCO 80종)"}


def detect(raw, score=0.35):
    """사진 → [{'label','score','box':[x0,y0,x1,y1] (0~1 비율)}]. 부품이 없으면 None."""
    if not detector_status()["ok"]:
        return None
    import numpy as np
    import onnxruntime as ort
    from PIL import Image, ImageOps
    if "s" not in _SESS:
        _SESS["s"] = ort.InferenceSession(str(MODEL), providers=["CPUExecutionProvider"])
    sess = _SESS["s"]
    S = 416
    im = Image.open(io.BytesIO(raw))
    if im.format == "JPEG":
        im.draft("RGB", (S * 2, S * 2))  # 휴대전화 고화질 사진도 작게 풀어 메모리를 아낀다(무료 서버 512MB)
    elif im.width * im.height > 4_000_000:
        im.thumbnail((S * 2, S * 2))
    im = ImageOps.exif_transpose(im).convert("RGB")
    W, H = im.size
    r = min(S / W, S / H)
    pad = np.full((S, S, 3), 114, dtype=np.uint8)
    rs = np.asarray(im.resize((max(1, int(W * r)), max(1, int(H * r))), Image.BILINEAR))
    pad[:rs.shape[0], :rs.shape[1]] = rs
    x = pad[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32)  # YOLOX는 BGR, 정규화 없음
    out = sess.run(None, {sess.get_inputs()[0].name: x})[0][0]
    grids, strides = [], []
    for st in (8, 16, 32):
        n = S // st
        yv, xv = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
        grids.append(np.stack((xv, yv), 2).reshape(-1, 2))
        strides.append(np.full((n * n, 1), st))
    g, s = np.concatenate(grids), np.concatenate(strides)
    xy = (out[:, :2] + g) * s
    wh = np.exp(out[:, 2:4]) * s
    sc = out[:, 4:5] * out[:, 5:]
    cls, conf = sc.argmax(1), sc.max(1)
    keep = conf >= score
    boxes = np.concatenate([xy - wh / 2, xy + wh / 2], 1)[keep] / r
    cls, conf = cls[keep], conf[keep]
    res = []
    idx = np.argsort(-conf)  # 종류 구분 없는 NMS(같은 물체에 두 이름이 붙지 않게)
    area = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    while len(idx):
        i = idx[0]
        res.append(i)
        b = boxes[idx[1:]]
        ix0, iy0 = np.maximum(boxes[i, 0], b[:, 0]), np.maximum(boxes[i, 1], b[:, 1])
        ix1, iy1 = np.minimum(boxes[i, 2], b[:, 2]), np.minimum(boxes[i, 3], b[:, 3])
        inter = np.clip(ix1 - ix0, 0, None) * np.clip(iy1 - iy0, 0, None)
        iou = inter / (area[i] + area[idx[1:]] - inter + 1e-9)
        idx = idx[1:][iou < 0.45]
    out = []
    for i in sorted(res, key=lambda i: -conf[i])[:30]:
        x0, y0, x1, y1 = boxes[i]
        out.append({"label": COCO[int(cls[i])], "score": round(float(conf[i]), 2),
                    "box": [round(float(max(0, x0)) / W, 3), round(float(max(0, y0)) / H, 3), round(float(min(W, x1)) / W, 3), round(float(min(H, y1)) / H, 3)]})
    return out


def object_hazards(objs):
    """사물 인식 결과로 낼 수 있는 위험요인 후보(규칙). 근거가 된 물건을 함께 적는다."""
    if not objs:
        return []
    names = [o["label"] for o in objs]
    people = names.count("사람")
    cars = [n for n in names if n in VEHICLE]
    floor = [o["label"] for o in objs if o["label"] in FLOOR and o["box"][3] > 0.6]
    out = []
    if people and cars:
        out.append(("H10", f"사람 {people}명과 {', '.join(dict.fromkeys(cars))}이(가) 한 사진에 있음"))
    if people >= 3:
        out.append(("H12", f"사람 {people}명이 보임(이용객이 있는 곳이면 작업 구역 통제 필요)"))
    if floor:
        out.append(("H13", f"바닥 쪽에 {', '.join(dict.fromkeys(floor))}이(가) 있음(걸려 넘어질 수 있음)"))
    return out
