# 识别（Detect）

## 目标

订 ROI 与最新 Frame，在手框画面内读出鱼漂 **0～100**。本段不做手框存盘、不改 mss 范围、不做键鼠。

## 要实现的

- 输入：订阅 **ROI** + **最新 Frame**（Frame 已是手框截取结果）；无 Frame 则等待；错 `roi_version` 丢弃。
- **只认最新帧**：积压 Frame **抛弃不识**；已开算的帧**算完仍发 Pos**。
- **mss 范围只由手框决定**；Detect **禁止**发布/缩小/改写当前 ROI。
- **对外只需三件事**：绿条在哪、鱼漂在哪、由此算出 **pos（0～100）**。
- **识别方法可替换**：统一 `detect(rgb) → 结果|无`。
  - **bobber_anchor（默认）**：见 [docs/autofish/detect/bobber_anchor.md](bobber_anchor.md)（先 find_bobber；同高由内向外彩色端帽定界；≥20fps）
  - **color_blocks**：绿带内取**最左橘红**与**最右橘红**为起止，中间为绿段（同高）；中部漂橙叶忽略；**入图过宽先等比压缩定条，坐标映回后在原图条框附近找漂**；单帧 **< 10 ms**（掩膜共用一次色彩转换；压缩定条结果须与未压缩同图一致到可读精度）；可选，`use_color_blocks()` 切换
  - **template**：见 [docs/autofish/detect/template.md](template.md)（压缩灰度 + 上一位置跟踪；可选）
  - **find_bobber**：见 [docs/autofish/detect/find_bobber.md](find_bobber.md)（独立 CV 定漂：颜色结构候选 + 小模板复核；不定条；供 bobber_anchor 调用）
- 绿段左右可外扩绿宽×5% 再映到 0～100。
  - **bobber_anchor**：**先漂后条**（定漂见 find_bobber）；漂未命中则本帧无读数。
  - **color_blocks / template**：**绿条既定必有漂**（白 → 绿孔 → 绿密度谷兜底）；无条才无读数；**漂只在条内**（质心出条即弃；白肚可略溢出条沿）。
- 识别线程**单帧异常不得退出**；监控重启时**重置帧序**，禁止「中断后永久不识别」。
- 每帧识别**耗时随读数一起发出**，供日志与界面显示效率。
- 不做：改 mss、手框 UI、吸色定框、键鼠。

## 解决步骤

1. 订 Frame（及 ROI 版本校验）。
2. 当前识别器：`detect(frame)` → Pos（默认 bobber_anchor）。
