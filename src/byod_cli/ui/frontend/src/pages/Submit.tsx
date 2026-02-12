import { useState, useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { slideInRight, slideInLeft, drawPath, successContainer, successItem } from "../animations/variants";
import { apiFetch } from "../hooks/useApi";
import { useSSE } from "../hooks/useSSE";
import { FileDropZone } from "../components/FileDropZone";
import { SecurityBanner } from "../components/SecurityBanner";
import { ProgressTracker } from "../components/ProgressTracker";
import { SkeletonChecklist } from "../components/Skeleton";

interface Plugin {
  name: string;
  description: string;
  version?: string;
  input_type?: string;
  tags?: string[];
}

interface HealthStatus {
  authenticated: boolean;
  tenant_valid: boolean;
  tenant_error: string | null;
  kms_key_configured: boolean;
  kms_key_error: string | null;
  role_configured: boolean;
  role_error: string | null;
}

const steps = ["Pipeline", "Files", "Review"];

export function Submit() {
  const [step, setStep] = useState(0);
  const [direction, setDirection] = useState(1);
  const [plugins, setPlugins] = useState<Plugin[]>([]);
  const [selectedPlugin, setSelectedPlugin] = useState<string>("");
  const [files, setFiles] = useState<File[]>([]);
  const [description, setDescription] = useState("");
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [healthLoading, setHealthLoading] = useState(true);
  const navigate = useNavigate();
  const sse = useSSE();

  useEffect(() => {
    apiFetch<HealthStatus>("/status")
      .then(setHealth)
      .catch(() => {})
      .finally(() => setHealthLoading(false));
  }, []);

  const healthy =
    health?.authenticated &&
    health?.tenant_valid &&
    health?.kms_key_configured &&
    health?.role_configured;

  useEffect(() => {
    // Only load plugins once health checks pass
    if (healthy) {
      apiFetch<Plugin[]>("/plugins").then(setPlugins).catch(() => {});
    }
  }, [healthy]);

  const goNext = () => {
    setDirection(1);
    setStep((s) => Math.min(s + 1, steps.length - 1));
  };

  const goBack = () => {
    setDirection(-1);
    setStep((s) => Math.max(s - 1, 0));
  };

  const handleRemoveFile = (index: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const handleSubmit = async () => {
    if (files.length === 0 || !selectedPlugin) return;

    const formData = new FormData();
    for (const f of files) {
      formData.append("files", f);
    }
    formData.append("plugin", selectedPlugin);
    formData.append("description", description);

    sse.start("/api/submit", {
      method: "POST",
      body: formData,
    });
  };

  const totalSize = files.reduce((sum, f) => sum + f.size, 0);
  const variants = direction > 0 ? slideInRight : slideInLeft;

  // Success state
  if (sse.result) {
    const result = sse.result as Record<string, string>;
    return (
      <motion.div
        className="success-content"
        variants={successContainer}
        initial="initial"
        animate="animate"
      >
        <motion.div className="success-icon confetti-container" variants={successItem}>
          <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="var(--green)" strokeWidth="2">
            <circle cx="12" cy="12" r="10" />
            <motion.path d="M9 12l2 2 4-4" variants={drawPath} initial="initial" animate="animate" />
          </svg>
          {/* Confetti particles */}
          {[
            { color: "var(--green)", target: "translate(-30px, -30px) scale(1)" },
            { color: "var(--accent)", target: "translate(30px, -25px) scale(1)" },
            { color: "var(--yellow)", target: "translate(-25px, 30px) scale(1)" },
            { color: "var(--blue)", target: "translate(35px, 20px) scale(1)" },
            { color: "var(--green)", target: "translate(0px, -35px) scale(1)" },
            { color: "var(--accent)", target: "translate(-35px, 5px) scale(1)" },
          ].map((p, i) => (
            <span
              key={i}
              className="confetti-particle"
              style={{
                background: p.color,
                top: "50%",
                left: "50%",
                animationDelay: `${i * 0.08}s`,
                "--confetti-target": p.target,
              } as React.CSSProperties}
            />
          ))}
        </motion.div>
        <motion.h2 variants={successItem}>Job Submitted!</motion.h2>
        <motion.div className="job-id" variants={successItem}>
          <code style={{ background: "var(--surface)", padding: "4px 12px", borderRadius: "6px", border: "1px solid var(--border)" }}>
            {result.job_id}
          </code>
        </motion.div>
        <motion.p variants={successItem} style={{ color: "var(--text-dim)", marginBottom: "24px" }}>
          Your data was encrypted locally and submitted for processing.
        </motion.p>
        <motion.div className="success-actions" variants={successItem}>
          <button className="btn-primary" onClick={() => navigate(`/jobs/${result.job_id}`)}>
            View Job
          </button>
          <button className="btn-secondary" onClick={() => { sse.reset(); setStep(0); setFiles([]); setSelectedPlugin(""); setDescription(""); }}>
            Submit Another
          </button>
        </motion.div>
      </motion.div>
    );
  }

  // Submitting state
  if (sse.active || sse.error) {
    return (
      <div>
        <div className="page-header">
          <h1>Submitting Job</h1>
          <p>Encrypting and uploading your data...</p>
        </div>
        <SecurityBanner />
        <ProgressTracker progress={sse.progress} error={sse.error} label="Submission Progress" />
        {sse.error && (
          <div style={{ marginTop: "16px" }}>
            <button className="btn-secondary" onClick={sse.reset}>Try Again</button>
          </div>
        )}
      </div>
    );
  }

  // Health gate — block submission if checks don't pass
  if (healthLoading) {
    return (
      <div>
        <div className="page-header">
          <h1>Submit Job</h1>
          <p>Encrypt and submit data for secure processing</p>
        </div>
        <SkeletonChecklist items={4} />
      </div>
    );
  }

  if (!healthy) {
    const issues: string[] = [];
    if (!health?.authenticated) issues.push("Not authenticated");
    if (health?.authenticated && !health?.tenant_valid)
      issues.push(health?.tenant_error || "Tenant is not active");
    if (!health?.kms_key_configured)
      issues.push(health?.kms_key_error || "KMS key not configured");
    if (!health?.role_configured)
      issues.push(health?.role_error || "IAM role not configured");

    return (
      <div>
        <div className="page-header">
          <h1>Submit Job</h1>
          <p>Encrypt and submit data for secure processing</p>
        </div>
        <div
          className="card"
          style={{
            textAlign: "center",
            padding: "48px 24px",
          }}
        >
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="var(--yellow)" strokeWidth="2" style={{ marginBottom: "16px" }}>
            <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
            <line x1="12" y1="9" x2="12" y2="13" />
            <line x1="12" y1="17" x2="12.01" y2="17" />
          </svg>
          <h2 style={{ marginBottom: "8px" }}>Setup Required</h2>
          <p style={{ color: "var(--text-dim)", marginBottom: "20px", maxWidth: "400px", margin: "0 auto 20px" }}>
            All prerequisites must be met before you can submit jobs.
          </p>
          <div style={{ display: "flex", flexDirection: "column", gap: "8px", alignItems: "center", marginBottom: "24px" }}>
            {issues.map((issue) => (
              <div
                key={issue}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "8px",
                  fontSize: "14px",
                  color: "var(--red)",
                }}
              >
                <span style={{ fontSize: "12px" }}>{"\u2717"}</span>
                {issue}
              </div>
            ))}
          </div>
          <Link to="/setup" className="btn-primary" style={{ textDecoration: "none" }}>
            Go to Setup
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="page-header">
        <h1>Submit Job</h1>
        <p>Encrypt and submit data for secure processing</p>
      </div>

      {/* Wizard steps indicator */}
      <div className="wizard-steps">
        {steps.map((label, i) => (
          <div key={label} style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            {i > 0 && <div className="step-connector" />}
            <div className={`wizard-step ${i === step ? "active" : i < step ? "completed" : ""}`}>
              <div className="step-number">{i < step ? "\u2713" : i + 1}</div>
              <span className="step-label">{label}</span>
            </div>
          </div>
        ))}
      </div>

      <div className="wizard-content">
        <AnimatePresence mode="wait">
          {step === 0 && (
            <motion.div key="step-0" variants={variants} initial="initial" animate="animate" exit="exit" className="step-content">
              <h2>Select Pipeline</h2>
              <p>Choose the analysis pipeline for your data</p>
              {plugins.length === 0 ? (
                <div className="loading">Loading pipelines...</div>
              ) : (
                <div className="pipeline-grid">
                  {plugins.map((p) => (
                    <div
                      key={p.name}
                      className={`pipeline-card ${selectedPlugin === p.name ? "selected" : ""}`}
                      onClick={() => setSelectedPlugin(p.name)}
                    >
                      <h3>{p.name}</h3>
                      <div className="desc">{p.description}</div>
                      {p.tags?.map((tag) => (
                        <span key={tag} className="tag">{tag}</span>
                      ))}
                      {p.input_type && (
                        <div style={{ marginTop: "8px", fontSize: "12px", color: "var(--text-dim)" }}>
                          Input: {p.input_type}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
              <div className="step-actions">
                <button className="btn-primary" disabled={!selectedPlugin} onClick={goNext}>
                  Continue
                </button>
              </div>
            </motion.div>
          )}

          {step === 1 && (
            <motion.div key="step-1" variants={variants} initial="initial" animate="animate" exit="exit" className="step-content">
              <h2>Upload Files</h2>
              <p>Select the file(s) you want to process</p>
              <FileDropZone
                files={files}
                onFilesSelect={setFiles}
                onClear={() => setFiles([])}
                onRemove={handleRemoveFile}
              />
              <div className="input-group" style={{ marginTop: "20px" }}>
                <label>Description (optional)</label>
                <input
                  type="text"
                  className="description-input"
                  placeholder="Brief description of this job..."
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                />
              </div>
              <div className="step-actions">
                <button className="btn-secondary" onClick={goBack}>Back</button>
                <button className="btn-primary" disabled={files.length === 0} onClick={goNext}>
                  Continue
                </button>
              </div>
            </motion.div>
          )}

          {step === 2 && (
            <motion.div key="step-2" variants={variants} initial="initial" animate="animate" exit="exit" className="step-content">
              <h2>Review & Submit</h2>
              <p>Confirm your submission details</p>
              <SecurityBanner />
              <div className="review-card">
                <div className="review-section">
                  <h4>Pipeline</h4>
                  <p style={{ fontSize: "15px" }}>{selectedPlugin}</p>
                </div>
                <div className="review-section">
                  <h4>Files</h4>
                  {files.length === 1 ? (
                    <p style={{ fontSize: "15px" }}>{files[0].name} ({formatBytes(files[0].size)})</p>
                  ) : (
                    <div>
                      <p style={{ fontSize: "15px", marginBottom: "8px" }}>
                        {files.length} files ({formatBytes(totalSize)})
                      </p>
                      <div style={{ fontSize: "13px", color: "var(--text-dim)" }}>
                        {files.map((f, i) => (
                          <div key={i} style={{ fontFamily: "monospace", fontSize: "12px" }}>
                            {f.name} ({formatBytes(f.size)})
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
                {description && (
                  <div className="review-section">
                    <h4>Description</h4>
                    <p style={{ fontSize: "15px" }}>{description}</p>
                  </div>
                )}
              </div>
              <div className="step-actions">
                <button className="btn-secondary" onClick={goBack}>Back</button>
                <button className="btn-primary" onClick={handleSubmit}>
                  Encrypt & Submit
                </button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}
