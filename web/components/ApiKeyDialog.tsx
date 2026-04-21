"use client";

import { useState, useEffect } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { getApiUrl } from "@/lib/api-client";

type VerifyStatus = "idle" | "testing" | "ok" | "fail";

interface Props {
  open: boolean;
  onClose: () => void;
}

interface KeysStatus {
  fish: boolean;
  groq: boolean;
  error?: string | null;
}

const API = getApiUrl();

// NOTE: /keys endpoints are NOT in the generated OpenAPI schema
// (web/lib/gen/openapi.d.ts), so we keep hand-written fetch here.
// When the backend schema exports /keys, migrate to `api.GET/POST/DELETE`.

interface SaveKeysBody {
  fish_key?: string;
  groq_key?: string;
}

async function parseKeysStatus(res: Response): Promise<KeysStatus> {
  if (!res.ok) {
    throw new Error(`keys request failed: ${res.status} ${res.statusText}`);
  }
  const body = (await res.json()) as Partial<KeysStatus>;
  return {
    fish: Boolean(body.fish),
    groq: Boolean(body.groq),
    error: body.error ?? null,
  };
}

async function fetchStatus(): Promise<KeysStatus> {
  const res = await fetch(`${API}/keys/status`, { credentials: "include" });
  return parseKeysStatus(res);
}

async function saveKeys(body: SaveKeysBody): Promise<KeysStatus> {
  const res = await fetch(`${API}/keys`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    credentials: "include",
  });
  return parseKeysStatus(res);
}

async function clearKeys(): Promise<KeysStatus> {
  const res = await fetch(`${API}/keys`, {
    method: "DELETE",
    credentials: "include",
  });
  return parseKeysStatus(res);
}

export function ApiKeyDialog({ open, onClose }: Props) {
  const [fishKey, setFishKey] = useState("");
  const [fishConfigured, setFishConfigured] = useState(false);
  const [fishStatus, setFishStatus] = useState<VerifyStatus>("idle");

  const [groqKey, setGroqKey] = useState("");
  const [groqConfigured, setGroqConfigured] = useState(false);
  const [groqStatus, setGroqStatus] = useState<VerifyStatus>("idle");

  useEffect(() => {
    if (open) {
      setFishKey("");
      setFishStatus("idle");
      setGroqKey("");
      setGroqStatus("idle");
      fetchStatus()
        .then((s) => {
          setFishConfigured(s.fish);
          setGroqConfigured(s.groq);
        })
        .catch((e) => {
          // Don't silently swallow — at minimum surface in console so a
          // failing /keys/status request is debuggable.
          console.warn("fetchStatus failed", e);
        });
    }
  }, [open]);

  const handleSaveFish = async () => {
    const trimmed = fishKey.trim();
    if (!trimmed) return;
    setFishStatus("testing");
    try {
      const s = await saveKeys({ fish_key: trimmed });
      if (s.fish && !s.error) {
        setFishConfigured(true);
        setFishKey("");
        setFishStatus("ok");
      } else {
        setFishStatus("fail");
      }
    } catch (e) {
      console.warn("saveKeys(fish) failed", e);
      setFishStatus("fail");
    }
  };

  const handleSaveGroq = async () => {
    const trimmed = groqKey.trim();
    if (!trimmed) return;
    setGroqStatus("testing");
    try {
      const s = await saveKeys({ groq_key: trimmed });
      if (s.groq && !s.error) {
        setGroqConfigured(true);
        setGroqKey("");
        setGroqStatus("ok");
      } else {
        setGroqStatus("fail");
      }
    } catch (e) {
      console.warn("saveKeys(groq) failed", e);
      setGroqStatus("fail");
    }
  };

  const handleClearAll = async () => {
    try {
      await clearKeys();
    } catch (e) {
      console.warn("clearKeys failed", e);
    }
    setFishConfigured(false);
    setGroqConfigured(false);
    setFishKey("");
    setGroqKey("");
    setFishStatus("idle");
    setGroqStatus("idle");
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-sm" onPointerDownOutside={(e) => e.preventDefault()}>
        <DialogHeader>
          <DialogTitle>API Keys</DialogTitle>
          <DialogDescription>
            Key 通过加密 Cookie 存储在服务端，不会明文传输或记录日志。建议使用专用测试 Key，用完后及时更换。
          </DialogDescription>
        </DialogHeader>

        <div className="px-5 py-4 space-y-6">
          <KeySection
            title="Fish Audio API Key"
            description={<>用于 TTS 语音合成（P2 阶段）。<strong className="text-neutral-700 dark:text-neutral-300">必填</strong>，否则无法合成音频。</>}
            inputId="fish-api-key-input"
            placeholder="粘贴 API Key"
            value={fishKey}
            onChange={setFishKey}
            configured={fishConfigured}
            status={fishStatus}
            onSave={handleSaveFish}
            onClear={handleClearAll}
            link={{ href: "https://fish.audio/zh-CN/go-api/api-keys", label: "fish.audio 获取 API Key" }}
          />

          <div className="border-t border-neutral-200 dark:border-neutral-700" />

          <KeySection
            title="Groq API Key"
            description={<>用于 ASR 语音转写（P2v 阶段）。<strong className="text-neutral-700 dark:text-neutral-300">必填</strong>，否则无法验证发音质量和生成字幕时间戳。免费额度足够日常使用。</>}
            inputId="groq-api-key-input"
            placeholder="粘贴 API Key"
            value={groqKey}
            onChange={setGroqKey}
            configured={groqConfigured}
            status={groqStatus}
            onSave={handleSaveGroq}
            onClear={handleClearAll}
            link={{ href: "https://console.groq.com/keys", label: "console.groq.com 获取 API Key" }}
          />
        </div>

        <DialogFooter>
          <div className="flex-1" />
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 text-sm rounded hover:bg-neutral-100 dark:hover:bg-neutral-800"
          >
            关闭
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function StatusBadge({ status }: { status: VerifyStatus }) {
  if (status === "testing") return <span className="text-xs text-blue-500">验证中...</span>;
  if (status === "ok") return <span className="text-xs text-emerald-600 dark:text-emerald-400">有效</span>;
  if (status === "fail") return <span className="text-xs text-red-600 dark:text-red-400">无效，请检查 Key</span>;
  return null;
}

function KeySection({
  title, description, inputId, placeholder, value, onChange, configured, status, onSave, onClear, link,
}: {
  title: string;
  description: React.ReactNode;
  inputId: string;
  placeholder: string;
  value: string;
  onChange: (v: string) => void;
  configured: boolean;
  status: VerifyStatus;
  onSave: () => void;
  onClear: () => void;
  link: { href: string; label: string };
}) {
  const testing = status === "testing";
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="space-y-2">
      <h3 className="text-sm font-medium text-neutral-900 dark:text-neutral-100">{title}</h3>

      {configured ? (
        <div className="flex items-center gap-2 text-xs">
          <span className="text-emerald-600 dark:text-emerald-400">已配置 ✓</span>
          <StatusBadge status={status} />
          <button
            type="button"
            onClick={() => setExpanded(!expanded)}
            className="ml-auto text-neutral-500 dark:text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-200"
          >
            {expanded ? "收起" : "替换"}
          </button>
          <button
            type="button"
            onClick={onClear}
            disabled={testing}
            className="text-red-500 dark:text-red-400 hover:text-red-700 dark:hover:text-red-300 disabled:opacity-50"
          >
            清除
          </button>
        </div>
      ) : (
        <p className="text-[11px] text-neutral-500 dark:text-neutral-400 leading-relaxed">{description}</p>
      )}

      {(!configured || expanded) && (
        <div className="space-y-1.5">
          <div className="flex gap-2">
            <input
              id={inputId}
              type="text"
              value={value}
              onChange={(e) => { onChange(e.target.value); }}
              placeholder={placeholder}
              autoComplete="off"
              data-1p-ignore
              data-lpignore="true"
              data-form-type="other"
              className="flex-1 px-3 py-2 text-sm rounded border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 text-neutral-900 dark:text-neutral-100 placeholder-neutral-400 focus:outline-none focus:ring-2 focus:ring-neutral-400 dark:focus:ring-neutral-500"
              onKeyDown={(e) => { if (e.key === "Enter" && value.trim() && !testing) onSave(); }}
            />
            <button
              type="button"
              onClick={onSave}
              disabled={!value.trim() || testing}
              className="px-3 py-2 text-sm bg-neutral-900 dark:bg-white text-white dark:text-neutral-900 rounded hover:bg-neutral-800 dark:hover:bg-neutral-200 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {testing ? "验证..." : "保存"}
            </button>
          </div>
          {status === "fail" && (
            <p className="text-xs text-red-600 dark:text-red-400">Key 无效，请检查后重试</p>
          )}
          <a href={link.href} target="_blank" rel="noopener noreferrer" className="text-xs text-blue-600 dark:text-blue-400 hover:underline inline-block">
            {link.label} &rarr;
          </a>
        </div>
      )}
    </div>
  );
}
