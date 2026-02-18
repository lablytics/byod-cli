import { useEffect, useState, useCallback, useRef, useMemo } from "react";
import { apiFetch } from "../hooks/useApi";

const REFRESH_INTERVAL = 3000;

interface LogEntry {
  id: number;
  timestamp: string;
  level: string;
  source: string;
  message: string;
  metadata?: Record<string, unknown>;
}

interface LogsResponse {
  job_id: string;
  logs: LogEntry[];
  count: number;
  limit: number;
}

interface LogViewerProps {
  jobId: string;
  jobStatus: string;
}

const LEVEL_COLORS: Record<string, string> = {
  DEBUG: "var(--text-dim)",
  INFO: "var(--green)",
  WARNING: "var(--yellow)",
  ERROR: "var(--red)",
  CRITICAL: "var(--red)",
};

const SOURCE_COLORS: Record<string, string> = {
  orchestrator: "var(--accent)",
};

export function LogViewer({ jobId, jobStatus }: LogViewerProps) {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set());
  const [levelFilter, setLevelFilter] = useState<string>("");
  const [sourceFilter, setSourceFilter] = useState<string>("");
  const [autoScroll, setAutoScroll] = useState(true);
  const logContainerRef = useRef<HTMLDivElement>(null);
  const intervalRef = useRef<number | null>(null);

  const levelFilterRef = useRef(levelFilter);
  const sourceFilterRef = useRef(sourceFilter);
  levelFilterRef.current = levelFilter;
  sourceFilterRef.current = sourceFilter;

  const isActive = useMemo(
    () => ["pending", "processing", "downloading", "uploading", "submitted"].includes(jobStatus),
    [jobStatus]
  );

  const fetchLogs = useCallback(async (showLoading = false) => {
    if (showLoading) setLoading(true);

    try {
      const params = new URLSearchParams();
      params.set("limit", "1000");
      if (levelFilterRef.current) params.set("level", levelFilterRef.current);
      if (sourceFilterRef.current) params.set("source", sourceFilterRef.current);

      const data = await apiFetch<LogsResponse>(`/jobs/${jobId}/logs?${params}`);
      // Filter out enclave logs (internal implementation detail)
      const filteredLogs = data.logs.filter(log => log.source !== "enclave");
      setLogs(filteredLogs);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load logs");
    } finally {
      if (showLoading) setLoading(false);
    }
  }, [jobId]);

  // Initial load
  useEffect(() => {
    fetchLogs(true);
  }, [fetchLogs]);

  // Re-fetch when filters change
  useEffect(() => {
    fetchLogs(false);
  }, [levelFilter, sourceFilter, fetchLogs]);

  // Auto-refresh for active jobs
  useEffect(() => {
    if (isActive) {
      intervalRef.current = window.setInterval(() => fetchLogs(false), REFRESH_INTERVAL);
    }
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [isActive, fetchLogs]);

  // Auto-scroll to bottom when new logs arrive
  useEffect(() => {
    if (autoScroll && logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [logs, autoScroll]);

  const toggleExpanded = (id: number) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const formatTimestamp = (ts: string) => {
    try {
      const date = new Date(ts);
      const time = date.toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
      const ms = date.getMilliseconds().toString().padStart(3, "0");
      return `${time}.${ms}`;
    } catch {
      return ts;
    }
  };

  if (loading) {
    return <div className="loading" style={{ padding: 24 }}>Loading logs...</div>;
  }

  if (error) {
    return (
      <div className="error-message">
        {error}
        <button
          className="btn-small"
          onClick={() => fetchLogs(true)}
          style={{ marginLeft: 12 }}
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="log-viewer">
      {/* Controls */}
      <div style={{
        display: "flex",
        gap: 12,
        marginBottom: 16,
        alignItems: "center",
        flexWrap: "wrap",
      }}>
        <select
          value={levelFilter}
          onChange={(e) => setLevelFilter(e.target.value)}
          style={{
            background: "var(--bg)",
            border: "1px solid var(--border)",
            borderRadius: 6,
            padding: "6px 12px",
            color: "var(--text)",
            fontSize: 13,
          }}
        >
          <option value="">All Levels</option>
          <option value="DEBUG">Debug</option>
          <option value="INFO">Info</option>
          <option value="WARNING">Warning</option>
          <option value="ERROR">Error</option>
        </select>

        <select
          value={sourceFilter}
          onChange={(e) => setSourceFilter(e.target.value)}
          style={{
            background: "var(--bg)",
            border: "1px solid var(--border)",
            borderRadius: 6,
            padding: "6px 12px",
            color: "var(--text)",
            fontSize: 13,
          }}
        >
          <option value="">All Sources</option>
          <option value="orchestrator">Orchestrator</option>
        </select>

        <label style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          fontSize: 13,
          color: "var(--text-dim)",
          cursor: "pointer",
        }}>
          <input
            type="checkbox"
            checked={autoScroll}
            onChange={(e) => setAutoScroll(e.target.checked)}
          />
          Auto-scroll
        </label>

        <span style={{ marginLeft: "auto", fontSize: 13, color: "var(--text-dim)" }}>
          {logs.length} log{logs.length !== 1 ? "s" : ""}
          {isActive && (
            <span style={{ marginLeft: 8, color: "var(--green)" }}>
              (live)
            </span>
          )}
        </span>
      </div>

      {/* Log entries */}
      <div
        ref={logContainerRef}
        style={{
          background: "#111318",
          border: "1px solid var(--border)",
          borderRadius: 8,
          maxHeight: 500,
          overflowY: "auto",
          fontFamily: "'SF Mono', 'Fira Code', monospace",
          fontSize: 12,
          lineHeight: 1.5,
        }}
      >
        {logs.length === 0 ? (
          <div style={{ padding: 24, color: "var(--text-dim)", textAlign: "center" }}>
            No logs available
          </div>
        ) : (
          logs.map((log) => (
            <div
              key={log.id}
              style={{
                padding: "6px 12px",
                borderBottom: "1px solid var(--border)",
                display: "flex",
                gap: 8,
                alignItems: "flex-start",
              }}
            >
              <span style={{ color: "var(--text-dim)", flexShrink: 0 }}>
                {formatTimestamp(log.timestamp)}
              </span>

              <span
                style={{
                  color: LEVEL_COLORS[log.level] || "var(--text)",
                  fontWeight: 600,
                  width: 60,
                  flexShrink: 0,
                }}
              >
                {log.level}
              </span>

              <span
                style={{
                  background: "rgba(99, 102, 241, 0.12)",
                  color: SOURCE_COLORS[log.source] || "var(--text-dim)",
                  padding: "1px 6px",
                  borderRadius: 3,
                  fontSize: 10,
                  flexShrink: 0,
                }}
              >
                {log.source}
              </span>

              <div style={{ flex: 1, minWidth: 0 }}>
                <span
                  style={{
                    color: log.level === "ERROR" || log.level === "CRITICAL"
                      ? "var(--red)"
                      : "var(--text)",
                    wordBreak: "break-word",
                  }}
                >
                  {log.message}
                </span>

                {log.metadata && Object.keys(log.metadata).length > 0 && (
                  <div style={{ marginTop: 4 }}>
                    <button
                      onClick={() => toggleExpanded(log.id)}
                      style={{
                        background: "none",
                        border: "none",
                        color: "var(--accent)",
                        cursor: "pointer",
                        padding: 0,
                        fontSize: 11,
                      }}
                    >
                      {expandedIds.has(log.id) ? "[-] Hide details" : "[+] Show details"}
                    </button>

                    {expandedIds.has(log.id) && (
                      <pre
                        style={{
                          marginTop: 8,
                          padding: 8,
                          background: "var(--bg)",
                          borderRadius: 4,
                          overflow: "auto",
                          fontSize: 11,
                          color: "var(--text-dim)",
                        }}
                      >
                        {JSON.stringify(log.metadata, null, 2)}
                      </pre>
                    )}
                  </div>
                )}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
