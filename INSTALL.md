# 安装说明

## 环境

- Python 3.10+
- 依赖：见 `requirements.txt`（pygame、mss、numpy、opencv-python-headless、Pillow）

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

玩法说明见 `docs/README.md`，难度见 `docs/difficulty/`，算法测试分包见 `docs/algo-test/`。手感基准参数见 `src/sim/config.py`。

## 算法侧（无头）

包在 `src/` 下；直接脚本请带上 `PYTHONPATH=src`（`main.py` 已自动处理）。

```bash
PYTHONPATH=src .conda/bin/python -c "from algo.runner import run_episode; ..."
```

```python
from algo.runner import run_episode, run_batch
from sim.api import Observation

class MyPolicy:
    def decide(self, obs: Observation) -> bool:
        # True=按住收线，False=松开
        ...

run_episode(MyPolicy(), tier=4)
run_batch(MyPolicy(), episodes=100, tier=4)
```

## 真机感知（截图 + 色块）

1. 打开预览窗，游戏画面露在主屏上。
2. **空格**：自动截全屏（窗口会先最小化）→ 进入框选。
3. **拖拽**框出张力条 → **Enter** 写入 `data/roi.json`。
4. 离线重框：对已有 `data/screen.png` 按 **C**，无需再截。

```bash
PYTHONPATH=src .conda/bin/python -m vision.preview --ui
```

读数 **0～100**（ROI 最左=0，最右=100）。窗口上方大号为**真机读数**，左侧真机截图，右侧模拟器。方案见 `docs/vision/`。
