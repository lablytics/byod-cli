import { Component, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: "48px 24px", maxWidth: 600, margin: "0 auto" }}>
          <div
            style={{
              background: "rgba(239, 68, 68, 0.1)",
              border: "1px solid rgba(239, 68, 68, 0.3)",
              borderRadius: "8px",
              padding: "24px",
            }}
          >
            <h2 style={{ margin: "0 0 8px", fontSize: "18px", color: "#ef4444" }}>
              Something went wrong
            </h2>
            <p style={{ margin: "0 0 16px", color: "var(--text-dim, #94a3b8)", fontSize: "14px" }}>
              {this.state.error?.message || "An unexpected error occurred"}
            </p>
            <button
              onClick={() => {
                this.setState({ hasError: false, error: null });
                window.location.reload();
              }}
              style={{
                background: "rgba(99, 102, 241, 0.15)",
                color: "#6366f1",
                border: "1px solid rgba(99, 102, 241, 0.3)",
                borderRadius: "6px",
                padding: "8px 16px",
                cursor: "pointer",
                fontSize: "13px",
              }}
            >
              Reload page
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
