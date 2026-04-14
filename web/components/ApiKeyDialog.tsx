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

function maskKey(key: string): string {
  if (!key) return "";
  if (key.length <= 8) return "****" + key.slice(-4);
  return "****..." + key.slice(-4);
}

interface Props {
  open: boolean;
  onClose: () => void;
}

export function ApiKeyDialog({ open, onClose }: Props) {
  const [fishKey, setFishKey] = useState("");
  const [fishSavedMask, setFishSavedMask] = useState("");
  const [fishHasSaved, setFishHasSaved] = useState(false);

  const [groqKey, setGroqKey] = useState("");
  const [groqSavedMask, setGroqSavedMask] = useState("");
  const [groqHasSaved, setGroqHasSaved] = useState(false);

  // Load current state when dialog opens
  useEffect(() => {
    if (open) {
      const storedFish = localStorage.getItem(FISH_STORAGE_KEY) || "";
      setFishSavedMask(maskKey(storedFish));
      setFishHasSaved(!!storedFish);
      setFishKey("");

      const storedGroq = localStorage.getItem(GROQ_STORAGE_KEY) || "";
      setGroqSavedMask(maskKey(storedGroq));
      setGroqHasSaved(!!storedGroq);
      setGroqKey("");
    }
  }, [open]);

  const handleSaveFish = () => {
    const trimmed = fishKey.trim();
    if (!trimmed) return;
    localStorage.setItem(FISH_STORAGE_KEY, trimmed);
    setFishSavedMask(maskKey(trimmed));
    setFishHasSaved(true);
    setFishKey("");
  };

  const handleClearFish = () => {
    localStorage.removeItem(FISH_STORAGE_KEY);
    setFishSavedMask("");
    setFishHasSaved(false);
    setFishKey("");
  };

  const handleSaveGroq = () => {
    const trimmed = groqKey.trim();
    if (!trimmed) return;
    localStorage.setItem(GROQ_STORAGE_KEY, trimmed);
    setGroqSavedMask(maskKey(trimmed));
    setGroqHasSaved(true);
    setGroqKey("");
  };

  const handleClearGroq = () => {
    localStorage.removeItem(GROQ_STORAGE_KEY);
    setGroqSavedMask("");
    setGroqHasSaved(false);
    setGroqKey("");
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-sm" onPointerDownOutside={(e) => e.preventDefault()}>
        <DialogHeader>
          <DialogTitle>API Keys</DialogTitle>
          <DialogDescription>
            Key 仅存储在浏览器 localStorage 中，不会发送到后端数据库。
          </DialogDescription>
        </DialogHeader>

        <div className="px-5 py-4 space-y-6">
          {/* Fish Audio API Key */}
          <div className="space-y-3">
            <h3 className="text-sm font-medium text-neutral-900 dark:text-neutral-100">
              Fish Audio API Key
            </h3>
            <p className="text-[11px] text-neutral-500 dark:text-neutral-400 leading-relaxed">
              用于 TTS 语音合成（P2 阶段）。<strong className="text-neutral-700 dark:text-neutral-300">必填</strong>，否则无法合成音频。
            </p>

            {fishHasSaved && (
              <div className="text-xs text-neutral-500 dark:text-neutral-400">
                当前 Key: <span className="font-mono">{fishSavedMask}</span>
              </div>
            )}

            <div className="space-y-1.5">
              <label
                htmlFor="fish-api-key-input"
                className="text-xs font-medium text-neutral-700 dark:text-neutral-300"
              >
                {fishHasSaved ? "替换 Key" : "输入 API Key"}
              </label>
              <div className="flex gap-2">
                <input
                  id="fish-api-key-input"
                  type="password"
                  value={fishKey}
                  onChange={(e) => setFishKey(e.target.value)}
                  placeholder="sk-..."
                  autoComplete="off"
                  className="flex-1 px-3 py-2 text-sm rounded border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 text-neutral-900 dark:text-neutral-100 placeholder-neutral-400 focus:outline-none focus:ring-2 focus:ring-neutral-400 dark:focus:ring-neutral-500"
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && fishKey.trim()) handleSaveFish();
                  }}
                />
                <button
                  type="button"
                  onClick={handleSaveFish}
                  disabled={!fishKey.trim()}
                  className="px-3 py-2 text-sm bg-neutral-900 dark:bg-white text-white dark:text-neutral-900 rounded hover:bg-neutral-800 dark:hover:bg-neutral-200 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  保存
                </button>
                {fishHasSaved && (
                  <button
                    type="button"
                    onClick={handleClearFish}
                    className="px-3 py-2 text-sm rounded text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20"
                  >
                    清除
                  </button>
                )}
              </div>
            </div>

            <a
              href="https://fish.audio/zh-CN/go-api/api-keys"
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-blue-600 dark:text-blue-400 hover:underline inline-block"
            >
              fish.audio 获取 API Key &rarr;
            </a>
          </div>

          {/* Divider */}
          <div className="border-t border-neutral-200 dark:border-neutral-700" />

          {/* Groq API Key */}
          <div className="space-y-3">
            <h3 className="text-sm font-medium text-neutral-900 dark:text-neutral-100">
              Groq API Key
            </h3>
            <p className="text-[11px] text-neutral-500 dark:text-neutral-400 leading-relaxed">
              用于 ASR 语音转写（P2v 阶段）。<strong className="text-neutral-700 dark:text-neutral-300">必填</strong>，否则无法验证发音质量和生成字幕时间戳。免费额度足够日常使用。
            </p>

            {groqHasSaved && (
              <div className="text-xs text-neutral-500 dark:text-neutral-400">
                当前 Key: <span className="font-mono">{groqSavedMask}</span>
              </div>
            )}

            <div className="space-y-1.5">
              <label
                htmlFor="groq-api-key-input"
                className="text-xs font-medium text-neutral-700 dark:text-neutral-300"
              >
                {groqHasSaved ? "替换 Key" : "输入 API Key"}
              </label>
              <div className="flex gap-2">
                <input
                  id="groq-api-key-input"
                  type="password"
                  value={groqKey}
                  onChange={(e) => setGroqKey(e.target.value)}
                  placeholder="gsk_..."
                  autoComplete="off"
                  className="flex-1 px-3 py-2 text-sm rounded border border-neutral-300 dark:border-neutral-600 bg-white dark:bg-neutral-800 text-neutral-900 dark:text-neutral-100 placeholder-neutral-400 focus:outline-none focus:ring-2 focus:ring-neutral-400 dark:focus:ring-neutral-500"
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && groqKey.trim()) handleSaveGroq();
                  }}
                />
                <button
                  type="button"
                  onClick={handleSaveGroq}
                  disabled={!groqKey.trim()}
                  className="px-3 py-2 text-sm bg-neutral-900 dark:bg-white text-white dark:text-neutral-900 rounded hover:bg-neutral-800 dark:hover:bg-neutral-200 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  保存
                </button>
                {groqHasSaved && (
                  <button
                    type="button"
                    onClick={handleClearGroq}
                    className="px-3 py-2 text-sm rounded text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20"
                  >
                    清除
                  </button>
                )}
              </div>
            </div>

            <a
              href="https://console.groq.com/keys"
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-blue-600 dark:text-blue-400 hover:underline inline-block"
            >
              console.groq.com 获取 API Key &rarr;
            </a>
          </div>
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
