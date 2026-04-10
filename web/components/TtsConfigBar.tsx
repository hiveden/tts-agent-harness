"use client";

import { useCallback, useEffect, useState } from "react";
import { updateConfig } from "@/lib/hooks";

interface Props {
  episodeId: string;
  config: Record<string, unknown>;
  onConfigSaved?: () => void;
}

const FIELDS = [
  { key: "temperature", label: "Temperature", type: "number", step: 0.1, min: 0, max: 2, default: 0.7 },
  { key: "top_p", label: "Top P", type: "number", step: 0.1, min: 0, max: 1, default: 0.7 },
  { key: "speed", label: "Speed", type: "number", step: 0.05, min: 0.5, max: 2, default: 1.15 },
  { key: "reference_id", label: "Reference ID", type: "text", default: "" },
  { key: "model", label: "Model", type: "text", default: "s2-pro" },
] as const;

/**
 * Lightweight TTS config editor (D-01).
 * Reads/writes episode.config via PUT /episodes/{id}/config.
 */
export function TtsConfigBar({ episodeId, config, onConfigSaved }: Props) {
  const [draft, setDraft] = useState<Record<string, unknown>>(config);
  const [saving, setSaving] = useState(false);
  const [collapsed, setCollapsed] = useState(true);

  useEffect(() => { setDraft(config); }, [config]);

  const dirty = JSON.stringify(draft) !== JSON.stringify(config);

  const handleSave = useCallback(async () => {
    setSaving(true);
    try {
      await updateConfig(episodeId, draft);
      onConfigSaved?.();
    } catch (e) {
      alert(`Config save failed: ${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  }, [episodeId, draft, onConfigSaved]);

  return (
    <div className="border-b border-neutral-100 bg-neutral-50 shrink-0">
      <button
        type="button"
        onClick={() => setCollapsed(!collapsed)}
        className="w-full px-6 py-1.5 flex items-center gap-2 text-[10px] text-neutral-500 uppercase tracking-wide hover:bg-neutral-100"
      >
        <span>{collapsed ? "▸" : "▾"}</span>
        <span>TTS Config</span>
        {dirty && <span className="text-amber-600 font-semibold ml-1">● 未保存</span>}
      </button>

      {!collapsed && (
        <div className="px-6 pb-3 pt-1">
          <div className="grid grid-cols-5 gap-3">
            {FIELDS.map((f) => (
              <div key={f.key}>
                <label className="text-[10px] text-neutral-500 block mb-0.5">{f.label}</label>
                <input
                  type={f.type}
                  step={f.type === "number" ? f.step : undefined}
                  min={f.type === "number" ? f.min : undefined}
                  max={f.type === "number" ? f.max : undefined}
                  value={(draft[f.key] as string | number) ?? f.default}
                  onChange={(e) =>
                    setDraft((prev) => ({
                      ...prev,
                      [f.key]: f.type === "number" ? parseFloat(e.target.value) || 0 : e.target.value,
                    }))
                  }
                  className="w-full px-2 py-1 text-xs border border-neutral-300 rounded font-mono focus:outline-none focus:ring-1 focus:ring-neutral-400"
                />
              </div>
            ))}
          </div>
          <div className="flex items-center gap-2 mt-2">
            <button
              type="button"
              onClick={handleSave}
              disabled={!dirty || saving}
              className={`px-3 py-1 text-xs rounded ${
                dirty && !saving
                  ? "bg-neutral-900 text-white hover:bg-neutral-800"
                  : "bg-neutral-200 text-neutral-400 cursor-not-allowed"
              }`}
            >
              {saving ? "Saving..." : "Save Config"}
            </button>
            {dirty && (
              <button
                type="button"
                onClick={() => setDraft(config)}
                className="text-xs text-neutral-500 hover:text-neutral-700"
              >
                Reset
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
