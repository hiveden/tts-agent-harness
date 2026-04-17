"use client";

import { useEffect, useState } from "react";

import {
  charTime as cuesCharTime,
  computeCutIndex,
  cuesToDisplayText,
  type SubtitleCue,
} from "@/lib/karaoke";

interface Props {
  text: string;
  durationS: number;
  isPlaying: boolean;
  /**
   * 真音频的 currentTime(秒)。优先于内部 fallback timer。
   */
  currentTime?: number;
  baseColorClass?: string;
  /**
   * 点字符回调:把"该字符所在的时间"传给 parent,parent 设 audio.currentTime。
   * undefined 时不可点击(如 dirty 状态)。
   */
  onSeek?: (timeS: number) => void;
  /**
   * 精确字幕时间戳（来自后端 P5 SRT，从 chunk.metadata.subtitle_cues 取出）。
   * 提供时走"按 cue 精确对齐"路径，高亮位置 = computeCutIndex(cues, elapsed)。
   * 缺失时退回旧的匀速切片——仅为兼容没有 P5 的 chunk。
   */
  cues?: SubtitleCue[];
}

/**
 * 卡拉 OK 字符遮罩 + 点击 seek。
 *
 * 两条路径：
 * - **精确模式（cues 存在）**：字符序列用 `cues.map(c => c.text).join("")`，
 *   每个字符的时间位置由所在 cue 的 [start, end] 决定。后端 P5 生成的
 *   SRT 时间戳就是"语音到达这个字符的真实时刻"，所以 UI 高亮和语音严
 *   格对齐。参考 `web/lib/karaoke.ts` 的算法细节。
 * - **匀速模式（cues 缺失）**：按 elapsed/durationS × charCount 推字符
 *   位置。这是旧的近似，仅保留以兼容没有跑过 P5 的 chunk（新 chunk、
 *   fallback）。长英文词 + 中文混合的 chunk 会明显滞后。
 *
 * parent（ChunkRow）负责从 `chunk.metadata.subtitle_cues` 提取 cues
 * 并传入；cues 获取失败（格式错、非数组、等等）时 parent 传 undefined。
 */
export function KaraokeSubtitle({
  text,
  durationS,
  isPlaying,
  currentTime,
  baseColorClass = "text-neutral-700",
  onSeek,
  cues,
}: Props) {
  const [fallbackElapsed, setFallbackElapsed] = useState(0);
  const useFallback = currentTime === undefined;

  useEffect(() => {
    if (!useFallback) return;
    if (!isPlaying) {
      setFallbackElapsed(0);
      return;
    }
    setFallbackElapsed(0);
    const id = window.setInterval(() => {
      setFallbackElapsed((e) => {
        const next = e + 0.1;
        if (next >= durationS) {
          window.clearInterval(id);
          return durationS;
        }
        return next;
      });
    }, 100);
    return () => window.clearInterval(id);
  }, [useFallback, isPlaying, durationS]);

  const elapsed = useFallback ? fallbackElapsed : (currentTime ?? 0);
  const hasCues = cues !== undefined && cues.length > 0;

  // 字符序列：精确模式用 cues 拼接（保证和时间映射同源）；匀速模式用
  // 外部传入的 text。
  const chars = Array.from(hasCues ? cuesToDisplayText(cues!) : text);

  let cut: number;
  if (!isPlaying) {
    cut = 0;
  } else if (hasCues) {
    cut = computeCutIndex(cues!, elapsed);
  } else {
    const pct = durationS > 0 ? Math.min(100, (elapsed / durationS) * 100) : 0;
    cut = Math.floor((chars.length * pct) / 100);
  }

  const charTime = (idx: number) => {
    if (hasCues) return cuesCharTime(cues!, idx);
    return chars.length > 0 ? ((idx + 0.5) / chars.length) * durationS : 0;
  };

  // 渲染字符为可点击 span
  return (
    <span className="select-none">
      {chars.map((ch, i) => {
        const played = isPlaying && i < cut;
        const colorClass = played
          ? "text-neutral-900 dark:text-neutral-100 font-medium"
          : isPlaying
            ? "text-neutral-300 dark:text-neutral-600"
            : baseColorClass;
        return (
          <span
            key={i}
            onClick={onSeek ? () => onSeek(charTime(i)) : undefined}
            className={`${colorClass} ${
              onSeek
                ? "cursor-pointer hover:bg-blue-100 dark:hover:bg-blue-900/30 hover:rounded-sm"
                : ""
            }`}
          >
            {ch}
          </span>
        );
      })}
      {isPlaying ? (
        <span className="ml-2 text-[10px] text-neutral-400 dark:text-neutral-500 font-mono">
          {elapsed.toFixed(1)}s / {durationS.toFixed(1)}s
        </span>
      ) : null}
    </span>
  );
}
