# 前端架构设计方案

## 现状分析

### 规模

- 28 个源文件，3797 行
- page.tsx 339 行（状态 + 逻辑 + 渲染混在一起）
- 19 个组件，最大 246 行

### 当前技术栈

| 技术 | 版本 | 用途 |
|---|---|---|
| Next.js | 16.2 | 框架（仅用 CSR，未用 SSR/RSC） |
| React | 19.2 | UI |
| SWR | 2.4 | 服务端状态（GET 缓存 + 轮询） |
| openapi-fetch | 0.17 | 类型安全 HTTP client |
| Tailwind CSS | 4 | 样式 |
| TypeScript | 5 | 类型 |

### 当前问题

1. **逻辑与 UI 不分层**——page.tsx 有 43 行 async 业务逻辑，组件直接 `fetch`
2. **状态管理碎片化**——10+ 个 `useState` 在 page.tsx 里，无法复用
3. **组件不纯**——StageLogDrawer 直接拼 URL 调 API，TtsConfigBar import hooks
4. **无统一 API 层**——有的走 `api-client.ts` (openapi-fetch)，有的直接 `fetch`

## 技术栈决策

### 保留

| 技术 | 理由 |
|---|---|
| **Next.js 16** | 已在用，换框架收益不值迁移成本。当前只用 CSR，足够 |
| **React 19** | 跟 Next.js 绑定 |
| **Tailwind CSS 4** | 已在用，组件全部 Tailwind，没有理由换 |
| **openapi-fetch** | 类型安全 API client，刚搭完契约链路 |
| **TypeScript** | 必须 |

### 替换

| 现有 | 替换为 | 理由 |
|---|---|---|
| **SWR** | **SWR**（保留） | SWR 足够用。项目规模不需要 TanStack Query 的复杂特性（infinite query、mutation cache 等）。SWR 的 `mutate` 语义跟 SSE 配合良好 |
| 直接 fetch | **统一到 openapi-fetch** | 消灭 StageLogDrawer 等组件里的手写 fetch |

### 新增

| 技术 | 用途 | 理由 |
|---|---|---|
| **Zustand** | 客户端 UI 状态管理 | page.tsx 的 10 个 useState（selectedId / editing / playing / drawerOpen / edits / ...）需要集中管理。Zustand 轻量（~1KB），API 简单（一个 `create` 函数），不需要 Provider wrapper |

### 新增

| 技术 | 用途 | 理由 |
|---|---|---|
| **Zustand** | 客户端 UI 状态管理 | page.tsx 的 10 个 useState 需集中管理。~1KB，API 简单 |
| **shadcn/ui** | UI 原语（Dialog/Sheet/Tooltip/DropdownMenu/Table/Button/Badge/Input/Select） | 当前 24 处手写遮罩/抽屉/tooltip/菜单/点外关闭/Esc 关闭。shadcn 基于 Radix + Tailwind，零额外 CSS，源码拷贝到本地可定制 |

#### shadcn/ui 替代清单

| 手写组件 | 次数 | shadcn 替代 | 收益 |
|---|---|---|---|
| `fixed inset-0 bg-black/40` 遮罩 | 8 | `<Dialog>` / `<AlertDialog>` | 自带 focus trap + Esc + 点外关闭 |
| `fixed right-0 h-full` 侧边抽屉 | 1 | `<Sheet side="right">` | 自带动画 + 关闭逻辑 |
| HelpIcon hover tooltip | 1 | `<Tooltip>` | 自带延迟 + 定位 |
| `absolute top-full` 下拉菜单 | 7 | `<DropdownMenu>` | 自带键盘导航 + 点外关闭 |
| `mousedown` 点外关闭 | 4 | Radix 内置 | 删除手写 |
| `Escape` 关闭 | 4 | Radix 内置 | 删除手写 |

#### 不需要 UI 库的部分

| 场景 | 理由 |
|---|---|
| 表格（72 处原生标签） | `<table>` 够用，不需要 DataTable 组件 |
| 音频播放（8 处） | 无成熟库，抽成 `useAudioPlayer` hook 复用 |
| 日期/时长格式化（8 处） | 量小，保留 utils.ts，不引 dayjs |

### 不引入

| 技术 | 理由 |
|---|---|
| Redux / MobX | 过重，Zustand 够用 |
| TanStack Query | SWR 够用，换的收益不值迁移成本 |
| Jotai / Recoil | 原子化状态对这个项目过度设计 |
| Ant Design | 跟 Tailwind 风格冲突，内部工具不需要完整组件库 |
| dayjs / date-fns | 日期格式化场景少，utils.ts 够用 |

## 目标架构

### 分层

```
┌──────────────────────────────────────────────┐
│  Layer 1: Pages                               │
│  web/app/page.tsx                             │
│  职责: 组合组件 + 绑定 store → props           │
│  禁止: async 操作、fetch、业务逻辑              │
└──────────────────┬───────────────────────────┘
                   │ props + callbacks
┌──────────────────┴───────────────────────────┐
│  Layer 2: Components (纯 UI)                  │
│  web/components/*.tsx                         │
│  职责: 接收 props → 渲染 UI → 调 callback      │
│  禁止: import hooks/store、fetch、副作用        │
└──────────────────┬───────────────────────────┘
                   │ callback → store action
┌──────────────────┴───────────────────────────┐
│  Layer 3: Store (状态 + 业务逻辑)              │
│  web/lib/store.ts                             │
│  职责:                                         │
│    - 客户端 UI 状态 (Zustand)                  │
│    - 业务 action (async: 调 API → 更新状态)    │
│    - 派生状态 (computed)                       │
│  禁止: 直接渲染 UI                             │
└──────────────────┬───────────────────────────┘
                   │ 调用
┌──────────────────┴───────────────────────────┐
│  Layer 4: Data (服务端状态 + API)              │
│  web/lib/hooks.ts      — SWR hooks            │
│  web/lib/api-client.ts — openapi-fetch client │
│  web/lib/sse-client.ts — EventSource          │
│  职责: HTTP 请求 + 缓存 + SSE                  │
│  禁止: UI 状态、DOM 操作                       │
└──────────────────┬───────────────────────────┘
                   │
┌──────────────────┴───────────────────────────┐
│  Layer 5: Types (契约)                        │
│  web/lib/types.ts        — 手写 domain types  │
│  web/lib/gen/openapi.d.ts — 自动生成 API types │
│  职责: 类型定义，不含逻辑                      │
└──────────────────────────────────────────────┘
```

### 数据流

```
用户点击 "合成全部"
  → Component: EpisodeHeader 调 props.onRun("synthesize")
  → Page: onRun={store.runEpisode}
  → Store: runEpisode(mode) {
      set({ running: true })
      await api.runEpisode(selectedId, mode)  // Layer 4
      mutateEpisode()                          // SWR refresh
    }
  → API: POST /episodes/{id}/run
  → SSE: stage_event → store.onSSEEvent() → mutateEpisode()
  → SWR: refetch → store 拿到新 episode → Component 重渲染
```

### Store 设计 (Zustand)

```typescript
// web/lib/store.ts

interface HarnessState {
  // --- UI 状态 ---
  selectedId: string | null;
  editing: string | null;
  playingChunkId: string | null;
  edits: EditBatch;
  drawerOpen: { cid: string; stage: StageName } | null;
  helpOpen: boolean;
  configDialogOpen: boolean;

  // --- 派生 (从 SWR 数据计算) ---
  // 不存在 store 里，用 selector 从 SWR 读

  // --- Actions ---
  selectEpisode: (id: string) => void;
  startEditing: (cid: string) => void;
  cancelEditing: () => void;
  stageEdit: (cid: string, draft: ChunkEdit) => void;
  togglePlay: (cid: string) => void;
  openDrawer: (cid: string, stage: StageName) => void;
  closeDrawer: () => void;

  // --- Async Actions (调 API) ---
  runEpisode: (mode: string, chunkIds?: string[]) => Promise<void>;
  applyEdits: () => Promise<void>;
  retryChunk: (cid: string, stage: StageName, cascade: boolean) => Promise<void>;
  createEpisode: (id: string, file: File) => Promise<void>;
  deleteEpisode: (id: string) => Promise<void>;
  duplicateEpisode: (id: string, newId: string) => Promise<void>;
  archiveEpisode: (id: string) => Promise<void>;
  updateConfig: (config: Record<string, unknown>) => Promise<void>;
  finalizeTake: (cid: string, takeId: string) => Promise<void>;
  previewTake: (audioUri: string) => void;
}
```

### 重构后的 page.tsx（目标）

```typescript
// web/app/page.tsx — 重构后只做组合，无业务逻辑

"use client";

import { useHarnessStore } from "@/lib/store";
import { useEpisodes, useEpisode, useEpisodeLogs } from "@/lib/hooks";
// ... import components

export default function Page() {
  const store = useHarnessStore();
  const { data: episodes } = useEpisodes();
  const { data: episode } = useEpisode(store.selectedId);
  const { data: logLines } = useEpisodeLogs(store.selectedId);

  return (
    <div>
      <EpisodeSidebar
        episodes={episodes ?? []}
        selectedId={store.selectedId}
        onSelect={store.selectEpisode}
        onDelete={store.deleteEpisode}
        // ... 纯 props 传递，无 async 逻辑
      />
      <EpisodeHeader
        episode={episode}
        onRun={store.runEpisode}
        // ...
      />
      {/* 全部 props 来自 store 或 SWR，page.tsx 不写任何 handler */}
    </div>
  );
}
```

### 组件改造规则

**改造前（当前）：**
```typescript
// StageLogDrawer — 直接 fetch
const apiBase = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8100";
fetch(`${apiBase}/episodes/${episodeId}/chunks/${chunkId}/log?stage=${stage}`)
```

**改造后：**
```typescript
// StageLogDrawer — 纯 props
interface Props {
  log: string;           // 父级传入已 fetch 好的数据
  stageRun: StageRun;
  onRetry: (cascade: boolean) => void;  // callback，不 fetch
  onClose: () => void;
}
```

数据获取移到 store/hooks 层：
```typescript
// store.ts
openDrawer: (cid, stage) => {
  set({ drawerOpen: { cid, stage } });
  // 自动 fetch log — 用 SWR 或在 action 里
},
```

### 文件结构（重构后）

```
web/lib/
├── store.ts           ← 新增: Zustand store（状态 + actions）
├── hooks.ts           ← 精简: 只保留 SWR hooks，async actions 移到 store
├── api-client.ts      ← 不变: openapi-fetch client
├── sse-client.ts      ← 不变: EventSource
├── types.ts           ← 不变: domain types
├── utils.ts           ← 不变: 纯函数工具
└── gen/
    ├── openapi.json
    └── openapi.d.ts

web/components/        ← 全部改为纯 props 组件，不 import hooks/store
web/app/page.tsx       ← 组合层：connect store → components
```

## 重构步骤

### Phase 1: shadcn/ui 初始化 + 基础组件
1. `npx shadcn@latest init`（配置 Tailwind + path aliases）
2. 添加基础组件：`npx shadcn@latest add dialog sheet tooltip dropdown-menu button badge input select`
3. 验收：`components/ui/` 目录出现，tsc 通过

### Phase 2: Zustand store + page.tsx 瘦身
1. `pnpm add zustand`
2. 创建 `web/lib/store.ts`，把 page.tsx 的 10 个 useState + async handlers 移进去
3. page.tsx 改为从 store 读状态、调 action
4. 验收：page.tsx 从 339 行缩到 ~100 行

### Phase 3: 组件迁移到 shadcn
1. TtsConfigBar Dialog → shadcn `<Dialog>`
2. StageLogDrawer → shadcn `<Sheet>`
3. EpisodeSidebar 菜单 → shadcn `<DropdownMenu>`
4. HelpIcon → shadcn `<Tooltip>`
5. NewEpisodeDialog → shadcn `<Dialog>`
6. 删除所有手写的遮罩/点外关闭/Esc 关闭逻辑
7. 验收：`grep "fixed inset-0\|mousedown\|Escape.*close" web/components/` 返回 0

### Phase 4: 组件纯化（逻辑剥离）
1. StageLogDrawer 的 `fetch` → props 传入（log 数据由 store 提供）
2. TtsConfigBar 的 `updateConfig` → callback prop
3. ChunkRow 的 `getAudioUrl` → props 传入
4. 音频播放逻辑抽成 `useAudioPlayer` hook
5. 删掉所有组件里的 `fetch` 和 hooks import
6. 验收：`grep -r "fetch\|import.*hooks" web/components/` 返回 0

### Phase 5: 测试验证
1. Playwright e2e 重跑（2 个 spec 全通过）
2. tsc --noEmit 通过
3. 人工验证关键交互（Dialog/Drawer/Tooltip 的动画和关闭行为）

## 预估

| Phase | 改动量 | 时间 |
|---|---|---|
| Phase 1 | shadcn init + 9 个 UI 组件 | 10 min |
| Phase 2 | store.ts ~150 行 + page.tsx 重写 | 20 min |
| Phase 3 | 6 个组件迁移 shadcn | 20 min |
| Phase 4 | 5 个组件纯化 | 15 min |
| Phase 5 | Playwright e2e + tsc | 5 min |
| **总计** | | **~70 min** |
