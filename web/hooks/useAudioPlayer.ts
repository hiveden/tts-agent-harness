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
  const continuousPlay = useHarnessStore((s) => s.continuousPlay);
  const advanceToNext = useHarnessStore((s) => s.advanceToNext);
  const playbackRate = useHarnessStore((s) => s.playbackRate);

  // Sync time + handle ended
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const onTime = () => setCurrentTime(el.currentTime);
    const onEnded = () => {
      setCurrentTime(0);
      const { continuousPlay } = useHarnessStore.getState();
      if (continuousPlay) {
        advanceToNext();
      } else {
        setPlayingChunkId(null);
      }
    };
    el.addEventListener("timeupdate", onTime);
    el.addEventListener("ended", onEnded);
    return () => {
      el.removeEventListener("timeupdate", onTime);
      el.removeEventListener("ended", onEnded);
    };
  }, [setPlayingChunkId, advanceToNext]);

  // Sync playbackRate to audio element
  useEffect(() => {
    if (ref.current) ref.current.playbackRate = playbackRate;
  }, [playbackRate]);

  // When isPlaying changes: pause if false, auto-play if true (for continuous mode)
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (!isPlaying) {
      el.pause();
      el.currentTime = 0;
      setCurrentTime(0);
    } else {
      // Auto-play when this chunk becomes active (continuous play or manual)
      el.playbackRate = playbackRate;
      if (el.readyState >= 1) {
        el.play().catch(() => {});
      } else {
        el.addEventListener("loadedmetadata", () => {
          el.playbackRate = playbackRate;
          el.play().catch(() => {});
        }, { once: true });
      }
    }
  }, [isPlaying, playbackRate]);

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
        if (ready) {
          ready.playbackRate = playbackRate;
          ready.play().catch(() => {});
        }
      });
    }
  }, [chunkId, isPlaying, setPlayingChunkId, ensureReady, playbackRate]);

  const seekTo = useCallback((timeS: number) => {
    const target = Math.max(0, Math.min(durationS, timeS));
    setPlayingChunkId(chunkId);
    ensureReady().then((el) => {
      if (!el) return;
      el.playbackRate = playbackRate;
      el.currentTime = target;
      setCurrentTime(target);
      el.play().catch(() => {});
    });
  }, [chunkId, durationS, setPlayingChunkId, ensureReady, playbackRate]);

  return { ref, currentTime, isPlaying, toggle, seekTo };
}
