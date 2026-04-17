import { test, expect } from "@playwright/test";
import { stripControlMarkers } from "../lib/utils";

// ----------------------------------------------------------------------------
// stripControlMarkers — contract mirror of server/core/p5_logic.py
//
// These tests lock the frontend behaviour to the backend's. Test cases here
// are 1:1 copies of server/tests/tasks/test_p5_logic.py::TestStripControlMarkers.
// ----------------------------------------------------------------------------

test("break marker", () => {
  expect(stripControlMarkers("你好 [break] 世界")).toBe("你好 世界");
});

test("long break marker", () => {
  expect(stripControlMarkers("开头 [long break] 结尾")).toBe("开头 结尾");
});

test("breath marker", () => {
  expect(stripControlMarkers("hello [breath] world")).toBe("hello world");
});

test("phoneme marker", () => {
  expect(stripControlMarkers("我喜欢 [^tomato] 番茄")).toBe("我喜欢 番茄");
});

test("mixed markers", () => {
  const raw = "开场 [breath] 中段 [long break] 关键词 [^pronounce] 结尾。";
  expect(stripControlMarkers(raw)).toBe("开场 中段 关键词 结尾。");
});

test("empty input", () => {
  expect(stripControlMarkers("")).toBe("");
  expect(stripControlMarkers("   ")).toBe("");
  expect(stripControlMarkers(null)).toBe("");
  expect(stripControlMarkers(undefined)).toBe("");
});

test("only markers returns empty", () => {
  expect(stripControlMarkers("[break][long break][^foo]")).toBe("");
});

test("preserves internal spacing (trim + collapse)", () => {
  expect(stripControlMarkers("  hello   world  ")).toBe("hello world");
});

// ----------------------------------------------------------------------------
// Contract debt #2: newlines must be preserved. The old frontend impl used
// ``\s+`` which clobbered them. Author-forced cue breaks matter.
// ----------------------------------------------------------------------------

test("preserves literal newlines for author-forced cue breaks", () => {
  expect(stripControlMarkers("第一句\n第二句")).toBe("第一句\n第二句");
});

test("trims whitespace around newlines", () => {
  expect(stripControlMarkers("第一句  \n  第二句")).toBe("第一句\n第二句");
});

test("newline between markers and text survives", () => {
  expect(stripControlMarkers("第一句 [break]\n第二句")).toBe("第一句\n第二句");
});
