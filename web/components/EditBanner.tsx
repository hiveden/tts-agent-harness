"use client";

interface Props {
  ttsCount: number;
  subCount: number;
  onApply: () => void;
  onDiscard: () => void;
}

export function EditBanner({ ttsCount, subCount, onApply, onDiscard }: Props) {
  if (ttsCount === 0 && subCount === 0) return null;

  return (
    <div className="px-6 py-2.5 bg-amber-50 dark:bg-amber-900/20 border-b border-amber-200 dark:border-amber-800 flex items-center gap-4 shrink-0">
      <span className="text-amber-700">●</span>
      <div className="flex gap-4 items-center text-sm">
        {ttsCount > 0 ? (
          <span className="text-amber-900 dark:text-amber-200">
            <b>{ttsCount}</b> TTS 改动{" "}
            <span className="text-amber-600 dark:text-amber-400 text-[11px]">
              → 重新合成 + 重转写
            </span>
          </span>
        ) : null}
        {ttsCount > 0 && subCount > 0 ? (
          <span className="text-amber-300">|</span>
        ) : null}
        {subCount > 0 ? (
          <span className="text-amber-900 dark:text-amber-200">
            <b>{subCount}</b> 字幕改动{" "}
            <span className="text-amber-600 dark:text-amber-400 text-[11px]">→ 只重生字幕</span>
          </span>
        ) : null}
      </div>
      <div className="ml-auto flex gap-2">
        <button
          type="button"
          onClick={onDiscard}
          className="text-xs px-2.5 py-1 text-amber-700 dark:text-amber-300 hover:bg-amber-100 dark:hover:bg-amber-800/30 rounded"
        >
          Discard
        </button>
        <button
          type="button"
          onClick={onApply}
          className="text-xs px-3 py-1 bg-amber-600 text-white rounded hover:bg-amber-700"
        >
          Apply All
        </button>
      </div>
    </div>
  );
}
