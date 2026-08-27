import { useEffect, useRef } from "react";
import { Pause, Play, SkipBack, SkipForward } from "lucide-react";
import styles from "./ReplayControls.module.css";

const SPEEDS = [0.5, 1, 2, 4] as const;
type Speed = (typeof SPEEDS)[number];

interface ReplayControlsProps {
  index: number;
  total: number;
  playing: boolean;
  speed: Speed;
  onIndexChange: (index: number) => void;
  onPlayingChange: (playing: boolean) => void;
  onSpeedChange: (speed: Speed) => void;
}

/** Replay is visually marked and never exposes live start/pause/cancel/package mutations. */
export function ReplayControls({ index, total, playing, speed, onIndexChange, onPlayingChange, onSpeedChange }: ReplayControlsProps) {
  const frameRef = useRef<number | null>(null);
  const lastTickRef = useRef(0);

  useEffect(() => {
    if (!playing) return;
    const baseIntervalMs = 400;
    const tick = (timestamp: number) => {
      if (timestamp - lastTickRef.current >= baseIntervalMs / speed) {
        lastTickRef.current = timestamp;
        onIndexChange(Math.min(index + 1, total - 1));
      }
      frameRef.current = requestAnimationFrame(tick);
    };
    frameRef.current = requestAnimationFrame(tick);
    return () => {
      if (frameRef.current) cancelAnimationFrame(frameRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing, speed, index, total]);

  useEffect(() => {
    if (index >= total - 1) onPlayingChange(false);
  }, [index, total, onPlayingChange]);

  return (
    <div className={styles.bar} role="group" aria-label="Replay controls">
      <span className={styles.badge}>REPLAY</span>
      <button type="button" className="pressable" onClick={() => onIndexChange(Math.max(0, index - 1))} aria-label="Previous event">
        <SkipBack size={16} aria-hidden="true" />
      </button>
      <button
        type="button"
        className="pressable"
        onClick={() => onPlayingChange(!playing)}
        aria-label={playing ? "Pause replay" : "Play replay"}
      >
        {playing ? <Pause size={18} aria-hidden="true" /> : <Play size={18} aria-hidden="true" />}
      </button>
      <button type="button" className="pressable" onClick={() => onIndexChange(Math.min(total - 1, index + 1))} aria-label="Next event">
        <SkipForward size={16} aria-hidden="true" />
      </button>
      <input
        type="range"
        min={0}
        max={Math.max(0, total - 1)}
        value={index}
        onChange={(event) => onIndexChange(Number(event.target.value))}
        aria-label="Replay position"
        className={styles.slider}
      />
      <span className="text-small">
        {index + 1} / {total}
      </span>
      <div className={styles.speedGroup}>
        {SPEEDS.map((option) => (
          <button
            key={option}
            type="button"
            className={styles.speedButton}
            data-active={option === speed || undefined}
            onClick={() => onSpeedChange(option)}
          >
            {option}×
          </button>
        ))}
      </div>
    </div>
  );
}
