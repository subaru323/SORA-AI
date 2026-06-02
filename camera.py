import time
import base64
import os
import urllib.request
import asyncio
import re
import cv2
import PIL.Image
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from google import genai
import config

class CameraSensor:
    def __init__(self):
        self.face_task_path = "blaze_face_short_range.tflite"
        self.obj_task_path = "efficientdet_lite0.tflite"
        self._prepare_mediapipe_tasks()

        base_face_options = python.BaseOptions(model_asset_path=self.face_task_path)
        face_options = vision.FaceDetectorOptions(base_options=base_face_options, min_detection_confidence=0.5)
        self.detector_face = vision.FaceDetector.create_from_options(face_options)

        base_obj_options = python.BaseOptions(model_asset_path=self.obj_task_path)
        obj_options = vision.ObjectDetectorOptions(base_options=base_obj_options, score_threshold=0.35)
        self.detector_obj = vision.ObjectDetector.create_from_options(obj_options)

        self.TARGET_MAP = {
            "backpack": "バックパック（リュック）", "umbrella": "傘", "handbag": "ハンドバッグ（カバン）",
            "tie": "ネクタイ", "suitcase": "スーツケース（大きな荷物）", "cell phone": "スマートフォン",
            "book": "本", "laptop": "ノートPC", "bottle": "ペットボトル/ボトル", "cup": "コップ/マグカップ",
            "apple": "果物", "banana": "果物", "orange": "果物", "sandwich": "食べ物", "pizza": "食べ物",
            "donut": "食べ物", "cake": "食べ物", "bird": "動物", "cat": "動物", "dog": "動物"
        }
        self.client = genai.Client(api_key=config.GEMINI_API_KEY)
        self.running = False

    def _prepare_mediapipe_tasks(self):
        urls = {
            self.face_task_path: "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite",
            self.obj_task_path: "https://storage.googleapis.com/mediapipe-models/object_detector/efficientdet_lite0/int8/1/efficientdet_lite0.tflite"
        }
        for file_path, url in urls.items():
            if not os.path.exists(file_path):
                from app import custom_log
                custom_log("INFO  ", "SYSTEM", f"MediaPipe Tasks 補完ダウンロードの開始: {file_path}")
                try:
                    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                    with urllib.request.urlopen(req) as response, open(file_path, 'wb') as out_file:
                        out_file.write(response.read())
                except Exception as e:
                    custom_log("ERROR ", "SYSTEM", f"モデルの取得失敗: {e}")
                    raise e

    def start_loop(self):
        from app import custom_log
        self.running = True
        current_cap_id = config.current_camera_id
        cap = cv2.VideoCapture(current_cap_id)
        
        custom_log("INFO  ", "SYSTEM", f"MediaPipe 統合型エッジAIパイプライン起動成功 (デバイスID: {current_cap_id})")
        preview_count = 0
        consecutive_face_frames = 0

        while self.running:
            if config.is_interacting:
                time.sleep(0.1)
                continue

            if config.current_camera_id != current_cap_id:
                cap.release()
                current_cap_id = config.current_camera_id
                cap = cv2.VideoCapture(current_cap_id)
                consecutive_face_frames = 0

            ret, frame = cap.read()
            if not ret:
                time.sleep(0.03)
                continue

            h, w = frame.shape[:2]
            preview_frame = frame.copy()
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
            face_result = self.detector_face.detect(mp_image)
            
            target_face_bbox = None
            proximity_status = "適正距離"

            if face_result.detections:
                consecutive_face_frames += 1
                first_face = face_result.detections[0]
                bbox = first_face.bounding_box
                target_face_bbox = bbox
                
                cv2.rectangle(preview_frame, (bbox.origin_x, bbox.origin_y), (bbox.origin_x + bbox.width, bbox.origin_y + bbox.height), (0, 255, 204), 2)

                face_ratio = bbox.width / w
                if face_ratio > 0.28:
                    proximity_status = "至近距離（至近接近）"
                elif face_ratio < 0.12:
                    proximity_status = "遠距離（遠方視線検知）"
            else:
                consecutive_face_frames = max(0, consecutive_face_frames - 1)

            if config.active_websocket and config.main_loop:
                preview_count += 1
                if preview_count % 3 == 0:
                    try:
                        small_preview = cv2.resize(preview_frame, (320, int(320 * h / w)))
                        _, pre_buf = cv2.imencode('.jpg', small_preview, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
                        pre_b64 = base64.b64encode(pre_buf).decode('utf-8')
                        config.latest_camera_frame_b64 = pre_b64
                        config.latest_camera_frame_ts = time.monotonic()
                        asyncio.run_coroutine_threadsafe(
                            config.active_websocket.send_json({"type": "camera_preview", "image": pre_b64}), config.main_loop
                        )
                    except Exception:
                        pass

            now = time.monotonic()
            is_after_cooldown = now - config.last_greeting_time > config.DETECTION_COOLDOWN_SEC
            is_user_idle_enough = now - config.last_user_activity_time > config.AUTO_GREETING_IDLE_GRACE_SEC
            if consecutive_face_frames >= 3 and is_after_cooldown and is_user_idle_enough:
                if target_face_bbox is not None:
                    config.last_greeting_time = now
                    consecutive_face_frames = 0

                    obj_result = self.detector_obj.detect(mp_image)
                    detected_objects = set()
                    if obj_result.detections:
                        for obj in obj_result.detections:
                            for category in obj.categories:
                                name = category.category_name
                                if name in self.TARGET_MAP:
                                    detected_objects.add(self.TARGET_MAP[name])

                    objects_str = "、".join(detected_objects) if detected_objects else "特になし"
                    local_features = f"物理距離: {proximity_status} / 持ち物: [{objects_str}]"
                    custom_log(" INFO ", "CAMERA", f"空間情報の変化看破 ({local_features})")

                    if config.main_loop:
                        asyncio.run_coroutine_threadsafe(self._process_spontaneous_greeting(local_features), config.main_loop)

            time.sleep(0.03)
        cap.release()

    def stop(self):
        self.running = False

    async def _process_spontaneous_greeting(self, local_features):
        if config.active_websocket is None:
            return
        from app import generate_cloud_audio, custom_log, retry_async_task
        try:
            config.is_interacting = True
            prompt = (
                f"指示: 冒頭に必ず [emotion:感情名] を付けて、"
                f"正面に立った新規ゲスト({local_features})に対して、"
                f"J.A.R.V.I.S.をモデルとした洗練されたトーンで、"
                f"距離・持ち物の情報を知性的かつ自然に活かした歓迎の一言を20〜30文字で言って。"
                f"（例：至近距離→「随分と近いですね。歓迎します」、バックパック→「お出かけ帰りでしょうか」）"
                f"持ち物への言及は自然な範囲のみ。無理に全て触れなくていい。"
            )
            
            try:
                response = await retry_async_task(asyncio.to_thread, self.client.models.generate_content, model='gemini-2.5-flash', contents=prompt)
                reply_text = response.text.strip()
            except Exception:
                reply_text = "[emotion:happy]わっ、いらっしゃい！会いに来てくれて嬉しいな！"

            current_emotion = "neutral"
            match = re.search(r'\[emotion:(.*?)\]', reply_text)
            if match:
                current_emotion = match.group(1)
                reply_text = re.sub(r'\[emotion:.*?\]', '', reply_text).strip()

            custom_log("INFO  ", "GEMINI", f"自発的お迎え文確定 ({current_emotion}): {reply_text}")

            mp3_data = await generate_cloud_audio(reply_text, config.system_settings["voice"], config.system_settings["rate"], config.system_settings["pitch"])
            if mp3_data and config.active_websocket:
                b64_audio = base64.b64encode(mp3_data).decode('utf-8')
                
                # 【修正ポイント】未定義だった関数名を、正しいグローバル変数「config.active_websocket」へ書き換え完治！
                await config.active_websocket.send_json({
                    "type": "audio", "audio": b64_audio, "text": reply_text, "emotion": current_emotion  
                })
                await config.active_websocket.send_json({"type": "end"})
        except Exception as e:
            custom_log("ERROR ", "SYSTEM", f"自発的お迎え処理の例外ハング: {e}")
            config.is_interacting = False
