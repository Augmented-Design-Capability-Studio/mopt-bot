import { useEffect, useRef, useState } from "react";

import { formatClock } from "../lib/format";

interface VideoPaneProps {
  playhead: number;
  onPlayheadChange: (t: number) => void;
  onDurationChange: (d: number | null) => void;
  onVideoElReady: (el: HTMLVideoElement | null) => void;
  onFileChosen: (name: string) => void;
}

/**
 * Local video player. The file is read via the File API (object URL) and never
 * uploaded. Reports the playhead up on a rAF loop while playing (smooth row
 * sync) plus on seek/timeupdate while paused.
 */
export function VideoPane({
  playhead,
  onPlayheadChange,
  onDurationChange,
  onVideoElReady,
  onFileChosen,
}: VideoPaneProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const rafRef = useRef<number | null>(null);
  const [objectUrl, setObjectUrl] = useState<string | null>(null);

  useEffect(() => {
    return () => {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [objectUrl]);

  function handleFile(file: File) {
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    const url = URL.createObjectURL(file);
    setObjectUrl(url);
    onFileChosen(file.name);
  }

  function pump() {
    const el = videoRef.current;
    if (el) onPlayheadChange(el.currentTime);
    rafRef.current = requestAnimationFrame(pump);
  }

  function startPump() {
    if (rafRef.current == null) rafRef.current = requestAnimationFrame(pump);
  }

  function stopPump() {
    if (rafRef.current != null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
  }

  useEffect(() => () => stopPump(), []);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "0.4rem" }}>
      <label className="muted" style={{ fontSize: "0.8rem" }}>
        Video file (stays local — not uploaded)
        <input
          type="file"
          accept="video/*"
          style={{ display: "block", marginTop: "0.25rem" }}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) handleFile(f);
          }}
        />
      </label>
      {objectUrl ? (
        <video
          ref={(el) => {
            videoRef.current = el;
            onVideoElReady(el);
          }}
          src={objectUrl}
          controls
          style={{ width: "100%", maxHeight: "42vh", background: "#000" }}
          onPlay={startPump}
          onPause={stopPump}
          onSeeked={(e) => onPlayheadChange(e.currentTarget.currentTime)}
          onTimeUpdate={(e) => {
            if (rafRef.current == null) onPlayheadChange(e.currentTarget.currentTime);
          }}
          onLoadedMetadata={(e) => onDurationChange(e.currentTarget.duration)}
        />
      ) : (
        <div className="muted" style={{ fontSize: "0.85rem", padding: "1rem 0" }}>
          Pick a video to enable the playhead and coding controls.
        </div>
      )}
      <div style={{ fontSize: "0.85rem" }}>
        Playhead: <strong>{formatClock(playhead)}</strong>{" "}
        <span className="muted">({playhead.toFixed(2)}s)</span>
      </div>
    </div>
  );
}
