"""
visitors.py — 来場者認識システム
顔ハッシュ（グレースケール特徴ベクトル）でリピーターを判定・記録する。
追加ライブラリ不要（OpenCV + NumPy のみ使用）。
"""
import json
import os
from datetime import datetime, date

import cv2
import numpy as np

DATA_DIR       = "data"
VISITORS_FILE  = os.path.join(DATA_DIR, "visitors.json")
VISIT_LOG_FILE = os.path.join(DATA_DIR, "visit_log.json")

HASH_SIZE  = 32          # 顔ハッシュの解像度（32×32）
THRESHOLD  = 0.91        # 同一人物と判定するコサイン類似度の閾値


# ── utils ──────────────────────────────────────────────────────

def _ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def compute_face_hash(face_bgr: np.ndarray) -> list:
    """顔画像 → 正規化特徴ベクトル（1024次元）"""
    gray    = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, (HASH_SIZE, HASH_SIZE))
    norm    = resized.astype(np.float32) / 255.0
    return norm.flatten().tolist()


def _cosine_sim(a: list, b: list) -> float:
    va, vb = np.array(a, np.float32), np.array(b, np.float32)
    return float(np.dot(va, vb) / (np.linalg.norm(va) * np.linalg.norm(vb) + 1e-8))


# ── CRUD ───────────────────────────────────────────────────────

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


def find_visitor(face_hash: list) -> dict | None:
    """顔ハッシュが閾値以上に一致する来場者を返す（なければ None）"""
    best, best_sim = None, 0.0
    for v in load_visitors():
        sim = _cosine_sim(face_hash, v["face_hash"])
        if sim > THRESHOLD and sim > best_sim:
            best_sim, best = sim, v
    return best


def register_visitor(face_hash: list) -> dict:
    """新規来場者を登録して返す"""
    visitors   = load_visitors()
    visitor_id = len(visitors) + 1
    now        = datetime.now().isoformat()
    visitor    = {
        "id":          visitor_id,
        "face_hash":   face_hash,
        "visit_count": 1,
        "first_visit": now,
        "last_visit":  now,
    }
    visitors.append(visitor)
    _save_visitors(visitors)
    return visitor


def update_visitor(visitor_id: int):
    """来訪回数・最終来訪日時を更新する"""
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
    """来場イベントをログに追記する"""
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
    """ダッシュボード向け統計を返す"""
    visitors  = load_visitors()
    logs      = _load_logs()
    today_str = date.today().isoformat()

    today_logs = [l for l in logs if l["timestamp"][:10] == today_str]
    today_uv   = len(set(l["visitor_id"] for l in today_logs))

    top_visitor = max(visitors, key=lambda v: v["visit_count"], default=None)

    return {
        "total_unique_visitors": len(visitors),
        "today_unique_visitors": today_uv,
        "total_visits":          len(logs),
        "today_visits":          len(today_logs),
        "top_visitor": {
            "id":          top_visitor["id"],
            "visit_count": top_visitor["visit_count"],
            "last_visit":  top_visitor["last_visit"][:10],
        } if top_visitor else None,
        "recent_logs": logs[-30:][::-1],
        "visitor_list": [
            {
                "id":          v["id"],
                "visit_count": v["visit_count"],
                "first_visit": v["first_visit"][:10],
                "last_visit":  v["last_visit"][:10],
            }
            for v in sorted(visitors, key=lambda x: x["visit_count"], reverse=True)
        ],
    }
