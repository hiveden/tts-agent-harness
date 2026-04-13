"use client";

import { useState, useCallback, useRef, useEffect, type ReactNode } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";

interface PromptState {
  title: string;
  description?: string;
  defaultValue?: string;
  placeholder?: string;
  resolve: (v: string | null) => void;
}

/**
 * Promise-based prompt dialog hook.
 * Returns [prompt, PromptDialogNode].
 *
 * Usage:
 *   const [prompt, PromptDialog] = usePrompt();
 *   const value = await prompt("输入新 ID:", { defaultValue: "copy" });
 *   if (value === null) return; // cancelled
 */
export function usePrompt() {
  const [state, setState] = useState<PromptState | null>(null);
  const [value, setValue] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const prompt = useCallback(
    (
      title: string,
      opts?: { description?: string; defaultValue?: string; placeholder?: string },
    ) =>
      new Promise<string | null>((resolve) => {
        setValue(opts?.defaultValue ?? "");
        setState({ title, ...opts, resolve });
      }),
    [],
  );

  // Auto-focus + select on open
  useEffect(() => {
    if (state) {
      requestAnimationFrame(() => {
        inputRef.current?.focus();
        inputRef.current?.select();
      });
    }
  }, [state]);

  const handleClose = useCallback(
    (submitted: boolean) => {
      state?.resolve(submitted ? value.trim() || null : null);
      setState(null);
    },
    [state, value],
  );

  const node: ReactNode = state ? (
    <Dialog open onOpenChange={(open) => { if (!open) handleClose(false); }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{state.title}</DialogTitle>
          {state.description && (
            <DialogDescription>{state.description}</DialogDescription>
          )}
        </DialogHeader>
        <div className="px-5 py-3">
          <input
            ref={inputRef}
            type="text"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") handleClose(true); }}
            placeholder={state.placeholder}
            className="w-full px-3 py-2 text-sm border border-neutral-300 dark:border-neutral-600 rounded bg-white dark:bg-neutral-800 dark:text-neutral-100 focus:outline-none focus:ring-1 focus:ring-blue-400"
          />
        </div>
        <DialogFooter>
          <button
            type="button"
            onClick={() => handleClose(false)}
            className="px-3 py-1.5 text-xs text-neutral-600 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800 rounded"
          >
            取消
          </button>
          <button
            type="button"
            onClick={() => handleClose(true)}
            className="px-4 py-1.5 text-xs rounded bg-neutral-900 dark:bg-white text-white dark:text-neutral-900 hover:bg-neutral-800 dark:hover:bg-neutral-200"
          >
            确定
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  ) : null;

  return [prompt, node] as const;
}
