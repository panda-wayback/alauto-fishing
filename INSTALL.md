# 安装说明

## 环境

- Python 3.10+
- 依赖：`pygame`（见 `requirements.txt`）

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

玩法说明见 `docs/README.md`，难度见 `docs/difficulty/`。手感基准参数见 `config.py`。
