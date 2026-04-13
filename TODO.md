# TODO

已知待办事项。按优先级排序。更新日期: 2026-04-13。

**一期目标：确定性的视频脚本转语音加字幕生产工具。**

输入脚本 JSON → 输出 per-shot WAV + 时间对齐字幕，全流程可通过 Web UI 操作和监控。

---

## 已完成 ✓

- Pipeline 全链路：P1 → P1c → P2 → P2c → P2v → P5 → P6 → P6v
- Web UI：Episode 管理、Chunk pipeline 可视化、音频播放、字幕预览
- 单 chunk 编辑/重试、Take 管理
- 导出功能（Remotion 格式：per-shot WAV + subtitles.json + durations.json）
- 错误处理、开发模式容错、P2 重试
- Dark mode + 主题切换
- 虚拟滚动（大 episode 性能）
- ChunkRow Zustand 直连 + React.memo（减少 re-render）
- 侧边栏可折叠 + 基础响应式兼容
- HelpDialog 动态渲染 stage 说明
- Stage 名称统一（check2/check3 → p2c/p2v）
- 旧版 CLI 脚本归档（`_archive/`）

---

## P0 · 生产可用性

### 多选 chunk 合成

后端已有：`run_episode_flow(mode="synthesize", chunk_ids=[...])`。
前端：ChunksTable checkbox + floating action bar。

### 发音质量预筛（确定性）

不需要 LLM，纯确定性逻辑。

- P1r：正则提取英文 token → 标记"有发音风险"
- P2r：P2v 后对比 original vs transcribed → 标记"发音偏差"
- UI 高亮偏差详情（如 "RAG → IG"）
- 不阻塞 pipeline

### 脚本预览/下载

已实现，待验证。

---

## P1 · 简化与稳定

### 简化 repair 循环

- 保留 char_ratio 粗筛 + needs_review 人工兜底
- 删除 L0/L1 自动循环
- `_synth_one_chunk` 简化为单次 P2→P2c→P2v

### Tech debt

- adapter 文件缺 TS 单元测试

---

## P2 · UI 打磨（低优先级）

- Sidebar 按状态分组
- 紧凑模式

---

## 二期方向（不在一期范围）

- LLM Agent 叠加：发音修改建议、风险判断、自然语言解释
- 架构设计见 `docs/017-llm-agent-design.md`
