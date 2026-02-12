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

export function StatusBadge({ status }: StatusBadgeProps) {
  const cls = statusMap[status.toLowerCase()] || "badge-pending";
  return <span className={`badge ${cls}`}>{status}</span>;
}
