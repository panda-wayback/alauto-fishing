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

## macOS 打包（真机预览 .app）

```bash
bash packaging/build_macos.sh
# 输出 dist/albn-autofish.app
```

把 `dist/albn-autofish.app` 拷到其它 Mac 双击即用（Apple Silicon）。ROI 等运行时数据写到 `~/Library/Application Support/albn-autofish/`。首次运行需在系统设置里授权「屏幕录制」和「辅助功能」；若被 Gatekeeper 拦截，右键打开或 `xattr -dr com.apple.quarantine albn-autofish.app`。Windows 需在 Windows 上另行打包。

## 真机感知（截图 + 色块）

1. 打开预览窗，游戏画面露在主屏上。
2. **空格**：自动截全屏（窗口会先最小化）→ 进入框选。
3. **拖拽**框出张力条 → **Enter** 写入 `data/roi.json`。
4. 离线重框：对已有 `data/screen.png` 按 **C**，无需再截。

```bash
PYTHONPATH=src .conda/bin/python -m autofish.preview --ui
```

读数 **0～100**（ROI 最左=0，最右=100）。窗口上方大号为**真机读数**，左侧真机截图，右侧模拟器。功能架构见 `docs/autofish/`。
