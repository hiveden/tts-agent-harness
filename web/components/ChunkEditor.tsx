"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import type { Chunk, ChunkEdit } from "@/lib/types";
import { GRID_COLS } from "./chunks-grid";

interface Props {
  chunk: Chunk;
  /** 初始草稿(若该 chunk 已 staged 过,从 edits 里取) */
  initialDraft?: ChunkEdit;
  onStage: (draft: ChunkEdit) => void;
  onCancel: () => void;
}

type EditingField = "tts" | "sub" | null;

/** Auto-resize a textarea to fit its content */
function autoResize(el: HTMLTextAreaElement) {
  el.style.height = "auto";
  el.style.height = el.scrollHeight + "px";
}

/**
 * 编辑面板 — 原型图风格 inline-edit。
 * 水平行布局：左侧标签(90px) + 中间内容(flex-1) + 右侧提示。
 * 点击文本区域进入编辑(textarea)，失焦或 Esc 退出。
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
  const [editingField, setEditingField] = useState<EditingField>(null);

  const ttsRef = useRef<HTMLTextAreaElement>(null);
  const subRef = useRef<HTMLTextAreaElement>(null);

  const isReview = chunk.status === "needs_review";
  const diagnosis = chunk.verifyDiagnosis;

  // Focus + auto-resize when entering edit mode
  useEffect(() => {
    const ref = editingField === "tts" ? ttsRef : editingField === "sub" ? subRef : null;
    if (ref?.current) {
      const el = ref.current;
      autoResize(el);
      el.focus();
      // Move cursor to end
      el.selectionStart = el.selectionEnd = el.value.length;
    }
  }, [editingField]);

  const handleBlur = useCallback(() => {
    setEditingField(null);
  }, []);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Escape") {
        e.currentTarget.blur();
      }
    },
    [],
  );

  const handleStage = () => {
    const draft: ChunkEdit = {};
    if (ttsValue !== chunk.textNormalized) draft.textNormalized = ttsValue;
    const origSub = chunk.subtitleText ?? "";
    if (subValue !== origSub) draft.subtitleText = subValue;
    onStage(draft);
  };

  // Build review banner text from diagnosis
  const reviewBannerParts: string[] = [];
  if (diagnosis) {
    if (diagnosis.missing && diagnosis.missing.length > 0) {
      reviewBannerParts.push(`缺失: "${diagnosis.missing.join('", "')}"`);
    }
    if (diagnosis.extra && diagnosis.extra.length > 0) {
      reviewBannerParts.push(`多余: "${diagnosis.extra.join('", "')}"`);
    }
    if (diagnosis.type) {
      reviewBannerParts.push(`类型: ${diagnosis.type}`);
    }
    if (diagnosis.lowConfidenceWords && diagnosis.lowConfidenceWords.length > 0) {
      reviewBannerParts.push(`低置信度: ${diagnosis.lowConfidenceWords.join(", ")}`);
    }
    if (diagnosis.verdict) {
      reviewBannerParts.push(diagnosis.verdict);
    }
  }

  const subPlaceholder = "未设置，兜底用 text";
  const subDisplayEmpty = !subValue;

  return (
    <div className="bg-neutral-50 dark:bg-neutral-900/50 border-b border-neutral-100 dark:border-neutral-700">
      <div className="grid" style={{ gridTemplateColumns: GRID_COLS }}>
        <div className="col-span-4 bg-neutral-50 dark:bg-neutral-900/50" />
        <div className="col-span-2 py-2 pr-6">
          <div
            className={`bg-white dark:bg-neutral-900 border rounded-md shadow-sm dark:shadow-neutral-900 overflow-hidden ${
              isReview
                ? "border-amber-400 dark:border-amber-500"
                : "border-neutral-300 dark:border-neutral-600"
            }`}
          >
            {/* Review banner */}
            {isReview && reviewBannerParts.length > 0 && (
              <div className="px-3 py-1.5 bg-amber-50 dark:bg-amber-950/40 border-b border-amber-200 dark:border-amber-800 text-[11px] text-amber-800 dark:text-amber-300 leading-relaxed">
                <strong className="font-semibold text-amber-700 dark:text-amber-400">
                  需要人工介入
                </strong>
                {" · "}
                {reviewBannerParts.join(" · ")}
              </div>
            )}

            {/* Field: TTS 源 */}
            <FieldRow
              label="TTS 源"
              fieldKey="text_normalized"
              hint="改 → 重新合成"
              hintWarn
            >
              {editingField === "tts" ? (
                <textarea
                  ref={ttsRef}
                  value={ttsValue}
                  onChange={(e) => {
                    setTtsValue(e.target.value);
                    autoResize(e.currentTarget);
                  }}
                  onBlur={handleBlur}
                  onKeyDown={handleKeyDown}
                  className="w-full text-[11px] text-neutral-800 dark:text-neutral-200 leading-relaxed px-1 py-0.5 border border-neutral-800 dark:border-neutral-400 rounded-[3px] bg-white dark:bg-neutral-800 font-inherit resize-none outline-none"
                />
              ) : (
                <div
                  onClick={() => setEditingField("tts")}
                  className="text-[11px] text-neutral-800 dark:text-neutral-200 leading-relaxed px-1 py-0.5 rounded-[3px] cursor-text border border-transparent hover:bg-neutral-100 dark:hover:bg-neutral-800 hover:border-neutral-200 dark:hover:border-neutral-700 min-h-[18px] whitespace-pre-wrap"
                >
                  {ttsValue}
                </div>
              )}
            </FieldRow>

            {/* Field: 字幕 */}
            <FieldRow
              label="字幕"
              fieldKey="subtitle_text"
              hint="改 → 重生字幕"
            >
              {editingField === "sub" ? (
                <textarea
                  ref={subRef}
                  value={subValue}
                  placeholder={subPlaceholder}
                  onChange={(e) => {
                    setSubValue(e.target.value);
                    autoResize(e.currentTarget);
                  }}
                  onBlur={handleBlur}
                  onKeyDown={handleKeyDown}
                  className="w-full text-[11px] text-neutral-800 dark:text-neutral-200 leading-relaxed px-1 py-0.5 border border-neutral-800 dark:border-neutral-400 rounded-[3px] bg-white dark:bg-neutral-800 font-inherit resize-none outline-none"
                />
              ) : (
                <div
                  onClick={() => setEditingField("sub")}
                  className={`text-[11px] leading-relaxed px-1 py-0.5 rounded-[3px] cursor-text border border-transparent hover:bg-neutral-100 dark:hover:bg-neutral-800 hover:border-neutral-200 dark:hover:border-neutral-700 min-h-[18px] whitespace-pre-wrap ${
                    subDisplayEmpty
                      ? "text-neutral-400 dark:text-neutral-500 italic"
                      : "text-neutral-800 dark:text-neutral-200"
                  }`}
                >
                  {subDisplayEmpty ? subPlaceholder : subValue}
                </div>
              )}
            </FieldRow>

            {/* Field: 原文 (readonly) */}
            <FieldRow
              label="原文"
              fieldKey="text"
              hint="只读"
              isLast
            >
              <div className="text-[11px] text-neutral-400 dark:text-neutral-500 leading-relaxed px-1 py-0.5 min-h-[18px] whitespace-pre-wrap cursor-default">
                {chunk.text}
              </div>
            </FieldRow>

            {/* Actions */}
            <div className="flex items-center gap-1.5 px-3 py-1.5 border-t border-neutral-100 dark:border-neutral-700">
              <button
                type="button"
                onClick={handleStage}
                className="text-[11px] font-medium px-2.5 py-1 bg-amber-500 text-white rounded hover:bg-amber-600 dark:bg-amber-600 dark:hover:bg-amber-700"
              >
                Stage Change
              </button>
              <button
                type="button"
                onClick={onCancel}
                className="text-[11px] px-2 py-1 rounded text-neutral-500 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800 hover:text-neutral-700 dark:hover:text-neutral-300"
              >
                Cancel
              </button>
              <span className="ml-auto text-[9px] text-neutral-400 dark:text-neutral-500">
                暂存，顶部 Apply All 统一执行
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ─── Field Row sub-component ─── */

function FieldRow({
  label,
  fieldKey,
  hint,
  hintWarn,
  isLast,
  children,
}: {
  label: string;
  fieldKey: string;
  hint: string;
  hintWarn?: boolean;
  isLast?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div
      className={`flex items-start gap-2 px-3 py-1.5 ${
        isLast ? "" : "border-b border-neutral-100 dark:border-neutral-700/50"
      }`}
    >
      {/* Label column: 90px */}
      <div className="w-[90px] flex-shrink-0 pt-0.5">
        <div className="text-[11px] font-semibold text-neutral-500 dark:text-neutral-400">
          {label}
        </div>
        <div className="text-[9px] font-mono text-neutral-300 dark:text-neutral-600">
          {fieldKey}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">{children}</div>

      {/* Hint */}
      <div
        className={`flex-shrink-0 text-[9px] pt-1 ${
          hintWarn
            ? "text-amber-700 dark:text-amber-500"
            : "text-neutral-400 dark:text-neutral-500"
        }`}
      >
        {hint}
      </div>
    </div>
  );
}
