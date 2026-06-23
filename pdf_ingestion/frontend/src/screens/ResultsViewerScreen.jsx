import React, { useState, useEffect } from "react";
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
import PdfViewer from "../components/PdfViewer";
import ResultsAbstentionsPanel from "./ResultsAbstentionsPanel";
import ResultsTablesPanel from "./ResultsTablesPanel";
import ResultsValidationPanel, { getValidationBadgeCount } from "./ResultsValidationPanel";
import ChatPanel from "../components/ChatPanel";
import SchemaApprovalBanner from "../components/SchemaApprovalBanner";
import { exportToCSV, exportToExcel } from "../utils/exportData";
import { clampPage, resolveTableClickPage } from "../utils/syncUtils";

const FINANCIAL_FIELDS = new Set(["iban", "isin", "bic", "swift_code", "account_number", "doc_hash"]);

/**
 * Determines if a field name is a financial identifier that should use MonospaceField.
 */
export function isFinancialIdentifier(fieldName) {
  return FINANCIAL_FIELDS.has(fieldName);
}

export default function ResultsViewerScreen() {
  const { jobId } = useParams();
  const navigate = useNavigate();
  const { data: result, loading, error } = useApi(`/v1/results/${jobId}`);
  const { data: jobData } = useApi(`/v1/jobs/${jobId}`);
  const [activeTab, setActiveTab] = useState("overview");
  const [correction, setCorrection] = useState(null);
  const [pdfHighlights, setPdfHighlights] = useState([]);
  const [currentPage, setCurrentPage] = useState(1);
  const [totalPages, setTotalPages] = useState(0);
  const [showAllTables, setShowAllTables] = useState(false);
  const [pendingSchemaId, setPendingSchemaId] = useState(null);
  const [overviewExpanded, setOverviewExpanded] = useState(false);

  // Get all jobs for prev/next navigation
  const allJobs = JSON.parse(sessionStorage.getItem("pdf_jobs") || "[]");
  const currentIndex = allJobs.indexOf(jobId);
  const prevJobId = currentIndex > 0 ? allJobs[currentIndex - 1] : null;
  const nextJobId = currentIndex < allJobs.length - 1 ? allJobs[currentIndex + 1] : null;

  // Initialise pendingSchemaId from output when it loads
  useEffect(() => {
    const output = result?.output || result || {};
    if (output?.pending_schema_id) {
      setPendingSchemaId(output.pending_schema_id);
    }
  }, [result]);

  // Remember the last result viewed so the "Results" LHS section can land here.
  useEffect(() => {
    if (jobId) sessionStorage.setItem("last_result_job", jobId);
  }, [jobId]);

  function handlePageChange(page) {
    // Just track the page — do NOT force the active tab. (Auto-switching to
    // "tables" on every page change made the other tabs feel unavailable.)
    setCurrentPage(clampPage(page, totalPages));
  }

  function handleTotalPages(n) {
    setTotalPages(n);
  }

  function handleTableClick(table) {
    if (!table.page_range || table.page_range.length === 0) return;
    setCurrentPage(resolveTableClickPage(table, totalPages, currentPage));
  }

  if (loading) return <div style={styles.loading}>Loading results...</div>;
  if (error) {
    return (
      <div>
        <div style={styles.navBar}>
          <button onClick={() => navigate("/queue")} style={styles.backBtn}>← Back to Queue</button>
        </div>
        <div style={styles.failedPanel}>
          <div style={styles.failedIcon}>⚠</div>
          <h2 style={{ ...styles.failedTitle, color: "var(--color-warning)" }}>Results Not Available</h2>
          <p style={{ fontSize: "var(--text-md)", color: "var(--color-text-secondary)", marginTop: "var(--space-2)", marginBottom: "var(--space-4)" }}>
            This job's results are no longer available. The server may have been restarted.
          </p>
          <button
            onClick={() => {
              // Remove stale job from session before navigating
              const stored = JSON.parse(sessionStorage.getItem("pdf_jobs") || "[]");
              sessionStorage.setItem("pdf_jobs", JSON.stringify(stored.filter((id) => id !== jobId)));
              navigate("/submit");
            }}
            style={{ padding: "var(--space-2) var(--space-5)", backgroundColor: "var(--color-info)", color: "#fff", border: "none", borderRadius: "var(--border-radius-sm)", fontSize: "var(--text-md)", fontWeight: 600, cursor: "pointer" }}
          >
            ↑ Re-submit File
          </button>
        </div>
      </div>
    );
  }

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

  // Collect tables: prefer output.tables (spec format) if non-empty, fallback to accounts-based tables
  const tables = (output.tables && output.tables.length > 0) ? output.tables : accounts.reduce((all, acct) => {
    (acct?.tables || []).forEach((tbl) => {
      all.push({
        table_id: tbl.table_id || `${acct.account_number || acct.iban || "table"}_${all.length}`,
        type: tbl.table_type || tbl.type || "transaction",
        page_range: tbl.page_range || [],
        headers: tbl.headers || [],
        rows: tbl.rows || [],
        triangulation: tbl.triangulation || null,
      });
    });
    return all;
  }, []);

  // Highlights for the Overview PDF: every extracted field that carries a
  // provenance bbox, drawn on its own page (PdfViewer filters by current page).
  const fieldHighlights = Object.entries(fields)
    .filter(([, f]) => f && typeof f === "object" && f.provenance?.bbox)
    .map(([name, f]) => ({ fieldName: name, page: f.provenance.page ?? 1, ...f.provenance.bbox }));

  const tabs = [
    { id: "overview", label: "Overview" },
    { id: "fields", label: "Fields" },
    { id: "tables", label: `Tables (${tables.length})` },
    { id: "abstentions", label: `Abstentions (${abstentions.length})` },
    { id: "validation", label: "Validation", badge: getValidationBadgeCount(valFailures) },
    { id: "chat", label: "Chat" },
    { id: "source", label: "Source PDF" },
  ];

  return (
    <div>
      {/* ── Header — always visible, in normal flow ── */}
      <div style={{ position: 'sticky', top: 0, zIndex: 10, backgroundColor: 'var(--color-bg, #f9fafb)', paddingBottom: 'var(--space-2)' }}>
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

        {/* Export buttons (source PDF is now a tab below) */}
        <div style={{ display: 'flex', gap: '8px', marginBottom: '12px', alignItems: 'center' }}>
          <button onClick={() => exportToCSV(result, jobData?.filename?.replace('.pdf', '') || jobId)} style={styles.exportBtn}>
            ↓ Export CSV
          </button>
          <button onClick={() => exportToExcel(result, jobData?.filename?.replace('.pdf', '') || jobId)} style={styles.exportBtn}>
            ↓ Export Excel
          </button>
        </div>
      </div>

      {/* ── Results body — single column; Source PDF is its own tab ── */}
      <div>
        {/* Schema Approval Banner — shown when a pending schema exists or LLM escalated */}
        {(pendingSchemaId != null || output?.llm_escalated) && (
          <SchemaApprovalBanner
            jobId={jobId}
            pendingSchemaId={pendingSchemaId || output?.pending_schema_id}
            schemaLabel={output?.schema_type}
            institution={output?.fields?.institution?.value}
            fieldCount={Object.keys(output?.fields || {}).length}
            tableCount={tables.length}
            onApproved={() => setPendingSchemaId(null)}
            onDiscarded={() => setPendingSchemaId(null)}
          />
        )}

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
          {activeTab === "overview" && (
            <div style={overviewExpanded ? styles.overviewOverlay : undefined}>
              <div style={styles.overviewToolbar}>
                <span style={styles.overviewHint}>
                  Source (page {currentPage}) with field highlights · extracted tables
                </span>
                <button
                  onClick={() => setOverviewExpanded((v) => !v)}
                  style={styles.expandBtn}
                  title={overviewExpanded ? "Collapse" : "Expand to full screen"}
                >
                  {overviewExpanded ? "⤡ Collapse" : "⤢ Expand"}
                </button>
              </div>
              <div
                style={{
                  ...styles.overviewSplit,
                  ...(overviewExpanded ? { flex: 1, minHeight: 0 } : { height: "72vh" }),
                }}
              >
                <div style={styles.overviewPane}>
                  <PdfViewer
                    jobId={jobId}
                    highlights={fieldHighlights}
                    currentPage={currentPage}
                    onPageChange={handlePageChange}
                    onTotalPages={handleTotalPages}
                  />
                </div>
                <div style={{ ...styles.overviewPane, overflow: "auto" }}>
                  {tables.length > 0 ? (
                    <ResultsTablesPanel
                      tables={tables}
                      currentPage={currentPage}
                      onTableClick={handleTableClick}
                      showAllTables={true}
                      onToggleShowAll={() => {}}
                    />
                  ) : (
                    <div style={styles.emptyPanel}>No tables extracted.</div>
                  )}
                </div>
              </div>
            </div>
          )}
          {activeTab === "fields" && (
            <FieldsPanel
              fields={fields}
              onCorrect={(name, val) => setCorrection({ name, val })}
              onViewSource={(name, field) => {
                if (field?.provenance?.bbox) {
                  setPdfHighlights([{ fieldName: name, ...field.provenance.bbox }]);
                  setCurrentPage(field.provenance.page ?? 1);
                  setActiveTab("source");
                }
              }}
            />
          )}
          {activeTab === "tables" && <ResultsTablesPanel
            tables={tables}
            currentPage={currentPage}
            onTableClick={handleTableClick}
            showAllTables={showAllTables}
            onToggleShowAll={() => setShowAllTables((v) => !v)}
          />}
          {activeTab === "abstentions" && <ResultsAbstentionsPanel abstentions={abstentions} />}
          {activeTab === "validation" && <ResultsValidationPanel failures={valFailures} />}
          {activeTab === "chat" && <ChatPanel jobId={jobId} filename={jobData?.filename} onPendingSchema={(id) => setPendingSchemaId(id)} />}
          {activeTab === "source" && (
            <div style={styles.pdfTabPane}>
              <PdfViewer
                jobId={jobId}
                highlights={pdfHighlights}
                currentPage={currentPage}
                onPageChange={handlePageChange}
                onTotalPages={handleTotalPages}
              />
            </div>
          )}
        </div>
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

function FieldsPanel({ fields, onCorrect, onViewSource }) {
  const [showTechnical, setShowTechnical] = React.useState(false);

  // Top-level scalar fields (exclude accounts array)
  const topEntries = Object.entries(fields).filter(([k]) => k !== "accounts");

  // Account-level scalar fields (opening_balance, currency, iban, account_type, etc.)
  const accounts = fields.accounts?.value || [];
  const accountEntries = [];
  if (accounts.length > 0) {
    const ACCOUNT_SCALAR_KEYS = ["account_number", "iban", "currency", "account_type", "opening_balance", "closing_balance"];
    accounts.forEach((acct, i) => {
      if (!acct || typeof acct !== "object") return;
      const label = acct.account_number || acct.iban || `Account ${i + 1}`;
      ACCOUNT_SCALAR_KEYS.forEach((key) => {
        if (acct[key] != null) {
          accountEntries.push({
            name: key,
            displayName: `${label} · ${key.replace(/_/g, " ")}`,
            value: acct[key],
            isAccountField: true,
          });
        }
      });
    });
  }

  const allEntries = [
    ...topEntries.map(([name, field]) => ({ name, displayName: name.replace(/_/g, " "), field, isAccountField: false })),
    ...accountEntries.map(({ name, displayName, value, isAccountField }) => ({
      name,
      displayName,
      field: { value, confidence: null, vlm_used: false, provenance: null },
      isAccountField,
    })),
  ];

  if (allEntries.length === 0) return <div style={styles.emptyPanel}>No fields extracted.</div>;

  // Grid template: name | value | [confidence | vlm | provenance] | actions
  const gridTemplate = showTechnical
    ? "180px 1fr 80px 48px 48px 80px"
    : "180px 1fr 80px";

  return (
    <div>
      {/* Toggle */}
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: "var(--space-2)" }}>
        <button
          onClick={() => setShowTechnical((v) => !v)}
          style={{
            padding: "3px 10px",
            fontSize: "var(--text-xs)",
            backgroundColor: showTechnical ? "rgba(52,152,219,0.1)" : "var(--color-surface)",
            color: showTechnical ? "var(--color-info)" : "var(--color-text-muted)",
            border: "1px solid var(--color-border)",
            borderRadius: "var(--border-radius-sm)",
            cursor: "pointer",
            fontWeight: showTechnical ? 600 : 400,
          }}
        >
          {showTechnical ? "⊙ Hide technical" : "⊙ Show technical"}
        </button>
      </div>

      {/* Table */}
      <div style={{ ...styles.fieldsGrid, display: "grid", gridTemplateColumns: gridTemplate }}>
        {/* Header row */}
        <div style={styles.fieldHeaderCell}>Field</div>
        <div style={styles.fieldHeaderCell}>Value</div>
        {showTechnical && <div style={{ ...styles.fieldHeaderCell, textAlign: "center" }}>Confidence</div>}
        {showTechnical && <div style={{ ...styles.fieldHeaderCell, textAlign: "center" }}>VLM</div>}
        {showTechnical && <div style={{ ...styles.fieldHeaderCell, textAlign: "center" }}>Source</div>}
        <div style={{ ...styles.fieldHeaderCell, textAlign: "right" }}>Actions</div>

        {/* Data rows */}
        {allEntries.map(({ name, displayName, field, isAccountField }) => (
          <FieldRow
            key={`${isAccountField ? "acct_" : ""}${displayName}`}
            name={name}
            displayName={displayName}
            field={field}
            showTechnical={showTechnical}
            isAccountField={isAccountField}
            onCorrect={onCorrect}
            onViewSource={onViewSource}
          />
        ))}
      </div>
    </div>
  );
}

function FieldRow({ name, displayName, field, showTechnical, isAccountField, onCorrect, onViewSource }) {
  const [hovered, setHovered] = React.useState(false);

  const isFinancial = FINANCIAL_FIELDS.has(name);
  const displayValue = field?.value != null
    ? (typeof field.value === "object" ? JSON.stringify(field.value) : String(field.value))
    : "—";
  const confidence = field?.confidence;
  const vlmUsed = field?.vlm_used === true;
  const provenance = field?.provenance;

  const rowBg = hovered ? "rgba(52,152,219,0.03)" : isAccountField ? "rgba(0,0,0,0.01)" : "transparent";

  return (
    <>
      {/* Field name */}
      <div
        style={{ ...styles.fieldCell, backgroundColor: rowBg, fontWeight: 500, color: isAccountField ? "var(--color-text-muted)" : "var(--color-text-secondary)", textTransform: "capitalize", fontSize: isAccountField ? "var(--text-sm)" : undefined }}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
      >
        {displayName || name.replace(/_/g, " ")}
      </div>

      {/* Value */}
      <div
        style={{ ...styles.fieldCell, backgroundColor: rowBg, cursor: "pointer" }}
        onClick={() => onCorrect(name, field?.value)}
        title="Click to submit correction"
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
      >
        {isFinancial ? (
          <MonospaceField>{displayValue}</MonospaceField>
        ) : (
          <span>{displayValue}</span>
        )}
      </div>

      {/* Technical columns — only rendered when toggle is on */}
      {showTechnical && (
        <div
          style={{ ...styles.fieldCell, backgroundColor: rowBg, justifyContent: "center" }}
          onMouseEnter={() => setHovered(true)}
          onMouseLeave={() => setHovered(false)}
        >
          <ConfidenceBadge value={confidence} />
        </div>
      )}
      {showTechnical && (
        <div
          style={{ ...styles.fieldCell, backgroundColor: rowBg, justifyContent: "center" }}
          onMouseEnter={() => setHovered(true)}
          onMouseLeave={() => setHovered(false)}
        >
          {vlmUsed && <span style={styles.vlmTag}>VLM</span>}
        </div>
      )}
      {showTechnical && (
        <div
          style={{ ...styles.fieldCell, backgroundColor: rowBg, justifyContent: "center" }}
          onMouseEnter={() => setHovered(true)}
          onMouseLeave={() => setHovered(false)}
        >
          {provenance && (
            <ProvenanceTooltip
              page={provenance.page}
              bbox={provenance.bbox}
              sourceRail={provenance.source_rail}
              rule={provenance.rule}
            />
          )}
        </div>
      )}

      {/* Actions */}
      <div
        style={{ ...styles.fieldCell, backgroundColor: rowBg, justifyContent: "flex-end", gap: "var(--space-1)" }}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
      >
        {provenance?.bbox && (
          <button
            onClick={() => onViewSource && onViewSource(name, field)}
            style={{ ...styles.viewSourceBtn, opacity: hovered ? 1 : 0 }}
            title="View in PDF"
          >
            ⊞
          </button>
        )}
        <button
          onClick={() => onCorrect(name, field?.value)}
          style={styles.editBtn}
          title="Submit a correction for this field"
        >
          ✎ Correct
        </button>
      </div>
    </>
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
  tabBar: { display: "flex", flexWrap: "wrap", gap: 0, borderBottom: "1px solid var(--color-border-light)", marginBottom: "var(--space-4)" },
  pdfTabPane: { height: "72vh", minHeight: 480, border: "1px solid var(--color-border-light)", borderRadius: "var(--border-radius)", display: "flex", flexDirection: "column", overflow: "hidden" },
  // Overview tab — PDF (left) + extracted tables (right).
  overviewToolbar: { display: "flex", justifyContent: "space-between", alignItems: "center", gap: "var(--space-2)", marginBottom: "var(--space-2)" },
  overviewHint: { fontSize: "var(--text-xs)", color: "var(--color-text-muted)" },
  overviewSplit: { display: "flex", gap: "var(--space-4)", minHeight: 480 },
  overviewPane: { flex: 1, minWidth: 0, height: "100%", border: "1px solid var(--color-border-light)", borderRadius: "var(--border-radius)", display: "flex", flexDirection: "column", overflow: "hidden" },
  // Expanded: cover the main content area full-screen but keep the LHS sidebar visible.
  overviewOverlay: { position: "fixed", top: 0, right: 0, bottom: 0, left: "var(--sidebar-width)", backgroundColor: "var(--color-bg, #f9fafb)", zIndex: 200, padding: "var(--space-4)", display: "flex", flexDirection: "column" },
  expandBtn: { padding: "4px 10px", fontSize: "var(--text-sm)", backgroundColor: "var(--color-surface)", border: "1px solid var(--color-border)", borderRadius: "var(--border-radius-sm)", cursor: "pointer", fontWeight: 500, whiteSpace: "nowrap" },
  tab: { padding: "var(--space-2) var(--space-4)", border: "none", borderBottom: "2px solid transparent", background: "none", cursor: "pointer", fontSize: "var(--text-md)", color: "var(--color-text-secondary)", display: "flex", alignItems: "center", gap: "var(--space-1)" },
  tabActive: { borderBottomColor: "var(--color-info)", color: "var(--color-info)", fontWeight: 600 },
  tabBadge: { backgroundColor: "var(--color-error)", color: "#fff", fontSize: "var(--text-xs)", padding: "1px 5px", borderRadius: "8px", fontWeight: 600 },
  tabContent: { minHeight: 200 },
  fieldsGrid: { backgroundColor: "#fff", borderRadius: "var(--border-radius)", border: "1px solid var(--color-border-light)", overflow: "hidden" },
  fieldHeaderCell: { padding: "var(--space-2) var(--space-3)", borderBottom: "2px solid var(--color-border-light)", backgroundColor: "var(--color-surface)", fontWeight: 600, fontSize: "var(--text-xs)", color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.03em", display: "flex", alignItems: "center" },
  fieldCell: { display: "flex", alignItems: "center", padding: "var(--space-2) var(--space-3)", borderBottom: "1px solid var(--color-border-light)", fontSize: "var(--text-md)", color: "var(--color-text-primary)", transition: "background 150ms ease", minHeight: 36 },
  vlmTag: { fontSize: "var(--text-xs)", color: "var(--color-info)", fontWeight: 600, backgroundColor: "rgba(52,152,219,0.1)", padding: "1px 4px", borderRadius: "3px" },
  provenanceHint: { fontSize: "var(--text-xs)", color: "var(--color-text-muted)", cursor: "help" },
  editBtn: { padding: "2px 8px", fontSize: "var(--text-xs)", color: "var(--color-info)", backgroundColor: "rgba(52,152,219,0.08)", border: "1px solid rgba(52,152,219,0.2)", borderRadius: "var(--border-radius-sm)", cursor: "pointer", transition: "opacity 150ms ease", fontWeight: 500, whiteSpace: "nowrap" },
  exportBtn: { padding: '6px 12px', fontSize: 'var(--text-sm)', backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)', borderRadius: 'var(--border-radius-sm)', cursor: 'pointer', fontWeight: 500 },
  viewSourceBtn: { padding: "2px 8px", fontSize: "var(--text-xs)", color: "var(--color-text-muted)", backgroundColor: "transparent", border: "1px solid var(--color-border)", borderRadius: "var(--border-radius-sm)", cursor: "pointer", transition: "opacity 150ms ease", whiteSpace: "nowrap" },
  emptyPanel: { textAlign: "center", padding: "var(--space-8)", color: "var(--color-text-muted)" },
  successPanel: { textAlign: "center", padding: "var(--space-8)", color: "var(--color-success)", fontWeight: 600 },
  accountSection: { marginBottom: "var(--space-5)" },
  accountTitle: { fontSize: "var(--text-md)", fontWeight: 600, marginBottom: "var(--space-2)", color: "var(--color-text-primary)" },
  currency: { fontWeight: 400, color: "var(--color-text-muted)" },
  tableBlock: { marginBottom: "var(--space-3)" },
  tableHeader: { fontSize: "var(--text-sm)", fontWeight: 600, color: "var(--color-text-secondary)", textTransform: "capitalize", marginBottom: "var(--space-1)", display: "flex", justifyContent: "space-between" },
  rowCount: { fontWeight: 400, color: "var(--color-text-muted)" },
};
