"use client";

import { useCallback, useState, type ReactNode } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface Props {
  episodeId: string;
  config: Record<string, unknown>;
  onConfigSaved?: () => void;
  onUpdateConfig: (epId: string, config: Record<string, unknown>) => Promise<void>;
}

// ---------------------------------------------------------------------------
// Form types
// ---------------------------------------------------------------------------

interface FormState {
  model: string;
  temperature: string;
  top_p: string;
  speed: string;
  reference_id: string;
}

const DEFAULTS: FormState = { model: "s2-pro", temperature: "0.7", top_p: "0.7", speed: "1.15", reference_id: "" };

function configToForm(config: Record<string, unknown>): FormState {
  return {
    model: String(config.model ?? DEFAULTS.model),
    temperature: String(config.temperature ?? DEFAULTS.temperature),
    top_p: String(config.top_p ?? DEFAULTS.top_p),
    speed: String(config.speed ?? DEFAULTS.speed),
    reference_id: String(config.reference_id ?? DEFAULTS.reference_id),
  };
}

function formToConfig(form: FormState): Record<string, unknown> {
  return {
    model: form.model,
    temperature: parseFloat(form.temperature) || 0.7,
    top_p: parseFloat(form.top_p) || 0.7,
    speed: parseFloat(form.speed) || 1.15,
    reference_id: form.reference_id || undefined,
  };
}

// ---------------------------------------------------------------------------
// HelpTip (shadcn Tooltip wrapper)
// ---------------------------------------------------------------------------

function HelpTip({ children }: { children: ReactNode }) {
  return (
    <TooltipProvider delayDuration={200}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="inline-flex items-center justify-center w-3.5 h-3.5 rounded-full border border-neutral-300 text-neutral-400 text-[9px] font-bold cursor-help hover:border-neutral-600 hover:text-neutral-600">?</span>
        </TooltipTrigger>
        <TooltipContent side="right">{children}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

// ---------------------------------------------------------------------------
// Config Bar (one-line summary + edit button)
// ---------------------------------------------------------------------------

export function TtsConfigBar({ episodeId, config, onConfigSaved, onUpdateConfig }: Props) {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [savedHint, setSavedHint] = useState(false);

  const hasOverride = Object.keys(config).length > 0;

  const field = (key: string, value: string) => (
    <span className="inline-flex items-center gap-1">
      <span className="text-neutral-400 dark:text-neutral-500">{key}=</span>
      <span className={`font-mono ${hasOverride ? "text-blue-600 dark:text-blue-400" : "text-neutral-600 dark:text-neutral-400"}`}>{value}</span>
    </span>
  );

  return (
    <>
      <div className="px-6 py-1.5 border-b border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800 text-[11px] flex items-center gap-4 flex-wrap">
        <span className="text-neutral-500 dark:text-neutral-400 font-semibold shrink-0">TTS Config:</span>
        {field("model", String(config.model ?? "s2-pro"))}
        {field("temperature", String(config.temperature ?? "0.7"))}
        {field("top_p", String(config.top_p ?? "0.7"))}
        {field("speed", `${config.speed ?? 1.15}x`)}
        {field("reference_id", String(config.reference_id || "(none)"))}
        <button type="button" onClick={() => setDialogOpen(true)}
          className="ml-auto px-2 py-0.5 text-[11px] rounded border border-neutral-300 dark:border-neutral-600 text-neutral-600 dark:text-neutral-400 hover:bg-white dark:hover:bg-neutral-700 hover:border-neutral-400 dark:hover:border-neutral-500"
          title="编辑 TTS 配置">✎ 编辑</button>
        {hasOverride && <span className="text-[10px] text-blue-600 dark:text-blue-400 font-mono">● override</span>}
      </div>
      {savedHint && (
        <div className="px-6 py-1 border-b border-emerald-200 bg-emerald-50 text-[11px] text-emerald-800 flex items-center gap-2">
          <span>✓ 已保存</span>
          <span className="text-emerald-700">· 点 chunk 的 P2 pill → 仅重跑 P2 验证新配置</span>
        </div>
      )}

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <ConfigForm
            episodeId={episodeId}
            config={config}
            onClose={() => setDialogOpen(false)}
            onSaved={() => {
              setDialogOpen(false);
              setSavedHint(true);
              onConfigSaved?.();
              setTimeout(() => setSavedHint(false), 6000);
            }}
            onUpdateConfig={onUpdateConfig}
          />
        </DialogContent>
      </Dialog>
    </>
  );
}

// ---------------------------------------------------------------------------
// Config Form (inside Dialog — pure UI, action via callback)
// ---------------------------------------------------------------------------

function ConfigForm({
  episodeId, config, onClose, onSaved, onUpdateConfig,
}: {
  episodeId: string;
  config: Record<string, unknown>;
  onClose: () => void;
  onSaved: () => void;
  onUpdateConfig: (epId: string, config: Record<string, unknown>) => Promise<void>;
}) {
  const [form, setForm] = useState<FormState>(configToForm(config));
  const [saving, setSaving] = useState(false);
  const set = (key: keyof FormState, value: string) => setForm((prev) => ({ ...prev, [key]: value }));

  const handleSave = useCallback(async () => {
    setSaving(true);
    try {
      await onUpdateConfig(episodeId, formToConfig(form));
      onSaved();
    } catch (e) {
      alert(`Save failed: ${(e as Error).message}`);
    } finally { setSaving(false); }
  }, [episodeId, form, onSaved, onUpdateConfig]);

  const inputClass = "w-full px-2 py-1.5 text-xs border border-neutral-300 dark:border-neutral-600 rounded font-mono bg-white dark:bg-neutral-800 dark:text-neutral-100 focus:outline-none focus:ring-1 focus:ring-blue-400";

  return (
    <>
      <DialogHeader>
        <DialogTitle>编辑 TTS 配置</DialogTitle>
        <DialogDescription>改配置 → 单 chunk retry 试听 → 满意后批量合成</DialogDescription>
      </DialogHeader>

      <div className="px-5 py-4 space-y-3 text-sm">
        <div>
          <label className="text-xs text-neutral-600 flex items-center gap-1 mb-1">Model <HelpTip>Fish Audio TTS 模型。s2-pro 质量更高（推荐），s1 速度更快但质量略低。</HelpTip></label>
          <select value={form.model} onChange={(e) => set("model", e.target.value)} className={inputClass}>
            <option value="s2-pro">s2-pro</option>
            <option value="s2">s2</option>
          </select>
        </div>
        <div>
          <label className="text-xs text-neutral-600 flex items-center gap-1 mb-1">Temperature <HelpTip>控制表现力。值越高变化越丰富，越低越一致稳定。范围 0-1，默认 0.7。英文发音不准时降到 0.3-0.5 可显著改善。</HelpTip></label>
          <input type="number" step="0.1" min="0" max="2" value={form.temperature} onChange={(e) => set("temperature", e.target.value)} className={inputClass} />
        </div>
        <div>
          <label className="text-xs text-neutral-600 flex items-center gap-1 mb-1">Top P <HelpTip>核采样控制多样性。与 temperature 配合，范围 0-1，默认 0.7。英文发音不准时和 temperature 一起降到 0.5，减少随机性。</HelpTip></label>
          <input type="number" step="0.1" min="0" max="1" value={form.top_p} onChange={(e) => set("top_p", e.target.value)} className={inputClass} />
        </div>
        <div>
          <label className="text-xs text-neutral-600 flex items-center gap-1 mb-1">Speed <HelpTip>语速倍率（prosody.speed）。1.0 = 正常速度，&gt;1 加速，&lt;1 减速。范围 0.5-2.0，默认 1.0。</HelpTip></label>
          <input type="number" step="0.05" min="0.5" max="2" value={form.speed} onChange={(e) => set("speed", e.target.value)} className={inputClass} />
        </div>
        <div>
          <label className="text-xs text-neutral-600 flex items-center gap-1 mb-1">Reference ID <HelpTip>Fish Audio 声音模型 ID。指向预置声音或自定义克隆模型。留空使用默认声音。在 fish.audio/discovery 获取。</HelpTip></label>
          <input type="text" value={form.reference_id} onChange={(e) => set("reference_id", e.target.value)} className={inputClass} placeholder="留空使用默认声音" />
        </div>
      </div>

      <DialogFooter>
        <button type="button" onClick={onClose} className="px-3 py-1.5 text-xs text-neutral-600 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800 rounded">取消</button>
        <button type="button" onClick={handleSave} disabled={saving}
          className={`ml-auto px-4 py-1.5 text-xs rounded ${saving ? "bg-neutral-200 dark:bg-neutral-700 text-neutral-400" : "bg-neutral-900 dark:bg-white text-white dark:text-neutral-900 hover:bg-neutral-800 dark:hover:bg-neutral-200"}`}>
          {saving ? "保存中..." : "保存配置"}
        </button>
      </DialogFooter>
    </>
  );
}
