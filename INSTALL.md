# 安装说明

## 环境

- Python 3.10+
- 依赖：见 `requirements.txt`（pygame、mss、numpy、opencv、Pillow、PySide6、pynput）

## 安装

```bash
cd /Users/panda/Documents/code/test/albn-fishing
python3 -m venv .venv   # 或使用已有 .conda
.venv/bin/pip install -r requirements.txt
```

## 启动

```bash
.conda/bin/python main.py
# 或
.venv/bin/python main.py
```

## 操作

| 操作 | 效果 |
|---|---|
| **1–8** | 开局前/结束后选鱼等级 T1–T8（默认 T4） |
| 点击 / 空格 | 开始；游戏中按住=收线 |
| 按住左键 / 空格 | 鱼漂向右，进度上涨（越靠右越快） |
| 松开 | 鱼漂向左 |
| 进左右红区 | 失败 |
| 进度到头 | 成功 |
| R | 重开（保留当前等级） |
| Esc | 退出 |

玩法说明见 `docs/simulator/`，难度见 `docs/simulator/difficulty/`，算法测试分包见 `docs/simulator/algo-test/`。手感基准参数见 `src/sim/config.py`。

## 算法侧（无头）

包在 `src/` 下；直接脚本请带上 `PYTHONPATH=src`（`main.py` 已自动处理）。

```bash
PYTHONPATH=src .conda/bin/python -m algo --tier 4 --episodes 50
```

```python
from algo import ThresholdHoldPolicy, run_batch

run_batch(ThresholdHoldPolicy(), episodes=100, tier=4)
```

策略：绿区内相对 pos（左绿=0，右绿=100）&lt;50 按住，&gt;90 松开；切换至少 0.2s + 约 0.1s 随机。测策略只走模拟器，不点真鼠标。

依赖列表见根目录 `requirements.txt`（含 PySide6 调试壳）。

## macOS / Windows 打包

本地：

```bash
make build-macos      # → dist/albn-autofish.app
make build-windows    # 须在 Windows；→ dist/albn-autofish/
```

GitHub Actions：

- **push `main`**：自动打 macOS + Windows 包（Artifacts 可下载）
- **push tag `v*`**：构建并上传到 GitHub Release
- 也可手动跑 workflow（可填 tag 发版）

```bash
git push origin main
# 发版：
git tag v0.1.0 && git push origin v0.1.0
```
产物：

- **Actions Artifact**（main 推送 / 手动且 tag 留空）：下载解压一次即可——macOS 得 `albn-autofish.app`，Windows 得 `albn-autofish/`（内含 `albn-autofish.exe`）。勿再预打 zip 上传，避免 zip 套 zip。  
- **GitHub Release**（打 tag / 手动填 tag）：附件为  
  - `albn-autofish-macos-arm64.zip`（内含 `.app`）  
  - `albn-autofish-windows-x64.zip`（内含 `albn-autofish/`）

macOS：打开预览壳顶栏 **「权限」** 授权屏幕录制与辅助功能；若被 Gatekeeper 拦截，右键打开或 `xattr -dr com.apple.quarantine albn-autofish.app`。  
本地反复重打包后授权「被旧包占用」：先 `make reset-perms`，或用 `make build-macos-dev`（独立 Bundle ID，不跟正式包抢）。系统设置里也可手动删掉旧的 Albn Autofish 条目再重授。  
Windows：顶栏可测截屏、以管理员重启（游戏提权时常用）。ROI、模板、长录音、设置等数据：macOS 在 `~/Library/Application Support/albn-autofish/`；Windows 在 `albn-autofish.exe` 同级的 `data\`（该目录不可写时退回 `%LOCALAPPDATA%\albn-autofish\`）。

## 真机感知（截图 + 色块）

1. 打开预览窗，游戏画面露在主屏上。
2. **空格**：自动截全屏（窗口会先最小化）→ 进入框选。
3. **拖拽**框出张力条 → **Enter** 写入 `data/roi.json`。
4. 离线重框：对已有 `data/screen.png` 按 **C**，无需再截。

```bash
PYTHONPATH=src .conda/bin/python -m autofish.preview --ui
```

读数 **0～100**（ROI 最左=0，最右=100）。窗口上方大号为**真机读数**，左侧真机截图，右侧模拟器。功能架构见 `docs/autofish/`。
