import React, { useRef, useEffect } from "react";
import ConfidenceBadge from "../components/ConfidenceBadge";
import DataTable from "../components/DataTable";
import { filterTablesByPage } from "../utils/syncUtils";

/**
 * Tables panel for the Results Viewer screen.
 *
 * Displays extracted tables with page-synchronisation support:
 * - Table listing (table_id, type, page_range)
 * - Column headers and row data in scrollable DataTable
 * - Triangulation metadata: score (ConfidenceBadge), verdict (colour-coded), winning method
 * - Header highlighting: red for "hard_flag", amber for "soft_flag"
 * - Page-filtered view: shows only tables matching `currentPage` unless `showAllTables` is true
 * - Active-page highlight: distinct border/background on tables matching the current page
 * - Clickable table blocks: clicking navigates the PDF viewer to the table's first page
 * - "Show all tables" toggle: lets users opt out of page-filtered view
 *
 * @param {{
 *   tables: Array,
 *   currentPage: number,
 *   onTableClick: (table: object) => void,
 *   showAllTables: boolean,
 *   onToggleShowAll: () => void
 * }} props
 *   tables         — array of table objects from the extraction output
 *   currentPage    — the active PDF page number (1-indexed), owned by parent
 *   onTableClick   — called when the user clicks a table block
 *   showAllTables  — when true, bypass page filter and show all tables
 *   onToggleShowAll — called when the "Show all tables" toggle is changed
 *
 *   Each table: { table_id, type, page_range, headers, rows, triangulation }
 *   triangulation: { score, verdict, winner, methods }
 */
/**
 * Normalize rows to header-keyed objects for DataTable.
 * Handles two formats:
 *   1. {cells: [...], row_index: N}  — from the pipeline's TableRow model
 *   2. {"Header": value, ...}        — from LLM extractor (already keyed)
 */
function normalizeRows(rows, headers) {
  if (!rows || rows.length === 0) return [];
  const first = rows[0];
  // Already header-keyed (dict format from LLM extractor)
  if (first && typeof first === "object" && !Array.isArray(first.cells)) {
    return rows;
  }
  // cells-array format from pipeline TableRow model
  return rows.map((row) => {
    const cells = Array.isArray(row.cells) ? row.cells : (Array.isArray(row) ? row : []);
    const obj = {};
    headers.forEach((h, i) => {
      obj[h] = cells[i] ?? null;
    });
    return obj;
  });
}

/**
 * Filter rows to only those whose _source_pages includes the current page.
 * If no rows have _source_pages metadata, returns all rows (no filtering possible).
 */
function filterRowsByPage(rows, currentPage) {
  if (!rows || rows.length === 0 || !currentPage) return rows;
  const hasPageMeta = rows.some((r) => r && r._source_pages);
  if (!hasPageMeta) return rows;
  return rows.filter((r) => {
    if (!r || !r._source_pages) return true; // keep rows without metadata
    return r._source_pages.includes(currentPage);
  });
}

export default function ResultsTablesPanel({
  tables,
  currentPage,
  onTableClick,
  showAllTables,
  onToggleShowAll,
}) {
  const firstMatchRef = useRef(null);

  // Scroll the first matching table into view when the active page changes
  // or when the panel becomes visible (tab switch)
  useEffect(() => {
    if (!showAllTables && firstMatchRef.current) {
      firstMatchRef.current.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [currentPage, showAllTables]);

  // Also scroll on mount (when tab is first opened)
  useEffect(() => {
    if (!showAllTables && firstMatchRef.current) {
      firstMatchRef.current.scrollIntoView({ behavior: "instant", block: "nearest" });
    }
  }, []);

  // No tables extracted at all
  if (!tables || tables.length === 0) {
    return <div style={styles.emptyPanel}>No tables extracted.</div>;
  }

  // Compute the visible subset based on page filter
  // Fall back to all tables if page filter returns empty (avoids misleading "no tables" message)
  const filteredTables = showAllTables
    ? tables
    : filterTablesByPage(tables, currentPage);
  const visibleTables = filteredTables.length > 0 ? filteredTables : tables;

  return (
    <div style={styles.container}>
      {/* "Show all tables" toggle — only shown when at least one table exists */}
      <label style={styles.toggleLabel}>
        <input
          type="checkbox"
          checked={showAllTables}
          onChange={onToggleShowAll}
          aria-label="Show all tables"
        />
        Show all tables
      </label>

      {/* When page-filtered view has no matches, show all tables instead of empty message */}
      {!showAllTables && visibleTables.length === 0 && tables.length > 0 && (
        <div style={styles.emptyPage}>
          <span>Tables not tagged to page {currentPage}. Showing all tables.</span>
        </div>
      )}

      {visibleTables.map((table, index) => {
        const triangulation = table.triangulation || {};
        const verdict = triangulation.verdict || "agreement";
        const headerBg = getHeaderBackground(verdict);

        const columns = (table.headers || []).map((h) => ({
          key: h,
          label: h,
        }));

        // Determine whether this table is on the active page
        const isActive =
          !showAllTables &&
          Array.isArray(table.page_range) &&
          table.page_range.includes(currentPage);

        return (
          <div
            key={table.table_id || table.type}
            ref={index === 0 ? firstMatchRef : null}
            role="button"
            tabIndex={0}
            style={{
              ...styles.tableBlock,
              cursor: "pointer",
              borderLeft: isActive
                ? "3px solid var(--color-info)"
                : "3px solid transparent",
              backgroundColor: isActive
                ? "rgba(52,152,219,0.04)"
                : undefined,
            }}
            onClick={() => onTableClick(table)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onTableClick(table);
              }
            }}
          >
            {/* Table header with metadata */}
            <div style={{ ...styles.tableHeader, backgroundColor: headerBg }}>
              <div style={styles.tableHeaderLeft}>
                <span style={styles.tableId}>{table.table_id}</span>
                <span style={styles.tableType}>
                  {(table.type || "").replace(/_/g, " ")}
                </span>
                {table.page_range && table.page_range.length > 0 && (
                  <span style={styles.pageRange}>
                    pp. {table.page_range[0]}
                    {table.page_range.length > 1 ? `–${table.page_range[table.page_range.length - 1]}` : ""}
                  </span>
                )}
              </div>
              <div style={styles.tableHeaderRight}>
                <span style={styles.rowCount}>
                  {(() => {
                    const allRows = table.rows || [];
                    const filtered = showAllTables ? allRows : filterRowsByPage(allRows, currentPage);
                    return filtered.length === allRows.length
                      ? `${allRows.length} rows`
                      : `${filtered.length} / ${allRows.length} rows (p.${currentPage})`;
                  })()}
                </span>
              </div>
            </div>

            {/* Triangulation metadata */}
            <div style={styles.triangulationBar}>
              <div style={styles.triItem}>
                <span style={styles.triLabel}>Score</span>
                <ConfidenceBadge value={triangulation.score} />
              </div>
              <div style={styles.triItem}>
                <span style={styles.triLabel}>Verdict</span>
                <span style={{ ...styles.triVerdict, color: getVerdictColour(verdict) }}>
                  {verdict.replace(/_/g, " ")}
                </span>
              </div>
              <div style={styles.triItem}>
                <span style={styles.triLabel}>Winner</span>
                <span style={styles.triValue}>
                  {triangulation.winner || "—"}
                </span>
              </div>
            </div>

            {/* Table data — filter rows by current page when not showing all */}
            <DataTable columns={columns} rows={normalizeRows(
              showAllTables ? (table.rows || []) : filterRowsByPage(table.rows || [], currentPage),
              table.headers || []
            )} />
          </div>
        );
      })}
    </div>
  );
}

/**
 * Returns the background colour for the table header based on verdict.
 * - "hard_flag" → red tint
 * - "soft_flag" → amber tint
 * - "agreement" or other → default surface
 */
function getHeaderBackground(verdict) {
  switch (verdict) {
    case "hard_flag":
      return "rgba(231, 76, 60, 0.12)";
    case "soft_flag":
      return "rgba(243, 156, 18, 0.12)";
    default:
      return "var(--color-surface)";
  }
}

/**
 * Returns the text colour for the verdict label.
 */
function getVerdictColour(verdict) {
  switch (verdict) {
    case "hard_flag":
      return "var(--color-error)";
    case "soft_flag":
      return "var(--color-warning)";
    case "agreement":
      return "var(--color-success)";
    default:
      return "var(--color-text-secondary)";
  }
}

const styles = {
  container: {
    display: "flex",
    flexDirection: "column",
    gap: "var(--space-5)",
    minWidth: "max-content",
  },
  emptyPanel: {
    textAlign: "center",
    padding: "var(--space-8)",
    color: "var(--color-text-muted)",
  },
  emptyPage: {
    textAlign: "center",
    padding: "var(--space-8)",
    color: "var(--color-text-muted)",
  },
  toggleLabel: {
    display: "flex",
    alignItems: "center",
    gap: "var(--space-2)",
    fontSize: "var(--text-sm)",
    color: "var(--color-text-secondary)",
    cursor: "pointer",
    userSelect: "none",
  },
  tableBlock: {
    border: "1px solid var(--color-border-light)",
    borderRadius: "var(--border-radius)",
    overflow: "hidden",
  },
  tableHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    padding: "var(--space-2) var(--space-3)",
    borderBottom: "1px solid var(--color-border-light)",
  },
  tableHeaderLeft: {
    display: "flex",
    alignItems: "center",
    gap: "var(--space-2)",
  },
  tableHeaderRight: {
    display: "flex",
    alignItems: "center",
    gap: "var(--space-2)",
  },
  tableId: {
    fontFamily: "var(--font-mono)",
    fontSize: "var(--text-sm)",
    fontWeight: 600,
    color: "var(--color-text-primary)",
  },
  tableType: {
    fontSize: "var(--text-sm)",
    color: "var(--color-text-secondary)",
    textTransform: "capitalize",
  },
  pageRange: {
    fontSize: "var(--text-xs)",
    color: "var(--color-text-muted)",
    backgroundColor: "rgba(0,0,0,0.04)",
    padding: "1px 6px",
    borderRadius: "var(--border-radius-sm)",
  },
  rowCount: {
    fontSize: "var(--text-xs)",
    color: "var(--color-text-muted)",
  },
  triangulationBar: {
    display: "flex",
    gap: "var(--space-5)",
    padding: "var(--space-2) var(--space-3)",
    backgroundColor: "#fff",
    borderBottom: "1px solid var(--color-border-light)",
  },
  triItem: {
    display: "flex",
    alignItems: "center",
    gap: "var(--space-2)",
  },
  triLabel: {
    fontSize: "var(--text-xs)",
    color: "var(--color-text-muted)",
    textTransform: "uppercase",
  },
  triVerdict: {
    fontSize: "var(--text-sm)",
    fontWeight: 600,
    textTransform: "capitalize",
  },
  triValue: {
    fontSize: "var(--text-sm)",
    color: "var(--color-text-primary)",
  },
};
