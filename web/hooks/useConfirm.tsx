"use client";

import { useState, useCallback, type ReactNode } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";

interface ConfirmState {
  message: string;
  description?: string;
  confirmLabel?: string;
  destructive?: boolean;
  resolve: (v: boolean) => void;
}

/**
 * Promise-based confirm dialog hook.
 * Returns [confirm, ConfirmDialogNode].
 *
 * Usage:
 *   const [confirm, ConfirmDialog] = useConfirm();
 *   // ...
 *   const ok = await confirm("确认删除？");
 *   if (!ok) return;
 *   // render {ConfirmDialog} somewhere in JSX
 */
export function useConfirm() {
  const [state, setState] = useState<ConfirmState | null>(null);

  const confirm = useCallback(
    (
      message: string,
      opts?: { description?: string; confirmLabel?: string; destructive?: boolean },
    ) =>
      new Promise<boolean>((resolve) => {
        setState({ message, ...opts, resolve });
      }),
    [],
  );

  const handleClose = useCallback(
    (accepted: boolean) => {
      state?.resolve(accepted);
      setState(null);
    },
    [state],
  );

  const node: ReactNode = state ? (
    <Dialog open onOpenChange={(open) => { if (!open) handleClose(false); }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{state.message}</DialogTitle>
          {state.description && (
            <DialogDescription>{state.description}</DialogDescription>
          )}
        </DialogHeader>
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
            className={`px-4 py-1.5 text-xs rounded text-white ${
              state.destructive
                ? "bg-red-600 hover:bg-red-700"
                : "bg-neutral-900 dark:bg-white dark:text-neutral-900 hover:bg-neutral-800 dark:hover:bg-neutral-200"
            }`}
          >
            {state.confirmLabel ?? "确认"}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  ) : null;

  return [confirm, node] as const;
}
