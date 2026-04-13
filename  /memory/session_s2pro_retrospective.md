---
name: S2-Pro 升级尝试回顾
description: 2026-04-02 session 尝试适配 Fish TTS S2-Pro 的完整过程、发现的问题和结论
type: project
---

## 背景

尝试将 TTS 引擎从 Fish TTS S1 升级到 S2-Pro，并优化 P1 normalize 和 P4 校验流程。

## 做了什么

1. **P1 normalize 收敛**：从 13 条规则砍到 3 条（只保留删标注、删停顿、应用补丁），删除了中英断句、缩写拆分、数字转换等规则
2. **P2 config 外部化**：speed/model/concurrency 从 .harness/config.json 读取
3. **P4 prompt 优化**：改 severity 判定规则，让英文音译判 low 不触发修复；加修复历史传递避免振荡
4. **S2-Pro 升级**：同价更好，API 兼容只改 model 参数
5. **extractDiffPairs 修复**：加最小长度保护防止坏数据写入 patches
6. **CLAUDE.md**：新 session 入门指南
7. **发音测试流程**：pronunciation fixture + 真实 API 验证

## 发现的核心问题

### 1. TTS 非确定性导致跨期记忆不可靠
- normalize-patches.json 记录具体替换对（"整机重启"→"系统重新启动"），但同样的文本下次 TTS 可能读对了，补丁反而过度修复
- tts-known-issues.json 记录已知限制（"RAG→拉格"），换 TTS 模型/版本后全部失效
- 出现过 `pattern: "."` 的坏数据污染所有后续 episode
- **结论：具体经验不可复用，只有方法论可复用**

### 2. P4 修复能力有限
- Claude 会违反 rules.md 的约束（prompt 说"不要音译"但还是把 RAG→拉格、Mac→苹果电脑）
- prompt 太具体（列举 RAG/Mac 等例子）→ 换稿子要改 prompt；太通用 → Claude 判断不准
- Claude 会自作主张用 phoneme 标注，反而让 TTS 多读
- **结论：P4 是筛选器不是万能修复器。能修同义词替换，修不了 TTS 引擎固有限制**

### 3. S2-Pro 需要不同的流水线设计
- S2-Pro 支持 [break]、[breath]、phoneme 控制标记，脚本作者直接控制发音
- 但 P1 的 `[.*?]` 正则会删掉这些控制标记
- precheck 的 char ratio 会因控制标记字符数失衡
- P4 不理解控制标记，会把 [break] 缺失判为"漏读"
- **结论：当前流水线为 S1 设计，适配 S2-Pro 需要重新设计 P1/precheck/P4**

### 4. P1 normalize 的教训
- 规则越多误伤越多（中英断句的 `.` 制造了大量问题）
- 缩写拆分无法用正则做对（LM Studio 被拆成 L M Studio）
- 执行顺序敏感（.jsonl 被 dot→空格规则抢先匹配）
- **结论：P1 应该做最少的事，把不确定的交给 TTS 引擎或人工**

## 有价值但未提交的改动

以下想法经过验证是对的，但实现发散了没提交：

1. **CLAUDE.md** — 新 session 入门指南，包含架构速查、运行方式、发音规则迭代流程
2. **P4 修复历史传递** — 把前几轮的修复事实（改了什么、TTS 读出了什么、为什么失败）传给下一轮的 fix prompt，减少重复错误
3. **P4 severity 通用原则** — 不列具体例子，只给"英文读音变体→low，中文语义改变→high"
4. **P4 修复手段约束** — 只允许换同义词或调断句，禁止加 phoneme/控制标记
5. **P2 config 外部化** — speed/model 从 config.json 读，环境变量可覆盖
6. **S2-Pro 同价更好** — $15/M UTF-8 bytes，和 S1 一样，API 兼容

## 下一步建议

1. **如果继续用 S1**：当前线上版本可用，52 个测试全通过
2. **如果要升级 S2-Pro**：需要重新设计流水线，核心变化是——脚本作者承担更多控制（[break]/phoneme），P1 做更少的事，P4 的 scope 收窄到"中文语义校验"
3. **跨期记忆**：应该记方法论（"缩写加空格"）而不是具体替换对（"RAG→R A G"），但自动归类方法论的实现复杂度高，建议先人工写在 rules.md
