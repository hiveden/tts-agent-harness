#!/usr/bin/env python3
"""
AB 测试 — 步骤 2：英文关键词发音验证

流程：音频 → WhisperX 自由转写 → 定位英文关键词区域 → 三路判定：
  1. ASR 转出英文且匹配原词 → 直接通过
  2. ASR 转出英文但不匹配 → 字符串编辑距离
  3. ASR 转出中文谐音 → pypinyin 转拼音 → 与期望拼音比编辑距离

Usage: python3 test/ab-param-test/ab-verify.py --audiodir output/param-ab-test
"""

import argparse
import glob
import json
import os
import re
import sys

import whisperx
from pypinyin import pinyin, Style

DEVICE = "cpu"
LANGUAGE = "zh"
BATCH_SIZE = 8
COMPUTE_TYPE = "int8"

# 原始 tts_text（去掉控制标签后）
ORIGINAL_TEXT = (
    "Mac 跑本地模型，之前一直很尴尬。装了 Ollama，跑个小模型还行，"
    "大一点的慢得受不了，玩两下就吃灰了。"
    "最近我在做一个 RAG 项目，需要大量跑测试，重新研究了一下，发现情况变了。"
)

# 关键词定义：原词 + 期望拼音（TTS 中文发音的拼音表示）
KEYWORDS = {
    "Mac": {
        "expected_pinyin": ["mai", "ke"],  # 麦克
        "context_before": "",  # 句首
        "context_after": "跑本地",
    },
    "Ollama": {
        "expected_pinyin": ["ou", "la", "ma"],  # 欧拉玛
        "context_before": "装了",
        "context_after": "跑个小",
    },
    "RAG": {
        "expected_pinyin": ["rui", "ge"],  # 瑞格 (备选)
        "context_before": "一个",
        "context_after": "项目",
    },
}

# 编辑距离阈值（归一化到 0~1，越小越严格）
PINYIN_THRESHOLD = 0.4  # 拼音距离 / max(len1, len2) < 0.4 视为通过
CHAR_THRESHOLD = 0.34   # 字符距离 / max(len1, len2) < 0.34 视为通过


def levenshtein(s1, s2):
    """编辑距离"""
    if len(s1) < len(s2):
        return levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (c1 != c2)))
        prev = curr
    return prev[-1]


def normalized_distance(s1, s2):
    """归一化编辑距离 (0~1)"""
    max_len = max(len(s1), len(s2))
    if max_len == 0:
        return 0.0
    return levenshtein(s1, s2) / max_len


def to_pinyin_str(text):
    """中文转拼音字符串（去声调，空格分隔）"""
    result = pinyin(text, style=Style.NORMAL)
    return " ".join(p[0] for p in result)


def is_chinese(text):
    """判断文本是否主要是中文"""
    cn = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    return cn > len(text) * 0.5


def extract_keyword_region(transcript, keyword, kw_def):
    """
    在转写文本中定位关键词区域。
    用上下文（前后中文）缩小搜索范围，取上下文之间的片段。
    """
    ctx_before = kw_def.get("context_before", "")
    ctx_after = kw_def.get("context_after", "")

    # 去标点空格做匹配
    clean = re.sub(r"[\s，。、？！,.?!\-]", "", transcript)
    cb = re.sub(r"[\s，。、？！,.?!\-]", "", ctx_before)
    ca = re.sub(r"[\s，。、？！,.?!\-]", "", ctx_after)

    start = 0
    end = len(clean)

    if cb:
        idx = clean.find(cb)
        if idx >= 0:
            start = idx + len(cb)

    if ca:
        idx = clean.find(ca, start)
        if idx >= 0:
            end = idx

    region = clean[start:end].strip()
    return region


def judge_keyword(region, keyword, kw_def):
    """
    三路判定：
    1. 英文且匹配 → pass
    2. 英文不匹配 → char edit distance
    3. 中文 → pinyin edit distance
    """
    if not region:
        return {"method": "missing", "pass": False, "score": 0.0, "region": ""}

    # 路径 1 & 2：ASR 转出英文
    if not is_chinese(region):
        dist = normalized_distance(region.lower(), keyword.lower())
        if dist == 0:
            return {
                "method": "exact_match",
                "pass": True,
                "score": 1.0,
                "region": region,
                "detail": f'"{region}" == "{keyword}"',
            }
        else:
            passed = dist < CHAR_THRESHOLD
            return {
                "method": "char_distance",
                "pass": passed,
                "score": round(1 - dist, 3),
                "region": region,
                "detail": f'"{region}" vs "{keyword}" dist={dist:.2f}',
            }

    # 路径 3：ASR 转出中文 → pypinyin
    region_pinyin = to_pinyin_str(region)
    expected_pinyin = " ".join(kw_def["expected_pinyin"])

    dist = normalized_distance(region_pinyin, expected_pinyin)
    passed = dist < PINYIN_THRESHOLD
    return {
        "method": "pinyin",
        "pass": passed,
        "score": round(1 - dist, 3),
        "region": region,
        "region_pinyin": region_pinyin,
        "expected_pinyin": expected_pinyin,
        "detail": f'"{region}"→[{region_pinyin}] vs [{expected_pinyin}] dist={dist:.2f}',
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--audiodir", required=True)
    args = parser.parse_args()

    if not os.path.isdir(args.audiodir):
        print(f"ERROR: {args.audiodir} not found", file=sys.stderr)
        sys.exit(1)

    # 加载模型
    print("  加载 WhisperX 模型...", flush=True)
    model = whisperx.load_model(
        "large-v3", device=DEVICE, compute_type=COMPUTE_TYPE, language=LANGUAGE
    )
    print("  模型就绪。\n", flush=True)

    groups = sorted(
        d for d in os.listdir(args.audiodir)
        if os.path.isdir(os.path.join(args.audiodir, d))
    )

    all_results = []

    print("============================================")
    print(" AB 测试 — 英文关键词发音验证")
    print("============================================")
    print(f"关键词: {', '.join(KEYWORDS.keys())}")
    print(f"判定方式: 英文→字符距离(<{CHAR_THRESHOLD}) | 中文→拼音距离(<{PINYIN_THRESHOLD})")
    print()

    for group in groups:
        group_dir = os.path.join(args.audiodir, group)
        wavs = sorted(glob.glob(os.path.join(group_dir, "run*.wav")))
        if not wavs:
            continue

        print(f"--- 组 {group} ---")

        for wav_path in wavs:
            run_name = os.path.splitext(os.path.basename(wav_path))[0]
            print(f"  {run_name}: ", end="", flush=True)

            try:
                audio = whisperx.load_audio(wav_path)
                result = model.transcribe(audio, batch_size=BATCH_SIZE, language=LANGUAGE)
                transcript = "".join(seg["text"] for seg in result.get("segments", []))

                parts = []
                run_result = {"group": group, "run": run_name, "transcript": transcript, "keywords": {}}

                for kw, kw_def in KEYWORDS.items():
                    region = extract_keyword_region(transcript, kw, kw_def)
                    judgement = judge_keyword(region, kw, kw_def)
                    run_result["keywords"][kw] = judgement

                    status = "✓" if judgement["pass"] else "✗"
                    parts.append(f'{kw}={status}{judgement["score"]:.2f}({judgement["method"]}) "{region}"')

                print("  ".join(parts))
                all_results.append(run_result)

            except Exception as e:
                print(f"ERROR: {e}")
                all_results.append({"group": group, "run": run_name, "error": str(e)})

        print()

    # --- 汇总 ---
    print("============================================")
    print(" 汇总")
    print("============================================")
    print()

    # 按关键词汇总
    for kw in KEYWORDS:
        print(f"关键词: {kw}")
        print("-" * 60)
        total = passed = 0
        scores = []
        methods = {}
        for r in all_results:
            if "error" in r:
                continue
            j = r["keywords"].get(kw, {})
            total += 1
            if j.get("pass"):
                passed += 1
            if "score" in j:
                scores.append(j["score"])
            m = j.get("method", "unknown")
            methods[m] = methods.get(m, 0) + 1

        avg_score = sum(scores) / len(scores) if scores else 0
        print(f"  通过率: {passed}/{total} ({passed/total*100:.0f}%)")
        print(f"  平均分: {avg_score:.3f}  range=[{min(scores):.3f}, {max(scores):.3f}]")
        print(f"  判定路径: {methods}")
        print()

    # 按组汇总（哪组最准）
    print("============================================")
    print(" 各组综合得分（哪组参数最准）")
    print("============================================")
    print()

    group_scores = {}
    for r in all_results:
        if "error" in r:
            continue
        g = r["group"]
        if g not in group_scores:
            group_scores[g] = {"scores": [], "passed": 0, "total": 0}
        for kw, j in r["keywords"].items():
            group_scores[g]["total"] += 1
            if j.get("pass"):
                group_scores[g]["passed"] += 1
            if "score" in j:
                group_scores[g]["scores"].append(j["score"])

    ranked = sorted(group_scores.items(), key=lambda x: sum(x[1]["scores"]) / len(x[1]["scores"]) if x[1]["scores"] else 0, reverse=True)

    for rank, (g, gs) in enumerate(ranked, 1):
        avg = sum(gs["scores"]) / len(gs["scores"]) if gs["scores"] else 0
        print(f"  #{rank} {g}: avg={avg:.3f}  通过={gs['passed']}/{gs['total']}")

    # 保存
    out_json = os.path.join(args.audiodir, "verify-results.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n详细结果: {out_json}")


if __name__ == "__main__":
    main()
