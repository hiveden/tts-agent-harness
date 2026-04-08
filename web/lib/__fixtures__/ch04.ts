/**
 * Mock fixture: ch04 episode
 *
 * 数据来自 .work/ch04/chunks.json 真实数据,转换为 domain 类型。
 * 给 FRONTEND agent 在 fixture mode 下用,无需后端就能跑通完整 UI。
 *
 * FRONTEND 验收标准:
 * - 这个 fixture 能驱动 sidebar、chunks 表、播放、编辑、Apply、TakeSelector 全套交互
 */

import type { Episode, EpisodeSummary } from "../types";

const NOW = "2026-04-08T08:54:00.000Z";

// ============================================================
// ch04 — 主 fixture(8 chunks 真实数据)
// ============================================================

export const ch04Episode: Episode = {
  id: "ch04",
  status: "done",
  currentStage: null,
  totalDurationS: 89.469,
  createdAt: "2026-04-08T02:09:34.049Z",
  updatedAt: NOW,
  metadata: {},
  chunks: [
    {
      id: "shot01_chunk01",
      shotId: "shot01",
      index: 1,
      text: "接下来这一段,是这一期的核心。[break]我要把它讲细,因为它细节里有钩子。[long break]Claude 教训练集、验证集、测试集为什么要切三份。",
      textNormalized:
        "接下来这一段,是这一期的核心。[break]我要把它讲细,因为它细节里有钩子。[long break]Claude 教训练集、验证集、测试集为什么要切三份。",
      subtitleText: null,
      status: "transcribed",
      charCount: 78,
      takes: [
        {
          id: "take_1",
          file: "shot01_chunk01.wav",
          durationS: 8.569,
          createdAt: NOW,
        },
      ],
      selectedTakeId: "take_1",
      metadata: {},
    },
    {
      id: "shot01_chunk02",
      shotId: "shot01",
      index: 2,
      text: "它没直接给定义,[break]先用了一个决策树调参的场景。[long break]假设你训练一个决策树预测房价。",
      textNormalized:
        "它没直接给定义,[break]先用了一个决策树调参的场景。[long break]假设你训练一个决策树预测房价。",
      subtitleText: null,
      status: "transcribed",
      charCount: 56,
      takes: [
        {
          id: "take_1",
          file: "shot01_chunk02.wav",
          durationS: 6.121,
          createdAt: NOW,
        },
      ],
      selectedTakeId: "take_1",
      metadata: {},
    },
    {
      id: "shot01_chunk03",
      shotId: "shot01",
      index: 3,
      text: "[break]第一次跑完,[breath]训练集准确率百分之九十八,测试集百分之七十二——[break]你看出过拟合了。[long break]你调一个参数,[breath]把 max depth 从默认改成 5。[break]再跑,训练百分之九十五,测试百分之八十五。[breath]好多了。",
      textNormalized:
        "[break]第一次跑完,[breath]训练集准确率百分之九十八,测试集百分之七十二——[break]你看出过拟合了。[long break]你调一个参数,[breath]把 max depth 从默认改成 5。[break]再跑,训练百分之九十五,测试百分之八十五。[breath]好多了。",
      // 演示 subtitle_text:把数字和缩写写成更适合字幕显示的形式
      subtitleText:
        "第一次跑完,训练集准确率 98%,测试集 72%——你看出过拟合了。你调一个参数,把 max_depth 从默认改成 5。再跑,训练 95%,测试 85%。好多了。",
      status: "transcribed",
      charCount: 147,
      takes: [
        {
          id: "take_1",
          file: "shot01_chunk03.wav",
          durationS: 14.225,
          createdAt: NOW,
        },
      ],
      selectedTakeId: "take_1",
      metadata: {},
    },
    {
      id: "shot01_chunk04",
      shotId: "shot01",
      index: 4,
      text: "[long break]再调,max depth 改成 8,[break]训练百分之九十六,测试百分之八十八。[breath]更好。[long break]再调,max depth 改成 10,[break]训练百分之九十七,测试百分之八十七。[breath]嗯?退步了,回去 8。[long break]最终定下来 max depth 等于 8,[break]准确率百分之八十八,[break]发布上线。",
      textNormalized:
        "[long break]再调,max depth 改成 8,[break]训练百分之九十六,测试百分之八十八。[breath]更好。[long break]再调,max depth 改成 10,[break]训练百分之九十七,测试百分之八十七。[breath]嗯?退步了,回去 8。[long break]最终定下来 max depth 等于 8,[break]准确率百分之八十八,[break]发布上线。",
      subtitleText:
        "再调,max_depth 改成 8,训练 96%,测试 88%。更好。再调,max_depth 改成 10,训练 97%,测试 87%。嗯?退步了,回去 8。最终定下来 max_depth = 8,准确率 88%,发布上线。",
      status: "transcribed",
      charCount: 203,
      // 演示 multi-take:这个 chunk 有 3 个 take,选中的是 take_2
      takes: [
        {
          id: "take_1",
          file: "shot01_chunk04.take_1.wav",
          durationS: 17.5,
          createdAt: "2026-04-08T08:30:00.000Z",
        },
        {
          id: "take_2",
          file: "shot01_chunk04.wav",
          durationS: 17.968,
          createdAt: "2026-04-08T08:32:00.000Z",
          params: { temperature: 0.4 },
        },
        {
          id: "take_3",
          file: "shot01_chunk04.take_3.wav",
          durationS: 18.2,
          createdAt: "2026-04-08T08:35:00.000Z",
          params: { temperature: 0.5 },
        },
      ],
      selectedTakeId: "take_2",
      metadata: {},
    },
    {
      id: "shot02_chunk01",
      shotId: "shot02",
      index: 1,
      text: "然后 Claude 问我两个问题。[long break]第一个问题是,[breath]你刚才反复调参数、看测试集、调参数、看测试集——[break]这个过程里,[long break]测试集还能算,模型从未见过,吗?[long break]我用工程师本能答,[breath]如果每次都是从 0 开始执行流程,那就算有效;[break]否则无效。",
      textNormalized:
        "然后 Claude 问我两个问题。[long break]第一个问题是,[breath]你刚才反复调参数、看测试集、调参数、看测试集——[break]这个过程里,[long break]测试集还能算,模型从未见过,吗?[long break]我用工程师本能答,[breath]如果每次都是从 0 开始执行流程,那就算有效;[break]否则无效。",
      subtitleText: null,
      status: "transcribed",
      charCount: 173,
      takes: [
        {
          id: "take_1",
          file: "shot02_chunk01.wav",
          durationS: 17.415,
          createdAt: NOW,
        },
      ],
      selectedTakeId: "take_1",
      metadata: {},
    },
    {
      id: "shot02_chunk02",
      shotId: "shot02",
      index: 2,
      text: "Claude 说我抓到了一半,",
      textNormalized: "Claude 说我抓到了一半,",
      subtitleText: null,
      status: "transcribed",
      charCount: 15,
      takes: [
        {
          id: "take_1",
          file: "shot02_chunk02.wav",
          durationS: 1.607,
          createdAt: NOW,
        },
      ],
      selectedTakeId: "take_1",
      metadata: {},
    },
    {
      id: "shot02_chunk03",
      shotId: "shot02",
      index: 3,
      text: "而且这是工程师才会想到的那一半——[breath]模型本身确实不记得测试集,[long break]max depth 等于 5 训出来的树,[break]和 max depth 等于 8 训出来的树,[break]是两棵完全独立的树。[long break]从模型的角度看,[break]每次它都是第一次见到测试集。",
      textNormalized:
        "而且这是工程师才会想到的那一半——[breath]模型本身确实不记得测试集,[long break]max depth 等于 5 训出来的树,[break]和 max depth 等于 8 训出来的树,[break]是两棵完全独立的树。[long break]从模型的角度看,[break]每次它都是第一次见到测试集。",
      subtitleText:
        "而且这是工程师才会想到的那一半——模型本身确实不记得测试集,max_depth=5 训出来的树,和 max_depth=8 训出来的树,是两棵完全独立的树。从模型的角度看,每次它都是第一次见到测试集。",
      status: "transcribed",
      charCount: 159,
      takes: [
        {
          id: "take_1",
          file: "shot02_chunk03.wav",
          durationS: 14.328,
          createdAt: NOW,
        },
      ],
      selectedTakeId: "take_1",
      metadata: {},
    },
    {
      id: "shot03_chunk01",
      shotId: "shot03",
      index: 1,
      text: "然后它给了我没看到的另一半。[long break]模型重置了,[break]但,你,没有重置。[long break]测试集结果——[breath]你的眼睛——[breath]你的大脑——[breath]你的决策——[breath]新模型。[long break]这条线就是泄漏通道。[long break]虽然每次模型从 0 开始,[break]但你不是。",
      textNormalized:
        "然后它给了我没看到的另一半。[long break]模型重置了,[break]但,你,没有重置。[long break]测试集结果——[breath]你的眼睛——[breath]你的大脑——[breath]你的决策——[breath]新模型。[long break]这条线就是泄漏通道。[long break]虽然每次模型从 0 开始,[break]但你不是。",
      subtitleText: null,
      status: "transcribed",
      charCount: 180,
      takes: [
        {
          id: "take_1",
          file: "shot03_chunk01.wav",
          durationS: 14.338,
          createdAt: NOW,
        },
      ],
      selectedTakeId: "take_1",
      metadata: {},
    },
  ],
};

// ============================================================
// 其他 episode summary(给 sidebar 列表用)
// ============================================================

export const fixtureEpisodeSummaries: EpisodeSummary[] = [
  {
    id: "ch01",
    status: "done",
    currentStage: null,
    chunkCount: 18,
    updatedAt: "2026-04-05T10:00:00.000Z",
  },
  {
    id: "ch02",
    status: "done",
    currentStage: null,
    chunkCount: 22,
    updatedAt: "2026-04-06T11:00:00.000Z",
  },
  {
    id: "ch03",
    status: "done",
    currentStage: null,
    chunkCount: 16,
    updatedAt: "2026-04-07T15:00:00.000Z",
  },
  {
    id: "ch04",
    status: "done",
    currentStage: null,
    chunkCount: 8,
    updatedAt: NOW,
  },
  {
    id: "ch05",
    status: "ready",
    currentStage: null,
    chunkCount: 0,
    updatedAt: "2026-04-08T07:00:00.000Z",
  },
];

// ============================================================
// 完整 fixture map
// ============================================================

export const fixtureEpisodes: Record<string, Episode> = {
  ch04: ch04Episode,
  ch01: { ...ch04Episode, id: "ch01", chunks: [], totalDurationS: 0 },
  ch02: { ...ch04Episode, id: "ch02", chunks: [], totalDurationS: 0 },
  ch03: { ...ch04Episode, id: "ch03", chunks: [], totalDurationS: 0 },
  ch05: {
    ...ch04Episode,
    id: "ch05",
    status: "ready",
    chunks: [],
    totalDurationS: 0,
  },
};

export const fixtureLogTail = `=== TTS Agent Harness: ch04 ===
=== P1: Text Chunking ===
  shot01: 484 chars → 4 chunks
  shot02: 347 chars → 3 chunks
  shot03: 238 chars → 1 chunks
  ✓ 可逆性校验通过
=== P2: TTS Synthesis (Fish TTS Agent) ===
  [TTS] shot01_chunk01: "接下来这一段,是这一期的核心..."
    → shot01_chunk01.wav (8.57s)
  [TTS] shot01_chunk02: "它没直接给定义..."
    → shot01_chunk02.wav (6.12s)
=== P3: Batch Transcription (via HTTP) ===
  [TRANSCRIBE] shot01_chunk01...
    转写: 接下来这一段是这一期的核心...
=== P5: Subtitle Generation ===
=== P6: Audio Concat ===
=== Done ===`;
