# 识别（Detect）

## 目标

订 ROI 与最新 Frame，在手框画面内读出鱼漂 **0～100**。本段不做手框存盘、不改 mss 范围、不做键鼠。

## 要实现的

- 输入：订阅 **ROI** + **最新 Frame**（Frame 已是手框截取结果）；无 Frame 则等待；错 `roi_version` 丢弃。
- **只认最新帧**：积压 Frame **抛弃不识**；已开算的帧**算完仍发 Pos**。
- **mss 范围只由手框决定**；Detect **禁止**发布/缩小/改写当前 ROI。
- **对外只需三件事**：绿条在哪、鱼漂在哪、由此算出 **pos（0～100）**。
- **识别方法**：统一 `detect(rgb) → 结果|无`；默认且唯一 **bobber_anchor**（见 [docs/autofish/detect/bobber_anchor.md](bobber_anchor.md)）。
  - **find_bobber**：见 [docs/autofish/detect/find_bobber.md](find_bobber.md)（独立 CV 定漂：颜色结构候选 + 小模板复核；不定条；供 bobber_anchor 调用）
- **bobber_anchor**：**先漂后条**；手动条界覆盖程序；漂未命中则本帧无读数；ROI 变则条界重标/重采。
- 识别线程**单帧异常不得退出**；监控重启时**重置帧序**，禁止「中断后永久不识别」。
- 每帧识别**耗时随读数一起发出**，供日志与界面显示效率。
- 不做：改 mss、手框 UI、吸色定框、键鼠；不做 color_blocks / template 备用识别器。

## 解决步骤

1. 订 Frame（及 ROI 版本校验）。
2. 当前识别器：`detect(frame)` → Pos（bobber_anchor）。
