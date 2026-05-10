import React, { useState, useRef, useCallback, useEffect } from "react";

const API_KEY = "demo-key";

// --- Utility functions ---

function formatNumber(value) {
  if (value == null || value === "" || value === "—") return "—";
  const num = typeof value === "string" ? parseFloat(value.replace(/,/g, "")) : value;
  if (isNaN(num)) return String(value);
  return num.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatDate(dateStr) {
  if (!dateStr) return "—";
  try {
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return dateStr;
    return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
  } catch {
    return dateStr;
  }
}

function getResultStatus(output) {
  if (!output) return "error";
  if (output.status === "failed") return "error";
  if (output.status === "complete") return "success";
  if (output.status === "partial") {
    // If validation passed and we have fields, treat as success
    const validationPassed = output.validation?.passed ?? true;
    const fieldsExtracted = Object.keys(output.fields || {}).length;
    if (validationPassed && fieldsExtracted > 0) return "success";
    return "warning";
  }
  const abstentions = output.abstentions?.length || 0;
  const fieldsExtracted = Object.keys(output.fields || {}).length;
  if (fieldsExtracted === 0 && abstentions > 0) return "error";
  if (abstentions > 0) return "warning";
  return "success";
}

function getStatusBanner(status) {
  switch (status) {
    case "success":
      return { text: "Extraction complete", bg: "#f0fdf4", border: "#16a34a", color: "#16a34a", icon: "✓" };
    case "warning":
      return { text: "Partial extraction — some fields could not be found", bg: "#fffbeb", border: "#d97706", color: "#d97706", icon: "⚠" };
    case "error":
      return { text: "Extraction failed", bg: "#fef2f2", border: "#dc2626", color: "#dc2626", icon: "✕" };
    default:
      return null;
  }
}

function downloadJSON(data, filename) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function downloadCSV(output, filename) {
  const rows = [];
  rows.push(["Account Number", "IBAN", "Currency", "Date", "Description", "Debit", "Credit", "Balance"]);

  const accounts = output?.fields?.accounts?.value || [];
  for (const account of accounts) {
    const txns = account.transactions || [];
    for (const txn of txns) {
      rows.push([
        account.account_number || "",
        account.iban || "",
        account.currency || "",
        txn.date || "",
        txn.description || "",
        txn.debit != null ? txn.debit : "",
        txn.credit != null ? txn.credit : "",
        txn.balance != null ? txn.balance : "",
      ]);
    }
  }

  const csvContent = rows.map(row => row.map(cell => `"${String(cell).replace(/"/g, '""')}"`).join(",")).join("\n");
  const blob = new Blob([csvContent], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// --- Main Component ---

export default function PdfExtractor({ apiBaseUrl = "" }) {
  const [file, setFile] = useState(null);
  const [batchId, setBatchId] = useState("");
  const [uploading, setUploading] = useState(false);
  const [polling, setPolling] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef(null);

  // Hidden debug state
  const [jobId, setJobId] = useState(null);
  const [traceId, setTraceId] = useState(null);
  const [jobStatus, setJobStatus] = useState(null);

  const resetState = () => {
    setError(null);
    setResult(null);
    setJobId(null);
    setTraceId(null);
    setJobStatus(null);
  };

  const handleFileChange = (e) => {
    const selected = e.target.files[0] || null;
    setFile(selected);
    resetState();
  };

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    setDragOver(false);
    const dropped = e.dataTransfer.files[0];
    if (dropped && dropped.type === "application/pdf") {
      setFile(dropped);
      resetState();
    } else {
      setError("Please drop a PDF file.");
    }
  }, []);

  const handleDragOver = useCallback((e) => {
    e.preventDefault();
    setDragOver(true);
  }, []);

  const handleDragLeave = useCallback(() => {
    setDragOver(false);
  }, []);

  const handleExtract = async () => {
    if (!file) {
      setError("Please select a PDF file.");
      return;
    }

    setUploading(true);
    resetState();

    try {
      const formData = new FormData();
      formData.append("file", file);
      if (batchId.trim()) formData.append("batch_id", batchId.trim());

      const response = await fetch(`${apiBaseUrl}/v1/extract`, {
        method: "POST",
        headers: { Authorization: `Bearer ${API_KEY}` },
        body: formData,
      });

      if (!response.ok) {
        const errBody = await response.json().catch(() => ({}));
        throw new Error(errBody.detail || `Upload failed: ${response.status}`);
      }

      const envelope = await response.json();
      const data = envelope.data || envelope;
      setJobId(data.job_id);
      setTraceId(data.trace_id);
      setJobStatus(data.status);

      if (data.result) {
        // Synchronous result (small files)
        setUploading(false);
        setResult({ output: data.result });
      } else {
        // Async processing — start polling before clearing uploading
        setPolling(true);
        setUploading(false);
        pollForResult(data.job_id);
      }
    } catch (err) {
      setError(err.message);
      setUploading(false);
    }
  };

  const pollForResult = async (id) => {
    setPolling(true);
    let attempts = 0;
    const maxAttempts = 900; // 30 minutes max (900 × 2s)
    const interval = 2000;

    const poll = async () => {
      attempts++;
      try {
        const jobRes = await fetch(`${apiBaseUrl}/v1/jobs/${id}`, {
          headers: { Authorization: `Bearer ${API_KEY}` },
        });

        if (jobRes.ok) {
          const jobEnvelope = await jobRes.json();
          const jobData = jobEnvelope.data || jobEnvelope;
          setJobStatus(jobData.status);

          if (["complete", "partial", "failed"].includes(jobData.status)) {
            const resultRes = await fetch(`${apiBaseUrl}/v1/results/${id}`, {
              headers: { Authorization: `Bearer ${API_KEY}` },
            });

            if (resultRes.ok) {
              const resultEnvelope = await resultRes.json();
              setResult(resultEnvelope.data || resultEnvelope);
            }
            setPolling(false);
            return;
          }
        }

        if (attempts < maxAttempts) {
          setTimeout(poll, interval);
        } else {
          setPolling(false);
          setError("Processing timed out. Please try again.");
        }
      } catch (err) {
        setPolling(false);
        setError(`Connection error: ${err.message}`);
      }
    };

    setTimeout(poll, interval);
  };

  const isProcessing = uploading || polling;
  const output = result?.output || result;

  return (
    <div style={{ maxWidth: 900, margin: "0 auto" }}>
      {/* Upload Section */}
      {!isProcessing && !result && (
        <UploadSection
          file={file}
          batchId={batchId}
          setBatchId={setBatchId}
          dragOver={dragOver}
          fileInputRef={fileInputRef}
          onFileChange={handleFileChange}
          onDrop={handleDrop}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onExtract={handleExtract}
          error={error}
        />
      )}

      {/* Processing State */}
      {isProcessing && (
        <ProcessingIndicator fileName={file?.name} jobId={jobId} apiBaseUrl={apiBaseUrl} />
      )}

      {/* Results Section */}
      {!isProcessing && result && output && (
        <ResultsSection
          output={output}
          jobId={jobId}
          traceId={traceId}
          jobStatus={jobStatus}
          onNewExtraction={() => {
            setFile(null);
            resetState();
          }}
        />
      )}

      {/* Error after processing */}
      {!isProcessing && !result && error && null /* already shown in upload section */}
    </div>
  );
}

// --- Upload Section ---

function UploadSection({ file, batchId, setBatchId, dragOver, fileInputRef, onFileChange, onDrop, onDragOver, onDragLeave, onExtract, error }) {
  return (
    <div>
      <div style={{ textAlign: "center", marginBottom: 32 }}>
        <h2 style={{ fontSize: 24, fontWeight: 700, margin: "0 0 8px 0", color: "#111827" }}>
          Extract Data from PDF
        </h2>
        <p style={{ color: "#6b7280", fontSize: 15, margin: 0 }}>
          Upload a bank statement or financial document to extract structured data
        </p>
      </div>

      {/* Drop zone */}
      <div
        onDrop={onDrop}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onClick={() => fileInputRef.current?.click()}
        style={{
          border: `2px dashed ${dragOver ? "#2563eb" : file ? "#16a34a" : "#d1d5db"}`,
          borderRadius: 12,
          padding: "48px 24px",
          textAlign: "center",
          marginBottom: 24,
          backgroundColor: dragOver ? "#eff6ff" : file ? "#f0fdf4" : "#fafafa",
          cursor: "pointer",
          transition: "all 0.2s ease",
        }}
        role="button"
        aria-label="Drop PDF file here or click to browse"
        tabIndex={0}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") fileInputRef.current?.click(); }}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,application/pdf"
          onChange={onFileChange}
          style={{ display: "none" }}
          aria-label="Select PDF file"
        />
        {!file ? (
          <>
            <div style={{ fontSize: 40, marginBottom: 12, opacity: 0.5 }}>📄</div>
            <p style={{ fontSize: 16, fontWeight: 500, color: "#374151", margin: "0 0 4px 0" }}>
              Drop your PDF here or click to browse
            </p>
            <p style={{ fontSize: 13, color: "#9ca3af", margin: 0 }}>
              Supports bank statements, custody statements, and SWIFT confirmations
            </p>
          </>
        ) : (
          <>
            <div style={{ fontSize: 40, marginBottom: 12 }}>✓</div>
            <p style={{ fontSize: 16, fontWeight: 600, color: "#16a34a", margin: "0 0 4px 0" }}>
              {file.name}
            </p>
            <p style={{ fontSize: 13, color: "#6b7280", margin: 0 }}>
              {(file.size / 1024).toFixed(1)} KB — Click to change file
            </p>
          </>
        )}
      </div>

      {/* Batch ID (optional) */}
      <div style={{ marginBottom: 24 }}>
        <label style={{ display: "block", fontSize: 13, color: "#6b7280", marginBottom: 6 }}>
          Batch ID (optional — for grouping related documents)
        </label>
        <input
          type="text"
          value={batchId}
          onChange={(e) => setBatchId(e.target.value)}
          placeholder="e.g. oct-2025-statements"
          style={{
            width: "100%",
            padding: "10px 14px",
            border: "1px solid #e5e7eb",
            borderRadius: 8,
            fontSize: 14,
            boxSizing: "border-box",
            outline: "none",
          }}
          onFocus={(e) => { e.target.style.borderColor = "#2563eb"; }}
          onBlur={(e) => { e.target.style.borderColor = "#e5e7eb"; }}
        />
      </div>

      {/* Error */}
      {error && (
        <div
          style={{
            padding: "12px 16px",
            backgroundColor: "#fef2f2",
            border: "1px solid #fca5a5",
            borderRadius: 8,
            marginBottom: 16,
            color: "#dc2626",
            fontSize: 14,
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}
          role="alert"
        >
          <span>✕</span> {error}
        </div>
      )}

      {/* Extract button */}
      <button
        onClick={onExtract}
        disabled={!file}
        style={{
          width: "100%",
          padding: "14px 28px",
          backgroundColor: !file ? "#e5e7eb" : "#2563eb",
          color: !file ? "#9ca3af" : "#fff",
          border: "none",
          borderRadius: 8,
          cursor: !file ? "not-allowed" : "pointer",
          fontWeight: 600,
          fontSize: 16,
          transition: "background-color 0.2s ease",
        }}
      >
        Extract
      </button>
    </div>
  );
}

// --- Processing Indicator ---

function ProcessingIndicator({ fileName, jobId, apiBaseUrl = "" }) {
  const [progress, setProgress] = useState(null);

  useEffect(() => {
    if (!jobId) return;

    let active = true;
    const poll = async () => {
      try {
        const res = await fetch(`${apiBaseUrl}/v1/jobs/${jobId}/progress`, {
          headers: { Authorization: `Bearer ${API_KEY}` },
        });
        if (res.ok && active) {
          const data = await res.json();
          setProgress(data);
        }
      } catch {
        // ignore polling errors
      }
      if (active) {
        setTimeout(poll, 1000);
      }
    };
    poll();

    return () => { active = false; };
  }, [jobId, apiBaseUrl]);

  const percent = progress?.progress_percent || 0;
  const pagesProcessed = progress?.pages_processed || 0;
  const totalPages = progress?.total_pages || 0;
  const stage = progress?.current_stage || "uploading";
  const elapsed = progress?.elapsed_seconds || 0;
  const remaining = progress?.estimated_remaining_seconds;

  const stageLabels = {
    uploading: "Uploading...",
    classifying: "Classifying pages...",
    extracting: "Running OCR...",
    vlm: `LLM extraction... ${progress?.vlm_windows_complete || 0}/${progress?.vlm_total_windows || "?"} windows`,
    packaging: "Packaging results...",
    complete: "Complete",
    unknown: "Processing...",
  };

  const formatTime = (seconds) => {
    if (seconds == null) return "calculating...";
    if (seconds < 60) return `~${Math.ceil(seconds)}s`;
    const mins = Math.floor(seconds / 60);
    const secs = Math.ceil(seconds % 60);
    return `~${mins}m ${secs}s`;
  };

  return (
    <div style={{ textAlign: "center", padding: "60px 24px" }}>
      <div style={{ marginBottom: 24 }}>
        <Spinner />
      </div>
      <h3 style={{ fontSize: 18, fontWeight: 600, color: "#111827", margin: "0 0 8px 0" }}>
        {stageLabels[stage] || "Processing..."}
      </h3>
      <p style={{ color: "#6b7280", fontSize: 14, margin: "0 0 16px 0" }}>
        Extracting data from <strong>{fileName}</strong>
      </p>

      {/* Progress bar */}
      {totalPages > 0 && (
        <div style={{ maxWidth: 400, margin: "0 auto 16px auto" }}>
          <div style={{
            height: 8,
            backgroundColor: "#e5e7eb",
            borderRadius: 4,
            overflow: "hidden",
            marginBottom: 8,
          }}>
            <div style={{
              height: "100%",
              width: `${percent}%`,
              backgroundColor: "#2563eb",
              borderRadius: 4,
              transition: "width 0.5s ease",
            }} />
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, color: "#6b7280" }}>
            <span>{pagesProcessed} / {totalPages} pages</span>
            <span>{percent}%</span>
          </div>
        </div>
      )}

      {/* Time estimates */}
      <div style={{ fontSize: 13, color: "#9ca3af" }}>
        {elapsed > 0 && (
          <span>Elapsed: {formatTime(elapsed)}</span>
        )}
        {elapsed > 0 && remaining != null && (
          <span> · </span>
        )}
        {remaining != null && (
          <span>Remaining: {formatTime(remaining)}</span>
        )}
      </div>
    </div>
  );
}

function Spinner() {
  return (
    <div
      style={{
        width: 40,
        height: 40,
        border: "4px solid #e5e7eb",
        borderTopColor: "#2563eb",
        borderRadius: "50%",
        animation: "spin 1s linear infinite",
        margin: "0 auto",
      }}
      role="status"
      aria-label="Processing"
    >
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}

// --- Results Section ---

function ResultsSection({ output, jobId, traceId, jobStatus, onNewExtraction }) {
  const [activeTab, setActiveTab] = useState("data");
  const status = getResultStatus(output);
  const banner = getStatusBanner(status);

  const institutionName = output?.fields?.institution?.value || output?.fields?.institution_name?.value || output?.fields?.bank_name?.value || "—";
  const clientName = output?.fields?.client_name?.value || output?.fields?.account_holder?.value || "—";
  const statementPeriod = output?.fields?.statement_period?.value || output?.fields?.period?.value
    || (output?.fields?.period_from?.value && output?.fields?.period_to?.value
      ? `${output.fields.period_from.value} – ${output.fields.period_to.value}`
      : output?.fields?.statement_date?.value || "—");
  const documentType = output?.schema_type?.replace(/_/g, " ") || "—";
  const accounts = output?.fields?.accounts?.value || [];
  const validationFailures = output?.validation?.failures || [];
  const validationPassed = output?.validation?.passed ?? validationFailures.length === 0;

  return (
    <div>
      {/* Status Banner */}
      {banner && (
        <div
          style={{
            padding: "14px 20px",
            backgroundColor: banner.bg,
            border: `1px solid ${banner.border}`,
            borderRadius: 8,
            marginBottom: 24,
            display: "flex",
            alignItems: "center",
            gap: 10,
          }}
          role="status"
        >
          <span style={{ fontSize: 18, color: banner.color }}>{banner.icon}</span>
          <span style={{ fontWeight: 600, color: banner.color, fontSize: 15 }}>{banner.text}</span>
        </div>
      )}

      {/* Tabs */}
      <div style={{ display: "flex", gap: 0, marginBottom: 24, borderBottom: "1px solid #e5e7eb" }}>
        <button
          onClick={() => setActiveTab("data")}
          style={{
            padding: "10px 20px",
            border: "none",
            borderBottom: activeTab === "data" ? "2px solid #2563eb" : "2px solid transparent",
            background: "none",
            cursor: "pointer",
            fontWeight: activeTab === "data" ? 600 : 400,
            color: activeTab === "data" ? "#2563eb" : "#6b7280",
            fontSize: 14,
          }}
        >
          Extracted Data
        </button>
        <button
          onClick={() => setActiveTab("validation")}
          style={{
            padding: "10px 20px",
            border: "none",
            borderBottom: activeTab === "validation" ? "2px solid #2563eb" : "2px solid transparent",
            background: "none",
            cursor: "pointer",
            fontWeight: activeTab === "validation" ? 600 : 400,
            color: activeTab === "validation" ? "#2563eb" : "#6b7280",
            fontSize: 14,
            display: "flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          Validation
          {validationFailures.length > 0 && (
            <span style={{
              backgroundColor: "#fef2f2",
              color: "#dc2626",
              fontSize: 11,
              fontWeight: 600,
              padding: "2px 6px",
              borderRadius: 10,
            }}>
              {validationFailures.length}
            </span>
          )}
          {validationPassed && validationFailures.length === 0 && (
            <span style={{ color: "#16a34a", fontSize: 14 }}>✓</span>
          )}
        </button>
      </div>

      {/* Tab Content: Extracted Data */}
      {activeTab === "data" && (
        <div>

      {/* Document Summary */}
      <div
        style={{
          backgroundColor: "#fff",
          border: "1px solid #e5e7eb",
          borderRadius: 10,
          padding: "20px 24px",
          marginBottom: 24,
        }}
      >
        <h3 style={{ fontSize: 16, fontWeight: 600, margin: "0 0 16px 0", color: "#111827" }}>
          Document Summary
        </h3>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px 32px" }}>
          <SummaryField label="Institution" value={institutionName} />
          <SummaryField label="Client" value={clientName} />
          <SummaryField label="Statement Period" value={statementPeriod} />
          <SummaryField label="Document Type" value={documentType} capitalize />
        </div>
      </div>

      {/* Accounts */}
      {accounts.length > 0 && (
        <div style={{ marginBottom: 24 }}>
          <h3 style={{ fontSize: 16, fontWeight: 600, margin: "0 0 16px 0", color: "#111827" }}>
            Accounts ({accounts.length})
          </h3>
          {accounts.map((account, idx) => (
            <AccountCard key={idx} account={account} index={idx} />
          ))}
        </div>
      )}

      {/* Extracted Fields (fallback when no accounts array) */}
      {accounts.length === 0 && output?.fields && Object.keys(output.fields).length > 0 && (
        <div style={{ backgroundColor: "#fff", border: "1px solid #e5e7eb", borderRadius: 10, padding: "20px 24px", marginBottom: 24 }}>
          <h3 style={{ fontSize: 16, fontWeight: 600, margin: "0 0 16px 0", color: "#111827" }}>
            Extracted Fields
          </h3>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px 32px" }}>
            {Object.entries(output.fields)
              .filter(([key]) => key !== "accounts")
              .map(([key, field]) => (
                <SummaryField
                  key={key}
                  label={key.replace(/_/g, " ")}
                  value={field?.value != null ? String(field.value) : "—"}
                  capitalize
                />
              ))}
          </div>
        </div>
      )}
        </div>
      )}

      {/* Tab Content: Validation */}
      {activeTab === "validation" && (
        <ValidationTab failures={validationFailures} passed={validationPassed} />
      )}

      {/* Download Buttons */}
      <div style={{ display: "flex", gap: 12, marginBottom: 32 }}>
        <button
          onClick={() => downloadJSON(output, "extraction-result.json")}
          style={{
            padding: "10px 20px",
            backgroundColor: "#fff",
            border: "1px solid #d1d5db",
            borderRadius: 8,
            cursor: "pointer",
            fontWeight: 500,
            fontSize: 14,
            display: "flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          ⬇ Download JSON
        </button>
        <button
          onClick={() => downloadCSV(output, "transactions.csv")}
          style={{
            padding: "10px 20px",
            backgroundColor: "#fff",
            border: "1px solid #d1d5db",
            borderRadius: 8,
            cursor: "pointer",
            fontWeight: 500,
            fontSize: 14,
            display: "flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          ⬇ Download CSV
        </button>
        <div style={{ flex: 1 }} />
        <button
          onClick={onNewExtraction}
          style={{
            padding: "10px 20px",
            backgroundColor: "#2563eb",
            color: "#fff",
            border: "none",
            borderRadius: 8,
            cursor: "pointer",
            fontWeight: 500,
            fontSize: 14,
          }}
        >
          New Extraction
        </button>
      </div>

      {/* Technical Details (collapsible) */}
      <TechnicalDetails output={output} jobId={jobId} traceId={traceId} jobStatus={jobStatus} />
    </div>
  );
}

// --- Sub-components ---

function SummaryField({ label, value, capitalize }) {
  return (
    <div>
      <div style={{ fontSize: 12, color: "#6b7280", marginBottom: 2 }}>{label}</div>
      <div style={{ fontSize: 14, fontWeight: 500, color: "#111827", textTransform: capitalize ? "capitalize" : "none" }}>
        {value || "—"}
      </div>
    </div>
  );
}

function AccountCard({ account, index }) {
  const [expanded, setExpanded] = useState(false);

  const accountLabel = account.account_number || account.iban || `Account ${index + 1}`;
  const txnCount = account.transactions?.length || 0;
  const tableCount = account.tables?.length || 0;
  const totalDataRows = txnCount + (account.tables || []).reduce((sum, t) => sum + (t.rows?.length || 0), 0);

  return (
    <div
      style={{
        backgroundColor: "#fff",
        border: "1px solid #e5e7eb",
        borderRadius: 10,
        marginBottom: 12,
        overflow: "hidden",
      }}
    >
      {/* Account Header */}
      <div
        onClick={() => setExpanded(!expanded)}
        style={{
          padding: "16px 20px",
          cursor: "pointer",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
        role="button"
        aria-expanded={expanded}
        tabIndex={0}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") setExpanded(!expanded); }}
      >
        <div>
          <div style={{ fontSize: 15, fontWeight: 600, color: "#111827", marginBottom: 4 }}>
            {accountLabel}
            {account.currency && (
              <span style={{ marginLeft: 10, fontSize: 13, fontWeight: 400, color: "#6b7280" }}>
                {account.currency}
              </span>
            )}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "#6b7280" }}>
            {account.iban && account.account_number && (
              <span>IBAN: {account.iban}</span>
            )}
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          {/* Balance summary */}
          <div style={{ textAlign: "right", fontSize: 13 }}>
            {account.opening_balance != null && account.closing_balance != null && (
              <span style={{ color: "#374151" }}>
                {formatNumber(account.opening_balance)} → {formatNumber(account.closing_balance)}
              </span>
            )}
            {(txnCount > 0 || tableCount > 0) && (
              <div style={{ color: "#9ca3af", fontSize: 12, marginTop: 2 }}>
                {txnCount > 0 && `${txnCount} transaction${txnCount !== 1 ? "s" : ""}`}
                {txnCount > 0 && tableCount > 0 && " · "}
                {tableCount > 0 && `${tableCount} table${tableCount !== 1 ? "s" : ""}`}
              </div>
            )}
          </div>
          <span style={{ color: "#9ca3af", fontSize: 12 }}>
            {expanded ? "▼" : "▶"}
          </span>
        </div>
      </div>

      {/* Expanded Content */}
      {expanded && (
        <div style={{ borderTop: "1px solid #f3f4f6" }}>
          {/* Account details row */}
          <div style={{ padding: "12px 20px", backgroundColor: "#f9fafb", display: "flex", gap: 24, flexWrap: "wrap", fontSize: 13 }}>
            {account.opening_balance != null && (
              <div><span style={{ color: "#6b7280" }}>Opening Balance:</span> <strong>{formatNumber(account.opening_balance)}</strong></div>
            )}
            {account.closing_balance != null && (
              <div><span style={{ color: "#6b7280" }}>Closing Balance:</span> <strong>{formatNumber(account.closing_balance)}</strong></div>
            )}
            {account.iban && (
              <div><span style={{ color: "#6b7280" }}>IBAN:</span> {account.iban}</div>
            )}
            {account.account_type && (
              <div><span style={{ color: "#6b7280" }}>Type:</span> {account.account_type}</div>
            )}
          </div>

          {/* Standard transactions table */}
          {txnCount > 0 ? (
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                <thead>
                  <tr style={{ backgroundColor: "#f9fafb", position: "sticky", top: 0 }}>
                    <th style={thStyle}>Date</th>
                    <th style={{ ...thStyle, minWidth: 200 }}>Description</th>
                    <th style={thStyleRight}>Debit</th>
                    <th style={thStyleRight}>Credit</th>
                    <th style={thStyleRight}>Balance</th>
                  </tr>
                </thead>
                <tbody>
                  {account.transactions.map((txn, ti) => (
                    <tr key={ti} style={{ borderBottom: "1px solid #f3f4f6" }}>
                      <td style={tdStyle}>{formatDate(txn.date)}</td>
                      <td style={tdStyle}>{txn.description || "—"}</td>
                      <td style={tdStyleRight}>{txn.debit != null ? formatNumber(txn.debit) : "—"}</td>
                      <td style={tdStyleRight}>{txn.credit != null ? formatNumber(txn.credit) : "—"}</td>
                      <td style={tdStyleRight}>{txn.balance != null ? formatNumber(txn.balance) : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : tableCount === 0 ? (
            <div style={{ padding: "16px 20px", color: "#9ca3af", fontSize: 13 }}>
              No transactions extracted for this account
            </div>
          ) : null}

          {/* Additional tables (settlement, clearing, fees, etc.) */}
          {account.tables && account.tables.length > 0 && account.tables.map((tbl, tblIdx) => (
            <div key={tblIdx} style={{ borderTop: "1px solid #e5e7eb" }}>
              <div style={{ padding: "10px 20px", backgroundColor: "#f0f9ff", fontSize: 13, fontWeight: 600, color: "#1e40af" }}>
                {(tbl.table_type || `Table ${tblIdx + 1}`).replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase())}
              </div>
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                  <thead>
                    <tr style={{ backgroundColor: "#f9fafb" }}>
                      {(tbl.headers || Object.keys(tbl.rows?.[0] || {})).map((h, hi) => (
                        <th key={hi} style={thStyle}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {(tbl.rows || []).map((row, ri) => (
                      <tr key={ri} style={{ borderBottom: "1px solid #f3f4f6" }}>
                        {(tbl.headers || Object.keys(row)).map((h, ci) => (
                          <td key={ci} style={tdStyle}>{row[h] != null ? String(row[h]) : "—"}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function TechnicalDetails({ output, jobId, traceId, jobStatus }) {
  const [open, setOpen] = useState(false);

  return (
    <div style={{ borderTop: "1px solid #e5e7eb", paddingTop: 16 }}>
      <button
        onClick={() => setOpen(!open)}
        style={{
          background: "none",
          border: "none",
          cursor: "pointer",
          fontSize: 13,
          color: "#9ca3af",
          padding: 0,
          display: "flex",
          alignItems: "center",
          gap: 6,
        }}
      >
        <span>{open ? "▼" : "▶"}</span>
        Technical Details
      </button>

      {open && (
        <div style={{ marginTop: 12, padding: "16px 20px", backgroundColor: "#f9fafb", borderRadius: 8, fontSize: 13 }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px 24px", marginBottom: 16 }}>
            <div><span style={{ color: "#6b7280" }}>Job ID:</span> <code style={codeStyle}>{jobId || "—"}</code></div>
            <div><span style={{ color: "#6b7280" }}>Trace ID:</span> <code style={codeStyle}>{traceId || "—"}</code></div>
            <div><span style={{ color: "#6b7280" }}>Status:</span> <code style={codeStyle}>{jobStatus || "—"}</code></div>
            <div><span style={{ color: "#6b7280" }}>Pipeline Version:</span> <code style={codeStyle}>{output?.pipeline_version || "—"}</code></div>
          </div>

          {/* Abstentions */}
          {output?.abstentions?.length > 0 && (
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontWeight: 600, marginBottom: 6, color: "#374151" }}>Abstentions ({output.abstentions.length})</div>
              {output.abstentions.map((abs, idx) => (
                <div key={idx} style={{ padding: "6px 10px", backgroundColor: "#fef2f2", borderRadius: 4, marginBottom: 4, fontSize: 12 }}>
                  <strong>{abs.field || abs.table_id}</strong>: {abs.reason}
                  {abs.detail && <span style={{ color: "#6b7280" }}> — {abs.detail}</span>}
                </div>
              ))}
            </div>
          )}

          {/* Raw JSON */}
          <details>
            <summary style={{ cursor: "pointer", color: "#6b7280", fontSize: 12 }}>
              Raw JSON Response
            </summary>
            <pre
              style={{
                marginTop: 8,
                padding: 12,
                backgroundColor: "#1f2937",
                color: "#e5e7eb",
                borderRadius: 6,
                fontSize: 11,
                overflow: "auto",
                maxHeight: 300,
              }}
            >
              {JSON.stringify(output, null, 2)}
            </pre>
          </details>
        </div>
      )}
    </div>
  );
}

// --- Validation Tab ---

function ValidationTab({ failures, passed }) {
  if (passed && failures.length === 0) {
    return (
      <div style={{ padding: "40px 24px", textAlign: "center" }}>
        <div style={{ fontSize: 40, marginBottom: 12 }}>✓</div>
        <h3 style={{ fontSize: 16, fontWeight: 600, color: "#16a34a", margin: "0 0 8px 0" }}>
          All Validation Checks Passed
        </h3>
        <p style={{ color: "#6b7280", fontSize: 14, margin: 0 }}>
          Balance reconciliation, running balance, column types, and completeness checks all passed.
        </p>
      </div>
    );
  }

  // Group failures by validator
  const grouped = {};
  for (const f of failures) {
    const name = f.validator_name || "unknown";
    if (!grouped[name]) grouped[name] = [];
    grouped[name].push(f);
  }

  const validatorLabels = {
    validate_arithmetic_totals: { label: "Balance Arithmetic", icon: "🧮", desc: "Opening + credits - debits = closing" },
    validate_running_balance: { label: "Running Balance", icon: "📊", desc: "Sequential balance chain consistency" },
    validate_account_balance_reconciliation: { label: "Account Reconciliation", icon: "⚖️", desc: "Per-account balance verification" },
    validate_column_type_consistency: { label: "Column Types", icon: "📋", desc: "Values match expected column data types" },
    validate_transaction_completeness: { label: "Completeness", icon: "📄", desc: "All accounts have extracted data" },
    validate_totals_crosscheck: { label: "Totals Cross-Check", icon: "🔢", desc: "Stated totals match sum of rows" },
    validate_iban: { label: "IBAN Checksum", icon: "🏦", desc: "IBAN mod-97 validation" },
    validate_isin: { label: "ISIN Check Digit", icon: "📈", desc: "ISO 6166 Luhn validation" },
    validate_bic: { label: "BIC Format", icon: "🌐", desc: "SWIFT BIC format validation" },
    validate_date_range: { label: "Date Range", icon: "📅", desc: "Dates within reasonable range" },
    validate_currency_codes: { label: "Currency Codes", icon: "💱", desc: "ISO 4217 validation" },
    validate_provenance_integrity: { label: "Provenance", icon: "🔗", desc: "Field source tracking integrity" },
  };

  return (
    <div>
      <div style={{ marginBottom: 16, padding: "12px 16px", backgroundColor: "#fef2f2", border: "1px solid #fca5a5", borderRadius: 8, fontSize: 14, color: "#dc2626" }}>
        {failures.length} validation issue{failures.length !== 1 ? "s" : ""} found — extracted data may have errors
      </div>

      {Object.entries(grouped).map(([validatorName, items]) => {
        const meta = validatorLabels[validatorName] || { label: validatorName.replace(/^validate_/, "").replace(/_/g, " "), icon: "⚠", desc: "" };
        return (
          <div key={validatorName} style={{ marginBottom: 16, backgroundColor: "#fff", border: "1px solid #e5e7eb", borderRadius: 10, overflow: "hidden" }}>
            <div style={{ padding: "12px 16px", backgroundColor: "#f9fafb", borderBottom: "1px solid #f3f4f6", display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontSize: 16 }}>{meta.icon}</span>
              <div>
                <div style={{ fontSize: 14, fontWeight: 600, color: "#111827" }}>{meta.label}</div>
                {meta.desc && <div style={{ fontSize: 12, color: "#9ca3af" }}>{meta.desc}</div>}
              </div>
              <span style={{ marginLeft: "auto", fontSize: 12, color: "#dc2626", fontWeight: 600, backgroundColor: "#fef2f2", padding: "2px 8px", borderRadius: 10 }}>
                {items.length} issue{items.length !== 1 ? "s" : ""}
              </span>
            </div>
            <div style={{ padding: "8px 16px" }}>
              {items.map((item, idx) => (
                <div key={idx} style={{ padding: "8px 0", borderBottom: idx < items.length - 1 ? "1px solid #f3f4f6" : "none", fontSize: 13 }}>
                  <div style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
                    {item.field_name && (
                      <code style={{ fontSize: 11, backgroundColor: "#f3f4f6", padding: "2px 6px", borderRadius: 3, color: "#374151" }}>
                        {item.field_name}
                      </code>
                    )}
                    <span style={{ color: "#9ca3af", fontSize: 11 }}>{item.error_code}</span>
                  </div>
                  <div style={{ color: "#6b7280", marginTop: 4, fontSize: 12 }}>
                    {item.detail}
                  </div>
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// --- Styles ---

const thStyle = { padding: "10px 14px", textAlign: "left", fontWeight: 600, color: "#374151", fontSize: 12, textTransform: "uppercase", letterSpacing: "0.05em" };
const thStyleRight = { ...thStyle, textAlign: "right" };
const tdStyle = { padding: "10px 14px", textAlign: "left", color: "#374151" };
const tdStyleRight = { ...tdStyle, textAlign: "right", fontFamily: "'SF Mono', 'Fira Code', monospace", fontSize: 12 };
const codeStyle = { fontSize: 11, backgroundColor: "#e5e7eb", padding: "2px 6px", borderRadius: 3, fontFamily: "monospace" };
