import React, { useState, useRef, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { apiPost } from "../hooks/useApi";

const SCHEMA_OPTIONS = [
  { value: "", label: "Auto-detect" },
  { value: "bank_statement", label: "Bank Statement" },
  { value: "custody_statement", label: "Custody Statement" },
  { value: "swift_confirm", label: "SWIFT Confirm" },
];

const DEFAULT_REDACTION_ENTITIES = [
  { type: "PERSON", label: "Person Names", enabled: true },
  { type: "EMAIL_ADDRESS", label: "Email Addresses", enabled: true },
  { type: "PHONE_NUMBER", label: "Phone Numbers", enabled: true },
  { type: "LOCATION", label: "Locations", enabled: false },
  { type: "IBAN_CODE", label: "IBAN Codes", enabled: false },
  { type: "CREDIT_CARD", label: "Credit Card Numbers", enabled: true },
  { type: "DATE_TIME", label: "Dates & Times", enabled: false },
];

const MAX_CONCURRENT = 3;

export default function JobSubmissionScreen() {
  const navigate = useNavigate();
  const fileInputRef = useRef(null);
  const [files, setFiles] = useState([]);
  const [schemaType, setSchemaType] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState([]); // { file, status: 'pending'|'uploading'|'done'|'error', jobId?, error? }
  const [error, setError] = useState(null);
  const [showRedaction, setShowRedaction] = useState(false);
  const [redactionEntities, setRedactionEntities] = useState(DEFAULT_REDACTION_ENTITIES);

  const validateFile = (f) => {
    if (!f) return "Please select a PDF file";
    if (f.type !== "application/pdf" && !f.name.toLowerCase().endsWith(".pdf")) {
      return "Only PDF files are accepted";
    }
    if (f.size > 50 * 1024 * 1024) {
      return `File "${f.name}" exceeds maximum size of 50 MB`;
    }
    return null;
  };

  const handleFileSelect = (selectedFiles) => {
    const fileList = Array.from(selectedFiles);
    const validFiles = [];
    const errors = [];

    for (const f of fileList) {
      const err = validateFile(f);
      if (err) {
        errors.push(err);
      } else {
        validFiles.push(f);
      }
    }

    if (errors.length > 0 && validFiles.length === 0) {
      setError(errors[0]);
      setFiles([]);
    } else {
      if (errors.length > 0) {
        setError(`${errors.length} file(s) skipped: ${errors[0]}`);
      } else {
        setError(null);
      }
      setFiles(validFiles);
    }
  };

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    setDragOver(false);
    handleFileSelect(e.dataTransfer.files);
  }, []);

  const uploadSingleFile = async (file) => {
    const formData = new FormData();
    formData.append("file", file);
    if (schemaType) formData.append("schema_type", schemaType);

    const data = await apiPost("/v1/extract", formData, true);
    
    // Handle duplicate response from backend
    if (data.status === "duplicate") {
      return { ...data, isDuplicate: true };
    }
    return data;
  };

  const handleSubmit = async () => {
    if (files.length === 0) return;
    
    setUploading(true);
    setError(null);

    const progress = files.map((f) => ({ file: f, status: "pending", jobId: null, error: null }));
    setUploadProgress([...progress]);

    // Upload with concurrency limit
    let completed = 0;
    const jobIds = [];

    const uploadNext = async (index) => {
      if (index >= files.length) return;
      progress[index].status = "uploading";
      setUploadProgress([...progress]);

      try {
        const data = await uploadSingleFile(files[index]);
        if (data.isDuplicate) {
          progress[index].status = "done";
          progress[index].jobId = data.job_id;
          progress[index].duplicate = true;
          jobIds.push(data.job_id);
        } else {
          progress[index].status = "done";
          progress[index].jobId = data.job_id;
          jobIds.push(data.job_id);
        }

        // Store job in session
        const stored = JSON.parse(sessionStorage.getItem("pdf_jobs") || "[]");
        stored.unshift(data.job_id);
        sessionStorage.setItem("pdf_jobs", JSON.stringify(stored));
        const jobFiles = JSON.parse(sessionStorage.getItem("pdf_job_files") || "{}");
        jobFiles[data.job_id] = files[index].name;
        sessionStorage.setItem("pdf_job_files", JSON.stringify(jobFiles));
      } catch (err) {
        progress[index].status = "error";
        progress[index].error = err.message;
      }

      completed++;
      setUploadProgress([...progress]);
    };

    // Process in batches of MAX_CONCURRENT
    for (let i = 0; i < files.length; i += MAX_CONCURRENT) {
      const batch = [];
      for (let j = i; j < Math.min(i + MAX_CONCURRENT, files.length); j++) {
        batch.push(uploadNext(j));
      }
      await Promise.all(batch);
    }

    setUploading(false);

    // Navigate to queue if at least one succeeded
    if (jobIds.length > 0) {
      navigate(`/queue?highlight=${jobIds[0]}`);
    }
  };

  return (
    <div style={styles.page}>
      <h1 style={styles.title}>Submit Extraction Job</h1>
      <p style={styles.subtitle}>Upload a PDF document to extract structured financial data.</p>

      {/* Upload progress banner */}
      {uploading && (
        <div style={styles.uploadBanner}>
          <div style={styles.uploadSpinner}>⟳</div>
          <div style={{ flex: 1 }}>
            <div style={styles.uploadBannerTitle}>
              Uploading {uploadProgress.filter(p => p.status === 'done').length}/{files.length} files...
            </div>
            <div style={styles.uploadBannerDetail}>
              {uploadProgress.filter(p => p.status === 'uploading').map(p => p.file.name).join(', ') || 'Preparing...'}
            </div>
            <div style={{ marginTop: '8px' }}>
              {uploadProgress.map((p, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: 'var(--text-xs)', padding: '2px 0' }}>
                  <span style={{ width: 16, textAlign: 'center' }}>
                    {p.status === 'done' ? (p.duplicate ? '⟲' : '✓') : p.status === 'error' ? '✕' : p.status === 'uploading' ? '⟳' : '·'}
                  </span>
                  <span style={{ color: p.status === 'error' ? 'var(--color-error)' : p.duplicate ? 'var(--color-warning)' : 'var(--color-text-secondary)' }}>
                    {p.file.name} {p.duplicate ? '(already processed)' : ''}
                  </span>
                  {p.error && <span style={{ color: 'var(--color-error)' }}>— {p.error}</span>}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Drop zone */}
      <div
        onDrop={handleDrop}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onClick={() => fileInputRef.current?.click()}
        style={{
          ...styles.dropZone,
          borderColor: dragOver ? "var(--color-info)" : files.length > 0 ? "var(--color-success)" : "var(--color-border)",
          backgroundColor: dragOver ? "rgba(52, 152, 219, 0.04)" : files.length > 0 ? "rgba(46, 204, 113, 0.04)" : "transparent",
        }}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,application/pdf"
          multiple
          onChange={(e) => handleFileSelect(e.target.files)}
          style={{ display: "none" }}
        />
        {files.length === 0 ? (
          <>
            <div style={styles.dropIcon}>↑</div>
            <div style={styles.dropText}>Drop PDF(s) here or click to browse</div>
            <div style={styles.dropHint}>Max 50 MB per file · PDF only · Multiple files supported</div>
          </>
        ) : files.length === 1 ? (
          <>
            <div style={styles.dropIcon}>✓</div>
            <div style={styles.dropText}>{files[0].name}</div>
            <div style={styles.dropHint}>{(files[0].size / 1024).toFixed(0)} KB · Click to change</div>
          </>
        ) : (
          <>
            <div style={styles.dropIcon}>✓</div>
            <div style={styles.dropText}>{files.length} files selected</div>
            <div style={styles.dropHint}>
              {(files.reduce((s, f) => s + f.size, 0) / (1024 * 1024)).toFixed(1)} MB total · Click to change
            </div>
          </>
        )}
      </div>

      {/* File list when multiple */}
      {files.length > 1 && (
        <div style={styles.fileList}>
          {files.map((f, i) => (
            <div key={i} style={styles.fileListItem}>
              <span style={styles.fileListName}>{f.name}</span>
              <span style={styles.fileListSize}>{(f.size / 1024).toFixed(0)} KB</span>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  setFiles(files.filter((_, j) => j !== i));
                }}
                style={styles.fileListRemove}
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Schema override */}
      <div style={styles.optionRow}>
        <label style={styles.optionLabel}>Schema Type</label>
        <select
          value={schemaType}
          onChange={(e) => setSchemaType(e.target.value)}
          style={styles.select}
        >
          {SCHEMA_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>
      </div>

      {/* Redaction options (collapsible, shown after file selected) */}
      {files.length > 0 && (
        <div style={styles.redactionSection}>
          <button
            onClick={() => setShowRedaction(!showRedaction)}
            style={styles.redactionToggle}
          >
            {showRedaction ? "▼" : "▶"} Redaction Options
            <span style={styles.redactionHint}>
              {redactionEntities.filter(e => e.enabled).length} of {redactionEntities.length} active
            </span>
          </button>
          {showRedaction && (
            <div style={styles.redactionGrid}>
              <p style={styles.redactionNote}>
                Toggle which PII entities to redact before sending to the LLM. Global defaults can be changed on the Redaction settings page.
              </p>
              {redactionEntities.map((entity, i) => (
                <label key={entity.type} style={styles.redactionItem}>
                  <input
                    type="checkbox"
                    checked={entity.enabled}
                    onChange={() => {
                      const updated = [...redactionEntities];
                      updated[i] = { ...entity, enabled: !entity.enabled };
                      setRedactionEntities(updated);
                    }}
                    style={styles.checkbox}
                  />
                  <span>{entity.label}</span>
                  {entity.type === "DATE_TIME" && entity.enabled && (
                    <span style={styles.warningBadge}>⚠ May affect extraction</span>
                  )}
                  {entity.type === "IBAN_CODE" && entity.enabled && (
                    <span style={styles.warningBadge}>⚠ May affect extraction</span>
                  )}
                  {!entity.enabled && (entity.type === "PERSON" || entity.type === "CREDIT_CARD") && (
                    <span style={styles.riskBadge}>PII exposed</span>
                  )}
                </label>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Error */}
      {error && <div style={styles.error}>{error}</div>}

      {/* Submit */}
      <button
        onClick={handleSubmit}
        disabled={files.length === 0 || uploading}
        style={styles.submitBtn}
      >
        {uploading
          ? `Uploading ${uploadProgress.filter(p => p.status === 'done').length}/${files.length}...`
          : files.length > 1
            ? `Submit ${files.length} Files for Extraction`
            : "Submit for Extraction"
        }
      </button>
    </div>
  );
}

const styles = {
  page: { maxWidth: "100%", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: "calc(100vh - 80px)", padding: "var(--space-6)" },
  title: {
    fontSize: "var(--text-xl)",
    fontWeight: 700,
    color: "var(--color-text-primary)",
    marginBottom: "var(--space-1)",
    textAlign: "center",
  },
  subtitle: {
    fontSize: "var(--text-md)",
    color: "var(--color-text-secondary)",
    marginBottom: "var(--space-6)",
    textAlign: "center",
  },
  dropZone: {
    border: "2px dashed",
    borderRadius: "var(--border-radius)",
    padding: "var(--space-10) var(--space-6)",
    textAlign: "center",
    cursor: "pointer",
    transition: "all 150ms ease",
    marginBottom: "var(--space-5)",
    width: "100%",
    maxWidth: 600,
  },
  dropIcon: {
    fontSize: "var(--text-2xl)",
    marginBottom: "var(--space-2)",
    opacity: 0.6,
  },
  dropText: {
    fontSize: "var(--text-md)",
    fontWeight: 500,
    color: "var(--color-text-primary)",
  },
  dropHint: {
    fontSize: "var(--text-sm)",
    color: "var(--color-text-muted)",
    marginTop: "var(--space-1)",
  },
  optionRow: {
    display: "flex",
    alignItems: "center",
    gap: "var(--space-3)",
    marginBottom: "var(--space-5)",
    width: "100%",
    maxWidth: 600,
  },
  optionLabel: {
    fontSize: "var(--text-sm)",
    fontWeight: 500,
    color: "var(--color-text-secondary)",
    minWidth: 90,
  },
  select: {
    flex: 1,
    padding: "var(--space-2) var(--space-3)",
    border: "1px solid var(--color-border)",
    borderRadius: "var(--border-radius-sm)",
    fontSize: "var(--text-md)",
    backgroundColor: "#fff",
  },
  error: {
    padding: "var(--space-2) var(--space-3)",
    backgroundColor: "rgba(231, 76, 60, 0.08)",
    border: "1px solid var(--color-error)",
    borderRadius: "var(--border-radius-sm)",
    color: "var(--color-error)",
    fontSize: "var(--text-sm)",
    marginBottom: "var(--space-4)",
    width: "100%",
    maxWidth: 600,
  },
  submitBtn: {
    width: "100%",
    maxWidth: 600,
    padding: "var(--space-3) var(--space-5)",
    backgroundColor: "var(--color-info)",
    color: "#fff",
    fontWeight: 600,
    fontSize: "var(--text-md)",
    borderRadius: "var(--border-radius-sm)",
    border: "none",
    cursor: "pointer",
  },
  redactionSection: {
    width: "100%",
    maxWidth: 600,
    marginBottom: "var(--space-5)",
  },
  redactionToggle: {
    display: "flex",
    alignItems: "center",
    gap: "var(--space-2)",
    width: "100%",
    padding: "var(--space-2) 0",
    background: "none",
    border: "none",
    fontSize: "var(--text-sm)",
    fontWeight: 500,
    color: "var(--color-text-secondary)",
    cursor: "pointer",
    textAlign: "left",
  },
  redactionHint: {
    marginLeft: "auto",
    fontSize: "var(--text-xs)",
    color: "var(--color-text-muted)",
  },
  redactionGrid: {
    padding: "var(--space-3)",
    backgroundColor: "#fff",
    border: "1px solid var(--color-border-light)",
    borderRadius: "var(--border-radius-sm)",
    marginTop: "var(--space-2)",
  },
  redactionNote: {
    fontSize: "var(--text-xs)",
    color: "var(--color-text-muted)",
    marginBottom: "var(--space-3)",
  },
  redactionItem: {
    display: "flex",
    alignItems: "center",
    gap: "var(--space-2)",
    padding: "var(--space-1) 0",
    fontSize: "var(--text-sm)",
    color: "var(--color-text-primary)",
    cursor: "pointer",
  },
  checkbox: {
    width: 14,
    height: 14,
    cursor: "pointer",
  },
  warningBadge: {
    fontSize: "var(--text-xs)",
    color: "var(--color-warning)",
    marginLeft: "auto",
  },
  riskBadge: {
    fontSize: "var(--text-xs)",
    color: "var(--color-error)",
    marginLeft: "auto",
  },
  uploadBanner: {
    display: "flex",
    alignItems: "center",
    gap: "var(--space-3)",
    width: "100%",
    maxWidth: 600,
    padding: "var(--space-4)",
    backgroundColor: "rgba(52, 152, 219, 0.08)",
    border: "1px solid var(--color-info)",
    borderRadius: "var(--border-radius)",
    marginBottom: "var(--space-5)",
    animation: "pulse 2s ease-in-out infinite",
  },
  uploadSpinner: {
    fontSize: "24px",
    animation: "spin 1s linear infinite",
    color: "var(--color-info)",
  },
  uploadBannerTitle: {
    fontSize: "var(--text-md)",
    fontWeight: 600,
    color: "var(--color-text-primary)",
  },
  uploadBannerDetail: {
    fontSize: "var(--text-sm)",
    color: "var(--color-text-secondary)",
    marginTop: "2px",
  },
  fileList: {
    width: "100%",
    maxWidth: 600,
    marginBottom: "var(--space-4)",
    border: "1px solid var(--color-border-light)",
    borderRadius: "var(--border-radius-sm)",
    backgroundColor: "#fff",
    maxHeight: 200,
    overflowY: "auto",
  },
  fileListItem: {
    display: "flex",
    alignItems: "center",
    gap: "var(--space-2)",
    padding: "var(--space-2) var(--space-3)",
    borderBottom: "1px solid var(--color-border-light)",
    fontSize: "var(--text-sm)",
  },
  fileListName: {
    flex: 1,
    color: "var(--color-text-primary)",
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  fileListSize: {
    fontSize: "var(--text-xs)",
    color: "var(--color-text-muted)",
    flexShrink: 0,
  },
  fileListRemove: {
    padding: "2px 6px",
    border: "none",
    backgroundColor: "transparent",
    color: "var(--color-text-muted)",
    cursor: "pointer",
    fontSize: "var(--text-xs)",
    borderRadius: "var(--border-radius-sm)",
  },
};
