import React, { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useApi } from "../hooks/useApi";
import JobStatusBadge from "../components/JobStatusBadge";
import SchemaTypeTag from "../components/SchemaTypeTag";
import ConfidenceBadge from "../components/ConfidenceBadge";
import MonospaceField from "../components/MonospaceField";
import ProvenanceTooltip from "../components/ProvenanceTooltip";
import AbstentionRow from "../components/AbstentionRow";
import CorrectionModal from "../components/CorrectionModal";
import DataTable from "../components/DataTable";

const FINANCIAL_FIELDS = new Set(["iban", "isin", "bic", "swift_code", "account_number", "doc_id"]);

export default function ResultsViewerScreen() {
  const { jobId } = useParams();
  const navigate = useNavigate();
  const { data: result, loading, error } = useApi(`/v1/results/${jobId}`);
  const { data: jobData } = useApi(`/v1/jobs/${jobId}`);
  const [activeTab, setActiveTab] = useState("fields");
  const [correction, setCorrection] = useState(null);

  // Get all jobs for prev/next navigation
  const allJobs = JSON.parse(sessionStorage.getItem("pdf_jobs") || "[]");
  const currentIndex = allJobs.indexOf(jobId);
  const prevJobId = currentIndex > 0 ? allJobs[currentIndex - 1] : null;
  const nextJobId = currentIndex < allJobs.length - 1 ? allJobs[currentIndex + 1] : null;

  if (loading) return <div style={styles.loading}>Loading results...</div>;
  if (error) return (
    <div>
      <h1 style={styles.fileName} title={jobData?.filename}>
        {jobData?.filename || "Document"}
      </h1>
      <div style={styles.navBar}>
        <button onClick={() => navigate("/queue")} style={styles.backBtn}>← Back to Queue</button>
      </div>
      <div style={styles.failedPanel}>
        <div style={styles.failedIcon}>⚠</div>
        <h2 style={{ ...styles.failedTitle, color: "var(--color-warning)" }}>Results Not Available</h2>
        <p style={{ fontSize: "var(--text-md)", color: "var(--color-text-secondary)", marginTop: "var(--space-2)" }}>
          This job's results are no longer available. The server may have been restarted. Please re-submit the file.
        </p>
      </div>
    </div>
  );

  const output = result?.output || result || {};

  // Handle failed jobs with error details
  if (output.error || output.status === "failed") {
    return (
      <div>
        <h1 style={styles.fileName} title={jobData?.filename}>
          {jobData?.filename || "Document"}
        </h1>
        <div style={styles.navBar}>
          <button onClick={() => navigate("/queue")} style={styles.backBtn}>← Back to Queue</button>
        </div>
        <div style={styles.failedPanel}>
          <div style={styles.failedIcon}>✕</div>
          <h2 style={styles.failedTitle}>Extraction Failed</h2>
          {output.error && (
            <div style={styles.failedDetail}>
              <div style={styles.failedLabel}>Error Code</div>
              <div style={styles.failedCode}>{output.error_code || output.error}</div>
            </div>
          )}
          {(output.error_code || output.error) && output.error !== output.error_code && (
            <div style={styles.failedDetail}>
              <div style={styles.failedLabel}>Details</div>
              <div style={styles.failedMessage}>{output.error}</div>
            </div>
          )}
          {output.abstentions && output.abstentions.length > 0 && (
            <div style={styles.failedDetail}>
              <div style={styles.failedLabel}>Abstentions ({output.abstentions.length})</div>
              {output.abstentions.slice(0, 10).map((a, i) => (
                <div key={i} style={styles.failedAbstention}>
                  <strong>{a.field || a.table_id}</strong>: {a.reason} — {a.detail}
                </div>
              ))}
              {output.abstentions.length > 10 && (
                <div style={styles.failedMore}>...and {output.abstentions.length - 10} more</div>
              )}
            </div>
          )}
        </div>
      </div>
    );
  }
  const fields = output.fields || {};
  const accounts = fields.accounts?.value || [];
  const abstentions = output.abstentions || [];
  const validation = output.validation || {};
  const valFailures = validation.failures || [];

  const tabs = [
    { id: "fields", label: "Fields" },
    { id: "tables", label: `Tables (${accounts.reduce((s, a) => s + (a?.tables?.length || 0), 0)})` },
    { id: "abstentions", label: `Abstentions (${abstentions.length})` },
    { id: "validation", label: "Validation", badge: valFailures.length || null },
  ];

  return (
    <div>
      {/* File name */}
      <h1 style={styles.fileName} title={jobData?.filename}>
        {jobData?.filename || "Document"}
      </h1>

      {/* Navigation bar */}
      <div style={styles.navBar}>
        <button onClick={() => navigate("/queue")} style={styles.backBtn}>
          ← Back to Queue
        </button>
        <div style={styles.navPrevNext}>
          <button
            onClick={() => prevJobId && navigate(`/results/${prevJobId}`)}
            disabled={!prevJobId}
            style={styles.navBtn}
          >
            ← Prev
          </button>
          <span style={styles.navPosition}>
            {currentIndex >= 0 ? `${currentIndex + 1} of ${allJobs.length}` : ""}
          </span>
          <button
            onClick={() => nextJobId && navigate(`/results/${nextJobId}`)}
            disabled={!nextJobId}
            style={styles.navBtn}
          >
            Next →
          </button>
        </div>
      </div>

      {/* Header */}
      <div style={styles.headerBar}>
        <div style={styles.headerLeft}>
          <JobStatusBadge status={output.status} />
        </div>
        <div style={styles.headerRight}>
          <span style={styles.metaLabel}>Pipeline</span>
          <MonospaceField>{output.pipeline_version}</MonospaceField>
        </div>
      </div>

      {/* Confidence summary */}
      <div style={styles.summaryBar}>
        <div style={styles.summaryItem}>
          <span style={styles.summaryLabel}>Confidence</span>
          <ConfidenceBadge value={output.confidence_summary?.mean_confidence} />
        </div>
        <div style={styles.summaryItem}>
          <span style={styles.summaryLabel}>Fields</span>
          <span style={styles.summaryValue}>{output.confidence_summary?.fields_extracted || Object.keys(fields).length}</span>
        </div>
        <div style={styles.summaryItem}>
          <span style={styles.summaryLabel}>Abstained</span>
          <span style={styles.summaryValue}>{output.confidence_summary?.fields_abstained || abstentions.length}</span>
        </div>
        <div style={styles.summaryItem}>
          <span style={styles.summaryLabel}>VLM Used</span>
          <span style={styles.summaryValue}>{output.confidence_summary?.vlm_used_count || 0}</span>
        </div>
      </div>

      {/* Tabs */}
      <div style={styles.tabBar}>
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            style={{
              ...styles.tab,
              ...(activeTab === tab.id ? styles.tabActive : {}),
            }}
          >
            {tab.label}
            {tab.badge > 0 && <span style={styles.tabBadge}>{tab.badge}</span>}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div style={styles.tabContent}>
        {activeTab === "fields" && (
          <FieldsPanel fields={fields} onCorrect={(name, val) => setCorrection({ name, val })} />
        )}
        {activeTab === "tables" && <TablesPanel accounts={accounts} />}
        {activeTab === "abstentions" && <AbstentionsPanel abstentions={abstentions} />}
        {activeTab === "validation" && <ValidationPanel failures={valFailures} />}
      </div>

      {/* Correction modal */}
      {correction && (
        <CorrectionModal
          open={true}
          onClose={() => setCorrection(null)}
          jobId={jobId}
          fieldName={correction.name}
          currentValue={correction.val}
          onSuccess={() => setCorrection(null)}
        />
      )}
    </div>
  );
}

function FieldsPanel({ fields, onCorrect }) {
  const entries = Object.entries(fields).filter(([k]) => k !== "accounts");

  if (entries.length === 0) return <div style={styles.emptyPanel}>No fields extracted.</div>;

  return (
    <div style={styles.fieldsGrid}>
      {entries.map(([name, field]) => (
        <FieldRow key={name} name={name} field={field} onCorrect={onCorrect} />
      ))}
    </div>
  );
}

function FieldRow({ name, field, onCorrect }) {
  const [hovered, setHovered] = React.useState(false);

  return (
    <div
      style={{ ...styles.fieldRow, backgroundColor: hovered ? "rgba(52,152,219,0.03)" : "transparent" }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <div style={styles.fieldName}>{name.replace(/_/g, " ")}</div>
      <div style={styles.fieldValue}>
        {FINANCIAL_FIELDS.has(name) ? (
          <MonospaceField>{String(field?.value ?? "—")}</MonospaceField>
        ) : (
          String(field?.value ?? "—")
        )}
      </div>
      <button
        onClick={() => onCorrect(name, field?.value)}
        style={{ ...styles.editBtn, opacity: hovered ? 1 : 0 }}
        title="Submit correction"
      >
        Edit
      </button>
    </div>
  );
}

function TablesPanel({ accounts }) {
  if (!accounts || accounts.length === 0) return <div style={styles.emptyPanel}>No tables extracted.</div>;

  return (
    <div>
      {accounts.map((acct, ai) => (
        <div key={ai} style={styles.accountSection}>
          <h3 style={styles.accountTitle}>
            {acct.account_number || acct.iban || `Account ${ai + 1}`}
            {acct.currency && <span style={styles.currency}> · {acct.currency}</span>}
          </h3>
          {(acct.tables || []).map((tbl, ti) => (
            <div key={ti} style={styles.tableBlock}>
              <div style={styles.tableHeader}>
                {(tbl.table_type || "Table").replace(/_/g, " ")}
                <span style={styles.rowCount}>{tbl.rows?.length || 0} rows</span>
              </div>
              <DataTable
                columns={(tbl.headers || []).map((h) => ({ key: h, label: h }))}
                rows={tbl.rows || []}
              />
            </div>
          ))}
          {(!acct.tables || acct.tables.length === 0) && (
            <div style={styles.emptyPanel}>No tables for this account.</div>
          )}
        </div>
      ))}
    </div>
  );
}

function AbstentionsPanel({ abstentions }) {
  if (abstentions.length === 0) {
    return <div style={styles.successPanel}>✓ Full extraction — no abstentions</div>;
  }

  return (
    <div>
      {abstentions.map((a, i) => (
        <AbstentionRow
          key={i}
          fieldName={a.field || a.table_id}
          reasonCode={a.reason}
          detail={a.detail}
          vlmAttempted={a.vlm_attempted}
        />
      ))}
    </div>
  );
}

function ValidationPanel({ failures }) {
  if (failures.length === 0) {
    return <div style={styles.successPanel}>✓ All validation checks passed</div>;
  }

  // Group by validator
  const grouped = {};
  failures.forEach((f) => {
    const key = f.validator_name || "unknown";
    if (!grouped[key]) grouped[key] = [];
    grouped[key].push(f);
  });

  return (
    <div>
      <div style={styles.valSummary}>{failures.length} validation issue{failures.length !== 1 ? "s" : ""}</div>
      {Object.entries(grouped).map(([name, items]) => (
        <div key={name} style={styles.valGroup}>
          <div style={styles.valGroupHeader}>
            {name.replace(/^validate_/, "").replace(/_/g, " ")}
            <span style={styles.valCount}>{items.length}</span>
          </div>
          {items.map((item, i) => (
            <div key={i} style={styles.valItem}>
              {item.field_name && <MonospaceField>{item.field_name}</MonospaceField>}
              <span style={styles.valDetail}>{item.detail}</span>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

const styles = {
  loading: { textAlign: "center", padding: "var(--space-10)", color: "var(--color-text-muted)" },
  error: { padding: "var(--space-4)", color: "var(--color-error)", backgroundColor: "rgba(231,76,60,0.08)", borderRadius: "var(--border-radius-sm)" },
  navBar: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "var(--space-4)" },
  fileName: { fontSize: "var(--text-xl)", fontWeight: 700, color: "var(--color-text-primary)", marginBottom: "var(--space-3)", userSelect: "text", cursor: "text" },
  failedPanel: { textAlign: "center", padding: "var(--space-8)", backgroundColor: "#fff", border: "1px solid var(--color-border-light)", borderRadius: "var(--border-radius)" },
  failedIcon: { fontSize: "32px", color: "var(--color-error)", marginBottom: "var(--space-3)" },
  failedTitle: { fontSize: "var(--text-lg)", fontWeight: 600, color: "var(--color-error)", marginBottom: "var(--space-4)" },
  failedDetail: { textAlign: "left", marginBottom: "var(--space-3)", padding: "var(--space-3)", backgroundColor: "rgba(231,76,60,0.04)", borderRadius: "var(--border-radius-sm)" },
  failedLabel: { fontSize: "var(--text-xs)", color: "var(--color-text-muted)", textTransform: "uppercase", marginBottom: "var(--space-1)" },
  failedCode: { fontFamily: "var(--font-mono)", fontSize: "var(--text-md)", color: "var(--color-error)", fontWeight: 600 },
  failedMessage: { fontSize: "var(--text-md)", color: "var(--color-text-primary)" },
  failedAbstention: { fontSize: "var(--text-sm)", color: "var(--color-text-secondary)", padding: "var(--space-1) 0", borderBottom: "1px solid var(--color-border-light)" },
  failedMore: { fontSize: "var(--text-xs)", color: "var(--color-text-muted)", marginTop: "var(--space-2)" },
  backBtn: { padding: "var(--space-1) var(--space-3)", backgroundColor: "transparent", border: "1px solid var(--color-border)", borderRadius: "var(--border-radius-sm)", fontSize: "var(--text-sm)", color: "var(--color-text-secondary)", cursor: "pointer" },
  navPrevNext: { display: "flex", alignItems: "center", gap: "var(--space-2)" },
  navBtn: { padding: "var(--space-1) var(--space-3)", backgroundColor: "transparent", border: "1px solid var(--color-border)", borderRadius: "var(--border-radius-sm)", fontSize: "var(--text-sm)", color: "var(--color-text-secondary)", cursor: "pointer" },
  navPosition: { fontSize: "var(--text-xs)", color: "var(--color-text-muted)" },
  headerBar: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "var(--space-4)", gap: "var(--space-3)" },
  headerLeft: { display: "flex", alignItems: "center", gap: "var(--space-2)" },
  headerRight: { display: "flex", alignItems: "center", gap: "var(--space-2)" },
  metaLabel: { fontSize: "var(--text-xs)", color: "var(--color-text-muted)" },
  summaryBar: { display: "flex", gap: "var(--space-5)", padding: "var(--space-3) var(--space-4)", backgroundColor: "#fff", borderRadius: "var(--border-radius)", border: "1px solid var(--color-border-light)", marginBottom: "var(--space-4)" },
  summaryItem: { display: "flex", alignItems: "center", gap: "var(--space-2)" },
  summaryLabel: { fontSize: "var(--text-xs)", color: "var(--color-text-muted)", textTransform: "uppercase" },
  summaryValue: { fontSize: "var(--text-md)", fontWeight: 600, color: "var(--color-text-primary)" },
  tabBar: { display: "flex", gap: 0, borderBottom: "1px solid var(--color-border-light)", marginBottom: "var(--space-4)" },
  tab: { padding: "var(--space-2) var(--space-4)", border: "none", borderBottom: "2px solid transparent", background: "none", cursor: "pointer", fontSize: "var(--text-md)", color: "var(--color-text-secondary)", display: "flex", alignItems: "center", gap: "var(--space-1)" },
  tabActive: { borderBottomColor: "var(--color-info)", color: "var(--color-info)", fontWeight: 600 },
  tabBadge: { backgroundColor: "var(--color-error)", color: "#fff", fontSize: "var(--text-xs)", padding: "1px 5px", borderRadius: "8px", fontWeight: 600 },
  tabContent: { minHeight: 200 },
  fieldsGrid: { display: "flex", flexDirection: "column", gap: "1px", backgroundColor: "#fff", borderRadius: "var(--border-radius)", border: "1px solid var(--color-border-light)", overflow: "hidden" },
  fieldRow: { display: "flex", alignItems: "center", gap: "var(--space-3)", padding: "var(--space-2) var(--space-3)", borderBottom: "1px solid var(--color-border-light)", transition: "background 150ms ease" },
  fieldName: { fontSize: "var(--text-sm)", color: "var(--color-text-secondary)", textTransform: "capitalize", minWidth: 140 },
  fieldValue: { flex: 1, fontSize: "var(--text-md)", color: "var(--color-text-primary)" },
  vlmTag: { fontSize: "var(--text-xs)", color: "var(--color-info)", fontWeight: 600, backgroundColor: "rgba(52,152,219,0.1)", padding: "1px 4px", borderRadius: "3px" },
  provenanceHint: { fontSize: "var(--text-xs)", color: "var(--color-text-muted)", cursor: "help" },
  editBtn: { padding: "2px 8px", fontSize: "var(--text-xs)", color: "var(--color-info)", backgroundColor: "rgba(52,152,219,0.08)", border: "1px solid rgba(52,152,219,0.2)", borderRadius: "var(--border-radius-sm)", cursor: "pointer", transition: "opacity 150ms ease", fontWeight: 500, whiteSpace: "nowrap" },
  emptyPanel: { textAlign: "center", padding: "var(--space-8)", color: "var(--color-text-muted)" },
  successPanel: { textAlign: "center", padding: "var(--space-8)", color: "var(--color-success)", fontWeight: 600 },
  accountSection: { marginBottom: "var(--space-5)" },
  accountTitle: { fontSize: "var(--text-md)", fontWeight: 600, marginBottom: "var(--space-2)", color: "var(--color-text-primary)" },
  currency: { fontWeight: 400, color: "var(--color-text-muted)" },
  tableBlock: { marginBottom: "var(--space-3)" },
  tableHeader: { fontSize: "var(--text-sm)", fontWeight: 600, color: "var(--color-text-secondary)", textTransform: "capitalize", marginBottom: "var(--space-1)", display: "flex", justifyContent: "space-between" },
  rowCount: { fontWeight: 400, color: "var(--color-text-muted)" },
  valSummary: { padding: "var(--space-2) var(--space-3)", backgroundColor: "rgba(231,76,60,0.08)", borderRadius: "var(--border-radius-sm)", color: "var(--color-error)", fontSize: "var(--text-sm)", marginBottom: "var(--space-3)" },
  valGroup: { marginBottom: "var(--space-3)", backgroundColor: "#fff", border: "1px solid var(--color-border-light)", borderRadius: "var(--border-radius)" },
  valGroupHeader: { padding: "var(--space-2) var(--space-3)", fontWeight: 600, fontSize: "var(--text-sm)", textTransform: "capitalize", borderBottom: "1px solid var(--color-border-light)", display: "flex", justifyContent: "space-between" },
  valCount: { fontSize: "var(--text-xs)", backgroundColor: "var(--color-error)", color: "#fff", padding: "1px 6px", borderRadius: "8px" },
  valItem: { padding: "var(--space-2) var(--space-3)", fontSize: "var(--text-sm)", borderBottom: "1px solid var(--color-border-light)", display: "flex", gap: "var(--space-2)", alignItems: "baseline" },
  valDetail: { color: "var(--color-text-secondary)", fontSize: "var(--text-xs)" },
};
