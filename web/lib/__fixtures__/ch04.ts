/**
 * Mock fixture: ch04 episode
 *
 * Updated to match new domain types (v2).
 */

import type { Episode, EpisodeSummary } from "../types";

const NOW = "2026-04-08T08:54:00.000Z";

export const ch04Episode: Episode = {
  id: "ch04",
  title: "Ch04 Episode",
  description: null,
  status: "done",
  scriptUri: "episodes/ch04/script.json",
  config: {},
  createdAt: "2026-04-08T02:09:34.049Z",
  updatedAt: NOW,
  metadata: {},
  chunks: [
    {
      id: "shot01_chunk01",
      episodeId: "ch04",
      shotId: "shot01",
      idx: 1,
      text: "接下来这一段,是这一期的核心。[break]我要把它讲细,因为它细节里有钩子。[long break]Claude 教训练集、验证集、测试集为什么要切三份。",
      textNormalized:
        "接下来这一段,是这一期的核心。[break]我要把它讲细,因为它细节里有钩子。[long break]Claude 教训练集、验证集、测试集为什么要切三份。",
      subtitleText: null,
      status: "transcribed",
      charCount: 78,
      selectedTakeId: "take_1",
      metadata: {},
      takes: [
        {
          id: "take_1",
          audioUri: "episodes/ch04/audio/shot01_chunk01.wav",
          durationS: 8.569,
          params: {},
          createdAt: NOW,
        },
      ],
      stageRuns: [],
    },
    {
      id: "shot01_chunk02",
      episodeId: "ch04",
      shotId: "shot01",
      idx: 2,
      text: "它没直接给定义,[break]先用了一个决策树调参的场景。[long break]假设你训练一个决策树预测房价。",
      textNormalized:
        "它没直接给定义,[break]先用了一个决策树调参的场景。[long break]假设你训练一个决策树预测房价。",
      subtitleText: null,
      status: "transcribed",
      charCount: 56,
      selectedTakeId: "take_1",
      metadata: {},
      takes: [
        {
          id: "take_1",
          audioUri: "episodes/ch04/audio/shot01_chunk02.wav",
          durationS: 6.121,
          params: {},
          createdAt: NOW,
        },
      ],
      stageRuns: [],
    },
    {
      id: "shot01_chunk03",
      episodeId: "ch04",
      shotId: "shot01",
      idx: 3,
      text: "[break]第一次跑完,[breath]训练集准确率百分之九十八,测试集百分之七十二——[break]你看出过拟合了。[long break]你调一个参数,[breath]把 max depth 从默认改成 5。[break]再跑,训练百分之九十五,测试百分之八十五。[breath]好多了。",
      textNormalized:
        "[break]第一次跑完,[breath]训练集准确率百分之九十八,测试集百分之七十二——[break]你看出过拟合了。[long break]你调一个参数,[breath]把 max depth 从默认改成 5。[break]再跑,训练百分之九十五,测试百分之八十五。[breath]好多了。",
      subtitleText:
        "第一次跑完,训练集准确率 98%,测试集 72%——你看出过拟合了。你调一个参数,把 max_depth 从默认改成 5。再跑,训练 95%,测试 85%。好多了。",
      status: "transcribed",
      charCount: 147,
      selectedTakeId: "take_1",
      metadata: {},
      takes: [
        {
          id: "take_1",
          audioUri: "episodes/ch04/audio/shot01_chunk03.wav",
          durationS: 14.225,
          params: {},
          createdAt: NOW,
        },
      ],
      stageRuns: [],
    },
    {
      id: "shot01_chunk04",
      episodeId: "ch04",
      shotId: "shot01",
      idx: 4,
      text: "[long break]再调,max depth 改成 8,[break]训练百分之九十六,测试百分之八十八。[breath]更好。[long break]再调,max depth 改成 10,[break]训练百分之九十七,测试百分之八十七。[breath]嗯?退步了,回去 8。[long break]最终定下来 max depth 等于 8,[break]准确率百分之八十八,[break]发布上线。",
      textNormalized:
        "[long break]再调,max depth 改成 8,[break]训练百分之九十六,测试百分之八十八。[breath]更好。[long break]再调,max depth 改成 10,[break]训练百分之九十七,测试百分之八十七。[breath]嗯?退步了,回去 8。[long break]最终定下来 max depth 等于 8,[break]准确率百分之八十八,[break]发布上线。",
      subtitleText:
        "再调,max_depth 改成 8,训练 96%,测试 88%。更好。再调,max_depth 改成 10,训练 97%,测试 87%。嗯?退步了,回去 8。最终定下来 max_depth = 8,准确率 88%,发布上线。",
      status: "transcribed",
      charCount: 203,
      selectedTakeId: "take_2",
      metadata: {},
      takes: [
        {
          id: "take_1",
          audioUri: "episodes/ch04/audio/shot01_chunk04.take_1.wav",
          durationS: 17.5,
          params: {},
          createdAt: "2026-04-08T08:30:00.000Z",
        },
        {
          id: "take_2",
          audioUri: "episodes/ch04/audio/shot01_chunk04.wav",
          durationS: 17.968,
          params: { temperature: 0.4 },
          createdAt: "2026-04-08T08:32:00.000Z",
        },
        {
          id: "take_3",
          audioUri: "episodes/ch04/audio/shot01_chunk04.take_3.wav",
          durationS: 18.2,
          params: { temperature: 0.5 },
          createdAt: "2026-04-08T08:35:00.000Z",
        },
      ],
      stageRuns: [],
    },
    {
      id: "shot02_chunk01",
      episodeId: "ch04",
      shotId: "shot02",
      idx: 1,
      text: "然后 Claude 问我两个问题。[long break]第一个问题是,[breath]你刚才反复调参数、看测试集、调参数、看测试集——[break]这个过程里,[long break]测试集还能算,模型从未见过,吗?[long break]我用工程师本能答,[breath]如果每次都是从 0 开始执行流程,那就算有效;[break]否则无效。",
      textNormalized:
        "然后 Claude 问我两个问题。[long break]第一个问题是,[breath]你刚才反复调参数、看测试集、调参数、看测试集——[break]这个过程里,[long break]测试集还能算,模型从未见过,吗?[long break]我用工程师本能答,[breath]如果每次都是从 0 开始执行流程,那就算有效;[break]否则无效。",
      subtitleText: null,
      status: "transcribed",
      charCount: 173,
      selectedTakeId: "take_1",
      metadata: {},
      takes: [
        {
          id: "take_1",
          audioUri: "episodes/ch04/audio/shot02_chunk01.wav",
          durationS: 17.415,
          params: {},
          createdAt: NOW,
        },
      ],
      stageRuns: [],
    },
    {
      id: "shot02_chunk02",
      episodeId: "ch04",
      shotId: "shot02",
      idx: 2,
      text: "Claude 说我抓到了一半,",
      textNormalized: "Claude 说我抓到了一半,",
      subtitleText: null,
      status: "transcribed",
      charCount: 15,
      selectedTakeId: "take_1",
      metadata: {},
      takes: [
        {
          id: "take_1",
          audioUri: "episodes/ch04/audio/shot02_chunk02.wav",
          durationS: 1.607,
          params: {},
          createdAt: NOW,
        },
      ],
      stageRuns: [],
    },
    {
      id: "shot02_chunk03",
      episodeId: "ch04",
      shotId: "shot02",
      idx: 3,
      text: "而且这是工程师才会想到的那一半——[breath]模型本身确实不记得测试集,[long break]max depth 等于 5 训出来的树,[break]和 max depth 等于 8 训出来的树,[break]是两棵完全独立的树。[long break]从模型的角度看,[break]每次它都是第一次见到测试集。",
      textNormalized:
        "而且这是工程师才会想到的那一半——[breath]模型本身确实不记得测试集,[long break]max depth 等于 5 训出来的树,[break]和 max depth 等于 8 训出来的树,[break]是两棵完全独立的树。[long break]从模型的角度看,[break]每次它都是第一次见到测试集。",
      subtitleText:
        "而且这是工程师才会想到的那一半——模型本身确实不记得测试集,max_depth=5 训出来的树,和 max_depth=8 训出来的树,是两棵完全独立的树。从模型的角度看,每次它都是第一次见到测试集。",
      status: "transcribed",
      charCount: 159,
      selectedTakeId: "take_1",
      metadata: {},
      takes: [
        {
          id: "take_1",
          audioUri: "episodes/ch04/audio/shot02_chunk03.wav",
          durationS: 14.328,
          params: {},
          createdAt: NOW,
        },
      ],
      stageRuns: [],
    },
    {
      id: "shot03_chunk01",
      episodeId: "ch04",
      shotId: "shot03",
      idx: 1,
      text: "然后它给了我没看到的另一半。[long break]模型重置了,[break]但,你,没有重置。[long break]测试集结果——[breath]你的眼睛——[breath]你的大脑——[breath]你的决策——[breath]新模型。[long break]这条线就是泄漏通道。[long break]虽然每次模型从 0 开始,[break]但你不是。",
      textNormalized:
        "然后它给了我没看到的另一半。[long break]模型重置了,[break]但,你,没有重置。[long break]测试集结果——[breath]你的眼睛——[breath]你的大脑——[breath]你的决策——[breath]新模型。[long break]这条线就是泄漏通道。[long break]虽然每次模型从 0 开始,[break]但你不是。",
      subtitleText: null,
      status: "transcribed",
      charCount: 180,
      selectedTakeId: "take_1",
      metadata: {},
      takes: [
        {
          id: "take_1",
          audioUri: "episodes/ch04/audio/shot03_chunk01.wav",
          durationS: 14.338,
          params: {},
          createdAt: NOW,
        },
      ],
      stageRuns: [],
    },
  ],
};

export const fixtureEpisodeSummaries: EpisodeSummary[] = [
  {
    id: "ch01",
    title: "Ch01",
    status: "done",
    chunkCount: 18,
    doneCount: 18,
    failedCount: 0,
    updatedAt: "2026-04-05T10:00:00.000Z",
  },
  {
    id: "ch02",
    title: "Ch02",
    status: "done",
    chunkCount: 22,
    doneCount: 22,
    failedCount: 0,
    updatedAt: "2026-04-06T11:00:00.000Z",
  },
  {
    id: "ch03",
    title: "Ch03",
    status: "done",
    chunkCount: 16,
    doneCount: 16,
    failedCount: 0,
    updatedAt: "2026-04-07T15:00:00.000Z",
  },
  {
    id: "ch04",
    title: "Ch04",
    status: "done",
    chunkCount: 8,
    doneCount: 8,
    failedCount: 0,
    updatedAt: NOW,
  },
  {
    id: "ch05",
    title: "Ch05",
    status: "ready",
    chunkCount: 0,
    doneCount: 0,
    failedCount: 0,
    updatedAt: "2026-04-08T07:00:00.000Z",
  },
];

export const fixtureEpisodes: Record<string, Episode> = {
  ch04: ch04Episode,
  ch01: { ...ch04Episode, id: "ch01", title: "Ch01", chunks: [] },
  ch02: { ...ch04Episode, id: "ch02", title: "Ch02", chunks: [] },
  ch03: { ...ch04Episode, id: "ch03", title: "Ch03", chunks: [] },
  ch05: {
    ...ch04Episode,
    id: "ch05",
    title: "Ch05",
    status: "ready",
    chunks: [],
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
