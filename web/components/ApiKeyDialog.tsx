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

const FISH_STORAGE_KEY = "fish-api-key";
const GROQ_STORAGE_KEY = "groq-api-key";

const FISH_VERIFY_URL = "https://api.fish.audio/wallet/self/api-credit";
const GROQ_VERIFY_URL = "https://api.groq.com/openai/v1/models";

function maskKey(key: string): string {
  if (!key) return "";
  if (key.length <= 8) return "****" + key.slice(-4);
  return "****..." + key.slice(-4);
}

type VerifyStatus = "idle" | "testing" | "ok" | "fail";

async function verifyKey(url: string, key: string): Promise<boolean> {
  try {
    const res = await fetch(url, {
      headers: { Authorization: `Bearer ${key}` },
    });
    return res.ok;
  } catch {
    return false;
  }
}

interface Props {
  open: boolean;
  onClose: () => void;
}

export function ApiKeyDialog({ open, onClose }: Props) {
  const [fishKey, setFishKey] = useState("");
  const [fishSavedMask, setFishSavedMask] = useState("");
  const [fishHasSaved, setFishHasSaved] = useState(false);
  const [fishStatus, setFishStatus] = useState<VerifyStatus>("idle");

  const [groqKey, setGroqKey] = useState("");
  const [groqSavedMask, setGroqSavedMask] = useState("");
  const [groqHasSaved, setGroqHasSaved] = useState(false);
  const [groqStatus, setGroqStatus] = useState<VerifyStatus>("idle");

  useEffect(() => {
    if (open) {
      const storedFish = localStorage.getItem(FISH_STORAGE_KEY) || "";
      setFishSavedMask(maskKey(storedFish));
      setFishHasSaved(!!storedFish);
      setFishKey("");
      setFishStatus("idle");

      const storedGroq = localStorage.getItem(GROQ_STORAGE_KEY) || "";
      setGroqSavedMask(maskKey(storedGroq));
      setGroqHasSaved(!!storedGroq);
      setGroqKey("");
      setGroqStatus("idle");
    }
  }, [open]);

  const handleSaveFish = async () => {
    const trimmed = fishKey.trim();
    if (!trimmed) return;
    setFishStatus("testing");
    const ok = await verifyKey(FISH_VERIFY_URL, trimmed);
    if (ok) {
      localStorage.setItem(FISH_STORAGE_KEY, trimmed);
      setFishSavedMask(maskKey(trimmed));
      setFishHasSaved(true);
      setFishKey("");
      setFishStatus("ok");
    } else {
      setFishStatus("fail");
    }
  };

  const handleClearFish = () => {
    localStorage.removeItem(FISH_STORAGE_KEY);
    setFishSavedMask("");
    setFishHasSaved(false);
    setFishKey("");
    setFishStatus("idle");
  };

  const handleSaveGroq = async () => {
    const trimmed = groqKey.trim();
    if (!trimmed) return;
    setGroqStatus("testing");
    const ok = await verifyKey(GROQ_VERIFY_URL, trimmed);
    if (ok) {
      localStorage.setItem(GROQ_STORAGE_KEY, trimmed);
      setGroqSavedMask(maskKey(trimmed));
      setGroqHasSaved(true);
      setGroqKey("");
      setGroqStatus("ok");
    } else {
      setGroqStatus("fail");
    }
  };

  const handleClearGroq = () => {
    localStorage.removeItem(GROQ_STORAGE_KEY);
    setGroqSavedMask("");
    setGroqHasSaved(false);
    setGroqKey("");
    setGroqStatus("idle");
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-sm" onPointerDownOutside={(e) => e.preventDefault()}>
        <DialogHeader>
          <DialogTitle>API Keys</DialogTitle>
          <DialogDescription>
            Key 仅存储在浏览器 localStorage 中，不会发送到后端数据库。保存时会自动验证有效性。
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
            savedMask={fishSavedMask}
            hasSaved={fishHasSaved}
            status={fishStatus}
            onSave={handleSaveFish}
            onClear={handleClearFish}
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
            savedMask={groqSavedMask}
            hasSaved={groqHasSaved}
            status={groqStatus}
            onSave={handleSaveGroq}
            onClear={handleClearGroq}
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
  title, description, inputId, placeholder, value, onChange, savedMask, hasSaved, status, onSave, onClear, link,
}: {
  title: string;
  description: React.ReactNode;
  inputId: string;
  placeholder: string;
  value: string;
  onChange: (v: string) => void;
  savedMask: string;
  hasSaved: boolean;
  status: VerifyStatus;
  onSave: () => void;
  onClear: () => void;
  link: { href: string; label: string };
}) {
  const testing = status === "testing";
  return (
    <div className="space-y-3">
      <h3 className="text-sm font-medium text-neutral-900 dark:text-neutral-100">{title}</h3>
      <p className="text-[11px] text-neutral-500 dark:text-neutral-400 leading-relaxed">{description}</p>

      {hasSaved && (
        <div className="flex items-center gap-2 text-xs text-neutral-500 dark:text-neutral-400">
          <span>当前 Key: <span className="font-mono">{savedMask}</span></span>
          <StatusBadge status={status} />
        </div>
      )}

      <div className="space-y-1.5">
        <label htmlFor={inputId} className="text-xs font-medium text-neutral-700 dark:text-neutral-300">
          {hasSaved ? "替换 Key" : "输入 API Key"}
        </label>
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
          {hasSaved && (
            <button
              type="button"
              onClick={onClear}
              disabled={testing}
              className="px-3 py-2 text-sm rounded text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 disabled:opacity-50"
            >
              清除
            </button>
          )}
        </div>
        {!hasSaved && status === "fail" && (
          <p className="text-xs text-red-600 dark:text-red-400">Key 无效，请检查后重试</p>
        )}
      </div>

      <a href={link.href} target="_blank" rel="noopener noreferrer" className="text-xs text-blue-600 dark:text-blue-400 hover:underline inline-block">
        {link.label} &rarr;
      </a>
    </div>
  );
}
