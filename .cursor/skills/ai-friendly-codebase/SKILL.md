---
name: ai-friendly-codebase
description: >-
  用 AI.md 索引代码、上层极简，减少 Agent 读代码量。
  触发：写/审 AI.md、按索引找代码、判上层是否过厚、拷到他仓。
---

# AI-Friendly Codebase

## 必须

1. `AI.md` = 代码目录索引与对外契约摘要；产品方案在 `docs/`，禁止写入 AI.md。
2. 找/改代码：根 `AI.md` 全树 → 叶子 `AI.md` → 实现文件；禁止无目标全量扫代码树。
3. 先 Read 本文件，再按需打开 [ai-md.md](ai-md.md) / [thin-upper.md](thin-upper.md) / [templates/](templates/)。
4. 改完且检查通过 → 更新相关 AI.md；新目录补叶子并在根全树加一行；父级清单只留「路径 + 一句话 + 指向叶子」，禁止重复子叶子细节。
5. 项目专属分层与业务禁令写在该仓库 `docs/` 或专属 rule；本 Skill 保持通用，禁止写死业务清单。

## 禁止

1. AI.md 新鲜时仍遍历该文件夹。
2. 上层堆复杂逻辑 / 内联 IO。
3. 把 AI.md 当行为规格书或产品方案书。
4. 把某仓业务模块表写进本 Skill 再扩散。
