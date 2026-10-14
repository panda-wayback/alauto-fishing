import base64
import json
import re
import sys
from datetime import date, timedelta

import pytest

from common import license as lic
from common.paths import data_root, user_state_root

D0 = date(2026, 5, 1)


def _state_files():
    return sorted(p.name for p in user_state_root().iterdir())


def test_issue_key_format_and_parse(sandbox):
    key = lic.issue_key(30)
    parts = key.split(".")
    assert len(parts) == 3 and parts[0] == "ALBN1"
    assert lic.parse_key(key)["days"] == 30
    assert lic.issue_key(30) != key


@pytest.mark.parametrize("days", [0, -5])
def test_issue_key_rejects_non_positive_days(days):
    with pytest.raises(ValueError):
        lic.issue_key(days)


def test_key_fingerprint():
    key = lic.issue_key(7)
    fp = lic.key_fingerprint(key)
    assert re.fullmatch(r"[0-9a-f]{12}", fp)
    assert lic.key_fingerprint(f"  {key}\n") == fp
    assert lic.key_fingerprint(f"{key[:10]} \t{key[10:]}") == fp
    assert lic.key_fingerprint(lic.issue_key(7)) != fp


def test_activate_roundtrip_and_expiry(sandbox):
    assert lic.load_license() is None
    assert lic.is_licensed(today=D0) is False

    key = lic.issue_key(10)
    info = lic.activate_key(key, today=D0)
    assert info.days == 10
    assert info.activated_on == D0
    assert info.expire_on == D0 + timedelta(days=10)
    assert info.key_fp == lic.key_fingerprint(key)

    assert lic.load_license() == info
    assert lic.is_licensed(today=D0) is True
    assert lic.is_licensed(today=info.expire_on - timedelta(days=1)) is True
    assert lic.is_licensed(today=info.expire_on) is False
    assert lic.is_licensed(today=info.expire_on + timedelta(days=100)) is False
    assert {"license.json", "license_ledger.json"} <= set(_state_files())


def test_activate_accepts_surrounding_and_inner_spaces(sandbox):
    key = lic.issue_key(3)
    spaced = f"  {key[:10]} {key[10:]}  "
    assert lic.parse_key(spaced)["days"] == 3
    assert lic.activate_key(f"  {key}\n", today=D0).expire_on == D0 + timedelta(days=3)


def _forge_days(key: str, days: int) -> str:
    prefix, payload, sig = key.split(".")
    body = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    body["days"] = days
    forged = base64.urlsafe_b64encode(json.dumps(body).encode()).decode().rstrip("=")
    return f"{prefix}.{forged}.{sig}"


def _flip(ch: str) -> str:
    return "A" if ch != "A" else "B"


@pytest.mark.parametrize(
    "tamper",
    [
        lambda k: k[:-1] + _flip(k[-1]),
        lambda k: _forge_days(k, 9999),
        lambda k: "ALBN2" + k[5:],
        lambda k: k.rsplit(".", 1)[0],
        lambda k: "garbage",
        lambda k: "",
    ],
    ids=["sig", "payload", "prefix", "two_parts", "garbage", "empty"],
)
def test_tampered_key_rejected_without_writing(sandbox, tamper):
    bad = tamper(lic.issue_key(30))
    before = _state_files()
    with pytest.raises(ValueError):
        lic.parse_key(bad)
    with pytest.raises(ValueError):
        lic.activate_key(bad, today=D0)
    assert _state_files() == before
    assert lic.is_licensed(today=D0) is False


def test_reactivating_same_key_keeps_first_expiry(sandbox):
    key = lic.issue_key(5)
    first = lic.activate_key(key, today=D0)

    again = lic.activate_key(key, today=D0 + timedelta(days=3))
    assert (again.activated_on, again.expire_on) == (first.activated_on, first.expire_on)

    lic.license_path().unlink()
    later = D0 + timedelta(days=30)
    reinstall = lic.activate_key(key, today=later)
    assert (reinstall.activated_on, reinstall.expire_on) == (first.activated_on, first.expire_on)
    assert lic.load_license() == first
    assert lic.is_licensed(today=later) is False

    spaced = f"{key[:10]} {key[10:20]}\t{key[20:]}"
    respaced = lic.activate_key(spaced, today=later)
    assert (respaced.activated_on, respaced.expire_on) == (first.activated_on, first.expire_on)


def test_new_key_overrides_and_old_key_keeps_its_record(sandbox):
    k1, k2 = lic.issue_key(5), lic.issue_key(20)
    first = lic.activate_key(k1, today=D0)
    d1 = D0 + timedelta(days=10)
    second = lic.activate_key(k2, today=d1)
    assert second.expire_on == d1 + timedelta(days=20)
    assert lic.load_license() == second
    assert lic.is_licensed(today=d1) is True

    back = lic.activate_key(k1, today=d1)
    assert back.expire_on == first.expire_on
    assert lic.is_licensed(today=d1) is False


@pytest.mark.parametrize("content", ["{oops", "[]", '{"days": 1}'])
def test_corrupt_license_file_is_unlicensed(sandbox, content):
    lic.license_path().write_text(content, encoding="utf-8")
    assert lic.load_license() is None
    assert lic.is_licensed(today=D0) is False


def test_legacy_license_migrates_to_user_state(sandbox, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    legacy_dir = data_root()
    assert legacy_dir != user_state_root()
    legacy = legacy_dir / "license.json"
    legacy.write_text(
        json.dumps(
            {
                "days": 7,
                "activated_on": D0.isoformat(),
                "expire_on": (D0 + timedelta(days=7)).isoformat(),
                "key_fp": "abcdef012345",
            }
        ),
        encoding="utf-8",
    )
    info = lic.load_license()
    assert info is not None and info.expire_on == D0 + timedelta(days=7)
    assert not legacy.exists()
    assert lic.license_path().is_file()
    assert lic.ledger_path().is_file()
    assert lic.is_licensed(today=D0) is True


def test_license_info_is_valid_boundary():
    info = lic.LicenseInfo(
        days=1, activated_on=D0, expire_on=D0 + timedelta(days=1), key_fp="x"
    )
    assert info.is_valid(today=D0) is True
    assert info.is_valid(today=D0 + timedelta(days=1)) is False
