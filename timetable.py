"""
timetable.py — タイムテーブル自動アナウンス
data/timetable.json にスケジュールを記述するだけで動作する。
"""
import json
import os
from datetime import datetime

TIMETABLE_FILE = "data/timetable.json"

DEFAULT = [
    {"time": "09:00", "message": "午前のプログラムを開始いたします。ご来場をお待ちしております。"},
    {"time": "12:00", "message": "お昼休憩のお時間です。午後は13時から再開いたします。"},
    {"time": "13:00", "message": "午後のプログラムを開始いたします。"},
    {"time": "18:00", "message": "本日も多くのご来場、誠にありがとうございました。"},
]


def load_timetable() -> list:
    if not os.path.exists(TIMETABLE_FILE):
        os.makedirs("data", exist_ok=True)
        with open(TIMETABLE_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT, f, ensure_ascii=False, indent=2)
        return DEFAULT
    try:
        with open(TIMETABLE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return DEFAULT


def get_due_announcements(announced: set) -> list:
    """現在時刻に該当するアナウンスを返す（今分だけ）"""
    now = datetime.now().strftime("%H:%M")
    due = []
    for entry in load_timetable():
        key = f"{entry['time']}_{entry['message']}"
        if entry.get("time") == now and key not in announced:
            announced.add(key)
            due.append(entry["message"])
    return due
