# 执行方案 — 并行开发计划

## 依赖图

```
Phase 1: Stage 可见化
├─ W1: 后端类型 + 迁移 + 4 个 check task ──┐
├─ W2: 前端类型 + StagePipeline + EpisodeBar ──┤ 合并 → Phase 1 done
└─ W3: 测试 fixture 准备（所有 Phase 共用） ──┘

Phase 2: P2v 合并 (依赖 Phase 1)
├─ W4: 后端 P2v task + ASR 下沉 + 状态机 ──┐
└─ W5: 前端 status 更新 + P3 移除 ──────────┤ 合并 → Phase 2 done

Phase 3: 多维评估 + Retry 行 (依赖 Phase 2)
├─ W6: 后端 5 维评估 + Event 写入 ──────────┐
└─ W7: 前端 RetryRow + VerifyScoreBar ──────┤ 合并 → Phase 3 done

Phase 4: 自动修复循环 (依赖 Phase 2，可与 Phase 3 部分并行)
├─ W8: 后端 repair.py + 合成循环 ───────────┐
└─ W9: 前端 needs_review + ChunkEditor ─────┤ 合并 → Phase 4 done

Phase 5: L2 智能修复 (依赖 Phase 4)
└─ W10: 后端 L2 策略 + 前端修改历史 ────────→ Phase 5 done
```

## 可并行的窗口

```
时间轴 →

W1 后端类型+task  ████████
W2 前端类型+pill  ████████
W3 fixture 准备   ████████
                         ↓ Phase 1 merge
W4 后端P2v            ████████
W5 前端status            ████████
                                  ↓ Phase 2 merge
W6 后端评估                        ██████
W7 前端RetryRow                    ██████
W8 后端repair                      ████████
                                          ↓ Phase 3+4 merge
W9 前端needs_review                       ██████
W10 L2                                          ████
```

**Phase 1**：W1/W2/W3 完全并行（3 路）
**Phase 2**：W4/W5 并行（2 路）
**Phase 3+4**：W6/W7/W8 并行（3 路），W9 等 W7+W8 完成后启动

## 工作流详细分解

### W1: 后端类型 + 迁移 + Check Tasks

**分支**：`refactor/w1-backend-stages`

**任务清单**：

1. `domain.py` 扩展 StageName 和 ChunkStatus
2. Alembic 迁移：Chunk 表加 `normalized_history`
3. 新建 `server/flows/tasks/p1c_check.py`
   - 输入：chunks 列表
   - 检查：长度上下限、空文本、字符集、控制标记比例
   - 输出：per-chunk pass/fail + Event
4. 新建 `server/flows/tasks/p2c_check.py`
   - 输入：WAV 路径
   - 检查：文件存在、ffprobe 时长/采样率/声道
   - 输出：pass/fail + Event
5. 新建 `server/flows/tasks/p6v_check.py`
   - 输入：final 产物
   - 检查：覆盖率、gap、overlap
   - 输出：pass/fail + Event
6. `run_episode.py` 插入 P1c/P2c/P6v 调用点
7. 单元测试：`test_p1c_check.py` (6), `test_p2c_check.py` (5), `test_p6v_check.py` (3)

**产出**：后端支持 8 个 stage，check gate 有独立 StageRun 记录。

### W2: 前端类型 + Stage 组件

**分支**：`refactor/w2-frontend-stages`

**任务清单**：

1. `types.ts` 扩展 StageName (8 个) + STAGE_ORDER
2. `stage-info.ts` 新增 p1c/p2c/p2v/p6v 描述
3. `StagePipeline.tsx` 改造
   - STAGE_ORDER 8 个 pill
   - gate 用方形样式（border-radius: 2px）
   - 处理 stage 和 gate 之间用 `·` 紧凑连接
4. `EpisodeStageBar.tsx` 扩展 CHUNK_STAGES
5. `StageLogDrawer.tsx` 更新 STAGE_LABELS
6. `make tsc` 通过

**产出**：前端渲染 8 个 stage pill，样式区分处理 stage 和校验 gate。

**注意**：W2 可以用 mock 数据开发，不依赖 W1 的后端 API 变更。前端类型变更先行，后端 API 响应的 stage 值会逐步补齐。

### W3: 测试 Fixture 准备

**分支**：`refactor/w3-fixtures`

**任务清单**：

1. 生成 WAV fixture（good/silence/short/corrupt）
2. 编写 mock transcript fixture（含 word.score）
3. 编写 7 个 repair scenario.json（TC-01~TC-07）
4. 编写 MockTTSProvider 和 MockWhisperX 的 Python 实现
5. `test/repair/run-repair-tests.js` 框架搭建（读 scenario.json，注入 mock，执行循环，断言结果）

**产出**：所有后续 Phase 需要的测试 fixture 和 mock 基础设施。

### W4: 后端 P2v Task

**分支**：`refactor/w4-p2v`（基于 W1 合并后）

**任务清单**：

1. 新建 `server/flows/tasks/p2v_verify.py`
   - 调用 WhisperX（复用 p3_transcribe 的 HTTP 调用逻辑）
   - 输出 transcript.json（供 P5 消费，格式不变）
   - 输出 verify 结果（scores + diagnosis）
   - 写 verify_finished / verify_failed Event
2. 废弃 p3_transcribe 的 Prefect task 注册
3. `run_episode.py` 用 P2v 替代 P3+check3
4. `retry_chunk.py` from_stage 支持 "p2v"
5. ChunkStatus 转移：`synth_done → verified`（不再有 `transcribed`）
6. 测试：`test_p2v_verify.py` (8)

### W5: 前端 Status 更新

**分支**：`refactor/w5-frontend-status`（基于 W2 合并后）

**任务清单**：

1. `types.ts` ChunkStatus 加 `verified`、`needs_review`，移除 `transcribed`
2. `ChunkRow.tsx` statusIcon 支持新状态
3. 全局搜索替换 `"transcribed"` → `"verified"`
4. 移除 P3 相关：stage-info 中的 p3 描述、StagePipeline 中 p3 不再显示
5. `make tsc` + `make test-e2e-browser`

### W6: 后端多维评估

**分支**：`refactor/w6-scoring`（基于 W4 合并后）

**任务清单**：

1. `p2v_verify.py` 扩展评估逻辑
   - 时长/字数比（ffprobe）
   - 静音检测（ffmpeg silencedetect）
   - 音素距离（pypinyin）
   - 字符比（现有逻辑）
   - ASR 置信度（word.score 均值）
2. 加权评分 + 阈值判定
3. `requirements.txt` 加 pypinyin
4. 测试：`test_p2v_scoring.py` (5), `test_p2v_phonetic.py` (4), `test_p2v_silence.py` (3)

### W7: 前端 Retry 行

**分支**：`refactor/w7-retry-rows`（基于 W5 合并后）

**任务清单**：

1. 新建 `RetryRow.tsx`
   - 小型 pipeline (P2→P2c→P2v)
   - Take 信息（label/dur/play/use）
   - Verdict（FAIL score / PASS score + 诊断摘要）
2. `ChunkRow.tsx` 渲染 retry 行列表
3. 新建 `VerifyScoreBar.tsx`（评估分数条）
4. `StageLogDrawer.tsx` P2v drawer 展示评估分数 + 文本对比
5. TakeSelector 功能合并到 retry 行，废弃独立组件
6. Playwright 测试：`retry-rows.spec.ts` (4)

### W8: 后端 Repair 循环

**分支**：`refactor/w8-repair`（基于 W4 合并后，可与 W6 并行）

**任务清单**：

1. 新建 `server/flows/repair.py`
   - RepairConfig 数据结构
   - decide_repair() 策略函数
   - L0：原样重试
   - L1：调参规则表
2. `run_episode.py` 合成循环
   - per-chunk: P2→P2c→P2v，while fail + attempt < N → repair → retry
   - needs_review 状态设置
3. Event 写入 repair_decided / needs_review
4. 测试：`test_repair.py` (7), `test_synth_loop.py` (5)

### W9: 前端 needs_review + ChunkEditor

**分支**：`refactor/w9-needs-review`（基于 W7+W8 合并后）

**任务清单**：

1. `ChunkRow.tsx` needs_review 琥珀色高亮
2. `ChunkEditor.tsx` 紧凑重构
   - 行式布局（label 90px + content + hint）
   - 点击切换编辑态
   - 修改历史直接展示（>1 条时）
   - 当前 Take 参数只读行
   - needs_review 诊断 banner
3. Playwright 测试：`needs-review.spec.ts` (3)

### W10: L2 智能修复

**分支**：`refactor/w10-l2`（基于 W8 合并后）

**任务清单**：

1. `repair.py` L2 策略
   - 品牌名映射表（JSON 配置）
   - 文本改写逻辑
2. normalized_history 追加 repair-l2 记录
3. 前端 ChunkEditor 展示 L2 修改历史
4. 测试：`test_repair_l2.py` (3)

## 合并顺序

```
W1 + W2 + W3 → main (Phase 1)
    ↓
W4 + W5 → main (Phase 2)
    ↓
W6 + W7 + W8 → main (Phase 3+4)
    ↓
W9 → main (Phase 4 完成)
    ↓
W10 → main (Phase 5)
```

每次合并前：
```bash
make tsc && make test && make test-e2e && bash test/run-unit.sh
```

## 并行开发实践

### Worktree 模式

```bash
# 同时开发 W1 和 W2
git worktree add ../tts-w1 -b refactor/w1-backend-stages
git worktree add ../tts-w2 -b refactor/w2-frontend-stages
git worktree add ../tts-w3 -b refactor/w3-fixtures

# 各 worktree 独立开发，互不阻塞
```

### 接口契约先行

W1 和 W2 并行的前提是**先约定接口**：

1. StageName 的 8 个值（W1 和 W2 同时使用）
2. ChunkStatus 的新值（Phase 2 时用到）
3. StageRun 的字段不变（现有字段够用）
4. Event payload 的 scores/diagnosis 结构（Phase 3 时用到）

这些接口在 012 和 009 设计文档中已定义，开发时以文档为准。

### 风险控制

| 风险 | 应对 |
|---|---|
| W1 和 W2 的 StageName 定义不一致 | 接口契约在 types.ts 中先统一，W1/W2 各自引用 |
| W4 P2v 的 ASR 调用与 P3 逻辑重复 | P3 的 HTTP 调用逻辑提取为共享函数，P2v 调用 |
| W6 pypinyin 在 CI 环境安装失败 | requirements.txt 提前加入，CI 验证 |
| W7 RetryRow 和 TakeSelector 的交互冲突 | W7 中一步完成：新建 RetryRow + 废弃 TakeSelector |
| W8 合成循环和现有 run_episode 冲突大 | W8 基于 W4 的 P2v 改动，不基于 main |
