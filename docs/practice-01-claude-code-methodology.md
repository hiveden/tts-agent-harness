# TTS Harness 工程实践（一）：Claude Code 编程方法论

> 项目：tts-agent-harness — 视频脚本转语音+字幕生产工具
> 时间跨度：2026-03-30 ~ 2026-04-14（16 天，239 commits）
> 技术栈：Next.js 16 + FastAPI + Prefect + PostgreSQL + MinIO

---

## 一、项目背景

TTS Agent Harness 是一个确定性视频脚本转语音加字幕的生产工具。它的核心价值是解决 **TTS 引擎对中英混合文本发音不稳定，需要人工反复试听、调整、重试** 的问题。

这个项目 100% 由我和 Claude Code 协作完成——从需求设计、架构选型、编码实现到部署上线。16 天 239 个 commit，经历了 CLI→Web、Node.js→Python、LLM 校验→确定性校验等多次架构转型。

本文记录在这个过程中，我对「如何用 Claude Code 高效编程」的实践总结。

---

## 二、人机协作的边界

### 2.1 核心原则：人做决策，Agent 做实现

在整个项目中，我逐渐形成了清晰的分工：

**人负责的事：**
- 架构选型（为什么选 FastAPI + Prefect 而不是 Temporal / Celery）
- Pipeline 设计（P1→P1c→P2→P2c→P2v→P5→P6→P6v 的拓扑）
- 做减法的决策（砍掉 P4 Claude 校验、砍掉 repair loop）
- 产品交互设计（逐句试听、即改即试的闭环）
- 并行策略设计（哪些模块可以同时开发、依赖关系怎么排）

**Agent 负责的事：**
- 代码实现（给定接口契约，写出完整的 task/route/component）
- 重构执行（shadcn/ui 迁移、Zustand store 抽取）
- 测试生成（E2E 测试、单元测试、集成测试）
- 文档编写（ADR、设计文档、README）
- Bug 修复（给定现象，定位并修复）

### 2.2 P4 Claude 校验的失败：从过拟合到删除

项目初期设计了 P4（Claude 语义校验），逻辑是：

```
TTS 合成音频 → WhisperX 转写回文字 → Claude 比对原文和转写 → 自动修复文本
```

#### 第一版的表面成绩

第一版做完后，demo 脚本上跑出了 87% auto-pass。但换新脚本后 P4 直接崩了——Claude 大量幻觉，修复循环越改越偏。

#### 根因：rules.md 是针对 demo 脚本的硬编码

Issue #1 记录了根因分析：

> 当前 pipeline 有两层：通用 harness 框架（P1-P6 流程、状态机、校验循环）+ 策略层（`.harness/rules.md` + P1 normalize 硬编码规则）。策略层是针对 demo 脚本的特定 pattern 手写的（英文品牌名加点号、OpenAI 拆空格、连字符改空格等），不具备泛化能力。

87% auto-pass 是 rules.md 和 demo 脚本匹配的结果，不是系统的泛化能力。rules.md 与新脚本内容不匹配时，变成误导 Claude 的噪音，Claude 拿着不匹配的规则做校验，在修复循环中产生幻觉。

#### P4 暴露的问题清单（GitHub Issues）

**Issue #1 — rules.md 过拟合：** 策略层（rules.md + P1 normalize 硬编码规则）针对 demo 脚本手写，换脚本后 pipeline 不可用。

**Issue #2 — 校验 agent 自身幻觉无独立验证：** P4 中 Claude 同时担任校验者和修复者，没有独立于 LLM 的硬校验层。Claude 说"没问题"时，human-in-the-loop 选择信任，导致错误被放行。

**Issue #3 — P1 normalize 职责混乱：** P1 混了"格式处理"和"内容优化"两个职责。升级 S2-Pro 后，内容优化规则大量误伤——`[break]` 被正则删掉、`AI→Ai`、`TTS→Tts`、中英交界加的 `.` 被 TTS 读出来。

**Issue #5 — 跨期记忆不可靠 + 修复循环振荡：** normalize-patches.json 记录具体替换对（如 `"整机重启" → "系统重新启动"`），但 TTS 和 WhisperX 都是非确定性的，导致补丁可能过度修复、产出坏数据、换模型后全部失效。修复循环还会振荡——Round 1 把 RAG 改成"拉格"，Round 2 发现违反规则又改回 RAG，Round 3 再改成"拉格"。

#### 问题的本质

中英混读发音不稳是 TTS 模型本身在 code-switching 上的能力缺陷，是上游问题。P4 试图在下游用 LLM 脚本绕过去，但模型该读错的还是读错——应用层的补丁解决不了模型能力层的缺陷。

面对这个问题，可选的方向：
1. **换模型** — 双语 TTS、带 language tag 的模型
2. **改变问题** — 按语言切片分别合成再拼接
3. **人机协同** — 人耳作为 ground truth，工具提供高效的试听-修改-重试循环

最终选了第三条，P4 被删除，pipeline 中不再包含 LLM 环节。

#### P4 的完整生命周期

| 日期 | 事件 |
|------|------|
| 3/30 | P4 创建：`scripts/p4-validate.js`（539行），Claude 校验 + 自动修复循环，最多 3 轮 |
| 3/30 | 增强：跨 episode 记忆（normalize-patches.json）+ text-diff（Levenshtein+同音字，auto-pass < 10%差异，节省 60-70% Claude 调用） |
| 3/30 | 增强：rules.md 业务规则注入 P4 prompt → demo 脚本 87% auto-pass |
| 3/30 | 第一个 bug：normalize-patches 把 Claude 的自然语言建议写入 patches，P1 执行 replaceAll 时用整句替换文本 |
| 4/2  | 换新脚本后 P4 大量幻觉，rules.md 过拟合暴露（Issue #1） |
| 4/2  | 移除 normalize-patches 管线 |
| 4/3  | 移除跨 episode 记忆，P4 只在单 episode 内工作 |
| 4/3  | 文档标注"P4 保留但生产流程中跳过" |
| 4/8  | **正式删除**：删除 p4-validate.js（590行）+ text-diff.js（120行），共 -942 行 |

后续方案是用确定性的 P2v（ASR 转写 + duration/silence 评分）替代，把"音频质量是否合格"的最终判断权交给人。

---

## 三、CLAUDE.md 的作用与演进

CLAUDE.md 是 Claude Code 加载上下文的入口文件。这个项目中它经历了 5 次显著变更，每次都反映了项目架构的重大转型。

### 3.1 五个版本的核心变化

**V1（4/2）— CLI 多 Agent 时代**

```
P1→P2→P3→text-diff→P4→P5→P6→V2
```

- 标题："多 Agent TTS 语音生产系统"
- 包含 P4 Claude 校验的完整描述
- `.harness/` 三层分离（config.json + rules.md + normalize-patches.json + tts-known-issues.json）
- 环境变量包含 `CLAUDE_API_URL` / `CLAUDE_MODEL`
- 状态机有 `validated / needs_human` 分支

**V2（4/2）— S2-Pro 升级**

只加了一行：`**当前只支持**：Fish Audio TTS（S2-Pro/S1）+ Claude API（Anthropic）+ WhisperX（本地）。`

**V3（4/3）— P4 实质淘汰**

- 分为"生产流程（跳过 P4）"和"完整流程（含 P4）"双轨描述
- 加了"单 chunk 重做（人工修复流程）"章节
- normalize-patches.json 和 tts-known-issues.json 标注已移除
- 状态机简化为 `transcribed → validated`

**V4（4/8）— P4 正式删除**

- 删除"完整流程（含 P4）"的架构描述
- 删除 text-diff.js 和 p4-validate.js 的条目
- 环境变量删除 `CLAUDE_API_URL` / `CLAUDE_MODEL`

**V5（4/13）— Web 架构重写**

- 标题改为"确定性视频脚本转语音加字幕生产工具"
- 架构改为 `Web UI → FastAPI → Prefect Tasks → PostgreSQL + MinIO`
- Pipeline 改为 `P1→P1c→P2→P2c→P2v→P5→P6→P6v`
- 运行方式改为 `make dev / make serve / make open`
- 测试改为 pytest + tsc --noEmit + playwright test
- 加了"导出产物（Remotion 消费）"章节
- 加了"归档"章节说明旧版 CLI 已归档

### 3.2 经验总结

1. **CLAUDE.md 要跟着架构走**：每次大的架构变更后，第一件事是更新 CLAUDE.md。否则新 session 的 Agent 会基于过时的上下文写代码。

2. **Pipeline 拓扑图是最有价值的信息**：Agent 最需要知道的是"系统由哪些环节组成、数据怎么流转"。一个清晰的 pipeline 描述比十页 API 文档更有用。

3. **写"不做什么"比"做什么"更重要**：V3 标注"P4 保留但跳过"、V5 写"归档"章节，都是为了防止 Agent 去碰已经废弃的代码。

4. **状态机的演进是很好的项目脉搏**：从 `validated/needs_human` → `transcribed/validated` → `pending/synth_done/verified/done`，每次状态机的变化都对应一次产品理解的深化。

---

## 四、Wave/Gate 并行开发

这是这个项目中最有价值的方法论创新——**在 ADR-002 中设计了一套多 Agent 并行构建的完整协议**。

### 4.1 为什么需要并行

Server 重写涉及 13 个模块（A0-A12），如果串行构建，每个 Agent 需要理解全部上下文。并行的好处是：
- 每个 Agent 只需关注自己的模块 + 冻结的契约
- 更短的上下文 = 更高的代码质量
- 总耗时显著缩短

### 4.2 设计：Wave 依赖图

```
W0 (契约冻结)
 └─ W1: A1-Infra (docker-compose + DB schema)
     └─ W2: A2-Domain (ORM + repos) ──┐
     └─ W2: A3-WhisperX (独立 HTTP 服务) ─┤
         └─ W3: A4-P1 (切分 task) ──────┤
         └─ W3: A5-P2 (合成 task) ──────┤
         └─ W3: A6-P5 (字幕 task) ──────┤
         └─ W3: A7-P6 (拼接 task) ──────┤
             └─ W4: A8-Flow (Prefect 编排)
             └─ W4: A9-API (FastAPI 路由)
                 └─ W5: A10-Frontend (前端适配)
                 └─ W5: A11-Integration (E2E 测试)
```

### 4.3 W0：契约冻结

并行的前提是 **在开始前冻结所有共享接口**。ADR-002 明确列出了 5 类需要冻结的契约：

1. **SQL DDL**：episodes/chunks/takes/stage_runs/events 表结构
2. **Pydantic schema**：domain.py 中的业务模型
3. **MinIO 路径规范**：`episodes/{eid}/chunks/{cid}/takes/{tid}.wav`
4. **OpenAPI 路由清单**：所有 endpoint 的 URL + method + request/response 类型
5. **Prefect Deployment 清单**：task 名称 + 参数签名

### 4.4 每个 Agent 的 spawn 模板

ADR-002 中为每个 Agent 定义了标准化的 spawn prompt：

```
## Agent {id}：{name}

### 输入契约
- 读取 {files}
- 依赖 {other agents} 的产物

### 输出产物
- 文件：{file list}
- 验收标准：{criteria}

### 禁止事项
- 不得修改 {files}
- 不得引入 {packages}
```

### 4.5 Gate 质量关卡

每个 Wave 结束时做 Gate Review：

**W1-W2 Gate Report 发现的问题：**
- 3 个 schema 不匹配被 gate review 发现并修复
- A3 docker build 被 Docker Desktop proxy 环境问题阻塞，标记为 deferred
- 端到端 smoke test 验证了 A2 ORM 与 A1 V001 schema 的兼容性

**W3 Gate Report 发现的问题：**
- 131 tests passed, zero regression
- **Incident 1: Worktree isolation collapse**（见下节）
- **Incident 2: Dockerfile dependency conflicts**（torch 版本冲突）

### 4.6 Worktree 事故与协议修订

W3 是并行度最高的一波（4 个 Agent 同时工作），暴露了 Claude Code 的一个 bug：

**事故经过：**
Agent tool 的 `isolation: "worktree"` 参数在并发 spawn 4 个 agent 时存在 race condition，4 个 worktree 全部创建失败，代码落到主 checkout。

**影响：**
A6（P5 字幕 task）和 A7（P6 拼接 task）的文件散落在主 checkout，需要手动恢复（commit `f816fed`，+2712行）。

**根因分析：**
"Despite parallel writes from 4 agents, no shared file was clobbered. domain.py was append-only by design"——因为 W0 契约冻结做得好，即使 worktree 隔离失败，也没出现文件冲突。

**修订协议（ADR-002 §5.1）：**
```
强制规则：
1. 主会话必须在 spawn 前用 git worktree add 串行预创建 worktree
2. 在 prompt 里告诉 agent cd <绝对路径>
3. 严禁使用 Agent tool 的 isolation: "worktree" 参数

预创建脚本：
for agent in A4 A5 A6 A7; do
  git worktree add -b "agent/${agent}-${TASK}" ".claude/worktrees/${agent}" HEAD
done
```

### 4.7 实际执行时间线

从 git log 可以看到并行的效果：

```
4/9 20:33  ADR-002 设计文档提交
4/9 20:45  A3-WhisperX 完成 ← W2 并行
4/9 20:55  A2-Domain 完成   ← W2 并行
4/9 21:00  A1-Infra 完成    ← W1
4/9 21:05  merge(W2) x2
4/9 21:09  W1-W2 Gate PASS
4/9 21:27  A4-P1 + A5-P2 完成 ← W3 并行
4/9 21:31  A6-P5 + A7-P6 恢复 ← W3 worktree 事故后恢复
4/9 22:09  W3 Gate PASS
4/10 08:45 A8-Flow + A9-API 完成 ← W4 并行
4/10 09:05 A10-Frontend + A11-Integration 完成 ← W5 并行
```

从 ADR 设计到 13 个模块全部集成：**约 12 小时**。

---

## 五、指令粒度与效率

### 5.1 什么样的指令 Agent 一次做对

**高成功率的指令特征：**
- 明确的输入/输出契约（"P5 接收 chunks 列表和 WAV 时长，输出 SRT 格式字幕"）
- 有参考实现（"参考原始 JS 版本的 p5-subtitles.js 重写为 Python"）
- 可验证的验收标准（"运行 pytest tests/tasks/test_p5_logic.py 全部通过"）

**低成功率的指令特征：**
- 模糊的目标（"优化一下前端性能"）
- 缺少上下文的修改（"改一下 P2 的逻辑"——哪个 P2？server/flows/tasks/p2_synth.py 还是旧的 scripts/p2-synth.js？）
- 跨多个文件的协调修改，且没有说明文件间的关系

### 5.2 设计文档先行

这个项目中，几乎每个大功能都先写设计文档再编码：

| 文档 | 对应功能 | 效果 |
|------|----------|------|
| ADR-001 | 技术选型 | 评估了 5 个备选方案，Agent 不会在实现时纠结技术选择 |
| ADR-002 | 并行构建 | 13 个 Agent 的分工和接口，一次就跑通了大部分 |
| 004-frontend-architecture | shadcn/ui 迁移 | 28 个文件 3797 行的重构，分 5 个 phase，~70 min |
| 015-error-handling | 错误处理 | 四种方案对比后选型，避免了 Agent 自作主张选方案 |
| 016-dev-mode-resilience | Dev Mode 容错 | 明确的状态转换图，Agent 写出的代码边界条件都覆盖了 |

**关键心得：花 10 分钟写设计文档，能省 2 小时的反复修改。**

### 5.3 用 commit message 当沟通协议

项目中的 commit message 遵循了高度结构化的格式：

```
feat(scope): 简短描述
fix(scope): 简短描述
merge(W{n}): {Agent} — 功能摘要
docs(gate): W{n} wave gate report — PASS/FAIL
recover(W{n}): 恢复描述 (原因)
```

这不只是给人看的，也是给下一个 session 的 Agent 看的——`git log --oneline` 就能快速理解项目历程。

---

## 六、确定性任务 vs LLM 任务的边界

经过 P4 的教训，我总结出一条清晰的界线。

### 6.1 Pipeline 中每个环节的确定性等级

| Task | 确定性 | 说明 |
|------|--------|------|
| P1 切分 | 确定性 | 按 JSON 结构机械切分 |
| P1c 校验 | 确定性 | 检查 chunks 数组非空、text 非空 |
| P2 TTS 合成 | 非确定性（API） | Fish Audio 每次合成结果不同 |
| P2c WAV 校验 | 确定性 | 检查采样率、声道数、时长范围 |
| P2v 转写验证 | 非确定性（模型） | ASR 转写 + duration/silence 评分 |
| P5 字幕 | 确定性 | 字符加权分配时间戳 |
| P6 拼接 | 确定性 | ffmpeg concat + padding |
| P6v 端到端验证 | 确定性 | 覆盖率/gap/overlap 检查 |

### 6.2 非确定性环节的处理策略

P2（TTS 合成）和 P2v（转写验证）是仅有的两个非确定性环节，处理策略是：

- **P2**：不做自动修复，合成失败就标记为 failed，人来决定是否重试
- **P2v**：给出量化评分（duration 偏差 + silence 比例），但不做自动判断"合格/不合格"——把判断权交给人
- **Repair Loop 被砍掉的原因**：曾经设计了 L0/L1 自动重试循环（4/12 创建，4/13 删除，存活仅 1 天），发现 TTS 的非确定性意味着"自动重试同样的文本"大概率得到同样的结果，不如让人改文本后手动重试

### 6.3 Agent 写代码 vs Agent 做运行时判断

```
✅ Claude Code 写 P2v 的评分代码（确定性的代码生成）
❌ Claude API 做 P4 的语义校验（非确定性的运行时判断）
```

前者是"生成确定性的工具"，后者是"用 LLM 做 pipeline 里的判官"。前者成功率 > 95%，后者成功率 < 60%。

---

## 七、回顾与反思

### 7.1 Claude Code 最擅长的场景

1. **给定契约的模块实现**：Wave 并行构建中，每个 Agent 拿着冻结的接口契约，独立实现一个模块，质量非常高
2. **重构执行**：shadcn/ui 迁移、Zustand store 抽取这种"目标明确、规则清晰"的重构
3. **测试生成**：37 个 server 测试文件 + E2E 测试，大部分由 Agent 生成
4. **Debug**：给定错误现象 + 堆栈，Agent 定位和修复 bug 的效率很高

### 7.2 Claude Code 需要人兜底的场景

1. **架构决策**：选 Prefect 还是 Temporal、用 Postgres 还是 SQLite——这些需要人综合考虑团队经验、运维成本、生态成熟度
2. **做减法**：砍掉 P4、砍掉 repair loop、砍掉 dark mode——Agent 倾向于"加"不倾向于"减"
3. **产品判断**：当 TTS 发音不准时，是自动修复还是让人手动调？这是产品决策，不是技术问题
4. **判断问题根因在哪一层**：中英混读问题的根因在 TTS 模型的 code-switching 能力，不在应用层——这类判断 Agent 做不了
5. **跨 session 的一致性**：每个新 session 的 Agent 都是"失忆"的，CLAUDE.md 是唯一的记忆载体

### 7.3 数据

- 16 天，239 commits
- 从 idea 到线上 demo：https://hiveden-tts.fly.dev
- 最终代码量：server ~15 个核心模块，web ~30 个组件
- 砍掉的代码：P4（942行）+ repair loop（536行）+ 旧版 CLI（整个 scripts/ 目录）
- 最大并行度：W3 的 4 个 Agent 同时工作

