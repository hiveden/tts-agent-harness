import { useCallback, useEffect, useRef, useState } from "react";
import { useHarnessStore } from "@/lib/store";

interface AudioPlayer {
  ref: React.RefObject<HTMLAudioElement | null>;
  currentTime: number;
  isPlaying: boolean;
  toggle: () => void;
  seekTo: (timeS: number) => void;
}

export function useAudioPlayer(chunkId: string, durationS: number): AudioPlayer {
  const ref = useRef<HTMLAudioElement>(null);
  const [currentTime, setCurrentTime] = useState(0);

  const isPlaying = useHarnessStore((s) => s.playingChunkId === chunkId);
  const setPlayingChunkId = useHarnessStore((s) => s.setPlayingChunkId);

  // Sync time from audio element
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const onTime = () => setCurrentTime(el.currentTime);
    const onEnded = () => {
      setCurrentTime(0);
      setPlayingChunkId(null);
    };
    el.addEventListener("timeupdate", onTime);
    el.addEventListener("ended", onEnded);
    return () => {
      el.removeEventListener("timeupdate", onTime);
      el.removeEventListener("ended", onEnded);
    };
  }, [setPlayingChunkId]);

  // When another chunk starts playing, pause this one
  useEffect(() => {
    if (!isPlaying && ref.current) {
      ref.current.pause();
      ref.current.currentTime = 0;
      setCurrentTime(0);
    }
  }, [isPlaying]);

  const ensureReady = useCallback(async () => {
    const el = ref.current;
    if (!el) return null;
    if (el.readyState < 1) {
      await new Promise<void>((resolve) =>
        el.addEventListener("loadedmetadata", () => resolve(), { once: true })
      );
    }
    return el;
  }, []);

  const toggle = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    if (isPlaying) {
      setPlayingChunkId(null);
    } else {
      setPlayingChunkId(chunkId);
      ensureReady().then((ready) => {
        if (ready) ready.play().catch(() => {});
      });
    }
  }, [chunkId, isPlaying, setPlayingChunkId, ensureReady]);

  const seekTo = useCallback((timeS: number) => {
    const target = Math.max(0, Math.min(durationS, timeS));
    setPlayingChunkId(chunkId);
    ensureReady().then((el) => {
      if (!el) return;
      el.currentTime = target;
      setCurrentTime(target);
      el.play().catch(() => {});
    });
  }, [chunkId, durationS, setPlayingChunkId, ensureReady]);

  return { ref, currentTime, isPlaying, toggle, seekTo };
}
