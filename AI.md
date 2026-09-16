# albn-fishing — 项目总览

更新时间：2026-09-16

## 这个项目是什么

Albion Online 拉鱼小游戏桌面模拟器（仅拉鱼段），供测试自动拉鱼算法；含真机 ROI 截图与色块跟漂基础。方案见 `docs/README.md`。

## 关键不变量

1. 规则对齐官方：按住右移并涨进度、松开左移、进红失败、进度到头成功。
2. 界面元素来自 `fish_icon.png` 提取的 `assets/`。
3. 算法逻辑依赖 `sim` + `algo`；真机感知在 `vision`（不依赖 pygame）。

## 全树索引

| 路径 | 一句话职责 |
|---|---|
| `main.py` | 人机窗口循环与输入（把 `src/` 加入 path） |
| `src/sim/` | 纯逻辑：物理、难度、参数、观测/步进 |
| `src/sim/game.py` | 拉鱼状态机与物理 |
| `src/sim/api.py` | 观测快照与 `step(holding)` |
| `src/sim/difficulty.py` | T1–T8 难度曲线 |
| `src/sim/config.py` | T4 基准参数与资源路径 |
| `src/ui/render.py` | 拼画面（pygame） |
| `src/algo/` | 策略接口与无头跑局 |
| `src/vision/` | 真机：手动 ROI、mss 截图、色块跟漂 |
| `src/vision/roi.py` | ROI 读写（`data/roi.json`） |
| `src/vision/capture.py` | mss 截 ROI / 主屏；存 `data/screen.png` |
| `src/vision/bobber.py` | AF 式：HSV 绿条 + 空洞/缺绿 → `pos` 0～100 |
| `src/vision/smooth.py` | 读数中值平滑 |
| `src/vision/hsv_calib.py` | 绿区吸色标定 |
| `src/vision/app.py` | 分区预览 + 截屏框选 + 监控/吸色 |
| `src/vision/preview.py` | CLI；`--ui` 开窗 |
| `assets/` | 运行时素材与几何 metrics |
| `data/` | ROI 标定、调试输出、截图源 |
| `docs/` | 方案 |
| `docs/difficulty/` | 鱼等级难度设计 |
| `docs/algo-test/` | 算法测试分包 |
| `docs/vision/` | 真机感知（截图 + 色块） |

## 验证命令

```bash
.conda/bin/python main.py
PYTHONPATH=src .conda/bin/python -m vision.preview --ui
```

## 关键文档

- `docs/README.md` — 方案
- `docs/algo-test/` — 分包与无头入口
- `docs/vision/` — 截图与色块
- `INSTALL.md` — 安装与操作
