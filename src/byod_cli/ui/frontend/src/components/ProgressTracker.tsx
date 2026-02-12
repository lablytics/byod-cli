import { useState, useEffect, useRef } from "react";
import type { SSEProgress } from "../hooks/useSSE";

interface ProgressTrackerProps {
  progress: SSEProgress | null;
  error: string | null;
  label?: string;
  stages?: string[];
}

const DEFAULT_SUBMIT_STAGES = ["receiving", "packaging", "encrypting", "uploading_data", "uploading_key", "submitting"];
const DEFAULT_RETRIEVE_STAGES = ["checking", "downloading", "unwrapping", "decrypting", "extracting"];

function inferStages(label?: string): string[] {
  if (label?.toLowerCase().includes("retriev")) return DEFAULT_RETRIEVE_STAGES;
  return DEFAULT_SUBMIT_STAGES;
}

function stageLabel(stage: string): string {
  return stage
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function ElapsedTime() {
  const startRef = useRef(Date.now());
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startRef.current) / 1000));
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  const mins = Math.floor(elapsed / 60);
  const secs = elapsed % 60;
  return (
    <span>{mins > 0 ? `${mins}m ${secs}s` : `${secs}s`}</span>
  );
}

export function ProgressTracker({ progress, error, label, stages: stagesProp }: ProgressTrackerProps) {
  if (error) {
    return <div className="error-message">{error}</div>;
  }

  if (!progress) return null;

  const stages = stagesProp || inferStages(label);
  const currentStageIndex = stages.indexOf(progress.stage);

  return (
    <div className="submission-progress">
      {label && (
        <div style={{
          fontSize: "12px",
          color: "var(--text-dim)",
          marginBottom: "8px",
          textTransform: "uppercase",
          letterSpacing: "0.5px",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}>
          <span>{label}</span>
          <ElapsedTime />
        </div>
      )}

      {/* Stage indicators */}
      <div className="progress-stages">
        {stages.map((stage, i) => {
          const isCompleted = i < currentStageIndex;
          const isActive = i === currentStageIndex;
          const cls = isCompleted ? "completed" : isActive ? "active" : "";
          return (
            <span key={stage} style={{ display: "inline-flex", alignItems: "center" }}>
              {i > 0 && <span className="progress-stage-arrow" aria-hidden="true">&rsaquo;</span>}
              <span className={`progress-stage ${cls}`}>
                <span className="progress-stage-dot" />
                {stageLabel(stage)}
              </span>
            </span>
          );
        })}
      </div>

      <div className="progress-message">{progress.message}</div>
      <div className="progress-bar">
        <div
          className={`progress-fill ${progress.percent < 100 ? "glowing" : ""}`}
          style={{ width: `${progress.percent}%` }}
        />
      </div>
      <div style={{ fontSize: "12px", color: "var(--text-dim)", marginTop: "6px", textAlign: "right" }}>
        {progress.percent}%
      </div>
    </div>
  );
}
