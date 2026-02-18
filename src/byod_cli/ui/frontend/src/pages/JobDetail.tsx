import { useState, useEffect, useCallback } from "react";
import { useParams, Link } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { fadeInUp } from "../animations/variants";
import { apiFetch } from "../hooks/useApi";
import { StatusBadge } from "../components/StatusBadge";
import { ProgressTracker } from "../components/ProgressTracker";
import { useSSE } from "../hooks/useSSE";
import { Skeleton, SkeletonCard } from "../components/Skeleton";
import { LogViewer } from "../components/LogViewer";

interface JobData {
  job_id: string;
  plugin_name: string;
  status: string;
  created_at: string;
  updated_at?: string;
  description?: string;
  timeline?: Array<{ phase: string; timestamp: string }>;
  results_available?: boolean;
}

interface ResultFile {
  path: string;
  name: string;
  size: number;
  mime: string;
}

interface ResultsData {
  files: ResultFile[];
  output_dir: string;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatRelativeTime(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  if (diffMins < 1) return "just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.floor(diffHours / 24);
  return `${diffDays}d ago`;
}

function fileIcon(mime: string): string {
  if (mime.startsWith("text/html")) return "HTML";
  if (mime === "application/json") return "JSON";
  if (mime.startsWith("text/")) return "TXT";
  if (mime.startsWith("image/")) return "IMG";
  if (mime === "application/zip") return "ZIP";
  if (mime === "application/gzip") return "GZ";
  return "BIN";
}

function fileIconColor(mime: string): { bg: string; fg: string } {
  if (mime.startsWith("text/html")) return { bg: "rgba(99, 102, 241, 0.15)", fg: "var(--accent)" };
  if (mime === "application/json") return { bg: "rgba(234, 179, 8, 0.15)", fg: "var(--yellow)" };
  if (mime.startsWith("text/")) return { bg: "rgba(34, 197, 94, 0.15)", fg: "var(--green)" };
  if (mime.startsWith("image/")) return { bg: "rgba(139, 92, 246, 0.15)", fg: "var(--purple)" };
  return { bg: "rgba(255,255,255,0.06)", fg: "var(--text-dim)" };
}

type ActiveTab = "overview" | "results" | "logs";

export function JobDetail() {
  const { jobId } = useParams<{ jobId: string }>();
  const [job, setJob] = useState<JobData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const sse = useSSE();

  // Results viewer state
  const [results, setResults] = useState<ResultsData | null>(null);
  const [selectedFile, setSelectedFile] = useState<ResultFile | null>(null);
  const [fileContent, setFileContent] = useState<string | null>(null);
  const [fileLoading, setFileLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<ActiveTab>("overview");

  useEffect(() => {
    if (!jobId) return;
    const fetchJob = () => {
      apiFetch<JobData>(`/jobs/${jobId}`)
        .then(setJob)
        .catch((e) => setError(e.message))
        .finally(() => setLoading(false));
    };
    fetchJob();
    const interval = setInterval(fetchJob, 5000);
    return () => clearInterval(interval);
  }, [jobId]);

  // Check for existing results on mount
  const loadResults = useCallback(() => {
    if (!jobId) return;
    apiFetch<ResultsData>(`/jobs/${jobId}/results`)
      .then((data) => {
        setResults(data);
        const html = data.files.find((f) => f.mime.startsWith("text/html"));
        if (html) setSelectedFile(html);
        setActiveTab("results");
      })
      .catch(() => {});
  }, [jobId]);

  useEffect(() => {
    loadResults();
  }, [loadResults]);

  useEffect(() => {
    if (sse.result) loadResults();
  }, [sse.result, loadResults]);

  // Load file content when a file is selected
  useEffect(() => {
    if (!selectedFile || !jobId) {
      setFileContent(null);
      return;
    }

    const isTextFile =
      selectedFile.mime.startsWith("text/") ||
      selectedFile.mime === "application/json";

    if (selectedFile.mime.startsWith("text/html")) {
      setFileContent(null);
      return;
    }

    if (!isTextFile) {
      setFileContent(null);
      return;
    }

    setFileLoading(true);
    fetch(`/api/jobs/${jobId}/results/file?path=${encodeURIComponent(selectedFile.path)}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.text();
      })
      .then(setFileContent)
      .catch(() => setFileContent("Failed to load file content."))
      .finally(() => setFileLoading(false));
  }, [selectedFile, jobId]);

  const handleGetResults = () => {
    if (!jobId) return;
    sse.start(`/api/jobs/${jobId}/get`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
  };

  if (loading) return (
    <div>
      <div style={{ marginBottom: "20px" }}>
        <Skeleton width={100} height={14} />
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 32 }}>
        <Skeleton width={200} height={28} />
        <Skeleton width={80} height={24} style={{ borderRadius: 12 }} />
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12, marginBottom: 24 }}>
        <SkeletonCard lines={2} />
        <SkeletonCard lines={2} />
        <SkeletonCard lines={2} />
      </div>
      <SkeletonCard lines={6} />
    </div>
  );
  if (error) return <div className="error-message">{error}</div>;
  if (!job) return <div className="error-message">Job not found</div>;

  const isHtml = selectedFile?.mime.startsWith("text/html");
  const isText =
    selectedFile &&
    !isHtml &&
    (selectedFile.mime.startsWith("text/") || selectedFile.mime === "application/json");
  const isImage = selectedFile?.mime.startsWith("image/");
  const fileUrl = selectedFile && jobId
    ? `/api/jobs/${jobId}/results/file?path=${encodeURIComponent(selectedFile.path)}`
    : null;
  const downloadUrl = fileUrl ? `${fileUrl}&download=true` : null;
  const hasResults = results && results.files.length > 0;
  const isCompleted = job.status.toLowerCase() === "completed";
  const isFailed = job.status.toLowerCase() === "failed";
  const isActive = ["pending", "processing", "downloading", "uploading", "submitted"].includes(job.status.toLowerCase());

  return (
    <motion.div variants={fadeInUp} initial="initial" animate="animate">
      {/* Breadcrumb */}
      <div style={{ marginBottom: "20px" }}>
        <Link to="/jobs" className="job-back-link">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M19 12H5" /><path d="M12 19l-7-7 7-7" />
          </svg>
          Back to Jobs
        </Link>
      </div>

      {/* Header */}
      <div style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "flex-start",
        marginBottom: "28px",
      }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "8px", flexWrap: "wrap" }}>
            <h1 style={{ fontSize: "22px", fontWeight: 700, margin: 0 }}>Job Details</h1>
            <StatusBadge status={job.status} />
            {isActive && (
              <span className="job-live-indicator">
                <span className="job-live-dot" />
                Live
              </span>
            )}
          </div>
          <p style={{
            fontFamily: "'SF Mono', 'Fira Code', monospace",
            fontSize: "13px",
            color: "var(--text-dim)",
            margin: 0,
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}>
            {job.job_id}
          </p>
        </div>

        {isCompleted && (
          <button
            className="btn-primary"
            onClick={handleGetResults}
            disabled={sse.active}
            style={{ flexShrink: 0, marginLeft: "16px" }}
          >
            {sse.active ? "Retrieving..." : hasResults ? "Re-download" : "Get Results"}
          </button>
        )}
      </div>

      {/* SSE progress */}
      {(sse.active || sse.error) && (
        <div style={{ marginBottom: "24px" }}>
          <ProgressTracker progress={sse.progress} error={sse.error} label="Retrieving Results" />
        </div>
      )}

      {/* Info cards */}
      <div className="job-info-row">
        <div className="job-info-card">
          <div className="job-info-label">Pipeline</div>
          <div className="job-info-value">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
              <path d="M12 2L2 7l10 5 10-5-10-5z" /><path d="M2 17l10 5 10-5" /><path d="M2 12l10 5 10-5" />
            </svg>
            <span>{job.plugin_name}</span>
          </div>
        </div>
        <div className="job-info-card">
          <div className="job-info-label">Submitted</div>
          <div className="job-info-value">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--text-dim)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
              <circle cx="12" cy="12" r="10" /><path d="M12 6v6l4 2" />
            </svg>
            <span title={new Date(job.created_at).toLocaleString()}>
              {formatRelativeTime(job.created_at)}
            </span>
          </div>
        </div>
        {isFailed ? (
          <div className="job-info-card" style={{ borderColor: "rgba(239, 68, 68, 0.3)" }}>
            <div className="job-info-label" style={{ color: "var(--red)" }}>Error</div>
            <div className="job-info-value" style={{ color: "var(--red)", fontSize: "13px" }}>
              {job.description || "Unknown error"}
            </div>
          </div>
        ) : (
          <div className="job-info-card">
            <div className="job-info-label">
              {hasResults ? "Results" : "Description"}
            </div>
            <div className="job-info-value">
              {hasResults ? (
                <>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--green)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
                    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                    <path d="M9 12l2 2 4-4" />
                  </svg>
                  <span style={{ color: "var(--green)" }}>
                    {results!.files.length} file{results!.files.length !== 1 ? "s" : ""} decrypted
                  </span>
                </>
              ) : (
                <span style={{ color: "var(--text-dim)" }}>
                  {job.description || "No description"}
                </span>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Segmented tab bar */}
      <div className="job-tab-bar">
        {(
          [
            { key: "overview" as ActiveTab, label: "Overview" },
            ...(hasResults ? [{ key: "results" as ActiveTab, label: `Results (${results!.files.length})` }] : []),
            { key: "logs" as ActiveTab, label: "Logs" },
          ] as Array<{ key: ActiveTab; label: string }>
        ).map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`job-tab-btn ${activeTab === tab.key ? "active" : ""}`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <AnimatePresence mode="wait">
        {activeTab === "overview" && (
          <motion.div
            key="overview"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.15 }}
          >
            {job.description && (
              <div className="card" style={{ marginBottom: "16px" }}>
                <div className="job-section-header">Description</div>
                <div style={{ fontSize: "14px", lineHeight: 1.6 }}>{job.description}</div>
              </div>
            )}

            {job.timeline && job.timeline.length > 0 && (
              <div className="card" style={{ marginBottom: "16px" }}>
                <div className="job-section-header">Timeline</div>
                <div className="job-timeline">
                  {job.timeline.map((event, i) => {
                    const isLast = i === (job.timeline?.length ?? 0) - 1;
                    return (
                      <div key={i} className="job-timeline-item">
                        <div className="job-timeline-dot-col">
                          <div
                            className={`job-timeline-dot ${isLast && isActive ? "active" : isLast ? "completed" : ""}`}
                          />
                          {!isLast && <div className="job-timeline-line" />}
                        </div>
                        <div style={{ flex: 1 }}>
                          <div style={{ fontWeight: 500, textTransform: "capitalize", fontSize: "14px" }}>
                            {event.phase}
                          </div>
                          <div style={{ fontSize: "12px", color: "var(--text-dim)", marginTop: "2px" }}>
                            {new Date(event.timestamp).toLocaleString()}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            <div className="job-cli-hint">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
                <polyline points="4 17 10 11 4 5" /><line x1="12" y1="19" x2="20" y2="19" />
              </svg>
              <code>byod status {job.job_id}</code>
            </div>
          </motion.div>
        )}

        {activeTab === "results" && hasResults && (
          <motion.div
            key="results"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.15 }}
          >
            <div className="results-container">
              <div className="results-header">
                <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--green)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                    <path d="M9 12l2 2 4-4" />
                  </svg>
                  <span style={{ fontSize: "13px", fontWeight: 600, color: "var(--green)" }}>
                    Decrypted locally
                  </span>
                </div>
                <span style={{ fontSize: "12px", color: "var(--text-dim)" }}>
                  {results!.files.length} file{results!.files.length !== 1 ? "s" : ""}
                  {" "}({formatSize(results!.files.reduce((sum, f) => sum + f.size, 0))} total)
                </span>
              </div>

              <div className="results-split">
                <div className="results-sidebar">
                  {results!.files.map((file) => {
                    const colors = fileIconColor(file.mime);
                    const isSelected = selectedFile?.path === file.path;
                    return (
                      <button
                        key={file.path}
                        onClick={() => setSelectedFile(file)}
                        className={`results-file-btn ${isSelected ? "selected" : ""}`}
                      >
                        <span className="results-file-icon" style={{ background: colors.bg, color: colors.fg }}>
                          {fileIcon(file.mime)}
                        </span>
                        <div style={{ minWidth: 0, flex: 1 }}>
                          <div className="results-file-name">{file.name}</div>
                          {file.path !== file.name && (
                            <div className="results-file-path">{file.path}</div>
                          )}
                          <div className="results-file-size">{formatSize(file.size)}</div>
                        </div>
                      </button>
                    );
                  })}
                </div>

                <div className="results-viewer">
                  {!selectedFile && (
                    <div className="results-empty">
                      <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="var(--border)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                        <polyline points="14 2 14 8 20 8" />
                        <line x1="16" y1="13" x2="8" y2="13" />
                        <line x1="16" y1="17" x2="8" y2="17" />
                      </svg>
                      <div style={{ marginTop: "12px" }}>Select a file to preview</div>
                    </div>
                  )}

                  {selectedFile && fileLoading && (
                    <div className="results-empty">
                      <div className="loading-spinner" style={{ width: 24, height: 24 }} />
                      <div style={{ marginTop: "12px" }}>Loading...</div>
                    </div>
                  )}

                  {selectedFile && isHtml && fileUrl && (
                    <iframe
                      src={fileUrl}
                      title={selectedFile.name}
                      style={{ width: "100%", height: "100%", border: "none", background: "#fff", borderRadius: "0 0 10px 0" }}
                    />
                  )}

                  {selectedFile && isText && fileContent !== null && !fileLoading && (
                    <pre className="results-text-content">{fileContent}</pre>
                  )}

                  {selectedFile && isImage && fileUrl && (
                    <div className="results-image-container">
                      <img src={fileUrl} alt={selectedFile.name} style={{ maxWidth: "100%", maxHeight: "100%", objectFit: "contain", borderRadius: "4px" }} />
                    </div>
                  )}

                  {selectedFile && !isHtml && !isText && !isImage && !fileLoading && (
                    <div className="results-empty">
                      <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="var(--border)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                        <polyline points="7 10 12 15 17 10" />
                        <line x1="12" y1="15" x2="12" y2="3" />
                      </svg>
                      <div style={{ marginTop: "12px" }}>Binary file ({formatSize(selectedFile.size)})</div>
                      {downloadUrl && (
                        <a href={downloadUrl} download={selectedFile.name} className="btn-primary" style={{ textDecoration: "none", marginTop: "12px", fontSize: "13px", padding: "8px 20px" }}>
                          Download {selectedFile.name}
                        </a>
                      )}
                    </div>
                  )}

                  {selectedFile && downloadUrl && (isHtml || isText || isImage) && (
                    <a href={downloadUrl} download={selectedFile.name} className="results-download-btn">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                        <polyline points="7 10 12 15 17 10" />
                        <line x1="12" y1="15" x2="12" y2="3" />
                      </svg>
                      Download
                    </a>
                  )}
                </div>
              </div>
            </div>
          </motion.div>
        )}

        {activeTab === "logs" && (
          <motion.div
            key="logs"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.15 }}
          >
            <div className="card">
              <LogViewer jobId={job.job_id} jobStatus={job.status} />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
