# src/autofish/locate/ 功能说明

更新时间：2026-09-25

## 本文件夹职责

段1：手框 ROI 与可选手动条界的存盘/读写。方案见 `docs/autofish/locate/`。

## 目录清单

- `roi.py` — `Roi` / `BarMark`；默认/手动存盘；条界参考图路径

## 对外契约

- `Roi` / `load_roi` / `save_roi` / `DEFAULT_ROI_PATH`
- `ROI_SOURCE_DEFAULT` / `ROI_SOURCE_MANUAL` / `load_roi_source`
- `default_center_roi` / `primary_screen_size`
- `BarMark` / `load_bar_mark` / `clear_bar_mark` / `bar_ref_path` / `clear_bar_ref`
- 无自动找绿 Worker；ROI 变更由壳 / `AutofishPipeline.set_roi_manual` 发布

## 约束

- 手框唯一决定 mss 范围；本段不截屏、不识图、不点鼠标。
- 存盘 `source=manual|default`；手动优先；无存盘/恢复默认 → 主屏居中 1/4×1/4。
- 重框 / 清空 ROI 须同步清手动条界与参考图。
