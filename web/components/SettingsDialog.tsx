"use client";

import { useEffect, useState } from "react";

interface Props {
  open: boolean;
  onClose: () => void;
}

interface HarnessConfigResponse {
  config: {
    p2?: { concurrency?: number };
    p3?: { workers?: number; auto_workers?: boolean };
    [k: string]: unknown;
  };
  system: { cores: number; ramGB: number };
  recommended: { p3Workers: number };
}

export function SettingsDialog({ open, onClose }: Props) {
  const [data, setData] = useState<HarnessConfigResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // 本地表单状态(未保存)
  const [p3Workers, setP3Workers] = useState(1);
  const [p3Auto, setP3Auto] = useState(false);

  const refetch = async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await fetch("/api/harness-config");
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = (await r.json()) as HarnessConfigResponse;
      setData(d);
      setP3Workers(Number(d.config.p3?.workers ?? 1));
      setP3Auto(Boolean(d.config.p3?.auto_workers ?? false));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open) void refetch();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const save = async () => {
    if (!data) return;
    setSaving(true);
    setError(null);
    try {
      const r = await fetch("/api/harness-config", {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          patch: {
            p3: {
              workers: p3Workers,
              auto_workers: p3Auto,
            },
          },
        }),
      });
      if (!r.ok) {
        const text = await r.text();
        throw new Error(text || `HTTP ${r.status}`);
      }
      const d = (await r.json()) as HarnessConfigResponse;
      setData(d);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const hasChanges =
    data != null &&
    (p3Workers !== (data.config.p3?.workers ?? 1) ||
      p3Auto !== (data.config.p3?.auto_workers ?? false));

  return (
    <div
      className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="bg-white dark:bg-neutral-900 rounded-lg shadow-2xl dark:shadow-neutral-900 w-full max-w-lg flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="px-5 py-3 border-b border-neutral-200 dark:border-neutral-700 flex items-center">
          <span className="text-lg mr-2">⚙</span>
          <h2 className="font-semibold text-sm flex-1">Harness Settings</h2>
          <button
            type="button"
            onClick={onClose}
            className="text-neutral-400 hover:text-neutral-900 dark:hover:text-neutral-100 text-lg leading-none"
            aria-label="关闭"
          >
            ✕
          </button>
        </div>

        {/* Body */}
        <div className="px-5 py-4 space-y-5 text-sm">
          {loading && !data ? (
            <div className="text-neutral-400 text-xs">加载配置…</div>
          ) : error && !data ? (
            <div className="text-red-600 text-xs">加载失败: {error}</div>
          ) : data ? (
            <>
              {/* System info */}
              <div className="bg-neutral-50 dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-700 rounded p-3 text-xs">
                <div className="font-semibold text-neutral-700 dark:text-neutral-300 mb-1">
                  本机硬件
                </div>
                <div className="text-neutral-600 dark:text-neutral-400 font-mono">
                  {data.system.cores} cores · {data.system.ramGB} GB RAM
                </div>
                <div className="text-neutral-500 mt-1">
                  推荐 P3 worker 上限:{" "}
                  <span className="font-mono font-semibold">
                    {data.recommended.p3Workers}
                  </span>
                  <span className="text-neutral-400">
                    {" "}
                    (基于 cores/4 和 ram/4 取保守最小值)
                  </span>
                </div>
              </div>

              {/* P3 workers */}
              <div>
                <div className="flex items-baseline mb-2">
                  <label className="text-xs font-semibold text-neutral-700">
                    P3 Workers
                  </label>
                  <span className="ml-2 text-[10px] text-neutral-400 font-mono">
                    WhisperX 并发转写
                  </span>
                  <span className="ml-auto text-xs font-mono text-neutral-900">
                    {p3Workers}
                  </span>
                </div>

                <input
                  type="range"
                  min={1}
                  max={data.recommended.p3Workers}
                  step={1}
                  value={p3Workers}
                  onChange={(e) => setP3Workers(Number(e.target.value))}
                  disabled={p3Auto}
                  className="w-full disabled:opacity-40 disabled:cursor-not-allowed"
                />
                <div className="flex justify-between text-[10px] text-neutral-400 font-mono mt-0.5">
                  <span>1</span>
                  <span>{data.recommended.p3Workers}</span>
                </div>

                <div className="mt-2 space-y-1 text-[11px] text-neutral-600">
                  <div>
                    <span className="font-mono">1</span>:{" "}
                    单进程串行(~100s / 10 chunks)· 内存 3-4GB
                  </div>
                  <div>
                    <span className="font-mono">2</span>:{" "}
                    ≈1.7x 加速 · 内存 6-8GB
                  </div>
                  <div>
                    <span className="font-mono">3</span>:{" "}
                    ≈2.3x 加速 · 内存 9-12GB · 推荐上限
                  </div>
                </div>

                <label className="mt-3 flex items-center gap-2 text-xs text-neutral-700">
                  <input
                    type="checkbox"
                    checked={p3Auto}
                    onChange={(e) => setP3Auto(e.target.checked)}
                  />
                  <span>自动推算</span>
                  <span className="text-neutral-400">
                    (运行时按硬件动态计算,覆盖上面的手动值)
                  </span>
                </label>
              </div>

              {error ? (
                <div className="text-xs text-red-600 bg-red-50 border border-red-200 rounded px-2 py-1.5">
                  {error}
                </div>
              ) : null}

              <div className="text-[10px] text-neutral-400 dark:text-neutral-500 border-t border-neutral-100 dark:border-neutral-700 pt-3">
                配置改动立即生效,下次运行 P3 时起使用新值。
                不会中断当前正在运行的 pipeline。
              </div>
            </>
          ) : null}
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-neutral-200 dark:border-neutral-700 flex items-center gap-2">
          <span className="text-[10px] text-neutral-400 dark:text-neutral-500">
            {hasChanges ? "有未保存改动" : "已保存"}
          </span>
          <div className="ml-auto flex gap-2">
            <button
              type="button"
              onClick={onClose}
              disabled={saving}
              className="px-3 py-1.5 text-sm rounded hover:bg-neutral-100 dark:hover:bg-neutral-800"
            >
              关闭
            </button>
            <button
              type="button"
              onClick={save}
              disabled={saving || !hasChanges}
              className="px-3 py-1.5 text-sm bg-neutral-900 dark:bg-white text-white dark:text-neutral-900 rounded hover:bg-neutral-800 dark:hover:bg-neutral-200 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {saving ? "保存中…" : "保存"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
