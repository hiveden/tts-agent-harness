/**
 * Frontend 共享小工具函数。
 * 这里不 import 任何 adapter / server-only 代码。
 */

import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/** Tailwind class merge utility (shadcn/ui standard). */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Strip S2-Pro 控制标记,供字幕显示用。与 P5 脚本的行为一致。
 *
 * 严格镜像 ``server/core/p5_logic.py::strip_control_markers``:
 *   1. 去掉所有 ``[...]`` 包裹的 token（替换为单个空格，避免粘字）
 *   2. 折叠空格/tab（但 **保留换行** ——作者用换行强制 cue break）
 *   3. 修剪换行两侧的空白
 *   4. 首尾 trim
 *
 * 旧实现用 ``\s+`` 把换行也折叠成空格，破坏了作者的显式分行意图——
 * 这是前端/后端契约漂移，已在本轮清债务中修复。
 */
export function stripControlMarkers(text: string | null | undefined): string {
  return String(text ?? "")
    .replace(/\[[^\[\]]*\]/g, " ")
    .replace(/[ \t]+/g, " ")
    .replace(/ *\n */g, "\n")
    .trim();
}

/** 得到字幕显示文本:优先 subtitleText,否则 strip 后的 text。 */
export function getDisplaySubtitle(c: {
  text: string;
  subtitleText: string | null;
}): string {
  if (c.subtitleText != null) return stripControlMarkers(c.subtitleText);
  return stripControlMarkers(c.text);
}
