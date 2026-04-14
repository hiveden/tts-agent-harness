"use client";

import { useCallback, useRef, useState } from "react";

interface Props {
  open: boolean;
  onClose: () => void;
  onCreate: (id: string, file: File) => void | Promise<void>;
}

export function NewEpisodeDialog({ open, onClose, onCreate }: Props) {
  const [id, setId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [dragging, setDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  if (!open) return null;

  const handleCreate = async () => {
    if (!id.trim() || !file) return;
    setSubmitting(true);
    try {
      await onCreate(id.trim(), file);
    } finally {
      setSubmitting(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const dropped = e.dataTransfer.files?.[0];
    if (dropped && dropped.name.endsWith(".json")) {
      setFile(dropped);
      // Auto-fill ID from filename if empty
      if (!id.trim()) {
        setId(dropped.name.replace(/\.json$/, ""));
      }
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
  };

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50">
      <div className="bg-white dark:bg-neutral-900 rounded-lg shadow-xl dark:shadow-neutral-900 w-96 p-5">
        <h2 className="font-semibold mb-4">New Episode</h2>
        <label className="block text-xs text-neutral-500 dark:text-neutral-400 mb-1">
          Episode ID
        </label>
        <input
          type="text"
          value={id}
          onChange={(e) => setId(e.target.value)}
          placeholder="ch06"
          className="w-full border border-neutral-300 dark:border-neutral-600 rounded px-2 py-1.5 text-sm mb-3 bg-white dark:bg-neutral-800 dark:text-neutral-100 focus:outline-none focus:border-neutral-900 dark:focus:border-neutral-400"
        />
        <label className="block text-xs text-neutral-500 dark:text-neutral-400 mb-1">
          script.json
        </label>
        <div
          onDrop={handleDrop}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onClick={() => fileInputRef.current?.click()}
          className={[
            "w-full border-2 border-dashed rounded-lg px-4 py-6 mb-4 cursor-pointer transition-colors text-center",
            dragging
              ? "border-blue-400 bg-blue-50 dark:bg-blue-900/20"
              : file
                ? "border-emerald-300 bg-emerald-50 dark:bg-emerald-900/20"
                : "border-neutral-300 dark:border-neutral-600 hover:border-neutral-400 hover:bg-neutral-50 dark:hover:bg-neutral-800",
          ].join(" ")}
        >
          {file ? (
            <div>
              <div className="text-sm font-medium text-emerald-700">{file.name}</div>
              <div className="text-[10px] text-neutral-500 mt-1">
                {(file.size / 1024).toFixed(1)} KB
                <span className="ml-2 text-neutral-400">点击更换</span>
              </div>
            </div>
          ) : (
            <div>
              <div className="text-sm text-neutral-500">
                拖拽 .json 文件到这里
              </div>
              <div className="text-[10px] text-neutral-400 mt-1">
                或点击选择文件
              </div>
            </div>
          )}
          <input
            ref={fileInputRef}
            type="file"
            accept=".json"
            onChange={(e) => {
              const f = e.target.files?.[0] ?? null;
              setFile(f);
              if (f && !id.trim()) {
                setId(f.name.replace(/\.json$/, ""));
              }
            }}
            className="hidden"
          />
        </div>
        <div className="flex gap-2 justify-end">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 text-sm rounded hover:bg-neutral-100 dark:hover:bg-neutral-800"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleCreate}
            disabled={!id.trim() || !file || submitting}
            className="px-3 py-1.5 text-sm bg-neutral-900 dark:bg-white text-white dark:text-neutral-900 rounded hover:bg-neutral-800 dark:hover:bg-neutral-200 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {submitting ? "Creating..." : "Create"}
          </button>
        </div>
      </div>
    </div>
  );
}
