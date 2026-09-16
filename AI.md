# albn-fishing — 项目总览

更新时间：2026-09-17

## 这个项目是什么

Albion 拉鱼：**模拟器**测算法 + **真机自动拉鱼**。方案索引见 `docs/README.md`。

## 关键不变量

1. 规则对齐官方：按住右移并涨进度、松开左移、进红失败、进度到头成功。
2. 界面元素来自 `fish_icon.png` 提取的 `assets/`。
3. 模拟器：`sim` + `algo`；真机：`autofish`；通用：`common`。

## 全树索引

| 路径 | 一句话职责 |
|---|---|
| `main.py` | 模拟器窗口入口 |
| `src/sim/` | 拉鱼纯逻辑与观测 API → `src/sim/AI.md` |
| `src/ui/` | 模拟器画面拼装 → `src/ui/AI.md` |
| `src/algo/` | 策略接口与无头跑局 → `src/algo/AI.md` |
| `src/common/` | 无业务通用库 → `src/common/AI.md` |
| `src/common/pubsub/` | 进程内 EventBus → `src/common/pubsub/AI.md` |
| `src/autofish/` | 真机五段实现 → `src/autofish/AI.md` |
| `src/tools/` | 调试编排（预览窗等）→ `src/tools/AI.md` |
| `assets/` | 运行时素材与几何 metrics |
| `data/` | ROI / 截图 / 调试输出 |
| `docs/` | 方案索引 |
| `docs/simulator/` | 模拟器方案 |
| `docs/autofish/` | 真机功能架构 |
| `docs/common/` | 通用库方案 |

## 验证命令

```bash
.conda/bin/python main.py
PYTHONPATH=src .conda/bin/python -m algo --tier 4 --episodes 50
PYTHONPATH=src .conda/bin/python -m autofish.preview --ui
```

## 关键文档

- `docs/README.md` — 方案索引
- `docs/simulator/` — 模拟器
- `docs/autofish/` — 真机五段
- `docs/common/pubsub/` — 订阅总线
- `INSTALL.md` — 安装与操作
