# SORA // NEXUS

> **等身大ホログラムAIキャラクター「ソラ」**  
> ペッパーズゴースト投影 × Gemini AI × リアルタイムVRMアバター

---

## 概要

SORA // NEXUS は、ペッパーズゴースト（ハーフミラー）を用いた等身大ホログラム投影システムに、  
GoogleのGemini AIを組み込んだ自律型AIエージェントです。

Webカメラを「目」として空間を認識し、来場者に自発的に話しかけ、会話・ゲーム・システム操作を  
文脈に応じて自律実行します。単なる応答ボットではなく、**空間を認識し能動的に関わるエージェント**として機能します。

---

## アーキテクチャ

```
┌─────────────────────────────────────────────────────────┐
│                  SORA // NEXUS  System                  │
│                                                         │
│  ┌──────────┐    WebSocket    ┌──────────────────────┐  │
│  │ Browser  │◄──────────────►│   FastAPI Backend    │  │
│  │(Three.js │                │     (app.py)         │  │
│  │ VRM+UI)  │                │                      │  │
│  └──────────┘                │  ┌────────────────┐  │  │
│                              │  │  Gemini 2.5    │  │  │
│  ┌──────────┐   Camera Feed  │  │  Flash (LLM)   │  │  │
│  │ Web Cam  │───────────────►│  └────────────────┘  │  │
│  └──────────┘                │  ┌────────────────┐  │  │
│                              │  │  edge-tts(TTS) │  │  │
│  ┌──────────┐   Hologram     │  └────────────────┘  │  │
│  │  Mirror  │◄───────────────│  ┌────────────────┐  │  │
│  │ Display  │                │  │ Memory/Visitor │  │  │
│  └──────────┘                │  │   System       │  │  │
│                              │  └────────────────┘  │  │
│                              └──────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

---

## 主な機能

### 🤖 AI会話エンジン
- **Gemini 2.5 Flash** によるリアルタイムストリーミング応答
- J.A.R.V.I.S.スタイルの洗練されたキャラクター人格
- 音声入力（Web Speech API）とテキスト入力に対応
- 感情タグ `[emotion:happy|sad|angry|surprised|neutral]` による表情自動制御

### 🎭 ホログラムアバター
- **VRM形式**の3Dキャラクターをリアルタイムレンダリング（Three.js + @pixiv/three-vrm）
- 感情に連動したポーズ・表情・ライティングの自動制御
- リップシンク（音量解析による口形制御）
- 自動まばたき・呼吸アニメーション・パーティクルエフェクト

### 👁 空間認識（カメラ）
- **MediaPipe** による顔検出・オブジェクト検出（リアルタイム）
- 距離判定（至近距離 / 適正距離 / 遠距離）
- 持ち物認識（バックパック・スマートフォン・傘など20種類）
- **顔ハッシュによるリピーター認識**（追加ライブラリ不要）

### 🧠 記憶システム
- 会話終了時にGeminiが自動でサマリーを生成・保存
- 次回起動時にシステムプロンプトへ注入し「前回の話」を覚えた状態で起動
- 最大50件の会話記憶を `data/memories.json` に永続化

### 📊 来場者ダッシュボード
- `http://localhost:8000/dashboard` でアクセス
- 累計・本日のユニーク来場者数、来場回数ランキング
- 会話記憶一覧、直近の来場ログ（30秒ごとに自動更新）

### 🎮 コマンドシステム
ソラ自身が応答の中にコマンドタグを埋め込み、UIを自律制御します。

| コマンド | 機能 |
|---|---|
| `[command:scale=UP/DOWN]` | アバターサイズ変更 |
| `[command:mirror=TOGGLE]` | 画面左右反転 |
| `[command:camera=TOGGLE/INTERNAL/USB]` | カメラ切替 |
| `[command:rate=FASTER/SLOWER]` | 話速変更 |
| `[command:volume=UP/DOWN]` | 音量変更 |
| `[command:color=WARM/COOL/NORMAL]` | カラーフィルター |
| `[command:game=START/END]` | ゲームモード制御 |
| `[command:history=RESET]` | 会話履歴リセット |

---

## 技術スタック

| カテゴリ | 技術 |
|---|---|
| **バックエンド** | Python 3.11+ / FastAPI / WebSocket |
| **AI** | Google Gemini 2.5 Flash |
| **音声合成** | edge-tts（Microsoft Edge TTS） |
| **音声認識** | Web Speech API |
| **3Dレンダリング** | Three.js / @pixiv/three-vrm |
| **エッジAI** | MediaPipe (顔検出・物体検出) |
| **フロントエンド** | Vanilla JS / CSS Custom Properties |
| **データ保存** | JSON ファイル（記憶・来場者DB） |
| **投影方式** | ペッパーズゴースト（ハーフミラー） |

---

## ファイル構成

```
SORA-AI/
├── app.py              # FastAPIメインサーバー・WebSocketハンドラ
├── camera.py           # カメラセンサー・空間認識・来場者認識
├── config.py           # グローバル設定・状態管理
├── memory.py           # 会話記憶の保存・読み込み・プロンプト注入
├── visitors.py         # 来場者認識・来場ログ・ダッシュボード統計
├── requirements.txt    # Pythonパッケージ一覧
├── .env                # APIキー（Gitignore対象）
├── data/               # 永続化データ（自動生成）
│   ├── memories.json   # 会話サマリー記録
│   ├── visitors.json   # 来場者プロファイル
│   └── visit_log.json  # 来場ログ
└── static/
    ├── index.html          # メインUI
    ├── style.css           # SORA // NEXUS デザインシステム
    ├── main.js             # フロントエンドロジック
    ├── avatar.js           # VRMアバター制御（Three.js）
    └── dashboard.html      # 来場者分析ダッシュボード
```

---

## セットアップ

### 必要環境
- Python 3.11以上
- Webカメラ（USB / 内蔵）
- Gemini API キー（[Google AI Studio](https://aistudio.google.com/) で無料取得可）

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
```

### 3. 起動

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
| クイック設定 | ステータスバー右端の ⚙ ボタン |
| ダッシュボード | `localhost:8000/dashboard` |

### 会話例

```
あなた：「大きくなって」
ソラ  ：「承知しました。[command:scale=UP] サイズを調整いたします。」
→ アバターが拡大

あなた：「しりとりしよう」
ソラ  ：「[emotion:happy][command:game=START] では参りましょう。りんご。」
→ ゲームバッジが表示され、ルール維持で進行

あなた：（翌日）「こんにちは」
ソラ  ：「昨日はAIの話をしましたね。承知しております。」
→ 前回の会話記憶を参照
```

---

## ペッパーズゴースト設定

1. モニターを垂直に設置
2. 45°に傾けたハーフミラーをモニター前面に配置
3. ブラウザを全画面表示（F11）
4. ⚙ → **Mirror ON** を確認
5. 設定画面（ESC）のスライダーでアバター位置・サイズを微調整

---

## 環境変数

| 変数名 | 説明 | デフォルト |
|---|---|---|
| `GEMINI_API_KEY` | Gemini API キー | 必須 |
| `APP_LOG_LEVEL` | ログレベル（DEBUG/INFO/WARN/ERROR） | `INFO` |

---

## ライセンス

MIT License

---

*Powered by Google Gemini / Three.js / MediaPipe / edge-tts*
