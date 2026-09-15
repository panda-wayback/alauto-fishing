# albn-fishing — 项目总览

更新时间：2026-09-16

## 这个项目是什么

Albion Online 拉鱼小游戏桌面模拟器（仅拉鱼段）。方案见 `docs/README.md`。

## 关键不变量

1. 规则对齐官方：按住右移并涨进度、松开左移、进红失败、进度到头成功。
2. 界面元素来自 `fish_icon.png` 提取的 `assets/`。

## 全树索引

| 路径 | 一句话职责 |
|---|---|
| `main.py` | 窗口循环与输入 |
| `fishing.py` | 拉鱼状态机与物理 |
| `difficulty.py` | T1–T8 难度曲线 |
| `render.py` | 拼画面 |
| `config.py` | T4 基准参数与资源路径 |
| `assets/` | 运行时素材与几何 metrics |
| `data/` | 手动截图源图（清干扰后写入 assets） |
| `docs/` | 方案 |
| `docs/difficulty/` | 鱼等级难度设计 |

## 验证命令

```bash
.conda/bin/python main.py
# 或
.venv/bin/python main.py
```

## 关键文档

- `docs/README.md` — 方案
- `INSTALL.md` — 安装与操作
