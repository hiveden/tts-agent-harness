import { test, expect } from "@playwright/test";
import {
  computeCutIndex,
  charTime,
  cuesToDisplayText,
  extractSubtitleCues,
  type SubtitleCue,
} from "../lib/karaoke";

// ----------------------------------------------------------------------------
// cuesToDisplayText
// ----------------------------------------------------------------------------

test("cuesToDisplayText joins cue texts in order without separators", () => {
  const cues: SubtitleCue[] = [
    { start: 0, end: 1, text: "你好" },
    { start: 1, end: 2, text: "世界" },
  ];
  expect(cuesToDisplayText(cues)).toBe("你好世界");
});

// ----------------------------------------------------------------------------
// computeCutIndex — boundary behaviour
// ----------------------------------------------------------------------------

test("computeCutIndex returns 0 for empty cues", () => {
  expect(computeCutIndex([], 5.0)).toBe(0);
});

test("computeCutIndex returns 0 before first cue starts", () => {
  const cues: SubtitleCue[] = [{ start: 1.0, end: 2.0, text: "abcd" }];
  expect(computeCutIndex(cues, 0.0)).toBe(0);
  expect(computeCutIndex(cues, 0.9)).toBe(0);
});

test("computeCutIndex returns full length after last cue ends", () => {
  const cues: SubtitleCue[] = [
    { start: 0, end: 1, text: "ab" },
    { start: 1, end: 2, text: "cd" },
  ];
  expect(computeCutIndex(cues, 10.0)).toBe(4);
});

test("computeCutIndex gives floor-proportional cut inside a cue", () => {
  const cues: SubtitleCue[] = [{ start: 0, end: 10, text: "0123456789" }];
  // At 50% through, 5 chars played; at 33% through, 3 chars.
  expect(computeCutIndex(cues, 5.0)).toBe(5);
  expect(computeCutIndex(cues, 3.3)).toBe(3);
  expect(computeCutIndex(cues, 9.99)).toBe(9); // not 10 until full end
});

test("computeCutIndex handles zero-duration cue (snap past)", () => {
  const cues: SubtitleCue[] = [
    { start: 1.0, end: 1.0, text: "snap" },
    { start: 1.0, end: 2.0, text: "next" },
  ];
  // Anywhere past start of the zero-duration cue: it's considered done.
  expect(computeCutIndex(cues, 1.5)).toBe(4 + Math.floor(4 * 0.5));
});

// ----------------------------------------------------------------------------
// computeCutIndex — the FLASH01-v2:shot05:2 regression scenario
// ----------------------------------------------------------------------------
//
// These cues come from the real shot05:2 SRT after the gap-aware P5 fix.
// They are the "truth" the UI must show. The previous KaraokeSubtitle
// used elapsed/durationS × charCount, which drifts by ~1s on this chunk
// due to long English words (GitHub / Development) packing many chars
// into a short spoken time.
//
// These tests lock the contract: at playhead T, the UI must highlight
// exactly the chars that P5 says were spoken by T.

const SHOT05_CUES: SubtitleCue[] = [
  { start: 0.0, end: 2.02, text: "Agent Skills 把指令模块化、" }, // 14
  { start: 2.02, end: 3.0, text: "按需加载；" }, // 5
  { start: 3.32, end: 4.02, text: "spec-driven" }, // 11
  { start: 4.02, end: 5.56, text: "development——GitHub" }, // 19
  { start: 5.56, end: 6.42, text: "Spec-Kit、" }, // 9
  { start: 6.82, end: 8.58, text: "OpenSpec——用规格驱动" }, // 15
  { start: 8.58, end: 10.02, text: "agent 的规划和实现。" }, // 11
];

function charsBefore(n: number): number {
  // Sum text lengths of the first n cues.
  return SHOT05_CUES.slice(0, n).reduce((s, c) => s + c.text.length, 0);
}

test("shot05 regression: at GitHub end (t=5.56), highlight lands at end of cue 3", () => {
  // cue 3 ("development——GitHub") ends at 5.56 → cut == sum of cue
  // lengths 0..3 inclusive == charsBefore(4). The next cue (Spec-Kit)
  // does not start until 5.56 and contributes nothing at this instant.
  const cut = computeCutIndex(SHOT05_CUES, 5.56);
  expect(cut).toBe(charsBefore(4));
});

test("shot05 regression: at t=7.54 (语音到'用'字), highlight has crossed into cue 5 'OpenSpec...'", () => {
  // cue 5 = "OpenSpec——用规格驱动" spans 6.82-8.58. At t=7.54 we are
  // (7.54 - 6.82)/(8.58 - 6.82) = 0.409 through it. Cue 5 text length is 15
  // → floor(15 × 0.409) = 6 chars of cue 5 visible.
  const cue5 = SHOT05_CUES[5]!;
  const ratio = (7.54 - cue5.start) / (cue5.end - cue5.start);
  const expected = charsBefore(5) + Math.floor(cue5.text.length * ratio);
  expect(computeCutIndex(SHOT05_CUES, 7.54)).toBe(expected);
  // Sanity: definitely past GitHub (cue 3 end at 5.56) and past Spec-Kit (cue 4).
  expect(computeCutIndex(SHOT05_CUES, 7.54)).toBeGreaterThan(charsBefore(5));
});

test("shot05 regression: old 'uniform slice' algorithm would be wrong at t=5.56", () => {
  // This test documents the bug the refactor fixes. Under the old algorithm:
  //   totalChars = sum of all cue lengths, durationS = 10.02 (end of last cue)
  //   pct = 5.56 / 10.02 = 0.555
  //   cut_old = floor(totalChars × pct)
  // which cuts at a char index significantly behind the correct one at
  // GitHub's end. We assert the cues-based cut is materially further.
  const totalChars = SHOT05_CUES.reduce((s, c) => s + c.text.length, 0);
  const durationS = SHOT05_CUES[SHOT05_CUES.length - 1]!.end;
  const cut_old = Math.floor(totalChars * (5.56 / durationS));
  const cut_new = computeCutIndex(SHOT05_CUES, 5.56);
  // The cue-based algorithm must highlight *more* characters at t=5.56 than
  // the uniform-slice would (that was the "subtitles lag audio" symptom).
  // Empirically this chunk drifts by ~4 chars, which in practice spans the
  // middle-to-end of the "GitHub" word — exactly matching the user report
  // "字幕到 GitHub 时语音已经到了用规格驱动".
  expect(cut_new).toBeGreaterThan(cut_old);
  expect(cut_new - cut_old).toBeGreaterThanOrEqual(3);
});

// ----------------------------------------------------------------------------
// charTime — click-to-seek inverse mapping
// ----------------------------------------------------------------------------

test("charTime returns the temporal midpoint of a character", () => {
  const cues: SubtitleCue[] = [{ start: 0, end: 10, text: "0123456789" }];
  // Char 0: (0 + 0.5) / 10 × 10 = 0.5
  expect(charTime(cues, 0)).toBeCloseTo(0.5, 5);
  // Char 5: 5.5
  expect(charTime(cues, 5)).toBeCloseTo(5.5, 5);
});

test("charTime maps indices across multiple cues", () => {
  const cues: SubtitleCue[] = [
    { start: 0, end: 2, text: "ab" }, // chars 0,1
    { start: 5, end: 7, text: "cd" }, // chars 2,3
  ];
  // Char 2 is first char of cue 2. midpoint at 5 + 0.5/2 × 2 = 5.5
  expect(charTime(cues, 2)).toBeCloseTo(5.5, 5);
});

test("charTime snaps to last cue end for out-of-range indices", () => {
  const cues: SubtitleCue[] = [{ start: 0, end: 2, text: "ab" }];
  expect(charTime(cues, 99)).toBe(2);
});

// ----------------------------------------------------------------------------
// extractSubtitleCues — runtime shape validation
// ----------------------------------------------------------------------------

test("extractSubtitleCues parses valid metadata", () => {
  const meta = {
    subtitle_cues: [
      { start: 0, end: 1, text: "a" },
      { start: 1, end: 2, text: "b" },
    ],
  };
  expect(extractSubtitleCues(meta)).toEqual([
    { start: 0, end: 1, text: "a" },
    { start: 1, end: 2, text: "b" },
  ]);
});

test("extractSubtitleCues returns undefined on missing / bad shape", () => {
  expect(extractSubtitleCues(null)).toBeUndefined();
  expect(extractSubtitleCues({})).toBeUndefined();
  expect(extractSubtitleCues({ subtitle_cues: "not an array" })).toBeUndefined();
  expect(extractSubtitleCues({ subtitle_cues: [] })).toBeUndefined();
  expect(
    extractSubtitleCues({ subtitle_cues: [{ start: "NaN", end: 1, text: "a" }] }),
  ).toBeUndefined();
  expect(
    extractSubtitleCues({ subtitle_cues: [{ start: 0, end: 1 }] }),
  ).toBeUndefined(); // missing text
});
