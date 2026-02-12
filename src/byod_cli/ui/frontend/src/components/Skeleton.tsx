interface SkeletonProps {
  width?: string | number;
  height?: string | number;
  variant?: "text" | "circle" | "card";
  style?: React.CSSProperties;
}

export function Skeleton({ width, height, variant = "text", style }: SkeletonProps) {
  const baseClass = `skeleton ${variant === "circle" ? "skeleton-circle" : variant === "text" ? "skeleton-text" : ""}`;

  return (
    <div
      className={baseClass}
      style={{
        width: width ?? "100%",
        height: height ?? (variant === "text" ? 14 : variant === "circle" ? 40 : 120),
        ...style,
      }}
    />
  );
}

export function SkeletonTable({ rows = 5, cols = 4 }: { rows?: number; cols?: number }) {
  return (
    <div className="table-container">
      <table>
        <thead>
          <tr>
            {Array.from({ length: cols }).map((_, i) => (
              <th key={i}><Skeleton width="60%" height={12} /></th>
            ))}
          </tr>
        </thead>
        <tbody>
          {Array.from({ length: rows }).map((_, row) => (
            <tr key={row} style={{ cursor: "default" }}>
              {Array.from({ length: cols }).map((_, col) => (
                <td key={col}>
                  <Skeleton width={col === 0 ? "70%" : "50%"} height={14} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function SkeletonCard({ lines = 3 }: { lines?: number }) {
  return (
    <div className="card">
      <Skeleton width="40%" height={16} style={{ marginBottom: 16 }} />
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          width={i === lines - 1 ? "60%" : "90%"}
          height={14}
          style={{ marginBottom: i < lines - 1 ? 10 : 0 }}
        />
      ))}
    </div>
  );
}

export function SkeletonChecklist({ items = 4 }: { items?: number }) {
  return (
    <div className="card">
      <Skeleton width="30%" height={16} style={{ marginBottom: 20 }} />
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        {Array.from({ length: items }).map((_, i) => (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <Skeleton variant="circle" width={24} height={24} />
            <div style={{ flex: 1 }}>
              <Skeleton width="50%" height={14} style={{ marginBottom: 4 }} />
              <Skeleton width="70%" height={11} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
