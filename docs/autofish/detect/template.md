# 模板识别器（template）

## 目标

提供一个可选的 `template` 识别器，用 matchTemplate 定位张力条，尽量压缩单帧耗时到 **~10 ms**，用于与 `color_blocks` 对比或备用。

## 要实现的

- 模板只加载一次：构造时读盘，预建灰度/多尺度金字塔，禁止每帧重复 `cv2.imread`。
- 默认模板取自**实机画面**裁出的张力条；模拟器条比例与实机不同，禁止作默认（会让 pos 系统性偏移）。
- 输入图与模板同时按比例压缩，默认缩放因子 `0.25`；灰度匹配（形状为主）。
- 默认每帧仅在上一命中位置附近 ROI 搜索；首次/丢失后回退全图搜索。
- 命中稳定后单帧耗时目标 **< 10 ms**；全图搜索目标 **< 20 ms**。
- 不替代 `color_blocks`：默认仍是 color_blocks；template 通过 `use_template()` 切换。
- 识别耗时随 `PosEvent` 发出，并在日志/UI 实时输出显示。

## 解决步骤

1. 默认模板 = 实机截图裁出的张力条（含两端端帽，漂已抹除），存于 `assets/tension_bar.live.png`。
2. `TemplateBarDetector` 预加载模板灰度图并缓存缩放后模板。
3. `detect(rgb)`：
   - 有上一命中框 → 在邻域 ROI 压缩搜索。
   - 无/丢失 → 全图压缩搜索。
4. `PosEvent` 带 `detect_ms`，由 Detect worker 计时填入。
5. 日志/预览 UI 显示最近识别耗时。
