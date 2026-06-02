"""
memory.py — ソラの会話記憶システム
会話サマリーを JSON で永続化し、次回起動時にコンテキストとして注入する。
"""
import json
import os
from datetime import datetime

DATA_DIR    = "data"
MEMORY_FILE = os.path.join(DATA_DIR, "memories.json")
MAX_ENTRIES = 50   # 保持する最大記憶数
INJECT_N    = 5    # プロンプトに注入する直近N件


def _ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def load_memories() -> list:
    """保存済み記憶を全件読み込む"""
    if not os.path.exists(MEMORY_FILE):
        return []
    try:
        with open(MEMORY_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_memory(summary: str):
    """会話サマリーを1件追記する（上限超過分は古い順に削除）"""
    _ensure_dir()
    memories = load_memories()
    memories.append({
        "date":    datetime.now().isoformat(),
        "summary": summary.strip(),
    })
    memories = memories[-MAX_ENTRIES:]
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(memories, f, ensure_ascii=False, indent=2)


def get_memory_context() -> str:
    """直近の記憶をシステムプロンプト注入用テキストに変換する"""
    memories = load_memories()
    if not memories:
        return ""
    recent = memories[-INJECT_N:]
    lines  = ["【過去の会話記録（参考情報）】"]
    for m in recent:
        date_str = m["date"][:10]
        lines.append(f"・{date_str}: {m['summary']}")
    return "\n".join(lines)


def get_all_memories() -> list:
    """ダッシュボード用に全記憶を返す"""
    return load_memories()
