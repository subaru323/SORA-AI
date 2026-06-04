"""
knowledge.py — ナレッジベース（簡易RAG）
data/knowledge/ に .txt / .md / .pdf ファイルを置くだけで自動参照する。
PDF対応は pypdf が必要（requirements.txt に記載）。
"""
import os
import re
from pathlib import Path

KNOWLEDGE_DIR = "data/knowledge"


def _ensure_dir():
    os.makedirs(KNOWLEDGE_DIR, exist_ok=True)
    readme = Path(KNOWLEDGE_DIR) / "README.md"
    if not readme.exists():
        readme.write_text(
            "# ナレッジベース\n\n"
            "このフォルダに .txt / .md / .pdf を追加するとソラが参照します。\n\n"
            "## 例\n"
            "- `faq.txt` : よくある質問と回答\n"
            "- `products.md` : 商品説明\n"
            "- `manual.pdf` : 操作マニュアル\n",
            encoding="utf-8",
        )


def _load_texts() -> list[tuple[str, str]]:
    """(ファイル名, テキスト) のリストを返す"""
    _ensure_dir()
    results = []
    for path in Path(KNOWLEDGE_DIR).rglob("*"):
        if not path.is_file():
            continue
        try:
            if path.suffix in (".txt", ".md"):
                results.append((path.name, path.read_text(encoding="utf-8")))
            elif path.suffix == ".pdf":
                try:
                    import pypdf
                    reader = pypdf.PdfReader(str(path))
                    text = "\n".join(p.extract_text() or "" for p in reader.pages)
                    results.append((path.name, text))
                except ImportError:
                    pass  # pypdf 未インストール時はスキップ
        except Exception:
            pass
    return results


def _chunk(text: str, size: int = 300) -> list[str]:
    """テキストを段落・または固定サイズでチャンク化"""
    paras = [p.strip() for p in re.split(r"\n\n+", text) if p.strip()]
    chunks = []
    for p in paras:
        if len(p) <= size:
            chunks.append(p)
        else:
            # 長い段落は固定サイズで分割
            for i in range(0, len(p), size):
                chunks.append(p[i:i + size])
    return chunks


def search(query: str, top_k: int = 3) -> str:
    """クエリに関連するナレッジチャンクを返す（空なら空文字）"""
    all_texts = _load_texts()
    if not all_texts:
        return ""

    # 全チャンクを収集
    all_chunks = []
    for _fname, text in all_texts:
        all_chunks.extend(_chunk(text))

    # キーワードスコアリング（シンプルBM25風）
    q_words = set(re.sub(r"[^\w]", " ", query.lower()).split())
    scored = []
    for chunk in all_chunks:
        c_lower = chunk.lower()
        score = sum(1 for w in q_words if w in c_lower and len(w) > 1)
        if score > 0:
            scored.append((score, chunk))

    if not scored:
        return ""

    scored.sort(key=lambda x: -x[0])
    top = [c for _, c in scored[:top_k]]
    return "【参照情報】\n" + "\n---\n".join(top)


def summary() -> dict:
    """ダッシュボード用サマリー"""
    _ensure_dir()
    files = [f for f in Path(KNOWLEDGE_DIR).rglob("*") if f.is_file() and f.name != "README.md"]
    total = sum(f.stat().st_size for f in files)
    return {"files": len(files), "size_kb": round(total / 1024, 1)}
