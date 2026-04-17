/**
 * 卡拉 OK 字幕高亮的纯函数。与 DOM / React 解耦，便于单元测试。
 *
 * ## 为什么要有这个文件
 *
 * 前端之前在 `KaraokeSubtitle.tsx` 里用 `elapsed/durationS × charCount`
 * 做匀速切片，完全忽略后端 P5 生成的精确 SRT 时间戳。中英混合 + 长英文
 * 词的 chunk 会因此出现"字幕慢于语音 ~0.5s 甚至更多"的可见问题。
 *
 * 本模块消费 `SubtitleCue[]`（由后端 P5 `compose_srt` 生成、随 chunk
 * metadata 返回），按 cue 精确映射 `currentTime → 高亮字符数`。
 */

export interface SubtitleCue {
  /** Chunk-relative start time in seconds. */
  start: number;
  /** Chunk-relative end time in seconds. */
  end: number;
  /** Cue displayed text (already stripped of control markers by P5). */
  text: string;
}

/**
 * cues.map(c => c.text).join("") — 字符基准序列。
 *
 * 前端渲染 KaraokeSubtitle 时使用这个字符串作为字符切分基准，而不是
 * 整段 chunk.text，因为后端 `split_subtitle_lines` 可能 trim 掉行间
 * 空格。用 cues 拼接能保证"渲染字符序列"和"时间映射字符序列"完全
 * 一致（无索引漂移）。
 */
export function cuesToDisplayText(cues: SubtitleCue[]): string {
  return cues.map((c) => c.text).join("");
}

/**
 * 按 currentTime 精确计算已高亮字符数（cut index）。
 *
 * 算法：
 *
 * 1. 顺序扫描 cues，累加每个 cue 的字符长度到 offset
 * 2. 找到 currentTime 所在的 cue
 *    - currentTime < cue.start → 停在当前 offset（cue 还没开始）
 *    - currentTime >= cue.end → offset += cue.text.length（cue 已放完）
 *    - 否则，在 cue 内按时间比例切：offset + floor(len × (t - start) / (end - start))
 * 3. 超过最后一个 cue.end → 返回全部字符数
 *
 * 用 `floor` 而不是 `round` 让高亮"恰好在字符完成时才点亮"——这和
 * 观看体验更吻合；`round` 会让字符在一半时就点亮，视觉上提早。
 */
export function computeCutIndex(
  cues: readonly SubtitleCue[],
  currentTime: number,
): number {
  if (cues.length === 0) return 0;
  let offset = 0;
  for (const cue of cues) {
    const len = cue.text.length;
    if (currentTime >= cue.end) {
      offset += len;
      continue;
    }
    if (currentTime <= cue.start) {
      return offset;
    }
    const duration = cue.end - cue.start;
    if (duration <= 0) {
      offset += len;
      continue;
    }
    const ratio = (currentTime - cue.start) / duration;
    return offset + Math.floor(len * ratio);
  }
  return offset; // beyond last cue
}

/**
 * 给定字符索引 idx，返回它在时间轴上的位置（用于点击 seek）。
 *
 * 字符 idx 落在哪个 cue 内，就按 `cue.start + (idx-offset+0.5)/len × duration`
 * 给出字符"中点"时间——点击跳转时听到的正好是那个字符。
 */
export function charTime(
  cues: readonly SubtitleCue[],
  idx: number,
): number {
  if (cues.length === 0) return 0;
  let offset = 0;
  for (const cue of cues) {
    const len = cue.text.length;
    if (idx < offset + len) {
      const localIdx = idx - offset;
      const ratio = (localIdx + 0.5) / len;
      return cue.start + ratio * (cue.end - cue.start);
    }
    offset += len;
  }
  // Clicked past the last character — snap to last cue end.
  return cues[cues.length - 1]!.end;
}

/**
 * 从 chunk.metadata JSON 里安全提取 subtitle_cues。
 *
 * OpenAPI schema 把 metadata 类型化为 `Record<string, unknown>`，
 * 所以需要 runtime 校验。返回 undefined 表示 "no cues available"
 * ——调用方应 fallback 到旧的匀速算法。
 */
export function extractSubtitleCues(
  metadata: unknown,
): SubtitleCue[] | undefined {
  if (!metadata || typeof metadata !== "object") return undefined;
  const raw = (metadata as Record<string, unknown>)["subtitle_cues"];
  if (!Array.isArray(raw)) return undefined;
  const cues: SubtitleCue[] = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") return undefined;
    const obj = item as Record<string, unknown>;
    const start = Number(obj.start);
    const end = Number(obj.end);
    const text = obj.text;
    if (
      !Number.isFinite(start) ||
      !Number.isFinite(end) ||
      typeof text !== "string"
    ) {
      return undefined;
    }
    cues.push({ start, end, text });
  }
  return cues.length > 0 ? cues : undefined;
}
