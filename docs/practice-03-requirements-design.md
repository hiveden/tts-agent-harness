# TTS Harness 工程实践（三）：需求设计

> 项目：tts-agent-harness — 视频脚本转语音+字幕生产工具
> 时间跨度：2026-03-30 ~ 2026-04-14（16 天，239 commits）

---

## 一、从痛点到产品形态

### 1.1 原始痛点

视频制作中的配音环节：

```
写好脚本 → 调用 TTS API → 下载 WAV → 本地播放器试听 → 发现"Karpathy"读成"卡帕西"
→ 改文本 → 重新调用 API → 再下载 → 再试听 → 还是不对 → 再改...
```

核心问题不是 TTS 合成本身，而是 **试听-修改-重试的循环太重**。每次循环需要：命令行调 API + 找文件 + 打开播放器 + 回到编辑器改文本。

### 1.2 产品形态的推导

目标：把 **试听-修改-重试** 的循环成本降到最低。

```
上传脚本 → 自动切分 → 批量合成 → 逐句试听（就在页面上）→ 不满意就改文本 → 点一下重试 → 满意后导出
```

关键交互决策：
- **逐句而非整篇**：一句不好只重做一句，不用等整篇重新合成
- **即听即改**：播放按钮和编辑按钮在同一行，不需要跳转页面
- **Take 历史**：每次重试产生新 take，旧的不删除，可以回退对比
- **批量 + 单条并存**："合成全部"做批量，单条 synthesize 做精修

### 1.3 用户故事体系

docs/003-user-stories.md 中定义了 19 个用户故事和 6 个产品设计决策：

**6 个产品设计决策（D-01 ~ D-06）：**

| ID | 决策 | 理由 |
|----|------|------|
| D-01 | text 同时用于 TTS 和字幕 | 简化模型，一处修改全链路生效 |
| D-02 | text_normalized 覆盖 text 做 TTS 输入 | 允许"显示文本"和"朗读文本"不同 |
| D-03 | Take 记录每次合成结果，不删除旧 take | 人工对比不同版本的发音效果 |
| D-04 | Pipeline 一键全跑，但支持逐 chunk 重试 | 批量效率 + 精修灵活性 |
| D-05 | 控制标记只影响 TTS，字幕自动过滤 | 用户不需要手动清理字幕文本 |
| D-06 | 导出面向下游 Remotion 消费 | 产物格式由消费方决定 |

**19 个用户故事的分层：**

```
基础操作（US-01 ~ US-03）：创建 episode、查看列表、查看详情
合成流程（US-04 ~ US-08）：配置 TTS、运行 pipeline、试听、编辑重试、切换 take
质量检查（US-09 ~ US-11）：查看 stage 状态、查看日志、查看验证评分
导出交付（US-12 ~ US-13）：导出 zip、预览脚本
管理操作（US-14 ~ US-19）：归档、锁定、取消运行、配置 API Key
```

---

## 二、做减法的艺术

### 2.1 砍掉的功能清单

这个项目中被砍掉的功能比保留的还多：

| 功能 | 创建时间 | 砍掉时间 | 存活 | 砍掉原因 |
|------|---------|---------|------|---------|
| P4 Claude 校验 | 3/30 | 4/8 | 9 天 | LLM 做运行时判断不可靠 |
| normalize-patches 跨期记忆 | 3/30 | 4/2 | 3 天 | 非确定性输出导致跨 episode 规则不通用 |
| tts-known-issues 记忆 | 3/30 | 4/3 | 4 天 | 同上 |
| 中英边界自动加点 | 3/30 | 4/2 | 3 天 | S2-Pro 引擎本身处理得更好 |
| P1 大写转 titlecase | 3/30 | 4/2 | 3 天 | `normalize: false`，让引擎原样处理 |
| Repair Loop (L0/L1) | 4/12 | 4/13 | **1 天** | 自动重试同样文本大概率得到同样结果 |
| 5 维评分 | 4/13 14:12 | 4/13 17:21 | **3 小时** | 3 个维度依赖不稳定的 ASR 转写 |
| dark mode | 4/13 12:06 | 4/13 19:50 | **8 小时** | 部署前清理，非核心功能 |
| P3 独立服务 | 4/9 | 4/12 | 3 天 | 并入 P2v，减少一个运行时服务 |
| Next.js Route Handlers | 4/8 | 4/10 | 2 天 | 被 FastAPI + openapi-fetch 替代 |
| 手写 adapter 层 | 4/10 09:01 | 4/10 10:44 | **1.7 小时** | 被 openapi-typescript codegen 替代 |

### 2.2 砍功能的判断框架

经过多次"做减法"的实践，我总结出一个判断框架：

**信号 1：非确定性组件链式传播**

```
P2(非确定) → P3(非确定) → P4(非确定)
```

三个非确定性环节串联，误差累积。P4 用 LLM 判断"P3 转写的文本和原文是否语义一致"——但 P3 的转写本身就可能有误，P4 基于错误的输入做判断，结论不可信。

**信号 2：功能存活时间 < 1 天**

Repair Loop 和 5 维评分都是当天创建当天（或次日）砍掉的。这说明在设计阶段没有充分考虑"这个功能在真实场景下是否有效"。以后的改进：**先在纸上推演一遍完整的用户流程，再写代码。**

**信号 3：部署前的减法优于上线后的减法**

dark mode 在部署前被砍掉，原因是"非核心功能 + 增加 CSS 复杂度"。这个决策虽然损失了 8 小时的工作，但避免了线上多一个需要维护的 feature。

### 2.3 `normalize: false` 的哲学

项目初期（V1 CLI 时代），P1 做了大量文本预处理：
- 英文连字符转空格
- 破折号转逗号
- 文件扩展名转中文（.md → 文档, .json → 文件）
- 大写英文转 titlecase
- 中英边界加停顿标记

升级到 Fish S2-Pro 后，发现引擎本身对中英混合文本的处理已经相当好。于是做了一个关键决策：

```python
# P2 发送 normalize: false，让 S2-Pro 引擎原样处理文本
response = await fish_client.synthesize(
    text=chunk.tts_text,
    normalize=False,
    ...
)
```

然后逐步删除 P1 中的所有预处理规则。这个过程在 commit 中清晰可见：

```
4/2 15:03  remove Chinese-English boundary dot insertion from P1
4/2 15:38  remove P4→P1 normalize-patches pipeline
4/3 10:22  S2-Pro pipeline cleanup — remove legacy normalize/memory code
```

**教训：当上游变强时，中间层应该变薄。** S2-Pro 引擎的能力提升了，我们的预处理层就应该退化为透传。

---

## 三、面向下游的导出契约

### 3.1 导出产物设计

导出 zip 的格式完全由下游 Remotion 项目（`astral-video`）决定：

```
episode-export.zip/
  shot01.wav          — per-shot 拼接音频
  shot02.wav
  ...
  durations.json      — [{id, duration_s, file}]
  subtitles.json      — {shot_id: [{id, text, start, end}]}
```

### 3.2 为什么是 per-shot 而不是 per-chunk

原始 pipeline 的产物是 per-chunk WAV（每个句子一个文件）。但下游 Remotion 的消费粒度是 shot（镜头），一个 shot 可能包含多个 chunk。

P6 的工作就是把同一个 shot 的 chunks 拼接为一个 WAV，同时偏移字幕时间戳。

```python
# P6 拼接逻辑
for shot_id, chunks in grouped_by_shot.items():
    # ffmpeg concat per-shot WAV + padding(0.2s between chunks)
    concat_wav = ffmpeg_concat([c.wav_path for c in chunks], gap=0.2)

    # 偏移字幕时间戳
    offset = 0
    for chunk in chunks:
        for subtitle in chunk.subtitles:
            subtitle.start += offset
            subtitle.end += offset
        offset += chunk.duration + 0.2  # chunk duration + gap
```

### 3.3 导出格式的迭代

导出功能经历了 3 次修复才稳定：

```
4/12 22:14  feat: GET /episodes/{id}/export — 初版
4/13 12:32  fix: export endpoint outputs Remotion-compatible subtitles.json
4/14 21:07  fix: re-encode WAV on export concat to fix duration calculation bug
```

第三个 fix 特别值得记录——ffmpeg concat 后的 WAV 文件 header 中的 duration 可能不准确（因为 concat 是简单拼接 raw data，header 未更新）。解决方案是 concat 后用 ffmpeg 重新编码一次：

```python
# 重新编码为 44100Hz mono PCM16，确保 header 正确
ffmpeg -i concat.wav -ar 44100 -ac 1 -c:a pcm_s16le output.wav
```

### 3.4 subtitles.json 的两种视角

字幕有两种时间视角：
- **chunk-level**：每个 chunk 内部，start/end 从 0 开始
- **shot-level**：同一 shot 内所有 chunks 的字幕，start/end 带 shot 内偏移

导出产物使用 shot-level 视角，因为 Remotion 直接按 shot 消费。

```json
{
  "1": [
    {"id": "c1", "text": "第一句话", "start": 0.0, "end": 1.2},
    {"id": "c2", "text": "第二句话", "start": 1.4, "end": 2.8}
  ]
}
```

这个格式的设计考量：
- key 是 shot_id（字符串），不是数组索引——方便 Remotion 按 shot 查找
- 每个字幕条目有 id，方便调试时追溯到原始 chunk
- start/end 是浮点秒数，不是毫秒——Remotion 的 `useCurrentFrame()` 更容易换算

---

## 四、渐进式 MVP

### 4.1 五层 MVP 边界

这个项目的开发不是一步到位，而是逐层叠加的：

**Layer 0：CLI 可用（3/30，Day 1）**

```
输入 script.json → 合成 WAV → 生成字幕 → 拼接导出
```

一天内跑通全链路。CLI 模式，手动操作，但核心 pipeline 已经可用。

**Layer 1：Web 可交互（4/8，Day 10）**

```
上传脚本 → 看到 chunk 列表 → 播放音频 → 编辑文本 → 重新合成
```

3 小时做出 Web MVP，用 fixture 数据，验证交互设计。

**Layer 2：后端持久化（4/9-4/10，Day 11-12）**

```
PostgreSQL 存状态 → MinIO 存音频 → Prefect 编排 task → SSE 实时推送
```

12 小时并行构建 13 个模块（Wave 1-5），前后端联调。

**Layer 3：质量体系（4/11-4/12，Day 13-14）**

```
gate check stages → P2v 评分 → 错误处理链路 → Dev Mode 容错
```

从"能用"到"好用"——加入质量保障、错误反馈、开发体验优化。

**Layer 4：部署上线（4/13-4/14，Day 15-16）**

```
Dockerfile → Fly.io → Caddy 反代 → CI/CD → API Key 安全 → SSE 流式
```

从本地到线上的最后一英里。

### 4.2 每层的 MVP 判断标准

| 层 | MVP 完成标志 | 不做什么 |
|----|-------------|---------|
| L0 | 能产出 Remotion 可消费的 zip | 不做 UI、不做持久化 |
| L1 | 能在浏览器里试听和编辑 | 不接真实后端、不做状态持久化 |
| L2 | 重启不丢数据、支持并发 | 不做自动校验、不做错误提示 |
| L3 | 错误有反馈、质量有评分 | 不做自动修复、不做多用户 |
| L4 | 外网可访问、API Key 安全 | 不做多声音、不做用户系统 |

### 4.3 时间线总览

```
Day 1  (3/30)  ████████████████  CLI 全链路跑通 + P4 Claude 校验
Day 2  (3/31)  ░░░░░░░░░░░░░░░░  (休息)
Day 3  (4/1)   ░░░░░░░░░░░░░░░░  (休息)
Day 4  (4/2)   ████████          S2-Pro 升级 + 砍 normalize-patches
Day 5  (4/3)   ████              砍 P4 跨期记忆 + 文档对齐
Day 6-9(4/4-7) ░░░░░░░░░░░░░░░░  (休息)
Day 10 (4/8)   ████████████████  砍 P4 + Web MVP + L1 业务设计
Day 11 (4/9)   ████████████████  ADR-001/002 + Wave 1-3 并行构建
Day 12 (4/10)  ████████████████  Wave 4-5 + 前端对齐 + openapi + Dev Mode + E2E
Day 13 (4/11)  ████████████████  UI 打磨 + shadcn 迁移 + 组件精细化
Day 14 (4/12)  ████████████████  Pipeline 重构 + gate stages + 错误处理 + 导出
Day 15 (4/13)  ████████████████  功能收尾 + 清理 + Fly.io 部署
Day 16 (4/14)  ████████████████  Caddy + CI/CD + 安全加固 + 产品文档
```

实际编码天数：10 天（Day 1, 4, 5, 10-16），其中 Day 10-16 连续 7 天是高强度开发。

### 4.4 commit 密度分析

```
3/30:  18 commits (CLI 全功能)
4/2:    6 commits (S2-Pro 升级)
4/3:    2 commits (清理)
4/8:    8 commits (Web MVP)
4/9:   12 commits (Server 重写)
4/10:  26 commits (集成打通) ← 最高产的一天
4/11:  12 commits (UI 打磨)
4/12:  42 commits (Pipeline + 错误处理 + 导出) ← commit 最多的一天
4/13:  55 commits (功能收尾 + 部署) ← commit 最密的一天
4/14:  22 commits (安全 + 文档)
```

4/12 和 4/13 两天合计 97 个 commit，占总量的 40%。这两天是从"功能开发"转向"产品化"的关键转折——大量的 fix、polish、cleanup 类 commit。

---

## 五、tts_text 与 text 的分离

### 5.1 问题起源

初始设计中 `text` 字段身兼两职：
1. 作为 TTS 合成的输入
2. 作为字幕的文本来源

当用户需要修改发音时（如 `transformer` → `trans former`），修改 `text` 会同时影响字幕显示。但用户想要的是：**字幕显示"transformer"，TTS 朗读"trans former"**。

### 5.2 解决方案

commit `628f7cf`（4/2）引入了 `tts_text` 字段：

```python
class Chunk:
    text: str           # 字幕文本（不可变）
    tts_text: str       # TTS 输入（可编辑）
```

- `text` 来自原始脚本，不可修改，用于字幕生成（P5）
- `tts_text` 默认等于 `text`，用户编辑后覆盖，用于 TTS 合成（P2）
- 前端的 ChunkEditor 编辑的是 `tts_text`

后来 Web 版本中这个字段改名为 `text_normalized`，语义更清晰：

```python
class Chunk:
    text: str                # 原文（字幕来源）
    text_normalized: str     # 归一化后的文本（TTS 输入，用户可编辑）
```

### 5.3 控制标记的过滤

S2-Pro 支持控制标记（`[break]`、`[breath]`、`[long break]`等），这些标记只应影响 TTS 合成，不应出现在字幕中。

P5 字幕生成时自动过滤：

```python
def strip_control_markers(text: str) -> str:
    """Strip all [...] control markers from text for subtitle generation."""
    return re.sub(r'\[.*?\]', '', text).strip()
```

commit `b4a2ed1` 的修复确保了匹配所有 `[...]` 格式的标记，而不只是预定义的几种。

---

## 六、tts_config 的设计

### 6.1 配置层级

TTS 配置支持三层覆盖：

```
环境变量 (.env) → 脚本级 (script.json.tts_config) → 运行时 (API 请求参数)
```

默认值来自环境变量，脚本可以覆盖，运行时可以再覆盖。

### 6.2 关键参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| model | s2-pro | TTS 模型 |
| temperature | 0.3 | 采样温度，低=稳定，高=有表现力 |
| top_p | 0.5 | Nucleus sampling |
| speed | 1.25 | 语速（后处理 atempo） |
| reference_id | 无 | 声音克隆 ID |
| normalize | false | 是否让引擎做文本归一化 |

`speed` 的默认值从 1.15 调整为 1.25（commit `14321ab`），因为实际使用中发现 1.15 的语速偏慢。

### 6.3 TtsConfigBar 的交互设计

前端的 TtsConfigBar 组件经历了两次重构：

```
4/10  初版：SideDrawer 形态
4/11  重构：centered modal，更符合"配置"的心智模型
4/13  精细化：加入每个参数的官方文档描述 + 发音修复建议
```

commit `8728eea` 加入的 tooltip 提示是一个小但有价值的设计——告诉用户 "如果发音不准，可以尝试降低 temperature 或调整 top_p"，把领域知识内嵌到 UI 中。

---

## 七、Episode 生命周期管理

### 7.1 状态机

```
pending → synth_done → verified → done
                ↘ failed ↗
```

- **pending**：刚创建或有 chunk 被修改待重试
- **synth_done**：所有 chunk 的 TTS 合成完成（P2 通过）
- **verified**：所有 chunk 的验证通过（P2v 通过）
- **done**：P6 拼接完成，可以导出
- **failed**：任何阶段出错

### 7.2 锁定机制

commit `a92c8e3`（4/13）加入了 episode 锁定：

```python
class Episode:
    locked: bool = False
```

锁定后：
- 不可修改（API 返回 403）
- 不会被自动清理
- 前端显示锁定图标

设计动机：自动存储清理（按时间删除最旧的 episode）可能误删重要数据。锁定机制让用户显式保护重要的 episode。

### 7.3 自动清理

commit `f37a183`（4/13）实现了基于容量的自动清理：

```python
async def cleanup_storage(session, max_episodes: int = 50):
    """Delete oldest unlocked episodes when count exceeds limit."""
    episodes = await repo.list_episodes(session)
    unlocked = [e for e in episodes if not e.locked]
    if len(episodes) > max_episodes:
        to_delete = sorted(unlocked, key=lambda e: e.created_at)[:len(episodes) - max_episodes]
        for episode in to_delete:
            await repo.delete_episode(session, episode.id)
```

Fly.io 的 volume 容量有限，需要自动清理。清理策略：按创建时间排序，删除最旧的未锁定 episode。

---

## 八、API Key 安全设计

### 8.1 三次迭代

**V1：localStorage（4/13 16:15）**

```typescript
// 前端存储，通过 HTTP header 传给后端
headers: { "X-Fish-Key": localStorage.getItem("fishKey") }
```

问题：Key 明文存储在浏览器中，F12 DevTools 可见。

**V2：加密 Cookie（4/14 16:00）**

```python
# 后端加密后写入 httpOnly cookie
response.set_cookie(
    key="fish_api_key",
    value=encrypt(api_key),
    httponly=True,
    secure=True,
    samesite="strict",
)
```

优点：前端无法读取，XSS 也拿不到 Key。

**V3：保存时验证（4/14 15:07）**

保存 Key 时自动调用 Fish/Groq 的验证端点，确认 Key 有效后才写入 Cookie。

```python
# 验证 Fish API Key
async def verify_fish_key(key: str) -> bool:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.fish.audio/v1/me",
            headers={"Authorization": f"Bearer {key}"},
        )
        return resp.status_code == 200
```

### 8.2 前端 UX

API Key 输入框的交互也经历了多次打磨：

```
4/14 15:04  防止弹窗意外关闭（outside click）
4/14 15:18  防止浏览器自动填充（autocomplete="off"）
4/14 15:31  去掉 placeholder 中的硬编码前缀
4/14 16:58  已配置时折叠输入框，展开才显示
```

这些都是在实际使用中发现的小问题，每个 fix 只改几行代码，但累积起来对用户体验影响很大。

---

## 九、回顾与反思

### 9.1 需求设计的关键决策

回看整个项目，影响最大的几个需求设计决策：

1. **逐句操作而非整篇操作** — 这决定了整个数据模型（episode → segment → chunk → take 的四层结构）
2. **text 和 tts_text 分离** — 这让"修改发音不影响字幕"成为可能
3. **导出面向 Remotion** — 这决定了 P6 的拼接粒度和字幕时间戳格式
4. **`normalize: false`** — 这让我们退出了"和 TTS 引擎抢文本预处理"的军备竞赛

### 9.2 做减法的价值

被砍掉的代码量统计：
- P4 Claude 校验：942 行
- Repair Loop：536 行
- 手写 adapter 层：~1000 行
- Legacy CLI 脚本：整个 scripts/ 目录
- 旧版文档/截图：docs/_archive/

**砍掉的代码比保留的代码更能说明一个项目的成熟度。** 每一次做减法，都是在澄清"这个产品到底要解决什么问题"。

### 9.3 16 天的节奏启示

```
Day 1:    全链路跑通（不管代码质量，先证明可行）
Day 4-5:  引擎升级 + 做减法（S2-Pro 变强了，中间层变薄）
Day 10:   Web MVP（3 小时验证交互设计）
Day 11-12: 后端重写（并行构建，一次到位）
Day 12-14: 质量体系 + 产品化（错误处理、导出、安全）
Day 15-16: 部署上线（Fly.io + CI/CD）
```

每个阶段都有明确的目标和"不做什么"的边界。最高效的两天（4/10 和 4/12）合计产出 68 个 commit，靠的不是加班，而是**前期设计文档清晰 + 并行构建策略 + 确定性优先减少返工**。
