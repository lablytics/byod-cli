import { useState, useRef, useCallback } from "react";

interface FileDropZoneProps {
  onFilesSelect: (files: File[]) => void;
  files: File[];
  onClear: () => void;
  onRemove: (index: number) => void;
  accept?: string;
  multiple?: boolean;
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

export function FileDropZone({ onFilesSelect, files, onClear, onRemove, accept, multiple = true }: FileDropZoneProps) {
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      const dropped = Array.from(e.dataTransfer.files);
      if (dropped.length > 0) {
        if (multiple) {
          onFilesSelect([...files, ...dropped]);
        } else {
          onFilesSelect([dropped[0]]);
        }
      }
    },
    [onFilesSelect, files, multiple]
  );

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const selected = Array.from(e.target.files || []);
      if (selected.length > 0) {
        if (multiple) {
          onFilesSelect([...files, ...selected]);
        } else {
          onFilesSelect([selected[0]]);
        }
      }
      // Reset so re-selecting the same file works
      e.target.value = "";
    },
    [onFilesSelect, files, multiple]
  );

  const totalSize = files.reduce((sum, f) => sum + f.size, 0);

  if (files.length > 0) {
    return (
      <div className="file-drop-zone has-files">
        <div className="file-list">
          {files.map((file, i) => (
            <div key={`${file.name}-${i}`} className="file-item">
              <div className="file-info">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                  <polyline points="14,2 14,8 20,8" />
                </svg>
                <span className="file-name">{file.name}</span>
                <span className="file-size">{formatBytes(file.size)}</span>
              </div>
              <button className="file-remove" onClick={() => onRemove(i)} title="Remove file">
                &times;
              </button>
            </div>
          ))}
        </div>
        <div style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          padding: "8px 16px",
          borderTop: "1px solid var(--border)",
          fontSize: "12px",
          color: "var(--text-dim)",
        }}>
          <span>{files.length} file{files.length !== 1 ? "s" : ""} ({formatBytes(totalSize)})</span>
          <div style={{ display: "flex", gap: "12px" }}>
            {multiple && (
              <button
                onClick={() => inputRef.current?.click()}
                style={{
                  background: "none",
                  border: "none",
                  color: "var(--accent)",
                  cursor: "pointer",
                  fontSize: "12px",
                  padding: 0,
                }}
              >
                + Add more
              </button>
            )}
            <button
              onClick={onClear}
              style={{
                background: "none",
                border: "none",
                color: "var(--red)",
                cursor: "pointer",
                fontSize: "12px",
                padding: 0,
              }}
            >
              Clear all
            </button>
          </div>
        </div>
        <input
          ref={inputRef}
          type="file"
          style={{ display: "none" }}
          accept={accept}
          multiple={multiple}
          onChange={handleChange}
        />
      </div>
    );
  }

  return (
    <div
      className={`file-drop-zone ${dragging ? "dragging" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      onClick={() => inputRef.current?.click()}
    >
      <input
        ref={inputRef}
        type="file"
        style={{ display: "none" }}
        accept={accept}
        multiple={multiple}
        onChange={handleChange}
      />
      <div className="drop-zone-content">
        <svg className="drop-zone-icon" width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
          <polyline points="17,8 12,3 7,8" />
          <line x1="12" y1="3" x2="12" y2="15" />
        </svg>
        <div>
          <div className="drop-zone-primary">
            Drop your file{multiple ? "s" : ""} here or click to browse
          </div>
          <div className="drop-zone-secondary">
            {multiple ? "Select one or more files" : "Supports any file format"}
          </div>
        </div>
        <div className="drop-zone-hint">Files will be encrypted locally with AES-256-GCM before upload</div>
      </div>
    </div>
  );
}
