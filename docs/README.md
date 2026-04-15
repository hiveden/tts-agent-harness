# TTS Agent Harness — 文档索引

## 运维

| # | 文档 | 内容 |
|---|---|---|
| 001 | [setup](001-setup.md) | 开发环境搭建、端口表、日常命令 |
| 002 | [config-design](002-config-design.md) | 统一配置管理（.env 切环境） |
| 019 | [deployment](019-deployment.md) | 线上部署方案（Fly.io + Cloudflare Pages） |

## 产品

| # | 文档 | 内容 |
|---|---|---|
| 003 | [user-stories](003-user-stories.md) | 用户故事、功能点清单、代码链路审计 |
| — | [product](product.md) | 产品功能说明 |

## 架构

| # | 文档 | 内容 |
|---|---|---|
| ADR-001 | [adr/001-server-stack](adr/001-server-stack.md) | 服务端技术选型（Prefect + FastAPI + Postgres + MinIO） |
| 004 | [frontend-architecture](004-frontend-architecture.md) | 前端分层设计（Zustand + shadcn + openapi-fetch） |
| 015 | [error-handling-design](015-error-handling-design.md) | 错误处理设计 |
| 016 | [dev-mode-resilience](016-dev-mode-resilience.md) | 开发模式容错设计 |
| 018 | [architecture-concurrency](018-architecture-concurrency.md) | 并发架构优化（阻塞修复 + 异步导出 + 多 Worker 规划） |

## 测试

| # | 文档 | 内容 |
|---|---|---|
| 006 | [e2e-plan](006-e2e-plan.md) | 全流程 E2E 测试计划（Playwright） |
| 007 | [e2e-test-cases](007-e2e-test-cases.md) | 细粒度测试用例（15 个 TC） |

## 未来方向

| # | 文档 | 内容 |
|---|---|---|
| 008 | [roadmap-auto-validation](008-roadmap-auto-validation.md) | 自动校验与自动修复 pipeline |
| 017 | [llm-agent-design](017-llm-agent-design.md) | LLM Agent 设计（二期） |

## 实践笔记

| # | 文档 | 内容 |
|---|---|---|
| practice-01 | [claude-code-methodology](practice-01-claude-code-methodology.md) | Claude Code 工作方法论 |
| practice-02 | [engineering-principles](practice-02-engineering-principles.md) | 工程原则 |
| practice-03 | [requirements-design](practice-03-requirements-design.md) | 需求与设计 |

## 归档

| 目录 | 内容 |
|---|---|
| [worklogs/](worklogs/) | Agent A1-A11 的工作日志 + W1-W3 wave gate 报告 |
| [_archive/](_archive/) | 已完成/过时的设计文档（005, 009-014, ADR-002） |
