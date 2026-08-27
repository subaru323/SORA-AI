"""
visitors.py — 来場者認識システム（デュアルモード対応）

face_recognition がインストールされていれば高精度モード（128次元）、
なければ自動的にハッシュモード（1024次元グレースケール）にフォールバック。
"""
import json
import os
from datetime import datetime, date

import cv2
import numpy as np

# ── insightface 自動検出（優先）──────────────────────────────────
# insightface + onnxruntime が入っていれば高精度モード（512次元ArcFace）
# 未インストールなら 32×32 グレースケールハッシュにフォールバック
try:
    from insightface.app import FaceAnalysis as _FaceAnalysis
    INSIGHT_AVAILABLE = True
except ImportError:
    INSIGHT_AVAILABLE = False

_insight_app = None   # lazy init（初回呼び出し時にモデルダウンロード）

DATA_DIR        = "data"
VISITORS_FILE   = os.path.join(DATA_DIR, "visitors.json")
VISIT_LOG_FILE  = os.path.join(DATA_DIR, "visit_log.json")    # 旧形式（JSON配列）
VISIT_LOG_JSONL = os.path.join(DATA_DIR, "visit_log.jsonl")   # 新形式（1行1件・追記のみ）
COUNTERS_FILE   = os.path.join(DATA_DIR, "visit_counters.json")  # 来訪回数のみ（小・高頻度更新）

HASH_SIZE        = 32
THRESHOLD_INSIGHT = 0.35   # insightface cosine similarity（同一人物とみなす下限）
THRESHOLD_HASH    = 0.91   # hash cosine similarity


def get_mode() -> str:
    return "insightface" if INSIGHT_AVAILABLE else "hash"


def _get_insight_app():
    global _insight_app
    if _insight_app is None:
        app = _FaceAnalysis(name="buffalo_sc", allowed_modules=["detection", "recognition"])
        app.prepare(ctx_id=-1, det_size=(320, 320))   # ctx_id=-1 = CPU
        _insight_app = app
    return _insight_app


# ── エンコーディング計算 ────────────────────────────────────────

def compute_encoding(face_bgr: np.ndarray) -> dict | None:
    """顔画像から特徴量を計算する（insightface 優先、なければハッシュ）"""
    if INSIGHT_AVAILABLE:
        try:
            app = _get_insight_app()
            img = face_bgr.copy()
            # insightface は最低 64x64 必要。小さければ拡大
            h, w = img.shape[:2]
            if h < 64 or w < 64:
                scale = max(64 / h, 64 / w)
                img   = cv2.resize(img, (int(w * scale), int(h * scale)))
            faces = app.get(img)
            if faces:
                emb = faces[0].embedding   # 512次元 L2正規化済み
                return {"type": "insightface", "data": emb.tolist()}
        except Exception:
            pass
    # Fallback: 32×32 グレースケールハッシュ
    try:
        gray    = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2GRAY)
        resized = cv2.resize(gray, (HASH_SIZE, HASH_SIZE))
        norm    = resized.astype(np.float32) / 255.0
        return {"type": "hash", "data": norm.flatten().tolist()}
    except Exception:
        return None


def compute_best_encoding(face_frames: list[np.ndarray]) -> dict | None:
    """複数フレームの平均エンコーディングを返す（より安定した特徴量）"""
    encodings = [compute_encoding(f) for f in face_frames]
    valid = [e for e in encodings if e is not None]
    if not valid:
        return None
    enc_type = valid[0]["type"]
    arrays   = [np.array(e["data"]) for e in valid if e["type"] == enc_type]
    if not arrays:
        return None
    avg = np.mean(arrays, axis=0)
    return {"type": enc_type, "data": avg.tolist()}


def _similarity(stored: dict, query: dict) -> float:
    """2つのエンコーディング間のコサイン類似度を返す（0〜1）"""
    if stored["type"] != query["type"]:
        return 0.0
    a = np.array(stored["data"], np.float32)
    b = np.array(query["data"],  np.float32)
    if stored["type"] == "insightface":
        # ArcFace 埋め込みは L2 正規化済み → ドット積 = コサイン類似度
        return float(np.dot(a, b))
    # hash: コサイン類似度
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8))


def _threshold_for(enc_type: str) -> float:
    return THRESHOLD_INSIGHT if enc_type == "insightface" else THRESHOLD_HASH


# ── CRUD ───────────────────────────────────────────────────────

def _ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


# ── 来訪カウンタ ────────────────────────────────────────────────
# 不変の埋め込み（1名あたり数十KB）と、来訪のたびに変わる回数（数十バイト）が
# 同じファイルに同居していると、挨拶1回ごとに巨大ファイルを読み書きすることになる。
# 更新頻度の高いカウンタだけを小さな別ファイルへ分離する。

def _load_counters() -> dict:
    """{visitor_id(str): {"visit_count": int, "last_visit": str}}"""
    try:
        with open(COUNTERS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_counters(counters: dict):
    _ensure_dir()
    with open(COUNTERS_FILE, "w", encoding="utf-8") as f:
        json.dump(counters, f, ensure_ascii=False, indent=2)


_visitors_cache: list | None = None
_visitors_cache_mtime: float | None = None


def _load_visitors_raw() -> list:
    """visitors.json をパースして返す。mtime が変わらない限り再パースしない。"""
    global _visitors_cache, _visitors_cache_mtime
    try:
        mtime = os.path.getmtime(VISITORS_FILE)
    except OSError:
        return []
    if _visitors_cache is not None and mtime == _visitors_cache_mtime:
        return _visitors_cache
    try:
        with open(VISITORS_FILE, encoding="utf-8") as f:
            _visitors_cache = json.load(f)
    except Exception:
        _visitors_cache = []
    _visitors_cache_mtime = mtime
    return _visitors_cache


def load_visitors() -> list:
    """来場者一覧を返す。来訪回数はカウンタファイル側の値で上書きする。

    カウンタが未整備の来場者は visitors.json に記録された値をそのまま使うため、
    分離前のデータでもそのまま動く。
    """
    counters = _load_counters()
    merged   = []
    # 呼び出し側（照合インデックス等）が書き換えてもキャッシュ本体が汚れないよう、
    # 必ず浅いコピーを返す。encodings は参照を共有するだけなのでコストは無視できる。
    for v in _load_visitors_raw():
        c = counters.get(str(v.get("id")))
        if c:
            merged.append({**v,
                           "visit_count": c.get("visit_count", v.get("visit_count", 1)),
                           "last_visit":  c.get("last_visit",  v.get("last_visit", ""))})
        else:
            merged.append(dict(v))
    return merged


def _save_visitors(visitors: list):
    global _match_index_mtime, _visitors_cache_mtime
    _ensure_dir()
    with open(VISITORS_FILE, "w", encoding="utf-8") as f:
        json.dump(visitors, f, ensure_ascii=False, indent=2)
    _match_index_mtime    = None   # 埋め込みが変わった可能性があるため作り直す
    _visitors_cache_mtime = None


# ── 照合インデックス ────────────────────────────────────────────
# visitors.json は 1 名あたり約 28 KB（512〜1024 次元の浮動小数点を JSON 文字列で保持）。
# 顔検知のたびに全体をパースして 1 件ずつ numpy 変換すると来場者数に比例して遅くなるため、
# ファイルが更新されたときだけ「方式ごとの行列」を組み直し、照合は行列積 1 回で済ませる。
_match_index_mtime: float | None = None
_match_index: dict = {}   # {enc_type: (np.ndarray[N, dim], [visitor, ...])}


def _get_match_index() -> dict:
    global _match_index_mtime, _match_index
    try:
        mtime = os.path.getmtime(VISITORS_FILE)
    except OSError:
        mtime = None

    if mtime is not None and mtime == _match_index_mtime:
        return _match_index

    rows: dict = {}   # {enc_type: ([data, ...], [visitor, ...])}
    for v in load_visitors():
        v = _migrate_old_format(v)
        for enc in v.get("encodings", []):
            enc_type, data = enc.get("type"), enc.get("data")
            if not enc_type or not data:
                continue
            vecs, owners = rows.setdefault(enc_type, ([], []))
            vecs.append(data)
            owners.append(v)

    _match_index = {
        enc_type: (np.asarray(vecs, dtype=np.float32), owners)
        for enc_type, (vecs, owners) in rows.items()
    }
    _match_index_mtime = mtime
    return _match_index


def _migrate_old_format(v: dict) -> dict:
    """旧フォーマット（face_hash キー）を新フォーマットへ変換"""
    if "face_hash" in v and "encodings" not in v:
        v["encodings"] = [{"angle": "auto", "type": "hash", "data": v.pop("face_hash")}]
    return v


def find_visitor(face_bgr_or_enc) -> dict | None:
    """顔画像またはエンコーディングから一致する来場者を返す"""
    if isinstance(face_bgr_or_enc, np.ndarray):
        query = compute_encoding(face_bgr_or_enc)
    else:
        query = face_bgr_or_enc
    if query is None:
        return None

    entry = _get_match_index().get(query["type"])
    if not entry:
        return None
    matrix, owners = entry

    q = np.asarray(query["data"], dtype=np.float32)
    if matrix.size == 0 or matrix.shape[1] != q.shape[0]:
        return None

    if query["type"] == "insightface":
        # ArcFace 埋め込みは L2 正規化済み → ドット積がそのままコサイン類似度
        sims = matrix @ q
    else:
        sims = (matrix @ q) / (np.linalg.norm(matrix, axis=1) * np.linalg.norm(q) + 1e-8)

    best_i = int(np.argmax(sims))
    return owners[best_i] if float(sims[best_i]) > _threshold_for(query["type"]) else None


def register_visitor(face_bgr: np.ndarray) -> dict:
    """自動登録（カメラ検知時の1枚で登録）"""
    enc = compute_encoding(face_bgr)
    encodings = [{"angle": "auto", **enc}] if enc else []
    return _create_visitor(encodings)


def register_visitor_with_angles(angle_encodings: dict) -> dict:
    """手動登録（角度ごとのエンコーディング辞書で登録）
    angle_encodings = {"front": enc_dict, "left": enc_dict, "right": enc_dict}
    """
    encodings = [
        {"angle": angle, **enc}
        for angle, enc in angle_encodings.items()
        if enc is not None
    ]
    return _create_visitor(encodings)


def _create_visitor(encodings: list) -> dict:
    visitors   = list(load_visitors())   # キャッシュ本体を壊さないよう複製してから追記
    visitor_id = len(visitors) + 1
    now        = datetime.now().isoformat()
    visitor    = {
        "id":               visitor_id,
        "encoding_method":  get_mode(),
        "encodings":        encodings,
        "visit_count":      1,
        "first_visit":      now,
        "last_visit":       now,
    }
    visitors.append(visitor)
    _save_visitors(visitors)
    return visitor


def update_visitor(visitor_id: int):
    """来訪回数を1つ進める。埋め込みを含む visitors.json には触れない。"""
    counters = _load_counters()
    key = str(visitor_id)
    if key in counters:
        base_count = counters[key].get("visit_count", 0)
    else:
        # カウンタ未整備の来場者は visitors.json 側の記録を引き継ぐ
        rec = next((v for v in _load_visitors_raw() if v.get("id") == visitor_id), None)
        base_count = (rec or {}).get("visit_count", 0)

    entry = {"visit_count": base_count + 1, "last_visit": datetime.now().isoformat()}
    counters[key] = entry
    _save_counters(counters)

    # 照合インデックスが持つ辞書にも反映し、find_visitor の返り値を古くさせない
    for _matrix, owners in _match_index.values():
        for o in owners:
            if o.get("id") == visitor_id:
                o["visit_count"] = entry["visit_count"]
                o["last_visit"]  = entry["last_visit"]
    return entry


# ── Visit Log ───────────────────────────────────────────────────

def _migrate_log_to_jsonl():
    """旧 visit_log.json（JSON配列）を 1 行 1 件の JSONL へ一度だけ移す。

    旧ファイルは保険としてそのまま残す。
    """
    if os.path.exists(VISIT_LOG_JSONL):
        return
    old = []
    if os.path.exists(VISIT_LOG_FILE):
        try:
            with open(VISIT_LOG_FILE, encoding="utf-8") as f:
                old = json.load(f)
        except Exception:
            old = []
    _ensure_dir()
    with open(VISIT_LOG_JSONL, "w", encoding="utf-8") as f:
        for row in old:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _load_logs() -> list:
    _migrate_log_to_jsonl()
    logs = []
    try:
        with open(VISIT_LOG_JSONL, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    logs.append(json.loads(line))
                except Exception:
                    continue   # 壊れた1行で全体を失わないようにする
    except OSError:
        return []
    return logs


def log_visit(visitor_id: int, duration_sec: float = 0.0, topics: str = ""):
    """1件を追記する。全件の読み直し・書き直しをしないため件数が増えても一定時間。"""
    _migrate_log_to_jsonl()
    _ensure_dir()
    row = {
        "visitor_id":   visitor_id,
        "timestamp":    datetime.now().isoformat(),
        "duration_sec": round(duration_sec, 1),
        "topics":       topics,
    }
    with open(VISIT_LOG_JSONL, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


# ── Dashboard Stats ─────────────────────────────────────────────

def get_stats() -> dict:
    visitors  = load_visitors()
    logs      = _load_logs()
    today_str = date.today().isoformat()
    today_logs = [l for l in logs if l["timestamp"][:10] == today_str]
    today_uv   = len(set(l["visitor_id"] for l in today_logs))
    top        = max(visitors, key=lambda v: v["visit_count"], default=None)
    return {
        "mode":                  get_mode(),
        "face_rec_available":    INSIGHT_AVAILABLE,
        "total_unique_visitors": len(visitors),
        "today_unique_visitors": today_uv,
        "total_visits":          len(logs),
        "today_visits":          len(today_logs),
        "top_visitor": {
            "id":          top["id"],
            "visit_count": top["visit_count"],
            "last_visit":  top["last_visit"][:10],
        } if top else None,
        "recent_logs": logs[-30:][::-1],
        "visitor_list": [
            {
                "id":             v["id"],
                "visit_count":    v["visit_count"],
                "encoding_method": v.get("encoding_method", "hash"),
                "angle_count":    len(v.get("encodings", [])),
                "first_visit":    v["first_visit"][:10],
                "last_visit":     v["last_visit"][:10],
            }
            for v in sorted(visitors, key=lambda x: x["visit_count"], reverse=True)
        ],
    }
