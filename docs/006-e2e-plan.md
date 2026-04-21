# 全流程 E2E 测试计划

> 初稿 v2: 2026-04-12
> 最近更新: 2026-04-21（阶段名更新；阻塞项已消除；spec 清单校正）

## 目标

用 Playwright 从浏览器出发，走通完整用户流程。全部真实服务，不 mock。

## 测试架构

```
┌─────────────────────────────────────────────────────────────────┐
│  Playwright (headless Chromium)                                 │
│                                                                 │
│  web/tests/                                                     │
│    full-pipeline.spec.ts    TC-01 ~ TC-07 happy path           │
│    ui-details.spec.ts       TC-10/11/14/15 UI 细节             │
│    record-v1.spec.ts        录屏 / 回归对比                    │
│                                                                 │
│  产出: video/ + trace/ + screenshots/ + server-logs/ + report   │
└──────────────────────┬──────────────────────────────────────────┘
                       │ HTTP (localhost:3010)
                       ▼
┌──────────────────────────────────┐
│  Next.js :3010                   │
│  (纯 UI，openapi-fetch client)   │
└──────────────────────┬───────────┘
                       │ HTTP + SSE (localhost:8100)
                       ▼
┌──────────────────────────────────────────────────────────────┐
│  FastAPI :8100  (dev mode, in-process flow execution)        │
│                                                              │
│  /episodes              CRUD                                 │
│  /episodes/{id}/run     P1 / synthesize / retry (async)     │
│  /episodes/{id}/stream  SSE real-time events                │
│  /audio/{key}           WAV streaming from MinIO            │
└───┬──────────┬──────────┬──────────┬─────────────────────────┘
    │          │          │          │
    │ SQL      │ S3       │ HTTP     │ HTTPS (via proxy)
    ▼          ▼          ▼          ▼
┌────────┐ ┌────────┐ ┌──────────┐ ┌──────────────┐
│Postgres│ │ MinIO  │ │whisperx- │ │ Fish Audio   │
│ :55432 │ │ :59000 │ │svc :7860 │ │ API (外网)   │
│        │ │WAV/SRT │ │WhisperX  │ │ S2-Pro       │
│episodes│ │transcr.│ │large-v3  │ │              │
│chunks  │ │logs    │ │CPU/GPU   │ │ via ClashX   │
│takes   │ │        │ │          │ │ SOCKS5       │
│stage_r │ │        │ │          │ │              │
│events  │ │        │ │          │ │              │
└────────┘ └────────┘ └──────────┘ └──────────────┘
  Docker     Docker     Docker       外部服务
```

### 数据流（一次完整 E2E）

```
Playwright 点击 "合成全部"
  → Next.js fetch POST /episodes/{id}/run {mode: "synthesize"}
    → FastAPI 启动 background task
      → P2: 逐 chunk 调 Fish API (HTTPS, via proxy)
        ← WAV bytes → 上传 MinIO → 写 takes → 写 stage_runs (p2: ok)
      → P2c: WAV 格式校验（RIFF/PCM/采样率/时长）
      → P2v: 从 MinIO 下载 WAV → POST whisperx-svc:7860/transcribe
              转写 + 2D scoring，低分标记 needs_review
      → P5: 字符级锚定 + 插值生成 cue → 上传 SRT
      → P6: ffmpeg concat → 上传 final WAV/SRT
      → P6v: 端到端校验（覆盖率/gap/overlap）
      → episode status → done
    ← SSE event push (stage_started / stage_finished)
  → Next.js SSE → SWR mutate → UI 刷新
Playwright 看到 stage pills 变绿 → 截图 → PASS
```

### 测试层次

```
┌─────────────────────────────────────────────┐
│ Layer 4: Playwright 浏览器 E2E              │
│   真浏览器 × 真全部服务 × 真外部 API        │
│   验证: 用户看到的就是对的                   │
├─────────────────────────────────────────────┤
│ Layer 3: pytest e2e (test_live_http.py)     │
│   真 uvicorn × 真 DB/MinIO × mock Prefect   │
│   验证: HTTP 层行为正确                      │
├─────────────────────────────────────────────┤
│ Layer 2: pytest API (test_routes.py)        │
│   ASGI transport × 真 DB × mock Prefect     │
│   验证: route handler 逻辑正确              │
├─────────────────────────────────────────────┤
│ Layer 1: pytest unit (test_*_logic.py)      │
│   纯函数 × 无 IO × 无外部依赖               │
│   验证: 算法正确                             │
└─────────────────────────────────────────────┘
```

## 技术选型

| 维度 | 工具 | 理由 |
|---|---|---|
| 浏览器 E2E | **Playwright** (`@playwright/test`) | headless Chrome，等待/截图/trace |
| 后端 API 测试 | pytest + httpx | 已有 |
| 前端组件测试 | vitest + testing-library | 已配置，用例待补 |

## 服务依赖

| 服务 | 端口 | 启动方式 | 状态 |
|---|---|---|---|
| Postgres | 55432 | `make dev` | ✅ |
| MinIO | 59000 | `make dev` | ✅ |
| Prefect Server | 54200 | `make dev`（dev mode 不依赖） | ✅ |
| whisperx-svc | 7860 | `make serve-whisperx` 或 Docker | ✅ |
| FastAPI | 8100 | `make serve-api` | ✅ |
| Next.js | 3010 | `make serve-web` | ✅ |
| Fish TTS API | 外网 | `.env.dev::FISH_TTS_KEY` | ✅ |

> 初稿阻塞项（whisperx Docker build / P3 连接地址 / Fish key 验证）均已解决。

## 执行方式

```bash
make dev                    # 起 postgres/minio/prefect
make serve-whisperx         # 起本地 WhisperX（或用 Groq 云端替代）
make serve                  # 起 fastapi + next.js
cd web && npx playwright test
```

## 当前 Spec 清单

| Spec | 覆盖 TC |
|------|--------|
| `full-pipeline.spec.ts` | TC-01 ~ TC-07 happy path |
| `ui-details.spec.ts` | TC-10 / TC-11 / TC-14 / TC-15 |
| `record-v1.spec.ts` | 录屏 / 回归对比 |

### 待新增

- `edit-retry.spec.ts` → TC-08/09/12/13（编辑 + 重试场景）
- `batch-and-continuous.spec.ts` → TC-16/17/18/19（批量 / 取消 / 连续播放）

## 典型旅程示例（happy path）

```typescript
test('完整用户旅程: 创建 → 切分 → 配置 → 合成 → 播放 → 日志 → 编辑 → 删除', async ({ page }) => {

  // ── Step 1: 创建 Episode ──
  await page.goto('/');
  await page.click('text=+ New');
  await page.fill('input[placeholder*="ID"]', 'e2e-test');
  await page.setInputFiles('input[type="file"]', 'tests/fixtures/test-script.json');
  await page.click('text=Create');
  await expect(page.locator('text=e2e-test')).toBeVisible();

  // ── Step 2: P1 切分 ──
  await page.click('text=e2e-test');
  await page.click('text=切分');
  await expect(page.locator('table tbody tr')).toHaveCount({ min: 1 }, { timeout: 15000 });

  // ── Step 3: TTS Config ──
  await page.click('text=TTS Config');
  await page.fill('input[type="number"] >> nth=0', '0.5');
  await page.click('text=Save Config');

  // ── Step 4: 合成全部（P2→P2c→P2v→P5→P6→P6v） ──
  await page.click('text=合成全部');
  await expect(page.locator('text=完成')).toBeVisible({ timeout: 180000 });
  await expect(page.locator('.bg-emerald-500')).toHaveCount({ min: 1 });

  // ── Step 5: 播放音频 ──
  await page.click('button:has-text("▶") >> nth=0');
  await expect(page.locator('audio')).toHaveAttribute('src', /\/audio\//);

  // ── Step 6: 查看 Stage 日志 ──
  await page.click('.rounded-full:has-text("P2") >> nth=0');
  await expect(page.locator('text=P2').first()).toBeVisible();
  await page.click('button:has-text("✕")');

  // ── Step 7: 编辑 + 重试 ──
  await page.click('button:has-text("✎") >> nth=0');
  await page.locator('textarea').fill('修改后的测试文本。');
  await page.click('text=Apply');
  await expect(page.locator('.animate-pulse')).toHaveCount(0, { timeout: 120000 });

  // ── Step 8: 删除 ──
  page.on('dialog', dialog => dialog.accept());
  await page.click('button:has-text("⋯") >> nth=0');
  await page.click('text=Delete');
  await expect(page.locator('text=e2e-test')).not.toBeVisible({ timeout: 5000 });
});
```

## Playwright 配置

`web/playwright.config.ts`：

```typescript
import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  timeout: 180000,       // 3 min per test（Fish API + WhisperX 慢）
  retries: 0,
  use: {
    baseURL: 'http://localhost:3010',
    screenshot: 'on',
    video: 'on',
    trace: 'on',
  },
  webServer: undefined,  // 服务手动起（make serve）
  projects: [
    { name: 'chromium', use: { browserName: 'chromium' } },
  ],
});
```

## 服务端日志收集

Playwright 的 `globalSetup` / `globalTeardown` 负责：

1. 测试开始前：打标记写入日志
2. 测试结束后：收集日志到 `test-results/server-logs/`

```typescript
// tests/global-setup.ts
import { execSync } from 'child_process';
export default function globalSetup() {
  execSync('echo "=== E2E START $(date) ===" >> /tmp/tts-harness-api.log');
  execSync('echo "=== E2E START $(date) ===" >> /tmp/tts-harness-web.log');
}
```

```typescript
// tests/global-teardown.ts
import { execSync } from 'child_process';
export default function globalTeardown() {
  const dest = 'test-results/server-logs';
  execSync(`mkdir -p ${dest}`);
  execSync(`cp /tmp/tts-harness-api.log ${dest}/fastapi.log 2>/dev/null || true`);
  execSync(`cp /tmp/tts-harness-web.log ${dest}/nextjs.log 2>/dev/null || true`);
  execSync(`docker logs whisperx-svc > ${dest}/whisperx.log 2>&1 || true`);
}
```

产物目录：

```
web/test-results/
├── server-logs/
│   ├── fastapi.log
│   ├── nextjs.log
│   └── whisperx.log
├── <test-name>/
│   ├── video.webm
│   ├── trace.zip
│   └── *.png
└── report/index.html
```

失败时同时看：浏览器 video / trace / fastapi.log / whisperx.log。

## Makefile 入口

```makefile
test-e2e-browser:
	cd web && npx playwright test --reporter=html

test-e2e-full:
	@curl -sf http://localhost:8100/healthz > /dev/null || (echo "API not running" && exit 1)
	@curl -sf http://localhost:3010         > /dev/null || (echo "Web not running" && exit 1)
	@curl -sf http://localhost:7860/healthz > /dev/null || (echo "WhisperX not running" && exit 1)
	cd web && npx playwright test
```

## Fixture

`web/tests/fixtures/test-script.json`:
```json
{
  "title": "E2E Test Episode",
  "segments": [
    {"id": 1, "type": "hook", "text": "你好世界。"},
    {"id": 2, "type": "content", "text": "这是测试内容。"}
  ]
}
```
