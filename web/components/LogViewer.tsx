"use client";

import { useEffect, useRef, useState } from "react";

interface Props {
  log: string[];
  error?: Error | null;
}

const MIN_H = 80;
const MAX_H = 800;
const STORAGE_KEY = "tts-harness-logviewer-h";

export function LogViewer({ log, error }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [height, setHeight] = useState(128);
  const [collapsed, setCollapsed] = useState(true);
  const draggingRef = useRef(false);

  // 初始从 localStorage 恢复高度
  useEffect(() => {
    if (typeof window === "undefined") return;
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved) {
      const n = parseInt(saved, 10);
      if (!Number.isNaN(n) && n >= MIN_H && n <= MAX_H) setHeight(n);
    }
  }, []);

  // 自动滚到底
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [log]);

  // 拖拽上边框调整高度
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!draggingRef.current) return;
      // 鼠标距视窗底部的距离 = 想要的高度
      const newH = window.innerHeight - e.clientY;
      const clamped = Math.max(MIN_H, Math.min(MAX_H, newH));
      setHeight(clamped);
    };
    const onUp = () => {
      if (!draggingRef.current) return;
      draggingRef.current = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      try {
        window.localStorage.setItem(STORAGE_KEY, String(height));
      } catch {
        // ignore
      }
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [height]);

  const startDrag = () => {
    draggingRef.current = true;
    document.body.style.cursor = "ns-resize";
    document.body.style.userSelect = "none";
  };

  return (
    <div
      className="border-t border-neutral-200 dark:border-neutral-700 bg-neutral-900 text-neutral-200 overflow-hidden flex flex-col shrink-0 relative"
      style={{ height: collapsed ? 28 : height }}
    >
      {!collapsed && (
        <div
          onMouseDown={startDrag}
          className="absolute top-0 left-0 right-0 h-1 cursor-ns-resize hover:bg-blue-500/60 active:bg-blue-500/80 z-10"
          title="拖拽调整日志面板高度"
        />
      )}
      <div
        className="px-4 py-1 border-b border-neutral-800 flex items-center text-[11px] text-neutral-400 select-none cursor-pointer hover:bg-neutral-800/50"
        onClick={() => setCollapsed((c) => !c)}
      >
        <span className="mr-1.5">{collapsed ? "▸" : "▾"}</span>
        <span className="uppercase tracking-wide">run.log</span>
        <span className="ml-3 text-neutral-500">{log.length} lines</span>
        <span className="ml-auto font-mono">{collapsed ? "展开" : "tail -f"}</span>
      </div>
      {!collapsed && (
        <div
          ref={ref}
          className="flex-1 overflow-y-auto px-4 py-2 font-mono text-[11px] leading-relaxed"
        >
          {error ? (
            <div className="text-red-400 italic">日志加载失败: {error.message || String(error)}</div>
          ) : log.length === 0 ? (
            <div className="text-neutral-500 italic">无日志</div>
          ) : (
            log.map((line, i) => <div key={i}>{line}</div>)
          )}
        </div>
      )}
    </div>
  );
}
