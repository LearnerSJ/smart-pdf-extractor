import React, { useState, useRef } from "react";

const API_KEY = "demo-key";

export default function ComparisonScreen() {
  const [fileA, setFileA] = useState(null);
  const [fileB, setFileB] = useState(null);
  const [resultA, setResultA] = useState(null);
  const [resultB, setResultB] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [diff, setDiff] = useState(null);
  const fileARef = useRef(null);
  const fileBRef = useRef(null);

  const processFile = async (file) => {
    const formData = new FormData();
    formData.append("file", file);

    const submitRes = await fetch("/v1/extract", {
      method: "POST",
      headers: { Authorization: `Bearer ${API_KEY}` },
      body: formData,
    });
    const submitJson = await submitRes.json();
    const jobId = submitJson.data?.job_id || submitJson.job_id;

    // Poll for completion
    let attempts = 0;
    while (attempts < 60) {
      await new Promise((r) => setTimeout(r, 2000));
      const statusRes = await fetch(`/v1/jobs/${jobId}`, {
        headers: { Authorization: `Bearer ${API_KEY}` },
      });
      const statusJson = await statusRes.json();
      const status = statusJson.data?.status || statusJson.status;
      if (status === "complete" || status === "partial") break;
      if (status === "failed") throw new Error("Extraction failed");
      attempts++;
    }

    // Get results
    const resultRes = await fetch(`/v1/results/${jobId}`, {
      headers: { Authorization: `Bearer ${API_KEY}` },
    });
    const resultJson = await resultRes.json();
    return resultJson.data || resultJson;
  };

  const handleCompare = async () => {
    if (!fileA || !fileB) return;
    setLoading(true);
    setError(null);
    setDiff(null);

    try {
      const [resA, resB] = await Promise.all([
        processFile(fileA),
        processFile(fileB),
      ]);
      setResultA(resA);
      setResultB(resB);
      setDiff(computeDiff(resA, resB));
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={styles.page}>
      <h1 style={styles.title}>Document Comparison</h1>
      <p style={styles.subtitle}>
        Upload two statements to compare extracted data side by side.
      </p>

      {/* Upload zones */}
      <div style={styles.uploadRow}>
        <DropZone
          label="Statement A"
          file={fileA}
          onSelect={setFileA}
          inputRef={fileARef}
        />
        <div style={styles.vsLabel}>vs</div>
        <DropZone
          label="Statement B"
          file={fileB}
          onSelect={setFileB}
          inputRef={fileBRef}
        />
      </div>

      {error && <div style={styles.error}>{error}</div>}

      <button
        onClick={handleCompare}
        disabled={!fileA || !fileB || loading}
        style={styles.compareBtn}
      >
        {loading ? "Processing..." : "Compare Documents"}
      </button>

      {loading && (
        <div style={styles.loadingBanner}>
          <span style={styles.spinner}>⟳</span>
          Processing both documents through the extraction pipeline...
        </div>
      )}

      {/* Diff Results */}
      {diff && <DiffView diff={diff} />}
    </div>
  );
}

function DropZone({ label, file, onSelect, inputRef }) {
  const [dragOver, setDragOver] = useState(false);

  return (
    <div
      onDrop={(e) => {
        e.preventDefault();
        setDragOver(false);
        const f = e.dataTransfer.files[0];
        if (f && (f.type === "application/pdf" || f.name.endsWith(".pdf"))) {
          onSelect(f);
        }
      }}
      onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
      onDragLeave={() => setDragOver(false)}
      onClick={() => inputRef.current?.click()}
      style={{
        ...styles.dropZone,
        borderColor: dragOver ? "var(--color-info)" : file ? "var(--color-success)" : "var(--color-border)",
        backgroundColor: dragOver ? "rgba(52,152,219,0.04)" : file ? "rgba(46,204,113,0.04)" : "transparent",
      }}
    >
      <input
        ref={inputRef}
        type="file"
        accept=".pdf"
        onChange={(e) => onSelect(e.target.files[0])}
        style={{ display: "none" }}
      />
      <div style={styles.dropLabel}>{label}</div>
      {file ? (
        <>
          <div style={styles.dropIcon}>✓</div>
          <div style={styles.dropFileName}>{file.name}</div>
          <div style={styles.dropHint}>{(file.size / 1024).toFixed(0)} KB</div>
        </>
      ) : (
        <>
          <div style={styles.dropIcon}>↑</div>
          <div style={styles.dropFileName}>Drop PDF here</div>
          <div style={styles.dropHint}>or click to browse</div>
        </>
      )}
    </div>
  );
}

function DiffView({ diff }) {
  return (
    <div style={styles.diffContainer}>
      <h2 style={styles.diffTitle}>Comparison Results</h2>

      {/* Summary */}
      <div style={styles.diffSummary}>
        <div style={styles.summaryItem}>
          <span style={styles.summaryCount}>{diff.changed.length}</span>
          <span style={styles.summaryLabel}>Changed</span>
        </div>
        <div style={styles.summaryItem}>
          <span style={{ ...styles.summaryCount, color: "var(--color-success)" }}>{diff.addedTransactions.length}</span>
          <span style={styles.summaryLabel}>New in B</span>
        </div>
        <div style={styles.summaryItem}>
          <span style={{ ...styles.summaryCount, color: "var(--color-error)" }}>{diff.removedTransactions.length}</span>
          <span style={styles.summaryLabel}>Missing from B</span>
        </div>
      </div>

      {/* Changed fields */}
      {diff.changed.length > 0 && (
        <div style={styles.diffSection}>
          <h3 style={styles.diffSectionTitle}>Changed Fields</h3>
          {diff.changed.map((item, i) => (
            <div key={i} style={styles.diffRow}>
              <div style={styles.diffFieldName}>{item.field}</div>
              <div style={styles.diffValues}>
                <span style={styles.diffOldValue}>{item.valueA}</span>
                <span style={styles.diffArrow}>→</span>
                <span style={styles.diffNewValue}>{item.valueB}</span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Balance changes */}
      {diff.balanceChanges.length > 0 && (
        <div style={styles.diffSection}>
          <h3 style={styles.diffSectionTitle}>Balance Changes</h3>
          {diff.balanceChanges.map((item, i) => (
            <div key={i} style={styles.diffRow}>
              <div style={styles.diffFieldName}>{item.account} — {item.type}</div>
              <div style={styles.diffValues}>
                <span style={styles.diffOldValue}>{item.valueA}</span>
                <span style={styles.diffArrow}>→</span>
                <span style={styles.diffNewValue}>{item.valueB}</span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* New transactions in B */}
      {diff.addedTransactions.length > 0 && (
        <div style={styles.diffSection}>
          <h3 style={{ ...styles.diffSectionTitle, color: "var(--color-success)" }}>
            New Transactions in B ({diff.addedTransactions.length})
          </h3>
          {diff.addedTransactions.slice(0, 20).map((tx, i) => (
            <div key={i} style={{ ...styles.diffRow, backgroundColor: "rgba(46,204,113,0.06)" }}>
              <span style={styles.txDate}>{tx.date || "—"}</span>
              <span style={styles.txDesc}>{tx.description || "—"}</span>
              <span style={styles.txAmount}>{tx.amount || "—"}</span>
            </div>
          ))}
          {diff.addedTransactions.length > 20 && (
            <div style={styles.moreText}>...and {diff.addedTransactions.length - 20} more</div>
          )}
        </div>
      )}

      {/* Removed transactions */}
      {diff.removedTransactions.length > 0 && (
        <div style={styles.diffSection}>
          <h3 style={{ ...styles.diffSectionTitle, color: "var(--color-error)" }}>
            Missing from B ({diff.removedTransactions.length})
          </h3>
          {diff.removedTransactions.slice(0, 20).map((tx, i) => (
            <div key={i} style={{ ...styles.diffRow, backgroundColor: "rgba(231,76,60,0.06)" }}>
              <span style={styles.txDate}>{tx.date || "—"}</span>
              <span style={styles.txDesc}>{tx.description || "—"}</span>
              <span style={styles.txAmount}>{tx.amount || "—"}</span>
            </div>
          ))}
          {diff.removedTransactions.length > 20 && (
            <div style={styles.moreText}>...and {diff.removedTransactions.length - 20} more</div>
          )}
        </div>
      )}

      {diff.changed.length === 0 && diff.addedTransactions.length === 0 && diff.removedTransactions.length === 0 && (
        <div style={styles.noDiff}>✓ Documents are identical</div>
      )}
    </div>
  );
}

/**
 * Compute diff between two extraction results.
 */
function computeDiff(resultA, resultB) {
  const outputA = resultA?.output || resultA || {};
  const outputB = resultB?.output || resultB || {};
  const fieldsA = outputA.fields || {};
  const fieldsB = outputB.fields || {};

  const changed = [];
  const balanceChanges = [];

  // Compare scalar fields
  const allFieldNames = new Set([
    ...Object.keys(fieldsA).filter((k) => k !== "accounts"),
    ...Object.keys(fieldsB).filter((k) => k !== "accounts"),
  ]);

  for (const name of allFieldNames) {
    const valA = getFieldValue(fieldsA[name]);
    const valB = getFieldValue(fieldsB[name]);
    if (String(valA) !== String(valB)) {
      changed.push({ field: name, valueA: String(valA), valueB: String(valB) });
    }
  }

  // Compare accounts/balances
  const accountsA = fieldsA.accounts?.value || fieldsA.accounts || [];
  const accountsB = fieldsB.accounts?.value || fieldsB.accounts || [];

  const acctMapA = {};
  const acctMapB = {};
  if (Array.isArray(accountsA)) {
    for (const a of accountsA) {
      if (a) acctMapA[a.account_number || a.iban || "unknown"] = a;
    }
  }
  if (Array.isArray(accountsB)) {
    for (const a of accountsB) {
      if (a) acctMapB[a.account_number || a.iban || "unknown"] = a;
    }
  }

  const allAcctKeys = new Set([...Object.keys(acctMapA), ...Object.keys(acctMapB)]);
  for (const key of allAcctKeys) {
    const a = acctMapA[key] || {};
    const b = acctMapB[key] || {};
    if (String(a.opening_balance ?? "") !== String(b.opening_balance ?? "")) {
      balanceChanges.push({ account: key, type: "Opening Balance", valueA: String(a.opening_balance ?? "—"), valueB: String(b.opening_balance ?? "—") });
    }
    if (String(a.closing_balance ?? "") !== String(b.closing_balance ?? "")) {
      balanceChanges.push({ account: key, type: "Closing Balance", valueA: String(a.closing_balance ?? "—"), valueB: String(b.closing_balance ?? "—") });
    }
  }

  // Compare transactions
  const txA = extractTransactions(accountsA);
  const txB = extractTransactions(accountsB);

  const txKeyA = new Set(txA.map(txKey));
  const txKeyB = new Set(txB.map(txKey));

  const addedTransactions = txB.filter((tx) => !txKeyA.has(txKey(tx)));
  const removedTransactions = txA.filter((tx) => !txKeyB.has(txKey(tx)));

  return { changed, balanceChanges, addedTransactions, removedTransactions };
}

function getFieldValue(field) {
  if (field == null) return "";
  if (typeof field === "object") return field.value ?? "";
  return field;
}

function extractTransactions(accounts) {
  const txs = [];
  if (!Array.isArray(accounts)) return txs;
  for (const acct of accounts) {
    if (!acct || !acct.tables) continue;
    for (const table of acct.tables) {
      if (!table || !table.rows) continue;
      const headers = table.headers || [];
      for (const row of table.rows) {
        if (Array.isArray(row)) {
          const obj = {};
          headers.forEach((h, i) => { obj[h.toLowerCase()] = row[i]; });
          txs.push(normalizeTx(obj));
        } else if (typeof row === "object") {
          const obj = {};
          for (const [k, v] of Object.entries(row)) {
            obj[k.toLowerCase()] = v;
          }
          txs.push(normalizeTx(obj));
        }
      }
    }
  }
  return txs;
}

function normalizeTx(obj) {
  return {
    date: obj.date || obj.value_date || obj.transaction_date || "",
    description: obj.description || obj.narrative || obj.details || "",
    amount: obj.amount || obj.debit || obj.credit || "",
  };
}

function txKey(tx) {
  return `${tx.date}|${tx.description}|${tx.amount}`;
}

const styles = {
  page: { maxWidth: 900, margin: "0 auto" },
  title: { fontSize: "var(--text-xl)", fontWeight: 700, color: "var(--color-text-primary)", marginBottom: "var(--space-2)" },
  subtitle: { fontSize: "var(--text-md)", color: "var(--color-text-secondary)", marginBottom: "var(--space-6)" },
  uploadRow: { display: "flex", gap: "var(--space-4)", alignItems: "center", marginBottom: "var(--space-5)" },
  vsLabel: { fontSize: "var(--text-lg)", fontWeight: 700, color: "var(--color-text-muted)", flexShrink: 0 },
  dropZone: { flex: 1, border: "2px dashed", borderRadius: "var(--border-radius)", padding: "var(--space-6) var(--space-4)", textAlign: "center", cursor: "pointer", transition: "all 150ms ease" },
  dropLabel: { fontSize: "var(--text-xs)", fontWeight: 600, color: "var(--color-text-muted)", textTransform: "uppercase", marginBottom: "var(--space-2)" },
  dropIcon: { fontSize: "var(--text-2xl)", marginBottom: "var(--space-1)", opacity: 0.6 },
  dropFileName: { fontSize: "var(--text-md)", fontWeight: 500, color: "var(--color-text-primary)" },
  dropHint: { fontSize: "var(--text-sm)", color: "var(--color-text-muted)", marginTop: "var(--space-1)" },
  error: { padding: "var(--space-2) var(--space-3)", backgroundColor: "rgba(231,76,60,0.08)", border: "1px solid var(--color-error)", borderRadius: "var(--border-radius-sm)", color: "var(--color-error)", fontSize: "var(--text-sm)", marginBottom: "var(--space-4)" },
  compareBtn: { width: "100%", padding: "var(--space-3) var(--space-5)", backgroundColor: "var(--color-info)", color: "#fff", fontWeight: 600, fontSize: "var(--text-md)", borderRadius: "var(--border-radius-sm)", border: "none", cursor: "pointer", marginBottom: "var(--space-5)" },
  loadingBanner: { display: "flex", alignItems: "center", gap: "var(--space-3)", padding: "var(--space-4)", backgroundColor: "rgba(52,152,219,0.06)", border: "1px solid var(--color-info)", borderRadius: "var(--border-radius)", marginBottom: "var(--space-5)", fontSize: "var(--text-sm)", color: "var(--color-text-secondary)" },
  spinner: { animation: "spin 1s linear infinite", fontSize: "20px", color: "var(--color-info)" },
  diffContainer: { marginTop: "var(--space-4)" },
  diffTitle: { fontSize: "var(--text-lg)", fontWeight: 600, color: "var(--color-text-primary)", marginBottom: "var(--space-4)" },
  diffSummary: { display: "flex", gap: "var(--space-5)", padding: "var(--space-3) var(--space-4)", backgroundColor: "#fff", borderRadius: "var(--border-radius)", border: "1px solid var(--color-border-light)", marginBottom: "var(--space-5)" },
  summaryItem: { display: "flex", alignItems: "center", gap: "var(--space-2)" },
  summaryCount: { fontSize: "var(--text-lg)", fontWeight: 700, color: "var(--color-warning)" },
  summaryLabel: { fontSize: "var(--text-sm)", color: "var(--color-text-muted)" },
  diffSection: { marginBottom: "var(--space-5)", backgroundColor: "#fff", border: "1px solid var(--color-border-light)", borderRadius: "var(--border-radius)", overflow: "hidden" },
  diffSectionTitle: { fontSize: "var(--text-md)", fontWeight: 600, padding: "var(--space-3) var(--space-4)", borderBottom: "1px solid var(--color-border-light)", margin: 0, color: "var(--color-warning)" },
  diffRow: { display: "flex", alignItems: "center", gap: "var(--space-3)", padding: "var(--space-2) var(--space-4)", borderBottom: "1px solid var(--color-border-light)", fontSize: "var(--text-sm)" },
  diffFieldName: { minWidth: 140, fontWeight: 500, color: "var(--color-text-secondary)", textTransform: "capitalize" },
  diffValues: { display: "flex", alignItems: "center", gap: "var(--space-2)", flex: 1 },
  diffOldValue: { color: "var(--color-error)", textDecoration: "line-through", fontFamily: "var(--font-mono)", fontSize: "var(--text-sm)" },
  diffArrow: { color: "var(--color-text-muted)" },
  diffNewValue: { color: "var(--color-success)", fontFamily: "var(--font-mono)", fontSize: "var(--text-sm)" },
  txDate: { minWidth: 80, color: "var(--color-text-muted)", fontSize: "var(--text-xs)", fontFamily: "var(--font-mono)" },
  txDesc: { flex: 1, color: "var(--color-text-primary)", fontSize: "var(--text-sm)" },
  txAmount: { fontFamily: "var(--font-mono)", fontSize: "var(--text-sm)", fontWeight: 500, color: "var(--color-text-primary)" },
  moreText: { padding: "var(--space-2) var(--space-4)", fontSize: "var(--text-xs)", color: "var(--color-text-muted)" },
  noDiff: { textAlign: "center", padding: "var(--space-8)", color: "var(--color-success)", fontWeight: 600, fontSize: "var(--text-md)" },
};
