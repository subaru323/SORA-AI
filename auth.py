"""管理画面の認証。

Cloudflare Tunnel でインターネットへ公開する運用を前提に、
「ローカルからの直接アクセスは素通し、外部からのアクセスはパスワード必須」とする。

Tunnel は同じPC上で動く cloudflared が localhost:8000 へ転送するため、
送信元アドレスだけでは内外を区別できない（外部からの通信も 127.0.0.1 に見える）。
そのため Cloudflare が付与する転送ヘッダの有無で判定する。

ADMIN_PASSWORD が未設定なら保護は無効。ローカルだけで動かす間は
これまで通り何も要求されない。
"""
import base64
import hashlib
import hmac
import os
import secrets

ADMIN_USER     = os.getenv("ADMIN_USER", "sora")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
SESSION_COOKIE = "sora_admin"

# 外部プロキシ（Cloudflare Tunnel 等）を経由したことを示すヘッダ
_PROXY_HEADERS = ("cf-connecting-ip", "cf-ray", "x-forwarded-for", "x-real-ip")
_LOCAL_HOSTS   = {"127.0.0.1", "::1", "localhost"}


def is_enabled() -> bool:
    return bool(ADMIN_PASSWORD)


def session_token() -> str:
    """パスワードから一意に決まるトークン。

    WebSocket のハンドシェイクでは Authorization ヘッダを送れないため、
    HTTP で認証が通った時点でこの値をクッキーに配り、WS 側はそれを検証する。
    パスワードを変更すれば既存のクッキーは自動的に無効になる。
    """
    return hmac.new(ADMIN_PASSWORD.encode("utf-8"),
                    b"sora-admin-session", hashlib.sha256).hexdigest()


def is_remote(client_host: str | None, headers) -> bool:
    """外部からのアクセスかどうかを判定する。"""
    if any(h in headers for h in _PROXY_HEADERS):
        return True
    return (client_host or "") not in _LOCAL_HOSTS


def check_basic(auth_header: str | None) -> bool:
    if not auth_header or not auth_header.lower().startswith("basic "):
        return False
    try:
        raw = base64.b64decode(auth_header.split(None, 1)[1]).decode("utf-8")
    except Exception:
        return False
    user, _, password = raw.partition(":")
    # 比較時間を一定に保ち、文字数の推測を防ぐ
    return (secrets.compare_digest(user, ADMIN_USER)
            and secrets.compare_digest(password, ADMIN_PASSWORD))


def check_cookie(cookies) -> bool:
    got = cookies.get(SESSION_COOKIE, "")
    return bool(got) and secrets.compare_digest(got, session_token())
