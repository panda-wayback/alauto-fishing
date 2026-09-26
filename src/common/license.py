"""密钥激活（离线 v1 HMAC）：与打包过期自毁独立。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from common.paths import data_root

# 半套共享密钥：生成器与客户端相同；后续服务器可改为非对称 v2
_HMAC_SECRET = b"albn-autofish-license-hmac-v1"
_PREFIX = "ALBN1"
_LICENSE_NAME = "license.json"


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def _sign(payload_b64: str) -> str:
    dig = hmac.new(_HMAC_SECRET, payload_b64.encode("ascii"), hashlib.sha256).digest()
    return _b64url_encode(dig)


def license_path() -> Path:
    return data_root() / _LICENSE_NAME


@dataclass(frozen=True)
class LicenseInfo:
    days: int
    activated_on: date
    expire_on: date
    key_fp: str

    def is_valid(self, *, today: date | None = None) -> bool:
        return (today or date.today()) < self.expire_on


def key_fingerprint(key: str) -> str:
    return hashlib.sha256(key.strip().encode("utf-8")).hexdigest()[:12]


def issue_key(days: int) -> str:
    """生成器：按天数签发密钥。"""
    n = int(days)
    if n <= 0:
        raise ValueError("days must be positive")
    body = {"v": 1, "days": n, "n": secrets.token_hex(8)}
    payload_b64 = _b64url_encode(
        json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
    return f"{_PREFIX}.{payload_b64}.{_sign(payload_b64)}"


def parse_key(key: str) -> dict:
    """验签并返回载荷 dict；失败抛 ValueError。"""
    text = key.strip().replace(" ", "")
    parts = text.split(".")
    if len(parts) != 3 or parts[0] != _PREFIX:
        raise ValueError("密钥格式无效")
    payload_b64, sig = parts[1], parts[2]
    if not hmac.compare_digest(_sign(payload_b64), sig):
        raise ValueError("密钥校验失败")
    try:
        body = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("密钥内容无效") from exc
    if not isinstance(body, dict):
        raise ValueError("密钥内容无效")
    days = int(body.get("days", 0))
    if days <= 0:
        raise ValueError("密钥天数无效")
    return body


def load_license() -> LicenseInfo | None:
    path = license_path()
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(raw, dict):
        return None
    try:
        return LicenseInfo(
            days=int(raw["days"]),
            activated_on=date.fromisoformat(str(raw["activated_on"])[:10]),
            expire_on=date.fromisoformat(str(raw["expire_on"])[:10]),
            key_fp=str(raw.get("key_fp") or ""),
        )
    except (KeyError, ValueError, TypeError):
        return None


def save_license(info: LicenseInfo) -> Path:
    path = license_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "days": info.days,
        "activated_on": info.activated_on.isoformat(),
        "expire_on": info.expire_on.isoformat(),
        "key_fp": info.key_fp,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def is_licensed(*, today: date | None = None) -> bool:
    info = load_license()
    return info is not None and info.is_valid(today=today)


def activate_key(key: str, *, today: date | None = None) -> LicenseInfo:
    """验签并写入 license；返回新 license。"""
    body = parse_key(key)
    days = int(body["days"])
    activated = today or date.today()
    info = LicenseInfo(
        days=days,
        activated_on=activated,
        expire_on=activated + timedelta(days=days),
        key_fp=key_fingerprint(key),
    )
    save_license(info)
    return info
