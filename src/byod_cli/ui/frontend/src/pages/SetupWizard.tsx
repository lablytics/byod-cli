import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import { fadeInUp } from "../animations/variants";
import { apiFetch } from "../hooks/useApi";
import { useSSE } from "../hooks/useSSE";
import { ProgressTracker } from "../components/ProgressTracker";

interface SetupStatus {
  authenticated: boolean;
  aws_configured: boolean;
  aws_account_id: string | null;
  tenant_valid: boolean;
  tenant_id: string | null;
  tenant_error: string | null;
  kms_key_configured: boolean;
  kms_key_arn: string | null;
  kms_key_error: string | null;
  role_configured: boolean;
  role_arn: string | null;
  role_error: string | null;
  registered: boolean;
}

export function SetupWizard() {
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [region, setRegion] = useState("us-east-1");
  const [forceNew, setForceNew] = useState(false);
  const sse = useSSE();

  useEffect(() => {
    apiFetch<SetupStatus>("/setup/status")
      .then(setStatus)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const handleRunSetup = () => {
    sse.start("/api/setup/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ region, force_new: forceNew }),
    });
  };

  const allGood =
    status?.authenticated &&
    status?.aws_configured &&
    status?.tenant_valid &&
    status?.kms_key_configured &&
    status?.registered;

  // Can we start the setup flow? Need auth + AWS + valid tenant
  const canRunSetup =
    status?.authenticated && status?.aws_configured && status?.tenant_valid;

  // Setup complete — show success
  if (sse.result) {
    const result = sse.result as Record<string, string>;
    return (
      <div className="success-content">
        <div className="success-icon">
          <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="var(--green)" strokeWidth="2">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
            <path d="M9 12l2 2 4-4" />
          </svg>
        </div>
        <h2>Setup Complete!</h2>
        <p style={{ color: "var(--text-dim)", marginBottom: "16px" }}>
          Your KMS key and IAM role have been configured with attestation enforcement.
        </p>
        <div className="review-card" style={{ textAlign: "left", maxWidth: "600px", margin: "0 auto" }}>
          <div className="review-section">
            <h4>KMS Key ARN</h4>
            <p style={{ fontFamily: "monospace", fontSize: "12px", wordBreak: "break-all" }}>{result.kms_key_arn}</p>
          </div>
          <div className="review-section">
            <h4>IAM Role ARN</h4>
            <p style={{ fontFamily: "monospace", fontSize: "12px", wordBreak: "break-all" }}>{result.role_arn}</p>
          </div>
          <div className="review-section">
            <h4>Region</h4>
            <p>{result.region}</p>
          </div>
          <div className="review-section">
            <h4>Security Guarantees</h4>
            <ul style={{ fontSize: "13px", color: "var(--text-dim)", paddingLeft: "18px", margin: "4px 0 0 0" }}>
              <li>Only you can manage/delete the KMS key</li>
              <li>Only the Nitro Enclave (with PCR0 verification) can decrypt</li>
              <li>Lablytics operators cannot access your data</li>
            </ul>
          </div>
        </div>
        <div className="success-actions">
          <Link to="/" className="btn-primary" style={{ textDecoration: "none" }}>Go to Home</Link>
          <Link to="/submit" className="btn-secondary" style={{ textDecoration: "none" }}>Submit a Job</Link>
        </div>
      </div>
    );
  }

  return (
    <motion.div variants={fadeInUp} initial="initial" animate="animate">
      <div className="page-header">
        <h1>Setup Wizard</h1>
        <p>Configure your AWS KMS key and IAM role for secure data processing</p>
      </div>

      {loading ? (
        <div className="loading">Checking prerequisites...</div>
      ) : (
        <>
          {/* Tenant error banner */}
          {status?.tenant_error && (
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
                        href="/api/status"
                        onClick={(e) => {
                          e.preventDefault();
                          apiFetch<{ api_url: string }>("/status").then((s) => {
                            if (s.api_url) window.open(s.api_url, "_blank");
                          });
                        }}
                        className="btn-small"
                      >
                        Open Dashboard
                      </a>
                    )}
                  </div>
                </div>
              </div>
            </motion.div>
          )}

          {/* Prerequisites checklist */}
          <div className="card" style={{ marginBottom: "24px" }}>
            <h3 style={{ fontSize: "16px", marginBottom: "16px" }}>Prerequisites</h3>
            <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
              <CheckItem
                label="API Authentication"
                ok={status?.authenticated}
                hint="Run 'byod auth login' in your terminal"
              />
              <CheckItem
                label="AWS Credentials"
                ok={status?.aws_configured}
                hint="Configure ~/.aws/credentials or set AWS_ACCESS_KEY_ID"
                detail={status?.aws_account_id ? `Account: ${status.aws_account_id}` : undefined}
              />
              <CheckItem
                label="Tenant Account"
                ok={status?.tenant_valid}
                pending={status?.authenticated && !status?.tenant_valid && !status?.tenant_error}
                hint={
                  status?.tenant_error
                    ? status.tenant_error
                    : !status?.authenticated
                      ? "Authenticate first to check tenant status"
                      : "Tenant must exist and be active"
                }
                detail={status?.tenant_id ? `ID: ${status.tenant_id.slice(0, 16)}...` : undefined}
              />
              <CheckItem
                label="KMS Key"
                ok={status?.kms_key_configured}
                pending={!status?.kms_key_configured && status?.tenant_valid && !status?.kms_key_error}
                hint={
                  status?.kms_key_error
                    ? status.kms_key_error
                    : status?.kms_key_configured
                      ? ""
                      : "Will be created during setup"
                }
                detail={status?.kms_key_arn ? truncateArn(status.kms_key_arn) : undefined}
              />
              <CheckItem
                label="IAM Role"
                ok={status?.role_configured}
                pending={!status?.role_configured && status?.tenant_valid && !status?.role_error}
                hint={
                  status?.role_error
                    ? status.role_error
                    : status?.role_configured
                      ? ""
                      : "Will be created during setup"
                }
                detail={status?.role_arn ? truncateArn(status.role_arn) : undefined}
              />
            </div>
          </div>

          {allGood ? (
            <div className="card" style={{ marginBottom: "24px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "16px" }}>
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--green)" strokeWidth="2">
                  <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                  <path d="M9 12l2 2 4-4" />
                </svg>
                <div>
                  <div style={{ fontWeight: 600, color: "var(--green)" }}>Setup is complete!</div>
                  <div style={{ color: "var(--text-dim)", fontSize: "13px" }}>
                    Your KMS key and IAM role are configured. You can submit jobs.
                  </div>
                </div>
              </div>
              <div style={{ borderTop: "1px solid var(--border)", paddingTop: "16px" }}>
                <p style={{ color: "var(--text-dim)", fontSize: "13px", marginBottom: "12px" }}>
                  If you've destroyed and recreated your AWS resources, you can re-run setup to create new ones.
                </p>
                <button
                  className="btn-secondary"
                  onClick={() => setForceNew(true)}
                  style={{ fontSize: "13px" }}
                >
                  Re-run Setup with New Resources
                </button>
              </div>
            </div>
          ) : null}

          {/* Setup configuration — only if we can actually run setup */}
          {canRunSetup && (!allGood || forceNew) && (
            <div className="card" style={{ marginBottom: "24px" }}>
              <h3 style={{ fontSize: "16px", marginBottom: "16px" }}>Configuration</h3>

              <div className="input-group">
                <label>AWS Region</label>
                <select
                  className="text-input"
                  value={region}
                  onChange={(e) => setRegion(e.target.value)}
                  style={{ maxWidth: "300px" }}
                >
                  <option value="us-east-1">US East (N. Virginia)</option>
                  <option value="us-east-2">US East (Ohio)</option>
                  <option value="us-west-1">US West (N. California)</option>
                  <option value="us-west-2">US West (Oregon)</option>
                  <option value="eu-west-1">EU (Ireland)</option>
                  <option value="eu-central-1">EU (Frankfurt)</option>
                </select>
                <div className="input-hint">The AWS region where your KMS key will be created</div>
              </div>

              {/* Force-new option */}
              {(status?.kms_key_configured || status?.role_configured) && (
                <div style={{ marginTop: "16px", marginBottom: "16px" }}>
                  <label
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "10px",
                      cursor: "pointer",
                      fontSize: "14px",
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={forceNew}
                      onChange={(e) => setForceNew(e.target.checked)}
                      style={{ width: "16px", height: "16px", accentColor: "var(--accent)" }}
                    />
                    <span>
                      Replace existing resources
                      <span style={{ color: "var(--text-dim)", fontSize: "12px", display: "block" }}>
                        Delete current KMS key and IAM role, then create new ones.
                        Use this if your AWS resources were destroyed.
                      </span>
                    </span>
                  </label>
                </div>
              )}

              {forceNew && (
                <div
                  style={{
                    background: "rgba(234, 179, 8, 0.08)",
                    border: "1px solid rgba(234, 179, 8, 0.2)",
                    borderRadius: "8px",
                    padding: "12px 16px",
                    marginBottom: "16px",
                    fontSize: "13px",
                    color: "var(--yellow)",
                  }}
                >
                  Existing KMS key will be scheduled for deletion (7-day waiting period).
                  A new key and IAM role will be created and registered.
                </div>
              )}

              <button
                className="btn-primary"
                onClick={handleRunSetup}
                disabled={sse.active}
              >
                {sse.active ? "Running..." : forceNew ? "Replace & Re-run Setup" : "Run Setup"}
              </button>
            </div>
          )}

          {/* SSE progress */}
          {(sse.active || sse.error) && (
            <ProgressTracker progress={sse.progress} error={sse.error} label="Setup Progress" />
          )}

          {/* Hints for missing prerequisites */}
          {!status?.authenticated && (
            <div className="card" style={{ marginBottom: "24px", textAlign: "center" }}>
              <p style={{ color: "var(--text-dim)", marginBottom: "12px" }}>
                Authenticate first to get started
              </p>
              <div className="cli-hint" style={{ display: "inline-block" }}>
                byod auth login
              </div>
            </div>
          )}
          {status?.authenticated && !status?.aws_configured && (
            <div className="card" style={{ marginBottom: "24px", textAlign: "center" }}>
              <p style={{ color: "var(--text-dim)", marginBottom: "12px" }}>
                AWS credentials are needed to create your KMS key and IAM role
              </p>
              <div className="cli-hint" style={{ display: "inline-block" }}>
                aws configure
              </div>
              <div style={{ color: "var(--text-dim)", fontSize: "12px", marginTop: "8px" }}>
                Or set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables
              </div>
            </div>
          )}
        </>
      )}
    </motion.div>
  );
}

function CheckItem({
  label,
  ok,
  pending,
  hint,
  detail,
}: {
  label: string;
  ok?: boolean;
  pending?: boolean;
  hint: string;
  detail?: string;
}) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
      <div
        style={{
          width: "24px",
          height: "24px",
          borderRadius: "50%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: ok
            ? "rgba(34, 197, 94, 0.15)"
            : pending
              ? "rgba(234, 179, 8, 0.15)"
              : "rgba(239, 68, 68, 0.15)",
          color: ok
            ? "var(--green)"
            : pending
              ? "var(--yellow)"
              : "var(--red)",
          fontSize: "14px",
          flexShrink: 0,
        }}
      >
        {ok ? "\u2713" : pending ? "\u2022" : "\u2717"}
      </div>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontWeight: 500 }}>{label}</div>
        {!ok && hint && (
          <div style={{ fontSize: "12px", color: "var(--text-dim)" }}>{hint}</div>
        )}
        {detail && (
          <div
            style={{
              fontSize: "11px",
              color: "var(--text-dim)",
              fontFamily: "monospace",
              marginTop: "2px",
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {detail}
          </div>
        )}
      </div>
    </div>
  );
}

function truncateArn(arn: string): string {
  // Show last meaningful segment: arn:aws:kms:us-east-1:123456:key/abc-def → key/abc-def...
  const parts = arn.split(":");
  if (parts.length >= 6) {
    return `${parts.slice(-1)[0].slice(0, 32)}...`;
  }
  return arn.slice(0, 40) + "...";
}
