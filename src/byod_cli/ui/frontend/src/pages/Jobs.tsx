import { useState, useEffect, useCallback } from "react";
import { Link, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { staggerContainer, staggerItem } from "../animations/variants";
import { apiFetch } from "../hooks/useApi";
import { StatusBadge } from "../components/StatusBadge";
import { SkeletonTable } from "../components/Skeleton";

interface Job {
  job_id: string;
  plugin_name: string;
  status: string;
  created_at: string;
  description?: string;
}

export function Jobs() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const navigate = useNavigate();

  const fetchJobs = useCallback(() => {
    apiFetch<Job[]>("/jobs?limit=50")
      .then(setJobs)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    fetchJobs();
    const interval = setInterval(fetchJobs, 10000);
    return () => clearInterval(interval);
  }, [fetchJobs]);

  const filtered = filter
    ? jobs.filter((j) => j.status.toLowerCase() === filter.toLowerCase())
    : jobs;

  const statusCounts = jobs.reduce<Record<string, number>>((acc, j) => {
    const s = j.status.toLowerCase();
    acc[s] = (acc[s] || 0) + 1;
    return acc;
  }, {});

  return (
    <div>
      <div className="page-header">
        <h1>Jobs</h1>
        <p>Monitor and manage your processing jobs</p>
      </div>

      {/* Filter bar */}
      <div style={{ display: "flex", gap: "8px", marginBottom: "24px", flexWrap: "wrap" }}>
        <button
          className={filter === "" ? "btn-primary" : "btn-secondary"}
          style={{ padding: "6px 14px", fontSize: "13px" }}
          onClick={() => setFilter("")}
        >
          All ({jobs.length})
        </button>
        {Object.entries(statusCounts).map(([status, count]) => (
          <button
            key={status}
            className={filter === status ? "btn-primary" : "btn-secondary"}
            style={{ padding: "6px 14px", fontSize: "13px" }}
            onClick={() => setFilter(filter === status ? "" : status)}
          >
            {status.charAt(0).toUpperCase() + status.slice(1)} ({count})
          </button>
        ))}
      </div>

      {error && <div className="error-message">{error}</div>}

      {loading ? (
        <div className="card" style={{ padding: 0 }}>
          <SkeletonTable rows={5} cols={5} />
        </div>
      ) : filtered.length === 0 ? (
        <div className="card" style={{ padding: 0 }}>
          <div className="empty-state">
            <svg className="empty-state-icon" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeDasharray="3 3">
              <rect x="3" y="3" width="18" height="18" rx="2" />
              <path d="M3 9h18" strokeDasharray="none" />
              <path d="M9 21V9" strokeDasharray="none" />
            </svg>
            <div className="empty-state-title">
              {filter ? `No ${filter} jobs` : "No jobs yet"}
            </div>
            <div className="empty-state-description">
              {filter
                ? "Try a different filter or check back later"
                : "Submit your first data processing job to get started"}
            </div>
            {!filter && (
              <Link to="/submit" className="btn-primary" style={{ textDecoration: "none" }}>
                Submit a Job
              </Link>
            )}
          </div>
        </div>
      ) : (
        <motion.div
          className="card"
          style={{ padding: 0 }}
          variants={staggerContainer}
          initial="initial"
          animate="animate"
        >
          <div className="table-container">
            <table>
              <thead>
                <tr>
                  <th>Job ID</th>
                  <th>Pipeline</th>
                  <th>Status</th>
                  <th>Description</th>
                  <th>Submitted</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((job) => (
                  <motion.tr
                    key={job.job_id}
                    className={`row-${job.status.toLowerCase()}`}
                    variants={staggerItem}
                    onClick={() => navigate(`/jobs/${job.job_id}`)}
                    style={{ cursor: "pointer" }}
                  >
                    <td style={{ fontFamily: "monospace", fontSize: "12px", whiteSpace: "nowrap" }}>
                      {job.job_id}
                    </td>
                    <td>{job.plugin_name}</td>
                    <td><StatusBadge status={job.status} /></td>
                    <td style={{ color: "var(--text-dim)", maxWidth: "200px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {job.description || "\u2014"}
                    </td>
                    <td style={{ color: "var(--text-dim)" }}>
                      {new Date(job.created_at).toLocaleString()}
                    </td>
                  </motion.tr>
                ))}
              </tbody>
            </table>
          </div>
        </motion.div>
      )}

      <div style={{ marginTop: "16px", fontSize: "12px", color: "var(--text-dim)" }}>
        Auto-refreshes every 10 seconds
      </div>
    </div>
  );
}
