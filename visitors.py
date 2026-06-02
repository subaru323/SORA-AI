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

# ── face_recognition 自動検出 ──────────────────────────────────
try:
    import face_recognition as _fr
    FACE_REC_AVAILABLE = True
except ImportError:
    FACE_REC_AVAILABLE = False

DATA_DIR       = "data"
VISITORS_FILE  = os.path.join(DATA_DIR, "visitors.json")
VISIT_LOG_FILE = os.path.join(DATA_DIR, "visit_log.json")

HASH_SIZE  = 32
# 類似度閾値（face_recognition は距離ベースなので 1-distance で変換）
THRESHOLD_FR   = 0.50   # face_recognition: distance < 0.5 → 同一人物
THRESHOLD_HASH = 0.91   # hash: cosine similarity > 0.91


def get_mode() -> str:
    return "face_recognition" if FACE_REC_AVAILABLE else "hash"


# ── エンコーディング計算 ────────────────────────────────────────

def compute_encoding(face_bgr: np.ndarray) -> dict | None:
    """顔画像から特徴量を計算する（最良の方法を自動選択）"""
    if FACE_REC_AVAILABLE:
        try:
            rgb = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2RGB)
            encodings = _fr.face_encodings(rgb)
            if encodings:
                return {"type": "face_recognition", "data": encodings[0].tolist()}
        except Exception:
            pass
    # Fallback: グレースケールハッシュ
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
    """2つのエンコーディング間の類似度を返す（0〜1）"""
    if stored["type"] != query["type"]:
        return 0.0
    if stored["type"] == "face_recognition" and FACE_REC_AVAILABLE:
        dist = _fr.face_distance(
            [np.array(stored["data"])], np.array(query["data"])
        )[0]
        return float(1.0 - dist)
    # hash: コサイン類似度
    a = np.array(stored["data"], np.float32)
    b = np.array(query["data"],  np.float32)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8))


def _threshold_for(enc_type: str) -> float:
    return THRESHOLD_FR if enc_type == "face_recognition" else THRESHOLD_HASH


# ── CRUD ───────────────────────────────────────────────────────

def _ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def load_visitors() -> list:
    if not os.path.exists(VISITORS_FILE):
        return []
    try:
        with open(VISITORS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_visitors(visitors: list):
    _ensure_dir()
    with open(VISITORS_FILE, "w", encoding="utf-8") as f:
        json.dump(visitors, f, ensure_ascii=False, indent=2)


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

    threshold = _threshold_for(query["type"])
    best, best_sim = None, 0.0

    for v in load_visitors():
        v = _migrate_old_format(v)
        for enc in v.get("encodings", []):
            sim = _similarity(enc, query)
            if sim > threshold and sim > best_sim:
                best_sim, best = sim, v
    return best


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
    visitors   = load_visitors()
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
    visitors = load_visitors()
    for v in visitors:
        if v["id"] == visitor_id:
            v["visit_count"] += 1
            v["last_visit"]   = datetime.now().isoformat()
            break
    _save_visitors(visitors)


# ── Visit Log ───────────────────────────────────────────────────

def _load_logs() -> list:
    if not os.path.exists(VISIT_LOG_FILE):
        return []
    try:
        with open(VISIT_LOG_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def log_visit(visitor_id: int, duration_sec: float = 0.0, topics: str = ""):
    logs = _load_logs()
    logs.append({
        "visitor_id":   visitor_id,
        "timestamp":    datetime.now().isoformat(),
        "duration_sec": round(duration_sec, 1),
        "topics":       topics,
    })
    _ensure_dir()
    with open(VISIT_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(logs, f, ensure_ascii=False, indent=2)


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
        "face_rec_available":    FACE_REC_AVAILABLE,
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
