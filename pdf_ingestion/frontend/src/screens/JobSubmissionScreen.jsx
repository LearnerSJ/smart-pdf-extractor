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

export default function JobSubmissionScreen() {
  const navigate = useNavigate();
  const fileInputRef = useRef(null);
  const [file, setFile] = useState(null);
  const [schemaType, setSchemaType] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState(null);
  const [showRedaction, setShowRedaction] = useState(false);
  const [redactionEntities, setRedactionEntities] = useState(DEFAULT_REDACTION_ENTITIES);

  const validateFile = (f) => {
    if (!f) return "Please select a PDF file";
    if (f.type !== "application/pdf" && !f.name.toLowerCase().endsWith(".pdf")) {
      return "Only PDF files are accepted";
    }
    if (f.size > 50 * 1024 * 1024) {
      return "File exceeds maximum size of 50 MB";
    }
    return null;
  };

  const handleFileSelect = (f) => {
    const err = validateFile(f);
    if (err) {
      setError(err);
      setFile(null);
    } else {
      // Check for duplicate filename in existing jobs
      const stored = JSON.parse(sessionStorage.getItem("pdf_jobs") || "[]");
      if (stored.length > 0 && f) {
        // We store filenames alongside job IDs for dedup check
        const jobFiles = JSON.parse(sessionStorage.getItem("pdf_job_files") || "{}");
        const existingJobId = Object.entries(jobFiles).find(([id, name]) => name === f.name)?.[0];
        if (existingJobId) {
          setError(`"${f.name}" has already been submitted. Check the Job Queue for existing results.`);
          setFile(f); // Still allow override
          return;
        }
      }
      setError(null);
      setFile(f);
    }
  };

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    setDragOver(false);
    const dropped = e.dataTransfer.files[0];
    handleFileSelect(dropped);
  }, []);

  const handleSubmit = async () => {
    if (!file) return;
    setUploading(true);
    setError(null);

    try {
      const formData = new FormData();
      formData.append("file", file);
      if (schemaType) formData.append("schema_type", schemaType);

      const data = await apiPost("/v1/extract", formData, true);
      // Store job in session for the queue to pick up
      const stored = JSON.parse(sessionStorage.getItem("pdf_jobs") || "[]");
      stored.unshift(data.job_id);
      sessionStorage.setItem("pdf_jobs", JSON.stringify(stored));
      // Store filename for dedup check
      const jobFiles = JSON.parse(sessionStorage.getItem("pdf_job_files") || "{}");
      jobFiles[data.job_id] = file.name;
      sessionStorage.setItem("pdf_job_files", JSON.stringify(jobFiles));
      navigate(`/queue?highlight=${data.job_id}`);
    } catch (err) {
      setError(err.message);
    } finally {
      setUploading(false);
    }
  };

  return (
    <div style={styles.page}>
      <h1 style={styles.title}>Submit Extraction Job</h1>
      <p style={styles.subtitle}>Upload a PDF document to extract structured financial data.</p>

      {/* Drop zone */}
      <div
        onDrop={handleDrop}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onClick={() => fileInputRef.current?.click()}
        style={{
          ...styles.dropZone,
          borderColor: dragOver ? "var(--color-info)" : file ? "var(--color-success)" : "var(--color-border)",
          backgroundColor: dragOver ? "rgba(52, 152, 219, 0.04)" : file ? "rgba(46, 204, 113, 0.04)" : "transparent",
        }}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,application/pdf"
          onChange={(e) => handleFileSelect(e.target.files[0])}
          style={{ display: "none" }}
        />
        {!file ? (
          <>
            <div style={styles.dropIcon}>↑</div>
            <div style={styles.dropText}>Drop PDF here or click to browse</div>
            <div style={styles.dropHint}>Max 50 MB · PDF only</div>
          </>
        ) : (
          <>
            <div style={styles.dropIcon}>✓</div>
            <div style={styles.dropText}>{file.name}</div>
            <div style={styles.dropHint}>{(file.size / 1024).toFixed(0)} KB · Click to change</div>
          </>
        )}
      </div>

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
      {file && (
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
        disabled={!file || uploading}
        style={styles.submitBtn}
      >
        {uploading ? "Uploading..." : "Submit for Extraction"}
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
};
