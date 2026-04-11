"use client";

import type { EpisodeStatus } from "@/lib/types";

interface Props {
  status: EpisodeStatus;
  running: boolean;
  currentStage: string | null;
  totalChunks: number;
  /** run.log 末尾一行,用于 failed 状态展示原因 */
  lastLogLine?: string;
}

/**
 * 状态进度条:在 EpisodeHeader 下方显示当前 episode 的运行情况。
 * 不同状态下展示不同信息和颜色:
 *   ready    → 灰  · "未运行"
 *   running  → 蓝  · "P3 12/18" + 进度条动画
 *   failed   → 红  · "失败:<日志末尾>"
 *   done     → 绿  · "✓ N chunks 已生成"
 *   empty    → 隐藏
 */
export function StageProgress({
  status,
  running,
  currentStage,
  totalChunks,
  lastLogLine,
}: Props) {
  if (status === "empty") return null;

  // 解析 currentStage 形如 "P3 12/18" / "P5/P6" / "P2 (3)"
  let stageName: string | null = null;
  let progressDone: number | null = null;
  let progressTotal: number | null = null;
  if (currentStage) {
    const m = currentStage.match(/^([\w/.]+)(?:\s+(\d+)\/(\d+))?/);
    if (m) {
      stageName = m[1];
      if (m[2] && m[3]) {
        progressDone = parseInt(m[2], 10);
        progressTotal = parseInt(m[3], 10);
      }
    } else {
      stageName = currentStage;
    }
  }

  const pct =
    progressDone != null && progressTotal != null && progressTotal > 0
      ? (progressDone / progressTotal) * 100
      : null;

  // 颜色 / 文本
  let bg = "bg-neutral-50";
  let border = "border-neutral-200";
  let icon = "○";
  let iconColor = "text-neutral-400";
  let mainText = "未运行";
  let detailText: string | null = null;
  let barColor = "bg-neutral-300";
  let indeterminate = false;

  if (running || status === "running") {
    bg = "bg-blue-50";
    border = "border-blue-200";
    icon = "⏵";
    iconColor = "text-blue-600 animate-pulse";
    mainText = stageName ? `Stage ${stageName}` : "Pipeline 进行中";
    if (progressDone != null && progressTotal != null) {
      detailText = `${progressDone} / ${progressTotal}`;
    } else {
      detailText = "等待 stage 启动...";
    }
    barColor = "bg-blue-500";
    indeterminate = pct == null;
  } else if (status === "failed") {
    bg = "bg-red-50";
    border = "border-red-200";
    icon = "✗";
    iconColor = "text-red-600";
    mainText = stageName
      ? `失败 (上次跑到 ${stageName})`
      : "失败";
    detailText = lastLogLine?.trim() || null;
    barColor = "bg-red-500";
  } else if (status === "done") {
    bg = "bg-emerald-50";
    border = "border-emerald-200";
    icon = "✓";
    iconColor = "text-emerald-600";
    mainText = `Done · ${totalChunks} chunks`;
    detailText = stageName ? `最后阶段 ${stageName}` : null;
    barColor = "bg-emerald-500";
  } else if (status === "ready") {
    icon = "○";
    iconColor = "text-neutral-400";
    mainText = `已切分 · ${totalChunks} chunks`;
    detailText = "点「合成全部」开始 TTS 合成";
  }

  return (
    <div
      className={`px-6 py-2.5 border-b ${border} ${bg} flex items-center gap-3`}
    >
      <span className={`text-lg leading-none ${iconColor}`}>{icon}</span>
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-2">
          <span className="text-sm font-medium text-neutral-900">{mainText}</span>
          {detailText ? (
            <span className="text-xs text-neutral-500 truncate">{detailText}</span>
          ) : null}
        </div>
        {/* 进度条:running 时一定显示,done/failed 也显示一个静态值 */}
        {(running || status === "running") && (
          <div className="mt-1.5 h-1 bg-neutral-200 rounded-full overflow-hidden">
            {indeterminate ? (
              <div className={`h-full ${barColor} animate-pulse`} style={{ width: "30%" }} />
            ) : (
              <div
                className={`h-full ${barColor} transition-all duration-300`}
                style={{ width: `${pct}%` }}
              />
            )}
          </div>
        )}
      </div>
      {pct != null && (running || status === "running") ? (
        <span className="text-xs text-neutral-600 font-mono shrink-0">
          {pct.toFixed(0)}%
        </span>
      ) : null}
    </div>
  );
}
