"use client";

import { useEffect, useState } from "react";

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
}

/**
 * 卡拉 OK 字符遮罩 + 点击 seek。
 * - 真音频模式: parent 通过 onTimeUpdate 把 currentTime 传进来,组件按字符切点渲染
 * - fallback 模式: currentTime 未传时,自启 100ms setInterval 模拟
 * - 点击字符: 调 onSeek((charIndex + 0.5) / chars.length * durationS)
 */
export function KaraokeSubtitle({
  text,
  durationS,
  isPlaying,
  currentTime,
  baseColorClass = "text-neutral-700",
  onSeek,
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
  const chars = Array.from(text);
  const pct =
    durationS > 0 ? Math.min(100, (elapsed / durationS) * 100) : 0;
  const cut = isPlaying ? Math.floor((chars.length * pct) / 100) : 0;

  const charTime = (idx: number) =>
    chars.length > 0 ? ((idx + 0.5) / chars.length) * durationS : 0;

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
