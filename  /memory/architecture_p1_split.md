---
name: P1 收敛 + 脚本 Harness 拆分方向
description: P1 只做格式校验，内容优化拆到上游脚本 Harness，已和用户对齐
type: project
---

## 结论

P1 normalize 当前混了两个职责：
- **格式处理**（删导演标注、删停顿标记）— 保留在 TTS Harness
- **内容优化**（加断句 `.`、转缩写大小写、数字转中文）— 拆到上游脚本 Harness

## 待办

### 1. P1 收敛（当前项目）
P1 只保留：
- 应用跨期补丁（normalize-patches）
- 删导演标注 `[画面切换]`（保留 S2-Pro 控制标记 `[break]` 等）
- 删停顿标记 `（停顿2秒）`
- 输入格式校验（JSON schema、必填字段、text 非空）

删除：全大写转 titlecase、中英断句加 `.`、破折号转逗号、文件后缀转中文、英文连字符转空格、数字范围转"到"、百分比转中文

### 2. 脚本 Harness（新项目）
独立的 Harness，职责是保证脚本可读性：
- 操作对象：segment.text（脚本原文）
- 评估函数：确定性规则检查 + Claude 打分
- 约束系统：rules.md + TTS 引擎已知限制
- 修复：Claude 改脚本文本
- 输出：定稿脚本 JSON，作为 TTS Harness 的输入

### 3. TTS Harness P0（当前项目）
在 P1 之前加输入格式校验：
- JSON schema 合法
- segments 非空
- text 非空
- 不做内容判断

## Why
- P1 为 S1 设计的 normalize 规则在 S2-Pro 下大量误伤
- TTS 引擎行为非确定性，P1 猜测 TTS 需要什么是不可靠的
- 脚本内容质量应由上游保证，TTS Harness 只负责"给定文本→生成音频"
