"use client";

import { useState } from "react";
import type { Chunk, ChunkEdit } from "@/lib/types";
import { GRID_COLS } from "./chunks-grid";

interface Props {
  chunk: Chunk;
  /** 初始草稿(若该 chunk 已 staged 过,从 edits 里取) */
  initialDraft?: ChunkEdit;
  onStage: (draft: ChunkEdit) => void;
  onCancel: () => void;
}

/**
 * 编辑面板,作为 chunk row 下方展开的区域。
 * 左侧留 4 列空白,右侧 2 列放编辑卡片。
 */
export function ChunkEditor({
  chunk,
  initialDraft,
  onStage,
  onCancel,
}: Props) {
  const [ttsValue, setTtsValue] = useState<string>(
    initialDraft?.textNormalized ?? chunk.textNormalized,
  );
  const [subValue, setSubValue] = useState<string>(
    initialDraft?.subtitleText ?? chunk.subtitleText ?? "",
  );

  const hasSubField = chunk.subtitleText != null;

  const handleStage = () => {
    const draft: ChunkEdit = {};
    if (ttsValue !== chunk.textNormalized) draft.textNormalized = ttsValue;
    const origSub = chunk.subtitleText ?? "";
    if (subValue !== origSub) draft.subtitleText = subValue;
    onStage(draft);
  };

  return (
    <div className="bg-neutral-50 border-b border-neutral-100">
      {/* Use grid to align with the row columns: skip first 4 cols, span last 2 */}
      <div className="grid" style={{ gridTemplateColumns: GRID_COLS }}>
        <div className="col-span-4 bg-neutral-50" />
        <div className="col-span-2 py-3 pr-6">
          <div className="bg-white border border-neutral-300 rounded-lg p-4 shadow-sm">
            {/* TTS source */}
            <div className="mb-4">
              <div className="flex items-baseline gap-2 mb-1.5">
                <span className="text-xs">🔊</span>
                <span className="text-xs font-semibold text-neutral-700">
                  TTS 源
                </span>
                <span className="text-[10px] text-neutral-400 font-mono">
                  text_normalized
                </span>
                <span className="ml-auto text-[10px] text-amber-600">
                  改 → 重新合成 + 重转写 (慢)
                </span>
              </div>
              <textarea
                rows={2}
                value={ttsValue}
                onChange={(e) => setTtsValue(e.target.value)}
                className="w-full border border-neutral-300 rounded px-2.5 py-1.5 text-sm focus:outline-none focus:border-neutral-900 resize-none"
              />
            </div>

            {/* Subtitle */}
            <div className="mb-4">
              <div className="flex items-baseline gap-2 mb-1.5">
                <span className="text-xs">💬</span>
                <span className="text-xs font-semibold text-neutral-700">
                  字幕文本
                </span>
                <span className="text-[10px] text-neutral-400 font-mono">
                  subtitle_text
                </span>
                {hasSubField ? (
                  <span className="text-[10px] text-purple-600">
                    ◆ 已独立设置
                  </span>
                ) : (
                  <span className="text-[10px] text-neutral-400">
                    未设置 → 字幕兜底用 text 字段
                  </span>
                )}
                <span className="ml-auto text-[10px] text-amber-600">
                  改 → 只重生字幕 (快)
                </span>
              </div>
              <textarea
                rows={2}
                value={subValue}
                placeholder={chunk.text}
                onChange={(e) => setSubValue(e.target.value)}
                className="w-full border border-neutral-300 rounded px-2.5 py-1.5 text-sm focus:outline-none focus:border-neutral-900 resize-none"
              />
            </div>

            {/* Original (readonly) */}
            <div className="mb-4">
              <div className="flex items-baseline gap-2 mb-1.5">
                <span className="text-xs">📄</span>
                <span className="text-xs font-semibold text-neutral-500">
                  原文
                </span>
                <span className="text-[10px] text-neutral-400 font-mono">
                  text
                </span>
                <span className="text-[10px] text-neutral-400">
                  script.json 切分,只读
                </span>
              </div>
              <div className="px-2.5 py-1.5 text-sm bg-neutral-50 border border-neutral-200 rounded text-neutral-500">
                {chunk.text}
              </div>
            </div>

            {/* Actions */}
            <div className="flex items-center gap-2 pt-3 border-t border-neutral-100">
              <button
                type="button"
                onClick={handleStage}
                className="text-xs px-3 py-1.5 bg-amber-600 text-white rounded hover:bg-amber-700"
              >
                Stage Change
              </button>
              <button
                type="button"
                onClick={onCancel}
                className="text-xs px-2.5 py-1.5 hover:bg-neutral-100 rounded text-neutral-600"
              >
                Cancel
              </button>
              <span className="ml-auto text-[10px] text-neutral-400">
                改动会先暂存,顶部 Apply All 时统一执行
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
