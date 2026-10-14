import importlib.util
import json
import os
import shutil
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

import common.license as license_mod

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PKG = Path(__file__).resolve().parents[1]
ROOT = PKG.parent
REPO_EXPIRE = ROOT / "assets" / "expire.json"

FAKE_PYTHON = r"""#!/usr/bin/env bash
echo "$*" >> "$FAKE_LOG"
if [[ "${1:-}" == "-m" && "${2:-}" == "PyInstaller" ]]; then
  dist=""; spec=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --distpath) dist="$2"; shift 2 ;;
      *) spec="$1"; shift ;;
    esac
  done
  case "$spec" in
    *albn_autofish.spec)
      mkdir -p "$dist/$ALBN_APP_NAME/Contents/Frameworks/QtWebEngineCore.framework" ;;
    *albn_autofish_windows.spec)
      rm -rf "$dist/$ALBN_DIST_NAME"
      mkdir -p "$dist/$ALBN_DIST_NAME"
      touch "$dist/$ALBN_DIST_NAME/albn-autofish.exe" ;;
    *albn_license_keygen.spec)
      mkdir -p "$dist/$ALBN_KEYGEN_APP_NAME" "$dist/albn-license-keygen" ;;
  esac
fi
"""


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_script(*args, env_extra=None, cwd=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ALBN_", "GITHUB_"))}
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, *args], capture_output=True, text=True, env=env, cwd=cwd, timeout=60
    )


# ---------- gen_license_key.py ----------


def test_gen_license_key_cli_keys_verify_and_activate(tmp_path, monkeypatch):
    res = _run_script(str(PKG / "gen_license_key.py"), "7", "--count", "3", cwd=tmp_path)
    assert res.returncode == 0, res.stderr
    keys = res.stdout.split()
    assert len(keys) == 3 and len(set(keys)) == 3
    assert "days=7" in res.stderr
    for key in keys:
        assert license_mod.parse_key(key)["days"] == 7

    monkeypatch.setattr(license_mod, "user_state_root", lambda: tmp_path / "state")
    monkeypatch.setattr(license_mod, "data_root", lambda: tmp_path / "data")
    today = date(2026, 1, 1)
    info = license_mod.activate_key(keys[0], today=today)
    assert info.expire_on == today + timedelta(days=7)
    assert (tmp_path / "state" / "license.json").is_file()
    assert license_mod.is_licensed(today=today)


@pytest.mark.parametrize("args", [["0"], ["-3"], ["7", "--count", "0"], ["abc"]])
def test_gen_license_key_cli_rejects_bad_args(tmp_path, args):
    res = _run_script(str(PKG / "gen_license_key.py"), *args, cwd=tmp_path)
    assert res.returncode == 2
    assert res.stdout.strip() == ""


# ---------- write_expire.py ----------


def _run_write_expire(bundle: Path, days):
    """以冻结包形态运行脚本，使 assets/ 落在 bundle 而非仓库。"""
    wrapper = (
        "import runpy, sys; sys.frozen = True; sys._MEIPASS = sys.argv[1]; "
        "runpy.run_path(sys.argv[2], run_name='__main__')"
    )
    env = {} if days is None else {"ALBN_EXPIRE_DAYS": days}
    return _run_script("-c", wrapper, str(bundle), str(PKG / "write_expire.py"), env_extra=env)


@pytest.fixture
def repo_expire_guard():
    before = REPO_EXPIRE.read_bytes() if REPO_EXPIRE.is_file() else None
    yield
    after = REPO_EXPIRE.read_bytes() if REPO_EXPIRE.is_file() else None
    assert after == before, "write_expire 测试改动了仓库 assets/expire.json"


def test_write_expire_writes_expire_json(tmp_path, repo_expire_guard):
    res = _run_write_expire(tmp_path, "30")
    assert res.returncode == 0, res.stderr
    raw = json.loads((tmp_path / "assets" / "expire.json").read_text(encoding="utf-8"))
    built = date.fromisoformat(raw["built_on"])
    assert abs((built - date.today()).days) <= 1
    assert raw["days"] == 30
    assert date.fromisoformat(raw["expire_on"]) == built + timedelta(days=30)


@pytest.mark.parametrize("days", [None, "", "  ", "0", "-5"])
def test_write_expire_unset_or_nonpositive_clears(tmp_path, days, repo_expire_guard):
    target = tmp_path / "assets" / "expire.json"
    target.parent.mkdir(parents=True)
    target.write_text('{"expire_on": "2000-01-01"}', encoding="utf-8")
    res = _run_write_expire(tmp_path, days)
    assert res.returncode == 0, res.stderr
    assert not target.exists()


def test_write_expire_invalid_exits_2_and_keeps_file(tmp_path, repo_expire_guard):
    target = tmp_path / "assets" / "expire.json"
    target.parent.mkdir(parents=True)
    target.write_text('{"expire_on": "2000-01-01"}', encoding="utf-8")
    res = _run_write_expire(tmp_path, "abc")
    assert res.returncode == 2
    assert "ALBN_EXPIRE_DAYS invalid" in res.stderr
    assert target.read_text(encoding="utf-8") == '{"expire_on": "2000-01-01"}'


# ---------- pyi_trim.py ----------


def test_pyi_trim_drops_unused_qt_and_keeps_rest():
    pyi_trim = _load("pyi_trim_under_test", PKG / "pyi_trim.py")
    a = SimpleNamespace(
        binaries=[
            ("PySide6/QtWebEngineCore.framework/x", "/p/QtWebEngineCore", "BINARY"),
            ("PySide6/QtWidgets.abi3.so", "/p/QtWidgets.abi3.so", "BINARY"),
        ],
        datas=[
            ("cv2/data/haarcascade_eye.xml", "/p/haarcascade_eye.xml", "DATA"),
            ("assets/bobber.png", "/p/assets/bobber.png", "DATA"),
        ],
        pure=[
            ("PySide6.QtQml", "/p/QtQml.py", "PYMODULE"),
            ("common.license", "/p/license.py", "PYMODULE"),
        ],
    )
    pyi_trim.trim_analysis(a)
    assert [x[0] for x in a.binaries] == ["PySide6/QtWidgets.abi3.so"]
    assert [x[0] for x in a.datas] == ["assets/bobber.png"]
    assert [x[0] for x in a.pure] == ["common.license"]


def test_pyi_trim_tolerates_missing_pure():
    pyi_trim = _load("pyi_trim_under_test", PKG / "pyi_trim.py")
    a = SimpleNamespace(binaries=[("QtSql.dll", "/p/QtSql.dll", "BINARY")], datas=[], pure=None)
    pyi_trim.trim_analysis(a)
    assert a.binaries == [] and a.pure is None


# ---------- 语法检查 ----------


@pytest.mark.parametrize(
    "name", ["albn_autofish.spec", "albn_autofish_windows.spec", "albn_license_keygen.spec"]
)
def test_spec_files_compile(name):
    src = (PKG / name).read_text(encoding="utf-8")
    compile(src, name, "exec")


@pytest.mark.parametrize(
    "name",
    ["build_macos.sh", "build_windows.sh", "build_license_macos.sh", "reset_macos_perms.sh"],
)
def test_shell_scripts_bash_syntax(name):
    res = subprocess.run(["bash", "-n", str(PKG / name)], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr


# ---------- 构建脚本（复制到 tmp，假 python 代替 pip / PyInstaller） ----------


@pytest.fixture
def fake_tree(tmp_path):
    (tmp_path / "packaging").mkdir()
    for name in ("build_macos.sh", "build_windows.sh", "build_license_macos.sh"):
        shutil.copy2(PKG / name, tmp_path / "packaging" / name)
    py = tmp_path / "fakepy"
    py.write_text(FAKE_PYTHON, encoding="utf-8")
    py.chmod(0o755)
    log = tmp_path / "calls.log"
    return tmp_path, py, log


def _run_build(tree, script, **env_extra):
    root, py, log = tree
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ALBN_", "GITHUB_"))}
    env.update(PYTHON=str(py), FAKE_LOG=str(log), **env_extra)
    return subprocess.run(
        ["bash", str(root / "packaging" / script)],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def _calls(tree):
    return tree[2].read_text(encoding="utf-8").splitlines()


def test_build_macos_default_name_and_markers(fake_tree):
    root = fake_tree[0]
    res = _run_build(fake_tree, "build_macos.sh", ALBN_BUILD_SUFFIX="s1")
    assert res.returncode == 0, res.stderr
    app = root / "dist" / "albn-autofish-s1.app"
    assert app.is_dir()
    assert not (app / "Contents" / "Frameworks" / "QtWebEngineCore.framework").exists()
    assert (root / "dist" / ".build_suffix").read_text().strip() == "s1"
    assert (root / "dist" / ".build_macos_name").read_text().strip() == "albn-autofish-s1.app"
    calls = _calls(fake_tree)
    i_expire = next(i for i, c in enumerate(calls) if c.endswith("packaging/write_expire.py"))
    i_pyi = next(i for i, c in enumerate(calls) if "PyInstaller" in c)
    assert i_expire < i_pyi
    assert calls[i_pyi].endswith("packaging/albn_autofish.spec")


@pytest.mark.parametrize(
    "given,expected",
    [
        ("albn-autofish-dev.app", "albn-autofish-dev-s2.app"),
        ("albn-autofish-dev", "albn-autofish-dev-s2.app"),
        ("albn-autofish-dev-s2.app", "albn-autofish-dev-s2.app"),
    ],
)
def test_build_macos_custom_app_name_gets_suffix(fake_tree, given, expected):
    root = fake_tree[0]
    res = _run_build(fake_tree, "build_macos.sh", ALBN_BUILD_SUFFIX="s2", ALBN_APP_NAME=given)
    assert res.returncode == 0, res.stderr
    assert (root / "dist" / expected).is_dir()
    assert (root / "dist" / ".build_macos_name").read_text().strip() == expected


def test_build_suffix_defaults_to_github_run_id(fake_tree):
    root = fake_tree[0]
    res = _run_build(fake_tree, "build_macos.sh", GITHUB_RUN_ID="987")
    assert res.returncode == 0, res.stderr
    assert (root / "dist" / ".build_suffix").read_text().strip() == "987"
    assert (root / "dist" / "albn-autofish-987.app").is_dir()


def test_build_macos_fails_when_app_missing(fake_tree):
    root, py, _ = fake_tree
    py.write_text('#!/usr/bin/env bash\necho "$*" >> "$FAKE_LOG"\n', encoding="utf-8")
    res = _run_build(fake_tree, "build_macos.sh", ALBN_BUILD_SUFFIX="s3")
    assert res.returncode == 1
    assert not (root / "dist" / ".build_macos_name").exists()


def test_build_windows_output_and_preserves_user_data(fake_tree):
    root = fake_tree[0]
    out = root / "dist" / "albn-autofish-w1"
    (out / "data").mkdir(parents=True)
    (out / "data" / "user.json").write_text("keep", encoding="utf-8")
    res = _run_build(fake_tree, "build_windows.sh", ALBN_BUILD_SUFFIX="w1", ALBN_DIST_NAME="ignored")
    assert res.returncode == 0, res.stderr
    assert (out / "albn-autofish.exe").is_file()
    assert (out / "data" / "user.json").read_text(encoding="utf-8") == "keep"
    assert not (root / "dist" / "ignored").exists()
    assert (root / "dist" / ".build_windows_name").read_text().strip() == "albn-autofish-w1"
    assert (root / "dist" / ".build_suffix").read_text().strip() == "w1"
    assert any(c.endswith("packaging/write_expire.py") for c in _calls(fake_tree))


def test_build_windows_refuses_leftover_backup(fake_tree):
    root = fake_tree[0]
    (root / "build" / "data_backup_w2").mkdir(parents=True)
    res = _run_build(fake_tree, "build_windows.sh", ALBN_BUILD_SUFFIX="w2")
    assert res.returncode == 1
    assert not any("PyInstaller" in c for c in _calls(fake_tree))


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="未安装 PowerShell（pwsh），无法解析 build_windows.ps1")
def test_build_windows_ps1_parses():
    script = (PKG / "build_windows.ps1").as_posix()
    cmd = (
        "$errs = $null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{script}', [ref]$null, [ref]$errs) | Out-Null; "
        "if ($errs.Count) { $errs | ForEach-Object { $_.Message }; exit 1 }"
    )
    res = subprocess.run(["pwsh", "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stdout + res.stderr


def test_build_license_macos_output(fake_tree):
    root = fake_tree[0]
    res = _run_build(fake_tree, "build_license_macos.sh", ALBN_BUILD_SUFFIX="k1")
    assert res.returncode == 0, res.stderr
    assert (root / "dist" / "albn-license-keygen-k1.app").is_dir()
    assert not (root / "dist" / "albn-license-keygen").exists()
    name = (root / "dist" / ".build_keygen_macos_name").read_text().strip()
    assert name == "albn-license-keygen-k1.app"
    calls = _calls(fake_tree)
    assert not any("write_expire" in c for c in calls)
    assert any(c.endswith("packaging/albn_license_keygen.spec") for c in calls)


# ---------- gen_license_ui.py ----------


def test_gen_license_ui_generate_append_copy_clear(monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import (
        QApplication,
        QMessageBox,
        QPlainTextEdit,
        QPushButton,
        QRadioButton,
        QSpinBox,
    )

    ui = _load("gen_license_ui_under_test", PKG / "gen_license_ui.py")
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    win = ui.GenLicenseWindow()
    try:
        radios = {r.text(): r for r in win.findChildren(QRadioButton)}
        buttons = {b.text(): b for b in win.findChildren(QPushButton)}
        spin = win.findChild(QSpinBox)
        out = win.findChild(QPlainTextEdit)
        assert radios["30 天"].isChecked()
        assert (spin.minimum(), spin.maximum()) == (1, 200)

        radios["7 天"].setChecked(True)
        spin.setValue(3)
        buttons["生成"].click()
        lines = out.toPlainText().splitlines()
        assert len(lines) == 3
        assert all(license_mod.parse_key(k)["days"] == 7 for k in lines)

        radios["30 天"].setChecked(True)
        spin.setValue(2)
        buttons["生成"].click()
        lines = out.toPlainText().splitlines()
        assert len(lines) == 5
        assert [license_mod.parse_key(k)["days"] for k in lines[3:]] == [30, 30]

        buttons["复制全部"].click()
        assert QGuiApplication.clipboard().text().splitlines() == lines

        buttons["清空"].click()
        assert out.toPlainText() == ""
    finally:
        win.close()
        win.deleteLater()
        app.processEvents()
