# 锚漂识别器（bobber_anchor）

## 目标

提供 **默认** `bobber_anchor` 识别器：**先独立 CV 定漂，再从漂沿同高由内向外用端帽外形定条边界**，降低半透明背景对定界的干扰；`color_blocks` 仍可切换对比。

## 要实现的

- 本方法资源统一放在 `assets/bobber_anchor/`，禁止与根目录其它模板混放。
  - 漂：见 [docs/autofish/detect/find_bobber.md](find_bobber.md)（`assets/bobber_anchor/bobber.png`）
  - 左边界（优先）：`endcap_left_full.png`（完整左端：多道橘黄贴绿，透明底）；短帽 `endcap_left.png` 仅作备选/对照
  - 右边界（优先）：`endcap_right_full.png`；短帽 `endcap_right.png` 仅作备选/对照
- **先漂后条（顺序固定）**：
  1. 定漂必须调用独立找漂能力；漂未命中 → 本帧无读数；
  2. 以漂为锚，**仅在同高窄带**，从漂位**向左 / 向右由内向外**匹配端帽，定 `bar_left` / `bar_right`；
  3. 禁止全图重新色块定条；禁止在超长带上取「灰度全局最高分」当边界（易贴到暗背景假峰）。
- **定界主手段**：端帽 **彩色（RGB）模板 + alpha 掩膜** 相关匹配（与找漂复核同类，非纯灰度主判）；尺度跟漂/条高度估计，少档即可。
- 颜色对端帽只作**软辅助**（如橘黄结构加分）；不得代替外形匹配，不得因颜色略差否决已成立的高分端帽形。
- 端帽只在漂已成立后确认边界，**不得用端帽高分救起低分假漂**。
- 选取规则：每一侧取**由内向外第一段过门槛的端帽**（或同等的「近漂优先」），不得用远离漂的更高分盖过近侧真端。
- **默认识别器**；可通过 `use_color_blocks()` / `use_template()` 切换其它方法。
- 输入：RGB 图（与其它识别器同）。
- 输出：`BobberHit`（条框 + pos）或 `None`。
- 核心假设：
  - 漂不透明、外形固定，可先精确定位；
  - 绿条/端帽半透明，纯灰度易假高峰，故定界须彩色外形，且从漂往外锁近邻；
  - 漂贴左/右端时，允许一侧端帽极短或几乎贴漂。
- **帧率**：整段（定漂 + 定界）须支撑 **≥ 20 fps**；硬上限单帧 **< 50 ms**，宜 **< 40 ms**。定界必须窄带、远轻于定漂。

## 解决步骤

1. 定漂：调用 [docs/autofish/detect/find_bobber.md](find_bobber.md)；无漂则结束。
2. 加载并缓存端帽彩色+alpha（优先 full；构造时读盘一次）。
3. 以漂身体为锚，同高窄带内向左/右做彩色端帽匹配；由内向外取合格近邻，得 `bar_left` / `bar_right`。
4. 由条框与漂质心算 pos；端帽只作成立条件，终选以漂分为主。
5. `find_bar`：同流程；无漂则无条。
6. `detect.api` 默认 `bobber_anchor`；保留 `use_color_blocks()` / `use_template()` / `use_bobber_anchor()`。
7. 验收：
   - 找漂：`data/test/find_bobber_baseline.json` + `check_find_bobber_baseline`；
   - 整段：同批测图 `detect_ms` 满足硬上限；条两端须落在真实橘端（重点回归 a956 / ea2ec 等曾跑飞案例）；输出标记图人工看；定界不得拖垮 20fps。
