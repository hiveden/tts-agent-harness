"use client";

import { useEffect } from "react";
import { CHUNK_STAGE_ORDER } from "@/lib/types";
import { STAGE_INFO } from "@/lib/stage-info";

interface Props {
  open: boolean;
  onClose: () => void;
}

/**
 * 使用说明 modal。顶部显示 tabs 切换不同文档，默认打开 TTS Config。
 *
 * 内容内联在组件里（MVP）。后续可以从 /docs/*.md 动态加载。
 */
export function HelpDialog({ open, onClose }: Props) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const codeClass = "px-1 py-0.5 bg-neutral-100 dark:bg-neutral-800 rounded text-xs font-mono";

  return (
    <div
      className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="bg-white dark:bg-neutral-900 rounded-lg shadow-2xl dark:shadow-neutral-900 w-full max-w-3xl max-h-[85vh] flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="px-5 py-3 border-b border-neutral-200 dark:border-neutral-700 flex items-center gap-3">
          <span className="text-lg">📖</span>
          <h2 className="font-semibold text-sm flex-1">使用说明</h2>
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
        <div className="flex-1 overflow-y-auto px-6 py-5 text-sm text-neutral-800 dark:text-neutral-200 leading-relaxed">
          <section className="mb-6">
            <h3 className="text-base font-semibold mb-2 text-neutral-900 dark:text-neutral-100">
              Script TTS Config
            </h3>
            <p className="mb-3 text-neutral-600 dark:text-neutral-400">
              每个 script.json 可以携带 <code className={codeClass}>tts_config</code>
              ，覆盖全局默认，让不同稿子使用不同 TTS 参数（声音、温度、语速）而不影响其他 episode。
            </p>

            <h4 className="font-semibold mt-4 mb-1.5">配置优先级</h4>
            <pre className="bg-neutral-50 dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-700 rounded p-2.5 text-xs font-mono mb-3">
{`env var  >  script.tts_config  >  .harness/config.json  >  代码默认`}
            </pre>

            <h4 className="font-semibold mt-4 mb-1.5">Script 示例</h4>
            <pre className="bg-neutral-900 dark:bg-neutral-800 text-neutral-100 rounded p-3 text-xs font-mono overflow-x-auto mb-3">
{`{
  "title": "拒绝自拟合",
  "description": "Alex 的第 42 期",
  "tts_config": {
    "model": "s2-pro",
    "normalize": false,
    "temperature": 0.3,
    "top_p": 0.5,
    "speed": 1.25,
    "reference_id": "7f3a2b..."
  },
  "segments": [
    { "id": 1, "type": "hook", "text": "..." }
  ]
}`}
            </pre>

            <h4 className="font-semibold mt-4 mb-1.5">支持的字段</h4>
            <div className="overflow-x-auto">
              <table className="w-full text-xs border-collapse">
                <thead>
                  <tr className="bg-neutral-50 dark:bg-neutral-800">
                    <th className="text-left px-2 py-1.5 border border-neutral-200 dark:border-neutral-700 font-mono">字段</th>
                    <th className="text-left px-2 py-1.5 border border-neutral-200 dark:border-neutral-700">类型</th>
                    <th className="text-left px-2 py-1.5 border border-neutral-200 dark:border-neutral-700">默认</th>
                    <th className="text-left px-2 py-1.5 border border-neutral-200 dark:border-neutral-700">说明</th>
                  </tr>
                </thead>
                <tbody>
                  {[
                    ["model", "string", "s2-pro", "Fish TTS 模型（s1 / s2-pro）"],
                    ["normalize", "boolean", "false", "让 Fish 引擎自动做文本归一化。英文混合建议 false"],
                    ["temperature", "number", "0.3", "采样温度。低=稳定，高=发音多样"],
                    ["top_p", "number", "0.5", "nucleus sampling 截断"],
                    ["speed", "number", "1.25", "atempo 后处理速度。1.0=原速"],
                    ["reference_id", "string", '""', "声音克隆 ID"],
                    ["concurrency", "number", "6", "并行 API 调用数（仅 .harness/config.json 有效）"],
                  ].map(([field, type, def, desc]) => (
                    <tr key={field}>
                      <td className="px-2 py-1.5 border border-neutral-200 dark:border-neutral-700 font-mono">{field}</td>
                      <td className="px-2 py-1.5 border border-neutral-200 dark:border-neutral-700">{type}</td>
                      <td className="px-2 py-1.5 border border-neutral-200 dark:border-neutral-700 font-mono">{def}</td>
                      <td className="px-2 py-1.5 border border-neutral-200 dark:border-neutral-700">{desc}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <p className="mt-3 text-xs text-neutral-500 dark:text-neutral-400">
              所有字段都是<strong>可选</strong>的，只写想改的。没写的字段会从下一层配置继承。
            </p>

            <h4 className="font-semibold mt-4 mb-1.5">可覆盖的环境变量</h4>
            <ul className="text-xs space-y-1 text-neutral-700 dark:text-neutral-300">
              <li><code className={codeClass}>FISH_TTS_MODEL</code> → <code className="font-mono">model</code></li>
              <li><code className={codeClass}>FISH_TTS_REFERENCE_ID</code> → <code className="font-mono">reference_id</code></li>
              <li><code className={codeClass}>TTS_SPEED</code> → <code className="font-mono">speed</code></li>
            </ul>
            <p className="mt-2 text-xs text-neutral-500 dark:text-neutral-400">
              只有这三个能用 env 临时覆盖；其他参数必须改 config 文件。
            </p>
          </section>

          <section className="mb-6">
            <h3 className="text-base font-semibold mb-2 text-neutral-900 dark:text-neutral-100">
              控制标记
            </h3>
            <p className="mb-2 text-neutral-600 dark:text-neutral-400">
              文本中可以插入 S2-Pro 控制标记，P5 字幕生成时会自动 strip：
            </p>
            <ul className="text-xs space-y-1 text-neutral-700 dark:text-neutral-300">
              <li><code className={codeClass}>[break]</code> / <code className={codeClass}>[long break]</code> — 停顿</li>
              <li><code className={codeClass}>[breath]</code> / <code className={codeClass}>[inhale]</code> — 呼吸声</li>
              <li><code className={codeClass}>[pause]</code> / <code className={codeClass}>[long pause]</code> — 兼容写法</li>
            </ul>
          </section>

          <section>
            <h3 className="text-base font-semibold mb-2 text-neutral-900 dark:text-neutral-100">
              Per-chunk Pipeline
            </h3>
            <p className="mb-2 text-neutral-600 dark:text-neutral-400">
              每个 chunk 行下方的 {CHUNK_STAGE_ORDER.length} 个 pill 表示：
              {CHUNK_STAGE_ORDER.map((stage, i) => {
                const info = STAGE_INFO[stage];
                const label = info.title.split(" · ")[0];
                return (
                  <span key={stage}>
                    <span className="inline-block mx-1 px-1.5 rounded bg-emerald-500 text-white text-[10px] font-mono">{label}</span>
                    ({info.description.split("，")[0]})
                    {i < CHUNK_STAGE_ORDER.length - 1 && " →"}
                  </span>
                );
              })}
            </p>
            <ul className="text-xs space-y-1 text-neutral-700 dark:text-neutral-300 mt-2">
              <li>
                <span className="inline-block w-3 h-3 rounded-full bg-emerald-500 align-middle mr-1" />
                深绿 = 真实事件（trace.jsonl 记录）
              </li>
              <li>
                <span className="inline-block w-3 h-3 rounded-full bg-emerald-200 align-middle mr-1" />
                浅绿 = 从文件推断（历史数据回填）
              </li>
              <li>
                <span className="inline-block w-3 h-3 rounded-full bg-red-500 align-middle mr-1" />
                红色 = 失败（点击查看日志 + Retry）
              </li>
              <li>
                <span className="inline-block w-3 h-3 rounded-full bg-blue-500 align-middle mr-1" />
                蓝色脉冲 = 正在运行
              </li>
              <li>
                <span className="inline-block w-3 h-3 rounded-full bg-neutral-300 dark:bg-neutral-600 align-middle mr-1" />
                灰色 = 未开始
              </li>
            </ul>
            <p className="mt-2 text-xs text-neutral-500 dark:text-neutral-400">
              点击任意 pill 弹出抽屉显示该 stage 的独立日志，支持单独 retry。
            </p>
          </section>
        </div>

        {/* Footer */}
        <div className="px-5 py-2.5 border-t border-neutral-200 dark:border-neutral-700 flex items-center justify-between text-[11px] text-neutral-500 dark:text-neutral-400">
          <span>按 Esc 关闭</span>
          <span>
            详细文档：<code className="font-mono">docs/tts-config.md</code>
          </span>
        </div>
      </div>
    </div>
  );
}
