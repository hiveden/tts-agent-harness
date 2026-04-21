# TTS Agent Harness — 文档索引

> **2026-04-21 重构 + 技术债清理**：所有编号文档（001-022）已对照当前代码重写，状态差异（已落地 / 半实装 / 未实装 / 已废弃）直接写入各文档正文。
>
> 同日完成一轮技术债清理，本次 PR 的否决决策（Export DB 持久化 / storage 流式预留 / Phase 3 多 worker）已落入 018 文档正文。修复项目（Event FK+CASCADE / MinIO 清理 / unmount 守卫简化 / ApiKeyDialog 错误处理等）已分别反映到 003/004/015。新加的测试覆盖（edit_chunk 失效 2 xfail、cue offset、delete MinIO）写入 003 测试覆盖表。

## 运维

| # | 文档 | 内容 |
|---|---|---|
| 001 | [setup](001-setup.md) | 开发环境搭建、端口表、日常命令 |
| 002 | [config-design](002-config-design.md) | 统一配置管理（.env 切环境） |
| 019 | [deployment](019-deployment.md) | 线上部署方案（Fly.io + Tigris） |

## 产品

| # | 文档 | 内容 |
|---|---|---|
| 003 | [user-stories](003-user-stories.md) | 用户故事、功能点清单、链路审计 |
| 020 | [product](020-product.md) | 产品功能说明 |

## 架构

| # | 文档 | 内容 |
|---|---|---|
| ADR-001 | [adr/001-server-stack](adr/001-server-stack.md) | 服务端技术选型（Prefect + FastAPI + Postgres + MinIO） |
| 004 | [frontend-architecture](004-frontend-architecture.md) | 前端分层设计（Zustand + shadcn + openapi-fetch） |
| 015 | [error-handling-design](015-error-handling-design.md) | 错误处理设计 |
| 016 | [dev-mode-resilience](016-dev-mode-resilience.md) | 开发模式容错设计 |
| 018 | [architecture-concurrency](018-architecture-concurrency.md) | 并发架构优化（🔴 Phase 1 ✅ / Phase 2 🟡 / Phase 3 ❌） |
| 021 | [design-p5-subtitle-alignment](021-design-p5-subtitle-alignment.md) | P5 字幕对齐设计（字符级锚定 + 插值） |

## 测试

| # | 文档 | 内容 |
|---|---|---|
| 006 | [e2e-plan](006-e2e-plan.md) | 全流程 E2E 测试计划（Playwright） |
| 007 | [e2e-test-cases](007-e2e-test-cases.md) | 细粒度测试用例（TC-01 ~ TC-19） |

## 规划 / 路线

| # | 文档 | 内容 |
|---|---|---|
| 008 | [roadmap-auto-validation](008-roadmap-auto-validation.md) | 自动校验 pipeline（Phase 1 ✅ / Phase 2-4 已废弃） |
| 017 | [llm-agent-design](017-llm-agent-design.md) | LLM Agent 设计（🟡 Planned，二期） |

## 竞品 / 调研

| # | 文档 | 内容 |
|---|---|---|
| 022 | [competitor-analysis-pixelle-video](022-competitor-analysis-pixelle-video.md) | Pixelle-Video TTS 模块竞品分析 |

## 实践笔记

| # | 文档 | 内容 |
|---|---|---|
| practice-01 | [claude-code-methodology](practice-01-claude-code-methodology.md) | Claude Code 工作方法论 |
| practice-02 | [engineering-principles](practice-02-engineering-principles.md) | 工程原则 |
| practice-03 | [requirements-design](practice-03-requirements-design.md) | 需求与设计 |
| practice-04 | [subtitle-alignment-journey](practice-04-subtitle-alignment-journey.md) | 字幕对齐三次错做与一次做对 |

## 归档

| 目录 | 内容 |
|---|---|
| [worklogs/](worklogs/) | Agent A1-A11 工作日志 + W1-W3 wave gate 报告 |
| [_archive/](_archive/) | 已过时的设计文档（005, 009-014, ADR-002） |

## 编号约定

- **001-022**：正式文档，按创建时间顺序编号，编号保留不复用
- **005 / 009-014**：已归档至 `_archive/`
- **practice-NN**：工程实践笔记，独立序列
- **ADR-NNN**：架构决策记录，独立序列

## Pipeline 术语（统一参考）

当前完整阶段（`server/core/domain.py:30`）：

```
P1 → P1c → P2 → P2c → P2v → P5 → P6 → P6v
```

历史文档的 **P3**（WhisperX 独立转录）已合并到 **P2v**。旧版 L0/L1 **Repair 模块**已在 `5e391a6`（2026-04-13）删除，失败统一走 `needs_review` 人工兜底。
