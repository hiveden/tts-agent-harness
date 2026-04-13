# 回归测试方案

## 现有测试体系

| 层 | 数量 | 运行方式 | 耗时 |
|---|---|---|---|
| v1 离线单元测试 | 42 | `bash test/run-unit.sh` | ~2s |
| v2 后端单元 | 75 | `make test` | ~10s |
| v2 后端集成 | 37 | `make test-e2e` | ~30s |
| v2 Playwright UI | 2 | `make test-e2e-browser` | ~5min |
| TypeScript 类型检查 | - | `make tsc` | ~5s |

## 受影响的测试

按 012-refactor-plan 的 5 个 Phase，列出每个 Phase 会破坏的现有测试和需要新增的测试。

### Phase 1: Stage 可见化

**破坏的现有测试**：

| 文件 | 原因 | 修复方式 |
|---|---|---|
| `server/tests/tasks/test_p3_task.py` (7) | P3 不再注册为独立 Prefect task | 测试迁移到 test_p2v_verify.py |
| `server/tests/e2e/test_full_pipeline.py` (2) | pipeline 阶段数和顺序变了 | 更新 stage 列表断言 |
| `server/tests/e2e/test_chunk_operations.py` (5) | retry from_stage 不再支持 "p3" | 更新 from_stage 参数为 "p2v" |
| `server/tests/api/test_routes.py` | stage-context 端点返回新 stage | 补充 p1c/p2c/p2v/p6v 的路由测试 |
| `web/e2e/ui-details.spec.ts` | stage pills 数量从 5 变 8 | 更新 pill 计数断言 |
| `test/run-unit.sh` precheck 用例 (7) | precheck.js 的 --stage 参数变更 | 迁移到新的 p2c/p6v 脚本测试 |

**新增测试**：

| 文件 | 用例 | 验证什么 |
|---|---|---|
| `server/tests/tasks/test_p1c_check.py` | 6 | chunk 长度上下限、空文本、字符集、控制标记、可逆性 |
| `server/tests/tasks/test_p2c_check.py` | 5 | WAV 存在/时长/采样率/声道/语速 |
| `server/tests/tasks/test_p6v_check.py` | 3 | 覆盖率/gap/overlap |

### Phase 2: P2v 合并

**破坏的现有测试**：

| 文件 | 原因 | 修复方式 |
|---|---|---|
| `server/tests/e2e/test_full_pipeline.py` | ChunkStatus "transcribed" 不存在了 | 改为断言 "verified" |
| `server/tests/flows/test_run_episode.py` (3) | flow 内部阶段顺序变了 | 更新 mock 和断言 |
| `server/tests/flows/test_retry_chunk.py` (2) | retry from p3 不存在了 | 改为 from p2v |
| `web/lib/types.ts` 引用 "transcribed" 的所有前端代码 | 类型不存在 | 全局替换为 "verified" |

**新增测试**：

| 文件 | 用例 | 验证什么 |
|---|---|---|
| `server/tests/tasks/test_p2v_verify.py` | 8 | ASR 调用、评估分数计算、pass/fail 判定、transcript 产出、Event 写入 |
| `server/tests/tasks/test_p2v_scoring.py` | 5 | 5 维评估各项的边界值（阈值、权重） |

### Phase 3: 多维评估 + Retry 行

**破坏的现有测试**：

| 文件 | 原因 | 修复方式 |
|---|---|---|
| `web/e2e/full-pipeline.spec.ts` | UI 结构变了（retry 行、take 位置） | 更新 selector 和断言 |

**新增测试**：

| 文件 | 用例 | 验证什么 |
|---|---|---|
| `server/tests/tasks/test_p2v_phonetic.py` | 4 | 音素距离计算（pypinyin）、中英混合、谐音判定 |
| `server/tests/tasks/test_p2v_silence.py` | 3 | ffmpeg silencedetect 解析、异常静音检测 |
| `web/e2e/retry-rows.spec.ts` | 4 | retry 行渲染、take 试听/Use、attempt 角标、verdict 显示 |

### Phase 4: 自动修复循环

**破坏的现有测试**：

| 文件 | 原因 | 修复方式 |
|---|---|---|
| `server/tests/flows/test_run_episode.py` | 合成循环逻辑变了 | 重写为测试循环行为 |

**新增测试**：

| 文件 | 用例 | 验证什么 |
|---|---|---|
| `server/tests/flows/test_repair.py` | 7 | L0/L1 策略决策、attempt 计数、needs_review 触发、配置边界 |
| `server/tests/flows/test_synth_loop.py` | 5 | 合成循环完整流程（mock TTS + mock ASR） |
| `test/repair/run-repair-tests.js` | 7 | TC-01~TC-07（见 010-repair-test-design.md），fixture 驱动 |
| `web/e2e/needs-review.spec.ts` | 3 | needs_review 状态展示、编辑器展开、重置重试 |

### Phase 5: L2 智能修复

**新增测试**：

| 文件 | 用例 | 验证什么 |
|---|---|---|
| `server/tests/flows/test_repair_l2.py` | 3 | 品牌名映射表查找、文本改写、normalized_history 追加 |

## 回归测试执行策略

### 每个 Phase 提交前必跑

```bash
# 1. TypeScript 类型检查（捕获类型不兼容）
make tsc

# 2. 后端单元测试
make test

# 3. 后端集成测试
make test-e2e

# 4. v1 离线单元测试（确认 scripts/ 不受影响）
bash test/run-unit.sh
```

### Phase 1/2 额外跑

```bash
# Playwright UI（stage pill 数量变了）
make test-e2e-browser
```

### Phase 3/4 额外跑

```bash
# repair fixture 测试
node test/repair/run-repair-tests.js

# Playwright UI（retry 行 + needs_review）
make test-e2e-browser
```

## 不变的测试

以下测试在所有 Phase 中都不应受影响，作为回归基线：

| 测试 | 验证什么 | 如果挂了说明什么 |
|---|---|---|
| `test_p1_logic.py` (18) | P1 切分算法 | 误改了 P1 |
| `test_p5_logic.py` | P5 字幕分配算法 | 误改了 P5 |
| `test_p6_logic.py` (22) | P6 拼接偏移算法 | 误改了 P6 |
| `test_fish_client.py` (14) | Fish API 客户端 | 误改了 TTS 调用 |
| `test_storage.py` (6) | MinIO 路径 | 误改了存储结构 |
| `test_episode_crud.py` (7) | Episode CRUD | 误改了 API |
| `run-unit.sh` P1/P5/P6 用例 (24) | v1 脚本逻辑 | scripts/ 被误修改 |

如果上述任何测试在重构过程中挂了，说明变更超出了预期范围，需要停下来检查。

## 新增 Fixture 清单

| 目录 | 内容 | 用途 |
|---|---|---|
| `test/fixtures/repair/tc-01-level0-pass/` | scenario.json + mock wav + mock transcript | TC-01 L0 通过 |
| `test/fixtures/repair/tc-02-level1-pass/` | 同上 | TC-02 L1 调参通过 |
| `test/fixtures/repair/tc-03-level2-pass/` | 同上 | TC-03 L2 改文本通过 |
| `test/fixtures/repair/tc-04-needs-review/` | 同上 | TC-04 全失败 |
| `test/fixtures/repair/tc-05-p2c-block/` | corrupt.wav + good.wav | TC-05 P2c 拦截 |
| `test/fixtures/repair/tc-06-false-positive/` | 音素匹配但文字不同 | TC-06 避免假阳性 |
| `test/fixtures/repair/tc-07-word-missing/` | 吞字音频 + 高置信度 transcript | TC-07 吞字检测 |
| `server/tests/fixtures/p2v/` | mock WhisperX 响应（含 score 字段） | 后端 P2v 单元测试 |

WAV fixture 生成方式：
```bash
# good.wav — 正常 440Hz 正弦波
ffmpeg -y -f lavfi -i "sine=frequency=440:duration=3" -ar 44100 -ac 1 good.wav

# silence.wav — 静音（模拟吞字）
ffmpeg -y -f lavfi -i anullsrc=r=44100:cl=mono -t 3.0 silence.wav

# short.wav — 极短（模拟截断）
ffmpeg -y -f lavfi -i "sine=frequency=440:duration=0.3" -ar 44100 -ac 1 short.wav

# corrupt.wav — 错误采样率
ffmpeg -y -f lavfi -i "sine=frequency=440:duration=3" -ar 22050 -ac 1 corrupt.wav
```

## E2E 全流程测试

现有 E2E 只有 happy path（全通过）和 UI 细节。缺少 retry/repair/needs_review 的全流程覆盖。

### 后端 E2E（Pytest，mock TTS + mock ASR）

新增 `server/tests/e2e/test_pipeline_v2.py`：

| 用例 | 场景 | 验证路径 |
|---|---|---|
| **E2E-01: Happy Path** | 所有 chunk 一次通过 | P1→P1c→P2→P2c→P2v(pass)→P5→P6→P6v，episode status=done |
| **E2E-02: L0 自动修复** | mock TTS 第一次返回坏音频，第二次返回好音频 | P2v fail→repair L0→P2(retry)→P2c→P2v(pass)→P5，chunk status=verified，StageRun attempt=2 |
| **E2E-03: L1 调参修复** | mock TTS 在 temp=0.7 时总失败，temp=0.3 时通过 | L0 用尽→repair L1→P2(temp=0.3)→P2v(pass)，Take.params.temperature=0.3 |
| **E2E-04: needs_review** | mock TTS 始终返回坏音频 | 5 次 attempt 全 fail→chunk status=needs_review，episode status≠done，其他 chunk 不受影响 |
| **E2E-05: 人工重置后恢复** | needs_review chunk 修改 text_normalized 后重试成功 | edit→reset→P2→P2c→P2v(pass)→P5，chunk status=verified，normalized_history 有 human 记录 |
| **E2E-06: P2c 拦截** | mock TTS 返回 22050Hz WAV | P2c fail→直接 retry P2（不调 ASR），WhisperX mock 调用次数=0 |
| **E2E-07: 混合状态** | 20 chunks，17 pass + 2 retry 后 pass + 1 needs_review | 最终 19 verified + 1 needs_review，P5 处理 19 个，P6 拼接 19 个 |
| **E2E-08: Take 手动选择** | P2v fail 的 take，用户手动 Use | finalize-take→跳过 P2v→强制 verified→P5 |
| **E2E-09: 事件序列** | 跑完一个带 retry 的 chunk | Event 表包含 verify_started→verify_failed→repair_decided→verify_started→verify_finished，顺序正确 |

Mock 策略：
- **MockTTSProvider**：按 (chunk_id, attempt) 返回预设 WAV（好/坏/corrupt）
- **MockWhisperX**：按 (chunk_id, attempt) 返回预设 transcript（含 score）
- 不需要真实 Fish API 和 WhisperX

运行方式：
```bash
# 纳入现有 make test-e2e
make test-e2e
```

### 前端 E2E（Playwright，真实后端 + mock TTS/ASR）

新增 `web/e2e/pipeline-v2.spec.ts`：

| 用例 | 场景 | 验证什么 |
|---|---|---|
| **UI-E2E-01: 8 stage pipeline** | 创建 episode，跑完全流程 | episode bar 显示 8 个 pill，全绿 |
| **UI-E2E-02: retry 行渲染** | chunk 经历 3 次 attempt | 主流程 pill 下方出现 3 行 retry 行，每行有 pipeline + take + verdict |
| **UI-E2E-03: needs_review 交互** | chunk 进入 needs_review | 琥珀色高亮，编辑器自动展开，诊断 banner 可见，修改文本后点重试产出新 take |
| **UI-E2E-04: take 试听和 Use** | 点击失败 take 的 Use 按钮 | chunk 状态变 verified，主流程继续 |
| **UI-E2E-05: P2v drawer** | 点击 P2v pill | drawer 打开，显示评估分数条 + 文本对比 |
| **UI-E2E-06: 修改历史** | L2 改过文本的 chunk 打开编辑器 | 修改历史直接展示，包含 p1 和 repair-l2 记录 |

前置条件：后端启动 mock TTS/ASR 模式（通过环境变量切换 provider）。

运行方式：
```bash
# 纳入现有命令
make test-e2e-browser
```

### 全流程冒烟测试（真实 API，手动触发）

不纳入 CI，人工在关键版本前执行：

```bash
# 真实 Fish TTS + 真实 WhisperX，端到端验证
make test-live
```

验证点：
- 真实 TTS 合成 → 真实 ASR 转写 → P2v 评估分数合理
- 中英混读文本（Mac/Ollama/RAG）的评估结果符合预期
- 自动修复是否真的能改善发音（L0/L1）

## 测试数量变化预估

| 层 | 现有 | 移除 | 新增 | 最终 |
|---|---|---|---|---|
| v1 离线单元 | 42 | 7 (precheck) | 0 | 35 |
| v2 后端单元 | 75 | 7 (test_p3_task) | 37 | 105 |
| v2 后端集成 | 37 | 0 | 14 (含 E2E-01~09) | 51 |
| Repair fixture | 0 | 0 | 7 | 7 |
| Playwright UI | 2 | 0 | 8 (含 UI-E2E-01~06 + retry/needs-review) | 10 |
| TypeScript | - | - | - | - |
| **总计** | **156** | **14** | **66** | **208** |
