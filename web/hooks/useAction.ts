"use client";

import { useCallback, useRef, useState } from "react";
import { toast } from "sonner";

interface UseActionOptions {
  successMessage?: string;
  errorPrefix?: string;
}

type ActionFn<A extends unknown[]> = (...args: A) => Promise<void>;

export function useAction<A extends unknown[]>(
  fn: ActionFn<A>,
  options?: UseActionOptions,
): [execute: (...args: A) => Promise<void>, pending: boolean] {
  const [pending, setPending] = useState(false);
  const pendingRef = useRef(false);

  const execute = useCallback(
    async (...args: A) => {
      if (pendingRef.current) return;
      pendingRef.current = true;
      setPending(true);
      try {
        await fn(...args);
        if (options?.successMessage) toast.success(options.successMessage);
      } catch (e) {
        const msg = (e as Error).message || String(e);
        const prefix = options?.errorPrefix ? `${options.errorPrefix}: ` : "";
        toast.error(`${prefix}${msg}`);
      } finally {
        pendingRef.current = false;
        setPending(false);
      }
    },
    [fn, options?.successMessage, options?.errorPrefix],
  );

  return [execute, pending];
}
