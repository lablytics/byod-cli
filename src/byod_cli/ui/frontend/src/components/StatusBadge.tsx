interface StatusBadgeProps {
  status: string;
}

const statusMap: Record<string, string> = {
  completed: "badge-completed",
  processing: "badge-processing",
  downloading: "badge-downloading",
  uploading: "badge-uploading",
  failed: "badge-failed",
  pending: "badge-pending",
  submitted: "badge-submitted",
};

function StatusIcon({ status }: { status: string }) {
  const s = status.toLowerCase();
  const size = 12;
  const sw = 2;

  if (s === "completed") {
    return (
      <span className="badge-icon" aria-hidden="true">
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round">
          <path d="M20 6L9 17l-5-5" />
        </svg>
      </span>
    );
  }

  if (s === "processing") {
    return (
      <span className="badge-icon" aria-hidden="true">
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={sw} strokeLinecap="round">
          <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
        </svg>
      </span>
    );
  }

  if (s === "failed") {
    return (
      <span className="badge-icon" aria-hidden="true">
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={sw} strokeLinecap="round">
          <circle cx="12" cy="12" r="10" />
          <path d="M15 9l-6 6M9 9l6 6" />
        </svg>
      </span>
    );
  }

  if (s === "uploading") {
    return (
      <span className="badge-icon" aria-hidden="true">
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={sw} strokeLinecap="round">
          <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
          <polyline points="17,8 12,3 7,8" />
          <line x1="12" y1="3" x2="12" y2="15" />
        </svg>
      </span>
    );
  }

  if (s === "downloading") {
    return (
      <span className="badge-icon" aria-hidden="true">
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={sw} strokeLinecap="round">
          <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
          <polyline points="7,10 12,15 17,10" />
          <line x1="12" y1="15" x2="12" y2="3" />
        </svg>
      </span>
    );
  }

  // pending / submitted — clock icon
  return (
    <span className="badge-icon" aria-hidden="true">
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={sw} strokeLinecap="round">
        <circle cx="12" cy="12" r="10" />
        <path d="M12 6v6l4 2" />
      </svg>
    </span>
  );
}

export function StatusBadge({ status }: StatusBadgeProps) {
  const cls = statusMap[status.toLowerCase()] || "badge-pending";
  return (
    <span className={`badge ${cls}`}>
      <StatusIcon status={status} />
      {status}
    </span>
  );
}
