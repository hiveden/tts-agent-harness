"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Chunk } from "@/lib/types";
import type { SubtitleCue } from "@/lib/karaoke";
import { extractSubtitleCues } from "@/lib/karaoke";
import {
  fetchChunkTranscript,
  putChunkCues,
  type TranscriptWord,
} from "@/lib/hooks";

/**
 * Chunk-level subtitle timing editor.
 *
 * # 为什么存在
 *
 * P5 自动对齐在中文 chunk 里夹**长英文片段**时（ThoughtWorks / OpenSpec /
 * GitHub）会失败——ASR 把英文听成别的（Falseworks / Open Cloud），字符
 * 守恒假设破坏，P5 贪心算法被迫把过多时间分配给英文行，导致后续所有字幕
 * 往后漂 0.3-0.5s。这是用户听到"字幕比语音慢"的根因。
 *
 * 本组件让用户绕过算法直接改 cue 时间戳：
 * - 看原始 ASR 真值（知道"听成了什么"，判断根因）
 * - 看每个 word 的精确时间戳（作为"应该改成几秒"的依据）
 * - 手动调 cue 的 start/end，保存后覆盖 metadata + 重生成 SRT
 *
 * # 为什么不在抽屉里
 *
 * Stage log drawer 是 stage 级诊断工具（看 log、看执行上下文）。字幕
 * 时间戳是 chunk 级产物的编辑，职责不同。放在 chunk 行下方展开，与
 * `ChunkEditor`（编辑 TTS 源/字幕文字）并列。
 *
 * # 预览的实现
 *
 * 本组件不自己渲染播放器——父组件（ChunkRow）已有音频播放 + karaoke。
 * 本组件 **lift** 修改状态给父组件（onCuesChange），父组件的 karaoke
 * 立刻用新 cues 同步高亮，用户点 chunk 行原有的播放按钮就能试听。
 * 免去"保存到后端 → 关面板 → 听 → 不对 → 重开 → 改"的慢循环。
 */

interface Props {
  chunk: Chunk;
  /** 当前正在预览的 cues（可能是用户未保存的编辑版本）。父组件 karaoke 读这个。 */
  previewCues: SubtitleCue[];
  onCuesChange: (cues: SubtitleCue[]) => void;
  /** 点击 ASR word 时父组件决定如何 seek 音频。传 undefined 表示不支持。 */
  onSeek?: (timeS: number) => void;
  onSaved: () => void;
  onCancel: () => void;
}

export function SubtitleTimingEditor({
  chunk,
  previewCues,
  onCuesChange,
  onSeek,
  onSaved,
  onCancel,
}: Props) {
  const [transcript, setTranscript] = useState<TranscriptWord[] | null>(null);
  const [transcriptError, setTranscriptError] = useState<string | null>(null);
  const [transcriptLoading, setTranscriptLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // Lift-initial-state ref: remember the original cues on open so Cancel /
  // Reset can restore them without refetching.
  const originalRef = useRef<SubtitleCue[] | null>(null);
  if (originalRef.current === null) {
    originalRef.current = extractSubtitleCues(chunk.metadata) ?? [];
  }

  // Fetch transcript once when the panel opens.
  useEffect(() => {
    let cancelled = false;
    setTranscriptLoading(true);
    setTranscriptError(null);
    fetchChunkTranscript(chunk.episodeId, chunk.id)
      .then((t) => {
        if (!cancelled) setTranscript(t.transcript);
      })
      .catch((e) => {
        if (!cancelled) setTranscriptError(String(e.message ?? e));
      })
      .finally(() => {
        if (!cancelled) setTranscriptLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [chunk.id, chunk.episodeId]);

  const dirty =
    JSON.stringify(previewCues) !== JSON.stringify(originalRef.current);

  const updateCue = useCallback(
    (idx: number, patch: Partial<SubtitleCue>) => {
      // Only touch the cue the user edited — no implicit linking to
      // neighbours. Auto-linking cue[i+1].start caused a subtle bug where
      // a subsequent "shift rest by Δ" button applied twice to that start
      // (once via link, once via shift), producing negative timestamps.
      // Users now trigger neighbour changes via the explicit "同步后续"
      // button below, which shifts cue[i+1..] by the delta they chose.
      const next = previewCues.map((c, i) => (i === idx ? { ...c, ...patch } : c));
      onCuesChange(next);
    },
    [previewCues, onCuesChange],
  );

  const shiftCuesFrom = useCallback(
    (idx: number, deltaS: number) => {
      // Shift every cue from idx onwards by deltaS. Useful when the user
      // tightened cue[idx-1] and wants all subsequent cues to move up by the
      // same amount (the classic "after-long-english-word" scenario).
      const next = previewCues.map((c, i) =>
        i >= idx ? { ...c, start: c.start + deltaS, end: c.end + deltaS } : c,
      );
      onCuesChange(next);
    },
    [previewCues, onCuesChange],
  );

  const reset = useCallback(() => {
    onCuesChange(originalRef.current ?? []);
    setSaveError(null);
  }, [onCuesChange]);

  const save = useCallback(async () => {
    setSaving(true);
    setSaveError(null);
    try {
      await putChunkCues(
        chunk.episodeId,
        chunk.id,
        previewCues.map((c) => ({ start: c.start, end: c.end, text: c.text })),
      );
      // Mark this set as the new baseline; Cancel after save won't rewind
      // further than this.
      originalRef.current = previewCues;
      onSaved();
    } catch (e) {
      setSaveError(String((e as Error).message ?? e));
    } finally {
      setSaving(false);
    }
  }, [chunk.episodeId, chunk.id, previewCues, onSaved]);

  return (
    <div className="bg-white dark:bg-neutral-900 border border-neutral-300 dark:border-neutral-600 rounded-md overflow-hidden text-[11px]">
      {/* Header */}
      <div className="flex items-center px-3 py-1.5 border-b border-neutral-100 dark:border-neutral-700/50 bg-neutral-50 dark:bg-neutral-800/50">
        <span className="font-semibold text-neutral-700 dark:text-neutral-300">
          调整字幕时间
        </span>
        <span className="ml-2 text-[10px] text-neutral-400">
          原文字幕保持，仅改时间戳
        </span>
        {dirty && (
          <span className="ml-2 px-1.5 py-0.5 rounded bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300 text-[10px]">
            未保存
          </span>
        )}
        <div className="ml-auto flex items-center gap-1.5">
          {dirty && (
            <button
              type="button"
              onClick={reset}
              disabled={saving}
              className="text-neutral-500 hover:text-neutral-800 dark:text-neutral-400 dark:hover:text-neutral-100 px-1.5 py-0.5"
            >
              重置
            </button>
          )}
          <button
            type="button"
            onClick={save}
            disabled={!dirty || saving}
            className={`px-2.5 py-1 rounded text-white ${
              !dirty || saving
                ? "bg-neutral-300 dark:bg-neutral-700 cursor-not-allowed"
                : "bg-amber-500 hover:bg-amber-600 dark:bg-amber-600 dark:hover:bg-amber-700"
            }`}
          >
            {saving ? "保存中…" : "保存"}
          </button>
          <button
            type="button"
            onClick={onCancel}
            className="px-1.5 py-0.5 text-neutral-500 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800 rounded"
          >
            关闭
          </button>
        </div>
      </div>

      {saveError && (
        <div className="px-3 py-1.5 bg-red-50 dark:bg-red-950/30 border-b border-red-200 dark:border-red-800 text-red-700 dark:text-red-300">
          保存失败：{saveError}
        </div>
      )}

      {/* Cue editor table */}
      <div className="px-3 py-2 border-b border-neutral-100 dark:border-neutral-700/50">
        <div className="text-[10px] text-neutral-500 dark:text-neutral-400 mb-1 font-mono">
          cue[i] start → end  text  |  采用 ASR 末位 / 后续整体前移
        </div>
        <div className="space-y-1">
          {previewCues.map((cue, i) => (
            <CueRow
              key={i}
              idx={i}
              cue={cue}
              originalEnd={originalRef.current![i]?.end ?? cue.end}
              onChange={(patch) => updateCue(i, patch)}
              onShiftRestBy={(delta) => shiftCuesFrom(i + 1, delta)}
            />
          ))}
        </div>
      </div>

      {/* Script vs ASR side-by-side — eyeball the mishearing */}
      <div className="px-3 py-2 border-b border-neutral-100 dark:border-neutral-700/50">
        <div className="grid grid-cols-[4rem_1fr] gap-x-2 gap-y-1">
          <div className="text-[10px] text-neutral-400 dark:text-neutral-500 pt-0.5">
            原文
          </div>
          <div className="text-[11px] text-neutral-700 dark:text-neutral-200 whitespace-pre-wrap break-words">
            {chunk.text}
          </div>
          <div className="text-[10px] text-neutral-400 dark:text-neutral-500 pt-0.5">
            ASR
          </div>
          {transcriptLoading && (
            <div className="text-neutral-400 italic">加载中…</div>
          )}
          {transcriptError && (
            <div className="text-red-600 dark:text-red-400 text-[11px]">
              {transcriptError}
            </div>
          )}
          {transcript && (
            <div className="text-[11px] text-neutral-700 dark:text-neutral-200 whitespace-pre-wrap break-words">
              {transcript.map((w) => w.word).join("")}
            </div>
          )}
        </div>
      </div>

      {/* Per-word time chips — click to seek */}
      <div className="px-3 py-2">
        <div className="text-[10px] text-neutral-500 dark:text-neutral-400 mb-1 font-mono">
          ASR 分词时间戳（点击跳转播放）
        </div>
        {transcript && (
          <TranscriptView words={transcript} onSeek={onSeek} />
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// CueRow — single editable cue
// ---------------------------------------------------------------------------

function CueRow({
  idx,
  cue,
  originalEnd,
  onChange,
  onShiftRestBy,
}: {
  idx: number;
  cue: SubtitleCue;
  /** ``end`` value from when the editor opened — stable baseline so the
   *  "sync rest of cues by Δ" delta is absolute (relative to original),
   *  not relative to the last commit. */
  originalEnd: number;
  onChange: (patch: Partial<SubtitleCue>) => void;
  onShiftRestBy: (deltaS: number) => void;
}) {
  const delta = cue.end - originalEnd;
  const showShiftButton = Math.abs(delta) > 1e-6;

  return (
    <div className="flex items-center gap-1.5 font-mono">
      <span className="text-neutral-400 w-8 text-right">[{idx}]</span>
      <TimeInput
        value={cue.start}
        onCommit={(v) => onChange({ start: v })}
      />
      <span className="text-neutral-300">→</span>
      <TimeInput value={cue.end} onCommit={(v) => onChange({ end: v })} />
      <span className="flex-1 min-w-0 truncate text-neutral-700 dark:text-neutral-300 ml-1">
        {cue.text}
      </span>
      {showShiftButton && (
        <button
          type="button"
          onClick={() => onShiftRestBy(delta)}
          className="text-[10px] px-1.5 py-0.5 rounded bg-blue-50 dark:bg-blue-950/30 text-blue-700 dark:text-blue-300 hover:bg-blue-100 dark:hover:bg-blue-900/30 whitespace-nowrap"
          title={`后续 cue 全部 ${delta > 0 ? "+" : ""}${delta.toFixed(2)}s`}
        >
          同步后续 Δ{delta > 0 ? "+" : ""}{delta.toFixed(2)}s
        </button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// TimeInput — second-precision number field with blur-commit
// ---------------------------------------------------------------------------

function TimeInput({
  value,
  onCommit,
}: {
  value: number;
  onCommit: (v: number) => void;
}) {
  const [draft, setDraft] = useState(value.toFixed(2));
  // Keep draft in sync with external value changes (e.g. after link).
  useEffect(() => {
    setDraft(value.toFixed(2));
  }, [value]);

  const commit = () => {
    const n = parseFloat(draft);
    if (Number.isFinite(n) && n >= 0 && Math.abs(n - value) > 1e-6) {
      onCommit(n);
    } else {
      setDraft(value.toFixed(2));
    }
  };

  return (
    <input
      type="text"
      inputMode="decimal"
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") (e.target as HTMLInputElement).blur();
        if (e.key === "Escape") {
          setDraft(value.toFixed(2));
          (e.target as HTMLInputElement).blur();
        }
      }}
      className="w-14 px-1 py-0.5 text-center rounded border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 text-neutral-800 dark:text-neutral-100 focus:outline-none focus:border-amber-400"
    />
  );
}

// ---------------------------------------------------------------------------
// TranscriptView — renders ASR words as clickable chips
// ---------------------------------------------------------------------------

function TranscriptView({
  words,
  onSeek,
}: {
  words: TranscriptWord[];
  onSeek?: (timeS: number) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1 leading-relaxed">
      {words.map((w, i) => {
        const label = `${w.word.trim()}`;
        const timeLabel = `${w.start.toFixed(2)}–${w.end.toFixed(2)}`;
        return (
          <button
            key={i}
            type="button"
            onClick={() => onSeek?.(w.start)}
            disabled={!onSeek}
            title={timeLabel}
            className={`px-1.5 py-0.5 rounded text-[11px] font-mono ${
              onSeek
                ? "bg-neutral-100 dark:bg-neutral-800 hover:bg-amber-100 dark:hover:bg-amber-900/30 text-neutral-700 dark:text-neutral-300 cursor-pointer"
                : "bg-neutral-100 dark:bg-neutral-800 text-neutral-500 cursor-default"
            }`}
          >
            {label || "·"}
            <span className="ml-1 text-[9px] text-neutral-400">
              {w.end.toFixed(2)}
            </span>
          </button>
        );
      })}
    </div>
  );
}
