import { useState, useCallback, useRef } from "react";

export interface SSEProgress {
  stage: string;
  percent: number;
  message: string;
}

interface SSEState {
  active: boolean;
  progress: SSEProgress | null;
  result: Record<string, unknown> | null;
  error: string | null;
}

export function useSSE() {
  const [state, setState] = useState<SSEState>({
    active: false,
    progress: null,
    result: null,
    error: null,
  });
  const readerRef = useRef<ReadableStreamDefaultReader | null>(null);

  const start = useCallback(async (url: string, init?: RequestInit) => {
    setState({ active: true, progress: null, result: null, error: null });

    try {
      const res = await fetch(url, init);
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: res.statusText }));
        setState((s) => ({ ...s, active: false, error: body.detail || `HTTP ${res.status}` }));
        return;
      }

      const reader = res.body?.getReader();
      if (!reader) {
        setState((s) => ({ ...s, active: false, error: "No response body" }));
        return;
      }
      readerRef.current = reader;

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        let currentEvent = "";
        for (const line of lines) {
          if (line.startsWith("event: ")) {
            currentEvent = line.slice(7).trim();
          } else if (line.startsWith("data: ")) {
            const data = JSON.parse(line.slice(6));
            if (currentEvent === "progress") {
              setState((s) => ({ ...s, progress: data as SSEProgress }));
            } else if (currentEvent === "complete") {
              setState({ active: false, progress: null, result: data, error: null });
            } else if (currentEvent === "error") {
              setState((s) => ({ ...s, active: false, error: data.message }));
            }
          }
        }
      }
    } catch (e) {
      setState((s) => ({
        ...s,
        active: false,
        error: e instanceof Error ? e.message : "Connection failed",
      }));
    }
  }, []);

  const reset = useCallback(() => {
    if (readerRef.current) {
      readerRef.current.cancel();
      readerRef.current = null;
    }
    setState({ active: false, progress: null, result: null, error: null });
  }, []);

  return { ...state, start, reset };
}
