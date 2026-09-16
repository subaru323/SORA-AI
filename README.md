# SORA // NEXUS

> **等身大ホログラムAIキャラクター「ソラ」**  
> ペッパーズゴースト投影 × Gemini AI × リアルタイムVRMアバター

---

## 概要

SORA // NEXUS は、ペッパーズゴースト（ハーフミラー）を用いた等身大ホログラム投影システムに、  
GoogleのGemini AIを組み込んだ自律型AIエージェントです。

Webカメラを「目」として空間を認識し、来場者に自発的に話しかけ、会話・ゲーム・システム操作を  
文脈に応じて自律実行します。単なる応答ボットではなく、**空間を認識し能動的に関わるエージェント**として機能します。

洗練された知的なトーンで対話する、SORA独自のキャラクター人格を持ちます。

---

## アーキテクチャ

```
┌──────────────────────────────────────────────────────────────┐
│                    SORA // NEXUS  System                     │
│                                                              │
│  ┌──────────┐    WebSocket    ┌────────────────────────────┐ │
│  │ Browser  │◄──────────────►│      FastAPI Backend       │ │
│  │(Three.js │                │        (app.py)            │ │
│  │ VRM+UI)  │                │  ┌──────────────────────┐  │ │
│  └──────────┘                │  │  Gemini 3.6 Flash    │  │ │
│                              │  │  (asyncio.to_thread) │  │ │
│  ┌──────────┐   Camera Feed  │  └──────────────────────┘  │ │
│  │ Web Cam  │───────────────►│  ┌──────────────────────┐  │ │
│  └──────────┘                │  │  edge-tts (TTS)      │  │ │
│                              │  └──────────────────────┘  │ │
│  ┌──────────┐   Hologram     │  ┌──────────────────────┐  │ │
│  │  Mirror  │◄───────────────│  │ Memory / Visitor /   │  │ │
│  │ Display  │                │  │ insightface (ArcFace)│  │ │
│  └──────────┘                │  └──────────────────────┘  │ │
│                              └────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

---

## 主な機能

### 🤖 AI会話エンジン
- **Gemini 3.6 Flash** によるストリーミング応答（`asyncio.to_thread` でイベントループを非ブロック）
- 洗練されたキャラクター人格（冷静・知的・ときにウィット）
- 音声入力（Web Speech API）＋ テキスト入力に対応
- 感情タグ `[emotion:happy|sad|angry|surprised|neutral]` による表情・ライティング自動制御
- **429 レート制限時、Ollama（ローカルLLM）へ自動フォールバック**
- 未対応の要求には正直に断る（存在しないコマンドを創作したり、実行せずに「対応しました」と答えない）
- エラー内容をチャット上に赤字で即時表示

### 🎭 NEXUS Hologram UI
- **全画面NEXUSリング**（外・中・内3リング ＋ 目盛り72刻み ＋ 軌道ピップ ＋ クロスヘア）
- **感情連動カラーパルス**：NEXUSブルー（#00d4ff）を軸に、感情色がゆっくり往復
  - `happy` → 青↔ゴールド、`sad` → 青↔ディープブルー、`angry` → 青↔レッド
- **全幅ステータスバー**（SORA // NEXUS タイトル・感情・ステータス・時刻・来場者数）
- **クイック設定パネル**（⚙ ボタン）：ミラー / ボイス / カメラ のON・OFF切り替え
- **チャットウィンドウはWindowsライクに可動**：既定配置・最大化・1/2・1/4のプリセット、タイトルバーのドラッグ移動、角のドラッグリサイズに対応（既定は常に固定配置で起動、変更は手動操作時のみ）

### 🎭 ホログラムアバター
- **VRM形式**の3Dキャラクターをリアルタイムレンダリング（Three.js + @pixiv/three-vrm）
- 感情連動ポーズ・表情・ライティング（感情ポイントライトがその都度変色）
- リップシンク（音量解析による口形制御）
- 自動まばたき・呼吸アニメーション・発話時パーティクルエフェクト

### 👁 空間認識（カメラ）
- **MediaPipe** による顔検出・オブジェクト検出（リアルタイム）
- 距離判定（至近距離 / 適正距離 / 遠距離）・持ち物認識（20種類）
- **insightface（ArcFace 512次元）** による高精度リピーター認識
- カメラプレビューは設定画面（ESC）と管理画面MONITORタブから確認可能

### 👤 来場者認識・顔登録
- 初来場者を自動登録、リピーターを検知して挨拶文を変える
- `「俺の顔を覚えて」` → **3角度撮影シーケンス**（正面・左・右）で高精度登録
- 照合は事前構築したインデックス＋行列積で判定（来場者数が増えても一定時間で応答）
- ステータスバーに **TODAY: X人 / NOW: X人検知中** をリアルタイム表示

### 🧠 記憶システム
- 会話終了時に Gemini が自動でサマリーを生成・`data/memories.json` に保存（最大50件）
- 次回起動時にプロンプトへ注入し「前回の話」を覚えた状態で起動

### 🖥 管理画面（`/admin`）
スタッフ・オペレーター向けの統合管理画面。3タブ構成。

| タブ | 内容 |
|---|---|
| **REMOTE** | チャットログ確認、テキスト発話指示、ミラー/ミュート/リセット等の操作、定型アナウンス |
| **ANALYTICS** | 来場者統計（累計・本日）、来場回数ランキング、会話記憶一覧（30秒ごと自動更新） |
| **MONITOR** | 実機ディスプレイのリアルタイムミラー表示（観測専用）＋カメラ映像のライブ配信 |

ローカルからのアクセス（`http://localhost:8000/admin`）は認証不要。Cloudflare Tunnel等で外部公開した場合のみ、`.env` の `ADMIN_USER` / `ADMIN_PASSWORD` によるパスワード認証が要求される。

---

## 🚧 セットアップ次第で使える機能

### 🤖 Ollama フォールバック
Gemini API の上限到達時にローカルLLM（Ollama）へ自動切り替え。**モデルを取得しないと機能しない。**

**セットアップ：**
1. [ollama.com](https://ollama.com) からインストール
2. `ollama pull gemma3:4b` でモデルをダウンロード（未取得の場合、429時のフォールバックが失敗する）
3. 以後、429エラー発生時に自動的にローカルLLMへ切り替わる

`.env` でモデルを変更可能：
```env
OLLAMA_MODEL=gemma3:4b
OLLAMA_URL=http://localhost:11434
```

---

### ✋ ジェスチャー認識
カメラで手のポーズを検知してソラが自動反応する。**追加設定不要、自動で動作。**

| ジェスチャー | ソラの反応 |
|---|---|
| 手を振る（wave） | 歓迎の挨拶 |
| 親指を立てる（thumbs up） | ポジティブな反応 |

> ⚠️ MediaPipe のバージョンによっては `mp.solutions.hands` が提供されず、無効化される場合があります。

---

### 🔔 タイムテーブル自動アナウンス
指定した時刻になると自動でソラが発話する。

`data/timetable.json` を編集（初回起動時に自動生成）：
```json
[
  {"time": "10:00", "message": "午前のプログラムを開始いたします。"},
  {"time": "12:00", "message": "お昼休憩のお時間です。"},
  {"time": "18:00", "message": "本日もご来場ありがとうございました。"}
]
```

---

### 📋 ナレッジベース
FAQや商品説明などのテキストをSORAが参照して回答する。

`data/knowledge/` フォルダにファイルを追加するだけで自動参照：
- `.txt` / `.md` → そのまま読み込み
- `.pdf` → テキスト自動抽出（pypdf使用）

```
data/knowledge/
├── faq.txt       # よくある質問
├── products.md   # 商品説明
└── manual.pdf    # マニュアル
```

---

### 🎮 コマンドシステム
ソラ自身が応答の中にコマンドタグを埋め込み、UIを自律制御します。定義外のキー・値は出力しない制約付き。

| コマンド | 機能 |
|---|---|
| `[command:scale=UP/DOWN]` | アバターサイズ変更 |
| `[command:mirror=TOGGLE]` | 画面左右反転 |
| `[command:camera=TOGGLE/INTERNAL/USB]` | カメラ切替 |
| `[command:rate=FASTER/SLOWER]` | 話速変更 |
| `[command:volume=UP/DOWN]` | 音量変更 |
| `[command:color=WARM/COOL/NORMAL]` | カラーフィルター |
| `[command:game=START/END]` | ゲームモード制御（Vision判定を自動スキップ） |
| `[command:history=RESET]` | 会話履歴リセット |
| `[command:register=FACE]` | 顔登録シーケンス開始 |

---

## 技術スタック

| カテゴリ | 技術 |
|---|---|
| **バックエンド** | Python 3.11+ / FastAPI / WebSocket |
| **AI** | Google Gemini 3.6 Flash（Ollamaフォールバック対応） |
| **顔認識** | insightface + ONNX Runtime（ArcFace 512次元、CPU動作） |
| **音声合成** | edge-tts（Microsoft Edge TTS） |
| **音声認識** | Web Speech API |
| **3Dレンダリング** | Three.js / @pixiv/three-vrm |
| **エッジAI** | MediaPipe（顔検出・物体検出） |
| **フロントエンド** | Vanilla JS / CSS Custom Properties / Canvas 2D |
| **データ保存** | JSON / JSONL ファイル（記憶・来場者DB・来場ログ） |
| **投影方式** | ペッパーズゴースト（ハーフミラー） |
| **外部公開** | Cloudflare Tunnel（任意）＋ Basic認証 |
| **環境変数** | python-dotenv |

---

## ファイル構成

```
SORA-AI/
├── app.py              # FastAPIメインサーバー・WebSocketハンドラ・登録シーケンス
├── auth.py             # 管理画面の認証（外部アクセス時のみパスワードを要求）
├── camera.py           # カメラセンサー・空間認識・顔登録バッファ・来場者カウント送信
├── config.py            # グローバル状態管理（ゲームフラグ・登録モード・来場者カウント等）
├── memory.py            # 会話記憶の保存・読み込み・プロンプト注入（最大50件）
├── visitors.py          # insightface顔認識・来場者DB・照合インデックス・統計
├── timetable.py         # タイムテーブル自動アナウンス
├── knowledge.py         # ナレッジベース（簡易RAG）
├── start.ps1            # 起動スクリプト（SORA本体＋Cloudflare Tunnel＋ブラウザ自動起動）
├── requirements.txt     # Pythonパッケージ一覧
├── .env                 # APIキー・管理画面パスワード（Gitignore対象）
├── data/                # 永続化データ（自動生成）
│   ├── memories.json      # 会話サマリー記録
│   ├── visitors.json      # 来場者プロファイル（顔埋め込み）
│   ├── visit_counters.json # 来訪回数カウンタ（高頻度更新分を分離）
│   ├── visit_log.jsonl    # 来場ログ（追記形式）
│   ├── timetable.json     # タイムテーブル設定
│   └── knowledge/         # ナレッジベース原本
└── static/
    ├── index.html      # メインUI（全幅ヘッダー・NEXUSリングキャンバス）
    ├── style.css       # SORA // NEXUS デザインシステム
    ├── main.js         # フロントエンドロジック（感情パルス・登録フロー・チャットウィンドウ制御）
    ├── avatar.js        # VRMアバター制御（Three.js・感情ライティング）
    └── admin.html       # 管理画面（REMOTE / ANALYTICS / MONITOR 統合）
```

---

## セットアップ

### 必要環境
- Python 3.11以上
- Webカメラ（USB / 内蔵）
- Gemini API キー（[Google AI Studio](https://aistudio.google.com/) で取得）

### 1. インストール

```bash
git clone https://github.com/subaru323/SORA-AI.git
cd SORA-AI

python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Mac/Linux

pip install -r requirements.txt
```

### 2. APIキー設定

`.env` ファイルをプロジェクトルートに作成：

```env
GEMINI_API_KEY=あなたのGeminiAPIキー

# 管理画面の認証（外部公開時のみ要求。ローカル直アクセスは不要）
ADMIN_USER=sora
ADMIN_PASSWORD=お好きなパスワード
```

### 3. 起動

**ワンコマンド起動（推奨）**：SORA本体＋Cloudflare Tunnel＋ブラウザを自動起動

```bash
.\start.ps1
```

外部公開が不要な場合：

```bash
.\start.ps1 -NoTunnel
```

**手動起動**：

```bash
python app.py
```

ブラウザで `http://localhost:8000` にアクセス。

---

## 使い方

### 基本操作

| 操作 | 方法 |
|---|---|
| システム起動 | 「▶ SYSTEM BOOT」ボタン or スペースキー |
| 音声入力 | 起動後に話しかける（自動でマイクON） |
| テキスト入力 | 画面下部のフォームから送信 |
| 設定画面 | ESCキー |
| クイック設定 | ステータスバー右端の ⚙ ボタン（ミラー・ボイス・カメラ切替） |
| 管理画面 | `localhost:8000/admin` |

### 会話例

```
あなた：「大きくなって」
ソラ  ：「承知しました。[command:scale=UP] サイズを調整いたします。」
→ アバターが拡大

あなた：「しりとりしよう」
ソラ  ：「[emotion:happy][command:game=START] では参りましょう。りんご。」
→ ゲームバッジが表示され、Vision判定が自動スキップされてゲームが続行

あなた：「俺の顔を覚えて」
ソラ  ：「承知しました。[command:register=FACE] 顔を登録いたします。」
→ 正面・左・右の3方向を撮影し、ArcFaceで高精度登録

あなた：（翌日）「こんにちは」
ソラ  ：「昨日はAIの話をしましたね。承知しております。」
→ 前回の会話記憶を参照して応答

あなた：「背景を赤色にして」（未対応の要求）
ソラ  ：「恐れ入りますが、その操作には対応しておりません。」
→ 存在しないコマンドを創作せず、正直に断る
```

### クイック設定（⚙）

| トグル | ON | OFF |
|---|---|---|
| MIRROR | 画面左右反転（ホログラム正像） | 反転解除 |
| VOICE | 音声認識・音声出力ON | マイク停止・ミュート |
| CAMERA | カメラプレビュー表示（設定画面内） | プレビュー非表示 |

---

## ペッパーズゴースト設定

1. モニターを垂直に設置
2. 45°に傾けたハーフミラーをモニター前面に配置
3. ブラウザを全画面表示（F11）
4. ⚙ → **Mirror ON** を確認
5. 設定画面（ESC）のスライダーでアバター位置・サイズを微調整

---

## 既知の制限

| 項目 | 内容 |
|---|---|
| Gemini 無料枠 | 1日20リクエスト上限。429エラー時はOllamaへ自動フォールバック（モデル未取得の場合は失敗） |
| 顔認識精度 | insightface（CPU）は照明・角度変化に強いが、完全一致ではない |
| 音声認識 | Web Speech API はオンライン必須・ノイズに弱い |
| Cloudflare Tunnel（無料版） | 公開URLは起動のたびに変わる。固定URLには独自ドメイン＋Cloudflareアカウントが必要 |

---

## 環境変数

| 変数名 | 説明 | デフォルト |
|---|---|---|
| `GEMINI_API_KEY` | Gemini API キー | 必須 |
| `APP_LOG_LEVEL` | ログレベル（DEBUG/INFO/WARN/ERROR） | `INFO` |
| `ADMIN_USER` | 管理画面のユーザー名（外部アクセス時のみ使用） | `sora` |
| `ADMIN_PASSWORD` | 管理画面のパスワード（未設定なら外部公開時に警告） | なし |
| `OLLAMA_URL` | OllamaサーバーのURL | `http://localhost:11434` |
| `OLLAMA_MODEL` | Ollamaフォールバックで使用するモデル | `gemma3:4b` |

---

## ライセンス

MIT License

---

*Powered by Google Gemini / Three.js / MediaPipe / insightface / edge-tts*
