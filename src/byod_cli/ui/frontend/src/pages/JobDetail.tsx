import { useState, useEffect, useCallback } from "react";
import { useParams, Link } from "react-router-dom";
import { motion } from "framer-motion";
import { fadeInUp } from "../animations/variants";
import { apiFetch } from "../hooks/useApi";
import { StatusBadge } from "../components/StatusBadge";
import { ProgressTracker } from "../components/ProgressTracker";
import { useSSE } from "../hooks/useSSE";

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

function fileIcon(mime: string): string {
  if (mime.startsWith("text/html")) return "HTML";
  if (mime === "application/json") return "JSON";
  if (mime.startsWith("text/")) return "TXT";
  if (mime.startsWith("image/")) return "IMG";
  return "BIN";
}

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

  // Check for existing results on mount (from a previous retrieval)
  const loadResults = useCallback(() => {
    if (!jobId) return;
    apiFetch<ResultsData>(`/jobs/${jobId}/results`)
      .then((data) => {
        setResults(data);
        // Auto-select the primary HTML report if available
        const html = data.files.find((f) => f.mime.startsWith("text/html"));
        if (html) setSelectedFile(html);
      })
      .catch(() => {
        // No results yet — that's fine
      });
  }, [jobId]);

  useEffect(() => {
    loadResults();
  }, [loadResults]);

  // Reload results list after SSE completes
  useEffect(() => {
    if (sse.result) {
      loadResults();
    }
  }, [sse.result, loadResults]);

  // Load file content when a file is selected
  useEffect(() => {
    if (!selectedFile || !jobId) {
      setFileContent(null);
      return;
    }

    const isText =
      selectedFile.mime.startsWith("text/") ||
      selectedFile.mime === "application/json";

    // For HTML, we use an iframe pointed at the raw file endpoint — no fetch needed
    if (selectedFile.mime.startsWith("text/html")) {
      setFileContent(null);
      return;
    }

    if (!isText) {
      setFileContent(null);
      return;
    }

    // Text/JSON — fetch content
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

  if (loading) return <div className="loading">Loading job details...</div>;
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

  return (
    <motion.div variants={fadeInUp} initial="initial" animate="animate">
      <div style={{ marginBottom: "16px" }}>
        <Link to="/jobs" style={{ fontSize: "14px", color: "var(--text-dim)" }}>
          &larr; Back to Jobs
        </Link>
      </div>

      <div className="page-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <h1 style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            Job Details
            <StatusBadge status={job.status} />
          </h1>
          <p style={{ fontFamily: "monospace", fontSize: "13px" }}>{job.job_id}</p>
        </div>
        {job.status.toLowerCase() === "completed" && (
          <button
            className="btn-primary"
            onClick={handleGetResults}
            disabled={sse.active}
          >
            {sse.active ? "Downloading..." : results ? "Re-download Results" : "Get Results"}
          </button>
        )}
      </div>

      {/* SSE progress for result retrieval */}
      {(sse.active || sse.error) && (
        <ProgressTracker progress={sse.progress} error={sse.error} label="Retrieving Results" />
      )}

      {/* Results viewer */}
      {results && results.files.length > 0 && (
        <div className="card" style={{ marginBottom: "24px", padding: 0, overflow: "hidden" }}>
          <div style={{
            padding: "16px 20px",
            borderBottom: "1px solid var(--border)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}>
            <div>
              <div style={{ fontSize: "12px", color: "var(--text-dim)", textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: "4px" }}>
                Decrypted Results
              </div>
              <div style={{ fontSize: "13px", color: "var(--text-dim)" }}>
                {results.files.length} file{results.files.length !== 1 ? "s" : ""}
              </div>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "12px", color: "var(--green)" }}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                <path d="M9 12l2 2 4-4" />
              </svg>
              Decrypted locally
            </div>
          </div>

          <div style={{ display: "flex", minHeight: "400px" }}>
            {/* File list sidebar */}
            <div style={{
              width: "260px",
              flexShrink: 0,
              borderRight: "1px solid var(--border)",
              overflowY: "auto",
              maxHeight: "600px",
            }}>
              {results.files.map((file) => (
                <button
                  key={file.path}
                  onClick={() => setSelectedFile(file)}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "10px",
                    width: "100%",
                    padding: "10px 16px",
                    border: "none",
                    borderBottom: "1px solid var(--border)",
                    background: selectedFile?.path === file.path
                      ? "rgba(99, 102, 241, 0.1)"
                      : "transparent",
                    cursor: "pointer",
                    textAlign: "left",
                    color: "var(--text)",
                    transition: "background 0.15s",
                  }}
                  onMouseEnter={(e) => {
                    if (selectedFile?.path !== file.path)
                      e.currentTarget.style.background = "rgba(255,255,255,0.03)";
                  }}
                  onMouseLeave={(e) => {
                    if (selectedFile?.path !== file.path)
                      e.currentTarget.style.background = "transparent";
                  }}
                >
                  <span style={{
                    fontSize: "10px",
                    fontWeight: 700,
                    padding: "2px 6px",
                    borderRadius: "4px",
                    background: file.mime.startsWith("text/html")
                      ? "rgba(99, 102, 241, 0.15)"
                      : file.mime === "application/json"
                        ? "rgba(234, 179, 8, 0.15)"
                        : "rgba(255,255,255,0.06)",
                    color: file.mime.startsWith("text/html")
                      ? "var(--accent)"
                      : file.mime === "application/json"
                        ? "var(--yellow)"
                        : "var(--text-dim)",
                    flexShrink: 0,
                  }}>
                    {fileIcon(file.mime)}
                  </span>
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div style={{
                      fontSize: "13px",
                      fontWeight: selectedFile?.path === file.path ? 600 : 400,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}>
                      {file.name}
                    </div>
                    {file.path !== file.name && (
                      <div style={{
                        fontSize: "11px",
                        color: "var(--text-dim)",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}>
                        {file.path}
                      </div>
                    )}
                    <div style={{ fontSize: "11px", color: "var(--text-dim)" }}>
                      {formatSize(file.size)}
                    </div>
                  </div>
                </button>
              ))}
            </div>

            {/* File content viewer */}
            <div style={{ flex: 1, overflow: "hidden", position: "relative" }}>
              {!selectedFile && (
                <div style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  height: "100%",
                  color: "var(--text-dim)",
                  fontSize: "14px",
                }}>
                  Select a file to view
                </div>
              )}

              {selectedFile && fileLoading && (
                <div style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  height: "100%",
                  color: "var(--text-dim)",
                }}>
                  Loading...
                </div>
              )}

              {/* HTML in iframe */}
              {selectedFile && isHtml && fileUrl && (
                <iframe
                  src={fileUrl}
                  title={selectedFile.name}
                  style={{
                    width: "100%",
                    height: "100%",
                    border: "none",
                    background: "#fff",
                  }}
                />
              )}

              {/* Text / JSON content */}
              {selectedFile && isText && fileContent !== null && !fileLoading && (
                <pre style={{
                  margin: 0,
                  padding: "16px",
                  fontSize: "12px",
                  fontFamily: "'Cascadia Code', 'Fira Code', 'JetBrains Mono', monospace",
                  lineHeight: 1.6,
                  overflowY: "auto",
                  maxHeight: "600px",
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                  color: "var(--text)",
                }}>
                  {fileContent}
                </pre>
              )}

              {/* Image preview */}
              {selectedFile && isImage && fileUrl && (
                <div style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  height: "100%",
                  padding: "16px",
                }}>
                  <img
                    src={fileUrl}
                    alt={selectedFile.name}
                    style={{ maxWidth: "100%", maxHeight: "100%", objectFit: "contain" }}
                  />
                </div>
              )}

              {/* Binary / unsupported — download prompt */}
              {selectedFile && !isHtml && !isText && !isImage && !fileLoading && (
                <div style={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  justifyContent: "center",
                  height: "100%",
                  gap: "12px",
                  color: "var(--text-dim)",
                }}>
                  <div style={{ fontSize: "14px" }}>
                    Binary file ({formatSize(selectedFile.size)})
                  </div>
                  {downloadUrl && (
                    <a
                      href={downloadUrl}
                      download={selectedFile.name}
                      className="btn-secondary"
                      style={{ textDecoration: "none" }}
                    >
                      Download {selectedFile.name}
                    </a>
                  )}
                </div>
              )}

              {/* Download bar for viewable files */}
              {selectedFile && downloadUrl && (isHtml || isText || isImage) && (
                <div style={{
                  position: "absolute",
                  bottom: 0,
                  right: 0,
                  padding: "8px 12px",
                  background: "var(--surface)",
                  borderTop: "1px solid var(--border)",
                  borderLeft: "1px solid var(--border)",
                  borderRadius: "8px 0 0 0",
                }}>
                  <a
                    href={downloadUrl}
                    download={selectedFile.name}
                    style={{ fontSize: "12px", color: "var(--accent)", textDecoration: "none" }}
                  >
                    Download
                  </a>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Metadata */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px", marginBottom: "24px" }}>
        <div className="card">
          <div style={{ fontSize: "12px", color: "var(--text-dim)", textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: "8px" }}>
            Pipeline
          </div>
          <div style={{ fontSize: "16px", fontWeight: 600 }}>{job.plugin_name}</div>
        </div>
        <div className="card">
          <div style={{ fontSize: "12px", color: "var(--text-dim)", textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: "8px" }}>
            Submitted
          </div>
          <div style={{ fontSize: "16px" }}>{new Date(job.created_at).toLocaleString()}</div>
        </div>
      </div>

      {job.description && (
        <div className="card" style={{ marginBottom: "24px" }}>
          <div style={{ fontSize: "12px", color: "var(--text-dim)", textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: "8px" }}>
            Description
          </div>
          <div>{job.description}</div>
        </div>
      )}

      {/* Timeline */}
      {job.timeline && job.timeline.length > 0 && (
        <div className="card">
          <div style={{ fontSize: "12px", color: "var(--text-dim)", textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: "16px" }}>
            Timeline
          </div>
          <div className="timeline">
            {job.timeline.map((event, i) => (
              <div key={i} className="timeline-item">
                <div className="phase">{event.phase}</div>
                <div className="time">{new Date(event.timestamp).toLocaleString()}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* CLI hint */}
      <div style={{ marginTop: "24px" }}>
        <div className="cli-hint">
          byod status {job.job_id}
        </div>
      </div>
    </motion.div>
  );
}
