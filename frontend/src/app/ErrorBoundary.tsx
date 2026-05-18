import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[ErrorBoundary]", error, info);
  }

  reset = () => this.setState({ error: null });

  render() {
    if (this.state.error) {
      return (
        <div style={{
          margin: "2rem", padding: "1.5rem", borderRadius: 8,
          background: "#3b0d0d", color: "#fcd9d9", border: "1px solid #6b1414",
          fontFamily: "ui-monospace, monospace",
        }}>
          <h3 style={{ marginTop: 0 }}>Something broke in the UI</h3>
          <pre style={{ whiteSpace: "pre-wrap", maxHeight: 200, overflow: "auto" }}>
            {String(this.state.error?.stack || this.state.error?.message || this.state.error)}
          </pre>
          <p style={{ fontSize: 13, opacity: 0.8 }}>
            The pipeline keeps running in the backend — events are still being recorded.
            Refresh the page to recover; the job continues in the worker container.
          </p>
          <button onClick={this.reset} style={{
            padding: "8px 16px", background: "#7a1a1a", color: "white",
            border: "none", borderRadius: 4, cursor: "pointer",
          }}>
            Try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
