import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import { staggerContainer, staggerItem } from "../animations/variants";
import { useApi } from "../hooks/useApi";
import { StatusBadge } from "../components/StatusBadge";

interface StatusData {
  authenticated: boolean;
  profile: string | null;
  api_url: string;
  api_reachable: boolean;
  version: string;
  tenant_valid: boolean;
  tenant_id: string | null;
  tenant_error: string | null;
  kms_key_configured: boolean;
  kms_key_error: string | null;
  role_configured: boolean;
  role_error: string | null;
}

interface Job {
  job_id: string;
  plugin_name: string;
  status: string;
  created_at: string;
}

export function Home() {
  const { data: status, loading: statusLoading } = useApi<StatusData>("/status");
  const { data: jobs, loading: jobsLoading, error: jobsError } = useApi<Job[]>("/jobs?limit=5");
  const [awsOk, setAwsOk] = useState<boolean | null>(null);

  useEffect(() => {
    fetch("/api/status/aws")
      .then((r) => r.json())
      .then((d) => setAwsOk(d.configured))
      .catch(() => setAwsOk(false));
  }, []);

  const jobCounts = (jobs || []).reduce(
    (acc, j) => {
      acc.total++;
      const s = j.status.toLowerCase();
      if (s === "completed") acc.completed++;
      else if (s === "processing") acc.processing++;
      else if (s === "failed") acc.failed++;
      return acc;
    },
    { total: 0, completed: 0, processing: 0, failed: 0 }
  );

  // Determine overall health
  const tenantOk = status?.tenant_valid ?? false;
  const allHealthy = tenantOk && awsOk && status?.kms_key_configured;

  return (
    <div>
      <div className="page-header">
        <h1>Welcome to BYOD</h1>
        <p>Secure biotech data processing with zero-knowledge encryption</p>
      </div>

      {/* Tenant health banner — stale/invalid tenant */}
      {!statusLoading && status?.tenant_error && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          style={{
            background: "rgba(239, 68, 68, 0.08)",
            border: "1px solid rgba(239, 68, 68, 0.25)",
            borderRadius: "12px",
            padding: "20px 24px",
            marginBottom: "24px",
          }}
        >
          <div style={{ display: "flex", alignItems: "flex-start", gap: "12px" }}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--red)" strokeWidth="2" style={{ flexShrink: 0, marginTop: "2px" }}>
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="8" x2="12" y2="12" />
              <line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
            <div>
              <div style={{ fontWeight: 600, marginBottom: "4px", color: "var(--red)" }}>
                Tenant issue detected
              </div>
              <div style={{ color: "var(--text-dim)", fontSize: "14px", marginBottom: "12px" }}>
                {status.tenant_error}
              </div>
              <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                {status.tenant_error.includes("API key") && (
                  <div className="cli-hint" style={{ display: "inline-block" }}>byod auth login</div>
                )}
                {status.tenant_error.includes("tenant") && (
                  <a
                    href={status.api_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="btn-small"
                  >
                    Open Dashboard
                  </a>
                )}
                <Link to="/setup" className="btn-small">Re-run Setup</Link>
              </div>
            </div>
          </div>
        </motion.div>
      )}

      {/* Setup needed banner (no auth or no AWS) */}
      {!statusLoading && !status?.tenant_error && (!status?.authenticated || awsOk === false) && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          style={{
            background: "rgba(234, 179, 8, 0.08)",
            border: "1px solid rgba(234, 179, 8, 0.2)",
            borderRadius: "12px",
            padding: "20px 24px",
            marginBottom: "24px",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <div>
            <div style={{ fontWeight: 600, marginBottom: "4px" }}>Setup required</div>
            <div style={{ color: "var(--text-dim)", fontSize: "14px" }}>
              {!status?.authenticated
                ? "Run 'byod auth login' in your terminal to authenticate, then refresh."
                : "AWS credentials not detected. Configure your ~/.aws/credentials."}
            </div>
          </div>
          <Link to="/setup" className="btn-primary" style={{ flexShrink: 0 }}>
            Run Setup
          </Link>
        </motion.div>
      )}

      {/* KMS/Role warning — missing or destroyed AWS resources */}
      {!statusLoading && tenantOk && (!status?.kms_key_configured || !status?.role_configured) && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          style={{
            background: (status?.kms_key_error || status?.role_error)
              ? "rgba(239, 68, 68, 0.08)"
              : "rgba(234, 179, 8, 0.08)",
            border: `1px solid ${(status?.kms_key_error || status?.role_error)
              ? "rgba(239, 68, 68, 0.25)"
              : "rgba(234, 179, 8, 0.2)"}`,
            borderRadius: "12px",
            padding: "20px 24px",
            marginBottom: "24px",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
            <div>
              <div style={{ fontWeight: 600, marginBottom: "4px" }}>
                {(status?.kms_key_error || status?.role_error)
                  ? "AWS resources missing"
                  : "KMS setup incomplete"}
              </div>
              <div style={{ color: "var(--text-dim)", fontSize: "14px" }}>
                {status?.kms_key_error && status?.role_error
                  ? "KMS key and IAM role no longer exist in AWS. Re-run setup to recreate them."
                  : status?.kms_key_error
                    ? status.kms_key_error
                    : status?.role_error
                      ? status.role_error
                      : !status?.kms_key_configured && !status?.role_configured
                        ? "KMS key and IAM role are not configured. Run setup to create them."
                        : !status?.kms_key_configured
                          ? "KMS key is not configured."
                          : "IAM role is not configured."}
              </div>
            </div>
            <Link to="/setup" className="btn-primary" style={{ flexShrink: 0 }}>
              {(status?.kms_key_error || status?.role_error) ? "Re-run Setup" : "Run Setup"}
            </Link>
          </div>
        </motion.div>
      )}

      {/* Status cards */}
      <motion.div
        className="stats-row"
        variants={staggerContainer}
        initial="initial"
        animate="animate"
      >
        <motion.div className="stat-card" variants={staggerItem}>
          <div className="label">Authentication</div>
          <div className="value" style={{ fontSize: "18px" }}>
            {statusLoading ? (
              <span className="loading-spinner" />
            ) : status?.authenticated ? (
              <span style={{ color: "var(--green)" }}>Connected</span>
            ) : (
              <span style={{ color: "var(--red)" }}>Not authenticated</span>
            )}
          </div>
          {status?.profile && (
            <div style={{ fontSize: "12px", color: "var(--text-dim)", marginTop: "4px" }}>
              Profile: {status.profile}
            </div>
          )}
        </motion.div>

        <motion.div className="stat-card" variants={staggerItem}>
          <div className="label">Tenant</div>
          <div className="value" style={{ fontSize: "18px" }}>
            {statusLoading ? (
              <span className="loading-spinner" />
            ) : tenantOk ? (
              <span style={{ color: "var(--green)" }}>Active</span>
            ) : status?.authenticated ? (
              <span style={{ color: "var(--red)" }}>Invalid</span>
            ) : (
              <span style={{ color: "var(--text-dim)" }}>—</span>
            )}
          </div>
          {status?.tenant_id && (
            <div style={{ fontSize: "12px", color: "var(--text-dim)", marginTop: "4px", fontFamily: "monospace" }}>
              {status.tenant_id.slice(0, 12)}...
            </div>
          )}
        </motion.div>

        <motion.div className="stat-card" variants={staggerItem}>
          <div className="label">AWS Credentials</div>
          <div className="value" style={{ fontSize: "18px" }}>
            {awsOk === null ? (
              <span className="loading-spinner" />
            ) : awsOk ? (
              <span style={{ color: "var(--green)" }}>Configured</span>
            ) : (
              <span style={{ color: "var(--yellow)" }}>Not found</span>
            )}
          </div>
        </motion.div>

        <motion.div className="stat-card" variants={staggerItem}>
          <div className="label">CLI Version</div>
          <div className="value" style={{ fontSize: "18px" }}>
            {status?.version || <span className="loading-spinner" />}
          </div>
          {status?.api_url && (
            <div style={{ fontSize: "12px", color: "var(--text-dim)", marginTop: "4px" }}>
              {status.api_url}
            </div>
          )}
        </motion.div>
      </motion.div>

      {/* Quick actions */}
      <div style={{ display: "flex", gap: "16px", marginBottom: "32px" }}>
        <Link
          to="/submit"
          className="btn-primary"
          style={{
            textDecoration: "none",
            opacity: allHealthy ? 1 : 0.5,
            pointerEvents: allHealthy ? "auto" : "none",
          }}
        >
          Submit New Job
        </Link>
        <Link to="/jobs" className="btn-secondary" style={{ textDecoration: "none" }}>
          View All Jobs
        </Link>
      </div>

      {/* Job stats row */}
      {!jobsLoading && !jobsError && jobs && jobs.length > 0 && (
        <motion.div
          className="stats-row"
          variants={staggerContainer}
          initial="initial"
          animate="animate"
          style={{ marginBottom: "24px" }}
        >
          <motion.div className="stat-card" variants={staggerItem}>
            <div className="label">Total Jobs</div>
            <div className="value">{jobCounts.total}</div>
          </motion.div>
          <motion.div className="stat-card" variants={staggerItem}>
            <div className="label">Completed</div>
            <div className="value" style={{ color: "var(--green)" }}>{jobCounts.completed}</div>
          </motion.div>
          <motion.div className="stat-card" variants={staggerItem}>
            <div className="label">Processing</div>
            <div className="value" style={{ color: "var(--yellow)" }}>{jobCounts.processing}</div>
          </motion.div>
          <motion.div className="stat-card" variants={staggerItem}>
            <div className="label">Failed</div>
            <div className="value" style={{ color: "var(--red)" }}>{jobCounts.failed}</div>
          </motion.div>
        </motion.div>
      )}

      {/* Recent jobs */}
      <div className="card" style={{ padding: 0 }}>
        <div style={{ padding: "20px 24px", borderBottom: "1px solid var(--border)" }}>
          <h2 style={{ fontSize: "18px", fontWeight: 600 }}>Recent Jobs</h2>
        </div>
        {jobsLoading ? (
          <div className="loading">Loading jobs...</div>
        ) : jobsError ? (
          <div style={{ padding: "32px 24px", textAlign: "center", color: "var(--text-dim)" }}>
            <p style={{ marginBottom: "8px" }}>Could not load jobs</p>
            <p style={{ fontSize: "13px" }}>
              {jobsError.includes("401") || jobsError.includes("authenticated")
                ? "Authentication required — run 'byod auth login' first."
                : jobsError.includes("502") || jobsError.includes("connect")
                  ? "API server is unreachable. Check your connection."
                  : jobsError}
            </p>
          </div>
        ) : !jobs || jobs.length === 0 ? (
          <div style={{ padding: "48px 24px", textAlign: "center", color: "var(--text-dim)" }}>
            <p style={{ marginBottom: "12px" }}>No jobs yet</p>
            {allHealthy && (
              <Link to="/submit" className="btn-primary" style={{ textDecoration: "none" }}>
                Submit your first job
              </Link>
            )}
          </div>
        ) : (
          <div className="table-container">
            <table>
              <thead>
                <tr>
                  <th>Job ID</th>
                  <th>Pipeline</th>
                  <th>Status</th>
                  <th>Submitted</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((job) => (
                  <tr key={job.job_id} onClick={() => window.location.href = `/jobs/${job.job_id}`}>
                    <td style={{ fontFamily: "monospace", fontSize: "13px" }}>
                      {job.job_id.slice(0, 8)}...
                    </td>
                    <td>{job.plugin_name}</td>
                    <td><StatusBadge status={job.status} /></td>
                    <td style={{ color: "var(--text-dim)" }}>
                      {new Date(job.created_at).toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
