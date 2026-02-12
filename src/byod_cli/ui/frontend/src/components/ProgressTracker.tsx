import type { SSEProgress } from "../hooks/useSSE";

interface ProgressTrackerProps {
  progress: SSEProgress | null;
  error: string | null;
  label?: string;
}

export function ProgressTracker({ progress, error, label }: ProgressTrackerProps) {
  if (error) {
    return <div className="error-message">{error}</div>;
  }

  if (!progress) return null;

  return (
    <div className="submission-progress">
      {label && (
        <div style={{ fontSize: "12px", color: "var(--text-dim)", marginBottom: "8px", textTransform: "uppercase", letterSpacing: "0.5px" }}>
          {label}
        </div>
      )}
      <div className="progress-message">{progress.message}</div>
      <div className="progress-bar">
        <div
          className="progress-fill"
          style={{ width: `${progress.percent}%` }}
        />
      </div>
      <div style={{ fontSize: "12px", color: "var(--text-dim)", marginTop: "6px", textAlign: "right" }}>
        {progress.percent}%
      </div>
    </div>
  );
}
