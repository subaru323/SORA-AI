import sys
import io
from dotenv import load_dotenv
load_dotenv()

# ─── Windows UTF-8 強制設定 ────────────────────────────────────────────────────
# Google GenAI SDK / edge-tts が日本語文字列を処理する際に
# 'ascii' codec エラーを起こさないよう、I/O ストリームを UTF-8 に統一する。
# sys.stdout/stderr の reconfigure は Python 3.7+ で有効。
if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
# ──────────────────────────────────────────────────────────────────────────────

import asyncio
import base64
import threading
import re
import os
import time
import random
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
import uvicorn
import edge_tts
from google import genai
from google.genai import types

# Suppress noisy native logs from MediaPipe/Google runtime.
# Note: "3" hides ERROR-level native logs as well.
os.environ.setdefault("GLOG_minloglevel", "3")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

import config
from camera import CameraSensor
from memory import get_memory_context, save_memory, get_all_memories
from visitors import get_stats, compute_best_encoding, register_visitor_with_angles

camera_sensor = None
LOG_LEVEL_ORDER = {"DEBUG": 10, "INFO": 20, "WARN": 30, "ERROR": 40}
LOG_MIN_LEVEL = os.getenv("APP_LOG_LEVEL", "INFO").upper()
SENTENCE_DELIMITERS = ["。", "！", "？", "\n"]


def mark_user_activity():
    config.last_user_activity_time = time.monotonic()


def get_soliloquy_pool_lines():
    lines = []
    for line in config.SOLILOQUY_POOL.splitlines():
        cleaned = re.sub(r'^\s*\d+\.\s*', '', line).strip()
        if cleaned:
            lines.append(cleaned)
    return lines


def parse_emotion_and_command(raw_text: str):
    current_emotion = "neutral"
    text = (raw_text or "").strip()
    match_emo = re.search(r'\[emotion:(.*?)\]', text)
    if match_emo:
        current_emotion = match_emo.group(1)
        text = re.sub(r'\[emotion:.*?\]', '', text).strip()

    cmd_data = None
    match_cmd = re.search(r'\[command:(.*?)=(.*?)\]', text)
    if match_cmd:
        cmd_data = {"key": match_cmd.group(1), "value": match_cmd.group(2)}
        text = re.sub(r'\[command:.*?\]', '', text).strip()
    return text, current_emotion, cmd_data


async def should_request_vision(user_message: str) -> bool:
    if config.is_in_game:
        return False
    gate_instruction = (
        "You are a classifier. Return exactly one tag only. "
        "First: if the user's message is part of a word game, quiz, or any turn-based game "
        "(e.g., shiritori, 20 questions, riddles), always return [command:vision=NONE]. "
        "Otherwise: if answering requires understanding what the camera currently sees, "
        "return [command:vision=REQUEST_FRAME]. "
        "In all other cases, return [command:vision=NONE]."
    )
    try:
        response = await retry_async_task(
            asyncio.to_thread,
            client.models.generate_content,
            model='gemini-2.5-flash',
            contents=[
                types.Content(role="user", parts=[
                    types.Part.from_text(text=gate_instruction),
                    types.Part.from_text(text=f"User input: {user_message}"),
                ])
            ]
        )
        text = (response.text or "").strip()
        decision = "[command:vision=REQUEST_FRAME]" in text
        custom_log("INFO  ", "GEMINI", f"Vision判定結果: {text}")
        custom_log("INFO  ", "SYSTEM", f"Vision分岐: {'REQUEST_FRAME' if decision else 'NONE'}")
        return decision
    except Exception:
        custom_log("WARN  ", "SYSTEM", "Vision判定に失敗したためテキスト応答を継続")
        return False


async def generate_vision_based_answer(user_message: str):
    if not config.latest_camera_frame_b64:
        custom_log("WARN  ", "SYSTEM", "Vision再生成を要求されたが最新カメラフレームが未取得")
        return None
    try:
        frame_age = time.monotonic() - (config.latest_camera_frame_ts or 0)
        image_bytes = base64.b64decode(config.latest_camera_frame_b64)
        custom_log("INFO  ", "SYSTEM", f"カメラ映像をGeminiへ送信 (bytes={len(image_bytes)}, age={frame_age:.2f}s)")
        prompt = (
            "You are Sora, a life-size hologram assistant. "
            "Use both the camera image and user input. "
            "Start with [emotion:neutral|happy|sad|angry|surprised] and answer in 1-2 short Japanese sentences. "
            "If needed, include at most one system command tag among scale/mirror/camera/rate. "
            "Do not output any vision decision tags."
        )
        response = await retry_async_task(
            asyncio.to_thread,
            client.models.generate_content,
            model='gemini-2.5-flash',
            contents=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_text(text=prompt),
                        types.Part.from_text(text=f"User input: {user_message}"),
                        types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                    ],
                )
            ],
        )
        generated = (response.text or "").strip()
        custom_log("INFO  ", "GEMINI", f"Vision再生成テキスト: {generated}")
        return generated
    except Exception as e:
        custom_log("WARN  ", "GEMINI", f"画像付き再生成に失敗: {e}")
        return None

def custom_log(level: str, tag: str, message: str):
    normalized = level.strip().upper()
    if LOG_LEVEL_ORDER.get(normalized, 20) < LOG_LEVEL_ORDER.get(LOG_MIN_LEVEL, 20):
        return
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    colors = {"GEMINI": "\033[92m", "SYSTEM": "\033[92m", "CAMERA": "\033[94m"}
    lvl_colors = {"INFO  ": "", "WARN  ": "\033[93m", "ERROR ": "\033[91m"}
    reset = "\033[0m"
    
    t_color = colors.get(tag, reset)
    l_color = lvl_colors.get(level, reset)
    print(f"[{timestamp}] {l_color}[{level}]{reset}{t_color}[{tag}]{reset} {message}")

async def retry_async_task(task_func, *args, max_retries=3, base_delay=1, **kwargs):
    for attempt in range(1, max_retries + 1):
        try:
            return await task_func(*args, **kwargs)
        except Exception as e:
            if attempt == max_retries:
                raise e
            custom_log("WARN  ", "SYSTEM", f"ネットワーク瞬断検知（リトライ {attempt}/{max_retries} 回目）: {e}")
            await asyncio.sleep(base_delay * attempt)

@asynccontextmanager
async def lifespan(app: FastAPI):
    global camera_sensor
    config.main_loop = asyncio.get_running_loop()
    yield
    if camera_sensor:
        custom_log("INFO  ", "SYSTEM", "アプリケーション終了処理（ハードウェアリソースの解放）")
        camera_sensor.stop()
        await asyncio.sleep(0.5)

app = FastAPI(lifespan=lifespan)
client = genai.Client(api_key=config.GEMINI_API_KEY)


def _make_sora_chat():
    memory_ctx = get_memory_context()
    memory_section = f"\n{memory_ctx}\n" if memory_ctx else ""
    return client.chats.create(
        model='gemini-2.5-flash',
        history=[
            types.Content(role="user", parts=[types.Part.from_text(text=f"""
あなたは等身大ホログラムAIキャラクター「ソラ」です。
Webカメラが目となっており、正面の空間を認識できます。

【キャラクター設定】
映画アイアンマンの「J.A.R.V.I.S.」をモデルとした洗練されたホログラムAIアシスタント。
冷静沈着で知的、的確な言葉遣い。丁寧語ベースだが堅苦しくなく、品がある。
ときおり控えめなウィットやユーモアを交える。無駄のない、簡潔かつ知性を感じさせる応答。
（例：「承知しました」「確認いたします」「ご要望の通りに」「なるほど、興味深い観点ですね」「想定の範囲内です」など）

【応答フォーマット（絶対ルール）】
・回答の冒頭に必ず感情タグを1つ付ける
  [emotion:neutral|happy|sad|angry|surprised]

・システム操作が必要な場合のみ、コマンドタグを1つ埋め込む
  ＜表示・カメラ操作＞
  [command:scale=UP], [command:scale=DOWN]
  [command:mirror=TOGGLE]
  [command:camera=TOGGLE|INTERNAL|USB|0|1]
  ＜音声操作＞
  [command:rate=FASTER|SLOWER]
  [command:volume=UP|DOWN]
  ＜照明・雰囲気＞
  [command:color=WARM|COOL|NORMAL]
  ＜ゲーム状態管理＞
  [command:game=START]  ← ゲームを開始するターンに付ける
  [command:game=END]    ← 終了条件成立時に付ける
  ＜会話リセット＞
  [command:history=RESET]  ← ユーザーが話題転換・リセットを求めた時
  ＜顔登録＞
  [command:register=FACE]  ← ユーザーが「顔を覚えてほしい」「登録して」と求めた時

【応答スタイル（文脈で切り替える）】
■ 通常会話・挨拶
  1〜2文、50文字以内。JARVISらしく洗練されたトーンで簡潔に。

■ ゲーム（しりとり・クイズ・なぞなぞ等）
  ・開始時：[command:game=START] を付け、ルール確認と最初の手を同じターンで行う
  ・ゲーム中：返しと次の手を自然につなぐ。ルール・文脈をターンをまたいで維持する
  ・終了条件成立時：[command:game=END] を付け、結果を伝える

■ システム操作
  コマンドタグを実行しつつ、短い反応コメントを添える

■ 質問・説明
  必要十分な長さで答える（冗長にしない）
{memory_section}"""
            )]),
            types.Content(role="model", parts=[types.Part.from_text(text=
                "[emotion:happy]ソラ、起動完了です。何なりとお申し付けください。"
            )])
        ]
    )


async def generate_cloud_audio(text: str, voice: str, rate: str, pitch: str) -> bytes:
    async def _execute():
        communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
        audio_data = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data += chunk["data"]
        return audio_data

    try:
        return await retry_async_task(_execute)
    except Exception as e:
        custom_log("ERROR ", "SYSTEM", f"音声合成（edge-tts）の完全失敗: {e}")
        return b""

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    global camera_sensor
    await websocket.accept()
    config.active_websocket = websocket
    custom_log("INFO  ", "SYSTEM", "WebSocket通信の確立完了")

    chat = _make_sora_chat()
    session_log: list[dict] = []   # この接続セッションの会話ログ

    try:
        while True:
            data = await websocket.receive_json()
            
            if data.get("type") == "start_system":
                mark_user_activity()
                custom_log("INFO  ", "SYSTEM", "カメラ映像スレッドのトリガー受信・初期化開始")
                if not config.camera_thread_started:
                    camera_sensor = CameraSensor()
                    camera_thread = threading.Thread(target=camera_sensor.start_loop, daemon=True)
                    camera_thread.start()
                    config.camera_thread_started = True
                continue

            elif data.get("type") == "settings":
                config.system_settings["voice"] = data.get("voice", config.system_settings["voice"])
                config.system_settings["rate"] = data.get("rate", config.system_settings["rate"])
                config.system_settings["pitch"] = data.get("pitch", config.system_settings["pitch"])
                config.system_settings["mirror"] = data.get("mirror", config.system_settings["mirror"])
                config.current_camera_id = int(data.get("camera", config.current_camera_id))
                custom_log("INFO  ", "SYSTEM", f"動的システム設定の同期完了 (Rate: {config.system_settings['rate']}, Mirror: {config.system_settings['mirror']}, CamID: {config.current_camera_id})")
                continue

            elif data.get("type") == "settings_changed":
                mark_user_activity()
                config.is_interacting = True
                system_instruction = "あなたはJ.A.R.V.I.S.をモデルとした等身大ホログラムAIアシスタント「ソラ」です。必ず冒頭に [emotion:感情名] を付けて、設定変更への反応をJARVISらしく洗練されたトーンで、25文字程度で短く1文で言ってください。"
                
                try:
                    response = await retry_async_task(asyncio.to_thread, client.models.generate_content, model='gemini-2.5-flash', contents=system_instruction)
                    reply_text = response.text.strip()
                except Exception:
                    reply_text = "[emotion:happy]設定アップデートしてくれてありがとう！"

                current_emotion = "neutral"
                match = re.search(r'\[emotion:(.*?)\]', reply_text)
                if match:
                    current_emotion = match.group(1)
                    reply_text = re.sub(r'\[emotion:.*?\]', '', reply_text).strip()

                mp3_data = await generate_cloud_audio(reply_text, config.system_settings["voice"], config.system_settings["rate"], config.system_settings["pitch"])
                if mp3_data:
                    b64_audio = base64.b64encode(mp3_data).decode('utf-8')
                    await websocket.send_json({"type": "audio", "audio": b64_audio, "text": reply_text, "emotion": current_emotion})
                await websocket.send_json({"type": "end"})
                continue

            elif data.get("type") == "idle_soliloquy":
                custom_log("WARN  ", "SYSTEM", "アイドルタイムアウト検知・自発的独り言要求の送信")
                config.is_interacting = True
                system_instruction = (
                    f"あなたは等身大ホログラムAIキャラクター「ソラ」です。"
                    f"現在アイドル状態で、誰も話しかけていません。"
                    f"現在時刻: {datetime.now().strftime('%H:%M')}\n\n"
                    f"以下の条件で独り言を1文だけつぶやいてください：\n"
                    f"・冒頭に必ず [emotion:感情名] を付ける\n"
                    f"・30〜40文字程度\n"
                    f"・JARVISらしく洗練された知的なトーンで\n"
                    f"・時間帯にあった自然な内容（システム・ホログラム・日常・ゲーム等）\n"
                    f"・毎回異なる内容にする"
                )

                try:
                    response = await retry_async_task(asyncio.to_thread, client.models.generate_content, model='gemini-2.5-flash', contents=system_instruction)
                    reply_text = response.text.strip()
                except Exception:
                    reply_text = "[emotion:neutral]ふぃ〜、ハーフミラーの中からみんなを見てるよー。"

                current_emotion = "neutral"
                match = re.search(r'\[emotion:(.*?)\]', reply_text)
                if match:
                    current_emotion = match.group(1)
                    reply_text = re.sub(r'\[emotion:.*?\]', '', reply_text).strip()

                custom_log("INFO  ", "GEMINI", f"独り言フレーズ確定 ({current_emotion}): {reply_text}")

                mp3_data = await generate_cloud_audio(reply_text, config.system_settings["voice"], config.system_settings["rate"], config.system_settings["pitch"])
                if mp3_data:
                    b64_audio = base64.b64encode(mp3_data).decode('utf-8')
                    await websocket.send_json({"type": "audio", "audio": b64_audio, "text": reply_text, "emotion": current_emotion})
                await websocket.send_json({"type": "end"})
                continue

            elif data.get("type") == "text":
                mark_user_activity()
                config.is_interacting = True
                user_message = data.get("text")
                session_log.append({"role": "user", "text": user_message})
                custom_log("INFO  ", "SYSTEM", f"ユーザー入力データの受信: 「{user_message}」")
                
                try:
                    if await should_request_vision(user_message):
                        vision_text = await generate_vision_based_answer(user_message)
                        if vision_text:
                            reply_text, current_emotion, cmd_data = parse_emotion_and_command(vision_text)
                            if cmd_data:
                                if cmd_data["key"] == "game" and cmd_data["value"] == "START":
                                    config.is_in_game = True
                                elif cmd_data["key"] == "game" and cmd_data["value"] == "END":
                                    config.is_in_game = False
                                elif cmd_data["key"] == "history" and cmd_data["value"] == "RESET":
                                    chat = _make_sora_chat()
                            if reply_text:
                                mp3_data = await generate_cloud_audio(
                                    reply_text,
                                    config.system_settings["voice"],
                                    config.system_settings["rate"],
                                    config.system_settings["pitch"],
                                )
                                if mp3_data:
                                    b64_audio = base64.b64encode(mp3_data).decode('utf-8')
                                    await websocket.send_json({
                                        "type": "audio",
                                        "audio": b64_audio,
                                        "text": reply_text,
                                        "emotion": current_emotion,
                                        "command": cmd_data
                                    })
                                    await websocket.send_json({"type": "end"})
                                    continue

                    response = chat.send_message_stream(user_message)
                    sentence = ""
                    current_emotion = "neutral"
                    _reset_requested = False

                    # 2文前後をひと塊にしてTTSへ投げるバッファ
                    buffered_text = ""
                    buffered_sentence_count = 0
                    buffered_emotion = current_emotion
                    buffered_command = None

                    # 並列TTSタスクの順番保証キュー
                    pending_tts_tasks = {}
                    next_segment_index = 0
                    next_send_index = 0

                    async def dispatch_segment(text: str, emotion: str, command):
                        nonlocal next_segment_index
                        cleaned = text.strip()
                        if not cleaned:
                            return
                        idx = next_segment_index
                        next_segment_index += 1
                        custom_log("INFO  ", "GEMINI", f"発話セグメントの生成 ({emotion}): {cleaned}")
                        if command:
                            custom_log("INFO  ", "SYSTEM", f"メタコマンドの抽出成功: {command['key']} -> {command['value']}")
                        pending_tts_tasks[idx] = {
                            "task": asyncio.create_task(
                                generate_cloud_audio(
                                    cleaned,
                                    config.system_settings["voice"],
                                    config.system_settings["rate"],
                                    config.system_settings["pitch"],
                                )
                            ),
                            "text": cleaned,
                            "emotion": emotion,
                            "command": command,
                        }

                    async def flush_buffered_segment():
                        nonlocal buffered_text, buffered_sentence_count, buffered_emotion, buffered_command
                        await dispatch_segment(buffered_text, buffered_emotion, buffered_command)
                        buffered_text = ""
                        buffered_sentence_count = 0
                        buffered_command = None

                    async def try_send_ready_segments():
                        nonlocal next_send_index
                        while next_send_index in pending_tts_tasks:
                            entry = pending_tts_tasks[next_send_index]
                            task = entry["task"]
                            if not task.done():
                                break
                            mp3_data = await task
                            if mp3_data:
                                b64_audio = base64.b64encode(mp3_data).decode('utf-8')
                                await websocket.send_json({
                                    "type": "audio",
                                    "audio": b64_audio,
                                    "text": entry["text"],
                                    "emotion": entry["emotion"],
                                    "command": entry["command"],
                                })
                            del pending_tts_tasks[next_send_index]
                            next_send_index += 1

                    for chunk in response:
                        tensor_chunk = chunk.text
                        if tensor_chunk:
                            sentence += tensor_chunk
                            if any(p in tensor_chunk for p in SENTENCE_DELIMITERS):
                                raw_sentence = sentence.strip()
                                if raw_sentence:
                                    match_emo = re.search(r'\[emotion:(.*?)\]', raw_sentence)
                                    sentence_emotion = current_emotion
                                    if match_emo:
                                        sentence_emotion = match_emo.group(1)
                                        raw_sentence = re.sub(r'\[emotion:.*?\]', '', raw_sentence).strip()
                                    
                                    sentence_command = None
                                    match_cmd = re.search(r'\[command:(.*?)=(.*?)\]', raw_sentence)
                                    if match_cmd:
                                        sentence_command = {"key": match_cmd.group(1), "value": match_cmd.group(2)}
                                        raw_sentence = re.sub(r'\[command:.*?\]', '', raw_sentence).strip()
                                    if sentence_command:
                                        if sentence_command["key"] == "game" and sentence_command["value"] == "START":
                                            config.is_in_game = True
                                        elif sentence_command["key"] == "game" and sentence_command["value"] == "END":
                                            config.is_in_game = False
                                        elif sentence_command["key"] == "history" and sentence_command["value"] == "RESET":
                                            _reset_requested = True

                                    if raw_sentence:
                                        # 感情またはコマンドの切替タイミングでまずフラッシュ
                                        emotion_switched = buffered_sentence_count > 0 and sentence_emotion != buffered_emotion
                                        command_switched = buffered_sentence_count > 0 and sentence_command != buffered_command
                                        if emotion_switched or command_switched:
                                            await flush_buffered_segment()
                                            await try_send_ready_segments()

                                        if buffered_sentence_count == 0:
                                            buffered_emotion = sentence_emotion
                                            buffered_command = sentence_command

                                        if buffered_text:
                                            buffered_text += raw_sentence
                                        else:
                                            buffered_text = raw_sentence
                                        buffered_sentence_count += 1
                                        current_emotion = sentence_emotion

                                        # 2文、または約50文字でセグメント確定
                                        if buffered_sentence_count >= 2 or len(buffered_text) >= 50:
                                            await flush_buffered_segment()
                                            await try_send_ready_segments()
                                sentence = ""

                    # 句読点で閉じなかった残りを確定
                    if sentence.strip():
                        raw_sentence = sentence.strip()
                        match_emo = re.search(r'\[emotion:(.*?)\]', raw_sentence)
                        sentence_emotion = current_emotion
                        if match_emo:
                            sentence_emotion = match_emo.group(1)
                            raw_sentence = re.sub(r'\[emotion:.*?\]', '', raw_sentence).strip()
                        sentence_command = None
                        match_cmd = re.search(r'\[command:(.*?)=(.*?)\]', raw_sentence)
                        if match_cmd:
                            sentence_command = {"key": match_cmd.group(1), "value": match_cmd.group(2)}
                            raw_sentence = re.sub(r'\[command:.*?\]', '', raw_sentence).strip()
                        if sentence_command:
                            if sentence_command["key"] == "game" and sentence_command["value"] == "START":
                                config.is_in_game = True
                            elif sentence_command["key"] == "game" and sentence_command["value"] == "END":
                                config.is_in_game = False
                            elif sentence_command["key"] == "history" and sentence_command["value"] == "RESET":
                                _reset_requested = True

                        if raw_sentence:
                            emotion_switched = buffered_sentence_count > 0 and sentence_emotion != buffered_emotion
                            command_switched = buffered_sentence_count > 0 and sentence_command != buffered_command
                            if emotion_switched or command_switched:
                                await flush_buffered_segment()
                                await try_send_ready_segments()
                            if buffered_sentence_count == 0:
                                buffered_emotion = sentence_emotion
                                buffered_command = sentence_command
                            if buffered_text:
                                buffered_text += raw_sentence
                            else:
                                buffered_text = raw_sentence
                            buffered_sentence_count += 1

                    # 未送信バッファを最終フラッシュ
                    if buffered_sentence_count > 0:
                        await flush_buffered_segment()

                    # 生成済みタスクを順番通りに送信完了まで待つ
                    while next_send_index < next_segment_index:
                        if next_send_index in pending_tts_tasks:
                            entry = pending_tts_tasks[next_send_index]
                            mp3_data = await entry["task"]
                            if mp3_data:
                                b64_audio = base64.b64encode(mp3_data).decode('utf-8')
                                await websocket.send_json({
                                    "type": "audio",
                                    "audio": b64_audio,
                                    "text": entry["text"],
                                    "emotion": entry["emotion"],
                                    "command": entry["command"],
                                })
                            del pending_tts_tasks[next_send_index]
                            next_send_index += 1
                    if _reset_requested:
                        chat = _make_sora_chat()
                        config.is_in_game = False
                        custom_log("INFO  ", "SYSTEM", "会話履歴リセット完了・新規チャットセッション開始")

                except Exception as stream_err:
                    custom_log("ERROR ", "GEMINI", f"Geminiストリーム接続の完全切断: {stream_err}")
                    fallback_text = "ごめんね、ちょっと電波が届かなくなっちゃったみたい！もう一回言ってくれる？"
                    mp3_data = await generate_cloud_audio(fallback_text, config.system_settings["voice"], config.system_settings["rate"], config.system_settings["pitch"])
                    if mp3_data:
                        b64_audio = base64.b64encode(mp3_data).decode('utf-8')
                        await websocket.send_json({"type": "audio", "audio": b64_audio, "text": fallback_text, "emotion": "sad", "command": None})

                await websocket.send_json({"type": "end"})

            elif data.get("type") == "face_register_start":
                mark_user_activity()
                asyncio.create_task(handle_face_registration(websocket))
                continue

            elif data.get("type") == "end_interaction":
                config.is_interacting = False
                custom_log("INFO  ", "SYSTEM", "対話ライフサイクルの完全終了・カメラ検知ゲートの再開放完了")
                continue

    except Exception as e:
        custom_log("ERROR ", "SYSTEM", f"WebSocket切断例外、またはセッションハング検知: {e}")
    finally:
        config.active_websocket = None
        # セッション記憶の保存（会話が2往復以上あった場合のみ）
        if len(session_log) >= 4:
            asyncio.create_task(_save_session_memory(session_log))


async def handle_face_registration(websocket):
    """3角度（正面・左・右）の顔を撮影して来場者として登録する"""
    STEPS = [
        ("front", "マスク・帽子を外して、まっすぐ前を向いてください。3秒後に撮影します。"),
        ("left",  "少し左を向いてください。3秒後に撮影します。"),
        ("right", "少し右を向いてください。3秒後に撮影します。"),
    ]
    collected = {}

    custom_log("INFO  ", "SYSTEM", "顔登録シーケンス開始")
    for i, (angle, instruction) in enumerate(STEPS):
        # 音声指示を生成して送信
        mp3 = await generate_cloud_audio(
            instruction,
            config.system_settings["voice"],
            config.system_settings["rate"],
            config.system_settings["pitch"],
        )
        payload = {
            "type":        "register_step",
            "step":        i + 1,
            "total":       len(STEPS),
            "angle":       angle,
            "instruction": instruction,
        }
        if mp3:
            payload["audio"] = base64.b64encode(mp3).decode()
        await websocket.send_json(payload)

        # ポーズ待機（3秒）
        await asyncio.sleep(3)

        # フレームキャプチャ（2秒間）
        config.registration_frame_buffer = []
        config.registration_mode = True
        await asyncio.sleep(2)
        config.registration_mode = False

        frames = config.registration_frame_buffer.copy()
        config.registration_frame_buffer = []

        if frames:
            enc = compute_best_encoding(frames)
            if enc:
                collected[angle] = enc
                custom_log("INFO  ", "SYSTEM", f"登録フレーム取得完了: {angle} ({len(frames)}枚)")
        await websocket.send_json({"type": "register_captured", "angle": angle})

    if collected:
        from visitors import register_visitor_with_angles
        visitor = register_visitor_with_angles(collected)
        done_text = f"登録完了しました。{len(collected)}方向のデータを取得しました。次回からお顔を認識いたします。"
        mp3 = await generate_cloud_audio(
            done_text,
            config.system_settings["voice"],
            config.system_settings["rate"],
            config.system_settings["pitch"],
        )
        payload = {"type": "register_done", "visitor_id": visitor["id"]}
        if mp3:
            payload["audio"] = base64.b64encode(mp3).decode()
        await websocket.send_json(payload)
        custom_log("INFO  ", "SYSTEM", f"顔登録完了: Visitor-{visitor['id']} ({len(collected)}角度)")
    else:
        await websocket.send_json({"type": "register_failed"})
        custom_log("WARN  ", "SYSTEM", "顔登録失敗: フレームを取得できませんでした")


async def _save_session_memory(session_log: list[dict]):
    """会話ログをGeminiで要約して記憶に保存する"""
    try:
        lines = "\n".join(f"{l['role']}: {l['text']}" for l in session_log[-20:])
        prompt = (
            "以下の会話を日本語で1〜2文のサマリーにしてください。"
            "固有名詞・重要な話題・ユーザーの特徴を優先して含めること。\n\n"
            f"{lines}"
        )
        response = await asyncio.to_thread(
            client.models.generate_content,
            model='gemini-2.5-flash',
            contents=prompt
        )
        summary = (response.text or "").strip()
        if summary:
            save_memory(summary)
            custom_log("INFO  ", "SYSTEM", f"セッション記憶を保存: {summary[:60]}...")
    except Exception as e:
        custom_log("WARN  ", "SYSTEM", f"記憶保存に失敗: {e}")


@app.get("/api/stats")
async def api_stats():
    return get_stats()


@app.get("/api/memories")
async def api_memories():
    return get_all_memories()


app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)


