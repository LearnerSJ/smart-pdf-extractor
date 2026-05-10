import React, { useState, useCallback } from "react";
import { useFetch } from "./useFetch.js";
import { useAuth } from "./AuthContext.jsx";

/**
 * AlertsPage — alerts management page with rule CRUD and history.
 *
 * Sub-components:
 *   - AlertRuleList: displays all alert rules with status badges and circuit breaker indicators
 *   - AlertRuleForm: create/edit alert rule form with dynamic config fields
 *   - AlertHistory: displays past alert firings with acknowledgment
 */
export default function AlertsPage({ apiBaseUrl = "" }) {
  const { token, logout } = useAuth();
  const [view, setView] = useState("rules"); // "rules" | "history"
  const [editingRule, setEditingRule] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const [mutating, setMutating] = useState(false);
  const [mutateError, setMutateError] = useState(null);
  const [validationErrors, setValidationErrors] = useState(null);

  // Fetch rules
  const rulesUrl = `${apiBaseUrl}/v1/admin/alerts/rules`;
  const { data: rulesData, loading: rulesLoading, error: rulesError, refetch: refetchRules } = useFetch(rulesUrl);

  // Fetch history
  const historyUrl = `${apiBaseUrl}/v1/admin/alerts/history`;
  const { data: historyData, loading: historyLoading, error: historyError, refetch: refetchHistory } = useFetch(historyUrl);

  const rules = rulesData?.data?.rules || [];
  const historyEntries = historyData?.data?.entries || [];

  // Manual mutation helper
  const doMutate = useCallback(async (url, method, body) => {
    setMutating(true);
    setMutateError(null);
    setValidationErrors(null);
    try {
      const headers = { "Content-Type": "application/json" };
      if (token) headers["Authorization"] = `Bearer ${token}`;

      const response = await fetch(url, {
        method,
        headers,
        body: body ? JSON.stringify(body) : undefined,
      });

      if (response.status === 401) {
        logout();
        setMutateError("Session expired. Please log in again.");
        return null;
      }

      if (response.status === 422) {
        const errBody = await response.json().catch(() => ({}));
        const detail = errBody.detail || "Validation error";
        setValidationErrors(detail);
        return null;
      }

      if (!response.ok) {
        const errBody = await response.json().catch(() => ({}));
        throw new Error(errBody.detail || errBody.message || `Request failed (${response.status})`);
      }

      return await response.json();
    } catch (err) {
      setMutateError(err.message);
      return null;
    } finally {
      setMutating(false);
    }
  }, [token, logout]);

  const handleCreateNew = () => {
    setEditingRule(null);
    setShowForm(true);
    setValidationErrors(null);
    setMutateError(null);
  };

  const handleEdit = (rule) => {
    setEditingRule(rule);
    setShowForm(true);
    setValidationErrors(null);
    setMutateError(null);
  };

  const handleCancelForm = () => {
    setShowForm(false);
    setEditingRule(null);
    setValidationErrors(null);
    setMutateError(null);
  };

  const handleSaveRule = async (ruleData) => {
    const url = editingRule
      ? `${apiBaseUrl}/v1/admin/alerts/rules/${editingRule.id}`
      : `${apiBaseUrl}/v1/admin/alerts/rules`;
    const method = editingRule ? "PUT" : "POST";

    const result = await doMutate(url, method, ruleData);
    if (result) {
      setShowForm(false);
      setEditingRule(null);
      refetchRules();
    }
  };

  const handleDeleteRule = async (ruleId) => {
    if (!window.confirm("Are you sure you want to delete this alert rule?")) return;
    const result = await doMutate(`${apiBaseUrl}/v1/admin/alerts/rules/${ruleId}`, "DELETE");
    if (result) {
      refetchRules();
    }
  };

  const handleAcknowledge = async (alertId) => {
    const result = await doMutate(`${apiBaseUrl}/v1/admin/alerts/${alertId}/ack`, "POST");
    if (result) {
      refetchHistory();
    }
  };

  return (
    <div style={styles.page}>
      {/* Tab navigation */}
      <div style={styles.tabBar}>
        <button
          style={view === "rules" ? styles.tabActive : styles.tab}
          onClick={() => setView("rules")}
        >
          Alert Rules
        </button>
        <button
          style={view === "history" ? styles.tabActive : styles.tab}
          onClick={() => setView("history")}
        >
          Alert History
        </button>
      </div>

      {mutateError && <div style={styles.errorBanner}>{mutateError}</div>}

      {view === "rules" && (
        <>
          {showForm ? (
            <AlertRuleForm
              rule={editingRule}
              onSave={handleSaveRule}
              onCancel={handleCancelForm}
              saving={mutating}
              validationErrors={validationErrors}
            />
          ) : (
            <AlertRuleList
              rules={rules}
              loading={rulesLoading}
              error={rulesError}
              onCreateNew={handleCreateNew}
              onEdit={handleEdit}
              onDelete={handleDeleteRule}
            />
          )}
        </>
      )}

      {view === "history" && (
        <AlertHistory
          entries={historyEntries}
          rules={rules}
          loading={historyLoading}
          error={historyError}
          onAcknowledge={handleAcknowledge}
        />
      )}
    </div>
  );
}

// ─── AlertRuleList ───────────────────────────────────────────────────────────

function AlertRuleList({ rules, loading, error, onCreateNew, onEdit, onDelete }) {
  if (loading) {
    return <div style={styles.loadingText}>Loading alert rules...</div>;
  }

  if (error) {
    return <div style={styles.errorBanner}>{error}</div>;
  }

  return (
    <div style={styles.section}>
      <div style={styles.sectionHeader}>
        <h3 style={styles.sectionTitle}>Alert Rules</h3>
        <button style={styles.primaryBtn} onClick={onCreateNew}>
          + New Rule
        </button>
      </div>

      {rules.length === 0 ? (
        <div style={styles.emptyState}>No alert rules configured yet.</div>
      ) : (
        <div style={styles.tableContainer}>
          <div style={styles.tableWrapper}>
            <table style={styles.table}>
              <thead>
                <tr>
                  <th style={styles.th}>Status</th>
                  <th style={styles.th}>Name</th>
                  <th style={styles.th}>Type</th>
                  <th style={styles.th}>Tenant</th>
                  <th style={styles.th}>Channel</th>
                  <th style={styles.th}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {rules.map((rule) => (
                  <tr key={rule.id} style={styles.tr}>
                    <td style={styles.td}>
                      <RuleStatusBadge rule={rule} />
                    </td>
                    <td style={styles.td}>
                      <span style={styles.ruleName}>
                        {rule.state === "firing" && (
                          <span style={styles.firingDot} title="Circuit breaker firing" />
                        )}
                        {rule.name}
                      </span>
                    </td>
                    <td style={styles.td}>
                      <span style={styles.ruleType}>{rule.rule_type}</span>
                    </td>
                    <td style={styles.td}>{rule.tenant_id || "Global"}</td>
                    <td style={styles.td}>{rule.notification_channel}</td>
                    <td style={styles.td}>
                      <div style={styles.actionBtns}>
                        <button style={styles.editBtn} onClick={() => onEdit(rule)}>
                          Edit
                        </button>
                        <button style={styles.deleteBtn} onClick={() => onDelete(rule.id)}>
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── RuleStatusBadge ─────────────────────────────────────────────────────────

function RuleStatusBadge({ rule }) {
  let label = "";
  let badgeStyle = {};

  if (!rule.enabled) {
    label = "disabled";
    badgeStyle = { backgroundColor: "#f3f4f6", color: "#6b7280" };
  } else if (rule.state === "firing") {
    label = "firing";
    badgeStyle = { backgroundColor: "#fef2f2", color: "#dc2626" };
  } else if (rule.state === "resolved") {
    label = "resolved";
    badgeStyle = { backgroundColor: "#f0fdf4", color: "#16a34a" };
  } else {
    // idle + enabled
    label = "enabled";
    badgeStyle = { backgroundColor: "#eff6ff", color: "#2563eb" };
  }

  return (
    <span style={{ ...styles.badge, ...badgeStyle }}>
      {label}
    </span>
  );
}

// ─── AlertRuleForm ───────────────────────────────────────────────────────────

function AlertRuleForm({ rule, onSave, onCancel, saving, validationErrors }) {
  const [name, setName] = useState(rule?.name || "");
  const [ruleType, setRuleType] = useState(rule?.rule_type || "budget");
  const [tenantId, setTenantId] = useState(rule?.tenant_id || "");
  const [notificationChannel, setNotificationChannel] = useState(rule?.notification_channel || "webhook");
  const [notificationTarget, setNotificationTarget] = useState(rule?.notification_target || "");
  const [enabled, setEnabled] = useState(rule?.enabled !== undefined ? rule.enabled : true);

  // Dynamic config fields
  const [thresholdTokens, setThresholdTokens] = useState(
    rule?.config?.threshold_tokens || ""
  );
  const [billingPeriod, setBillingPeriod] = useState(
    rule?.config?.billing_period || "monthly"
  );
  const [thresholdPercent, setThresholdPercent] = useState(
    rule?.config?.threshold_percent || ""
  );
  const [evaluationWindow, setEvaluationWindow] = useState(
    rule?.config?.evaluation_window_minutes || ""
  );
  const [serviceName, setServiceName] = useState(
    rule?.config?.service_name || ""
  );

  const buildConfig = () => {
    if (ruleType === "budget") {
      return {
        threshold_tokens: parseInt(thresholdTokens, 10) || 0,
        billing_period: billingPeriod,
      };
    } else if (ruleType === "error_rate") {
      return {
        threshold_percent: parseFloat(thresholdPercent) || 0,
        evaluation_window_minutes: parseInt(evaluationWindow, 10) || 0,
      };
    } else if (ruleType === "circuit_breaker") {
      return {
        service_name: serviceName,
      };
    }
    return {};
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    const data = {
      name,
      rule_type: ruleType,
      tenant_id: tenantId || null,
      config: buildConfig(),
      notification_channel: notificationChannel,
      notification_target: notificationTarget,
      enabled,
    };

    // For updates, only send changed fields
    if (rule) {
      const updateData = {};
      if (name !== rule.name) updateData.name = name;
      updateData.config = buildConfig();
      if (notificationChannel !== rule.notification_channel) updateData.notification_channel = notificationChannel;
      if (notificationTarget !== rule.notification_target) updateData.notification_target = notificationTarget;
      if (enabled !== rule.enabled) updateData.enabled = enabled;
      onSave(updateData);
    } else {
      onSave(data);
    }
  };

  return (
    <div style={styles.section}>
      <div style={styles.sectionHeader}>
        <h3 style={styles.sectionTitle}>{rule ? "Edit Alert Rule" : "Create Alert Rule"}</h3>
      </div>

      {validationErrors && (
        <div style={styles.validationBanner}>{validationErrors}</div>
      )}

      <form onSubmit={handleSubmit} style={styles.form}>
        <div style={styles.formRow}>
          <div style={styles.formGroup}>
            <label style={styles.formLabel}>Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Alert rule name"
              style={styles.formInput}
              required
            />
          </div>

          <div style={styles.formGroup}>
            <label style={styles.formLabel}>Rule Type</label>
            <select
              value={ruleType}
              onChange={(e) => setRuleType(e.target.value)}
              style={styles.formSelect}
              disabled={!!rule}
            >
              <option value="budget">Budget</option>
              <option value="error_rate">Error Rate</option>
              <option value="circuit_breaker">Circuit Breaker</option>
            </select>
          </div>

          <div style={styles.formGroup}>
            <label style={styles.formLabel}>Tenant ID</label>
            <input
              type="text"
              value={tenantId}
              onChange={(e) => setTenantId(e.target.value)}
              placeholder="Global (leave empty)"
              style={styles.formInput}
            />
          </div>
        </div>

        {/* Dynamic config fields based on rule_type */}
        <div style={styles.formRow}>
          {ruleType === "budget" && (
            <>
              <div style={styles.formGroup}>
                <label style={styles.formLabel}>Threshold Tokens</label>
                <input
                  type="number"
                  value={thresholdTokens}
                  onChange={(e) => setThresholdTokens(e.target.value)}
                  placeholder="e.g. 1000000"
                  style={styles.formInput}
                  min="1"
                  required
                />
              </div>
              <div style={styles.formGroup}>
                <label style={styles.formLabel}>Billing Period</label>
                <select
                  value={billingPeriod}
                  onChange={(e) => setBillingPeriod(e.target.value)}
                  style={styles.formSelect}
                >
                  <option value="monthly">Monthly</option>
                  <option value="weekly">Weekly</option>
                </select>
              </div>
            </>
          )}

          {ruleType === "error_rate" && (
            <>
              <div style={styles.formGroup}>
                <label style={styles.formLabel}>Threshold (%)</label>
                <input
                  type="number"
                  value={thresholdPercent}
                  onChange={(e) => setThresholdPercent(e.target.value)}
                  placeholder="e.g. 10"
                  style={styles.formInput}
                  min="0"
                  max="100"
                  step="0.1"
                  required
                />
              </div>
              <div style={styles.formGroup}>
                <label style={styles.formLabel}>Evaluation Window (min)</label>
                <input
                  type="number"
                  value={evaluationWindow}
                  onChange={(e) => setEvaluationWindow(e.target.value)}
                  placeholder="e.g. 15"
                  style={styles.formInput}
                  min="1"
                  required
                />
              </div>
            </>
          )}

          {ruleType === "circuit_breaker" && (
            <div style={styles.formGroup}>
              <label style={styles.formLabel}>Service Name</label>
              <input
                type="text"
                value={serviceName}
                onChange={(e) => setServiceName(e.target.value)}
                placeholder="e.g. delivery-api"
                style={styles.formInput}
                required
              />
            </div>
          )}
        </div>

        <div style={styles.formRow}>
          <div style={styles.formGroup}>
            <label style={styles.formLabel}>Notification Channel</label>
            <select
              value={notificationChannel}
              onChange={(e) => setNotificationChannel(e.target.value)}
              style={styles.formSelect}
            >
              <option value="webhook">Webhook</option>
              <option value="email">Email</option>
            </select>
          </div>

          <div style={styles.formGroup}>
            <label style={styles.formLabel}>Notification Target</label>
            <input
              type="text"
              value={notificationTarget}
              onChange={(e) => setNotificationTarget(e.target.value)}
              placeholder={notificationChannel === "webhook" ? "https://hooks.example.com/..." : "ops@example.com"}
              style={styles.formInput}
              required
            />
          </div>

          <div style={styles.formGroup}>
            <label style={styles.formLabel}>Enabled</label>
            <div style={styles.toggleContainer}>
              <button
                type="button"
                onClick={() => setEnabled(!enabled)}
                style={enabled ? styles.toggleOn : styles.toggleOff}
              >
                {enabled ? "ON" : "OFF"}
              </button>
            </div>
          </div>
        </div>

        <div style={styles.formActions}>
          <button type="button" onClick={onCancel} style={styles.cancelBtn}>
            Cancel
          </button>
          <button type="submit" disabled={saving} style={styles.primaryBtn}>
            {saving ? "Saving..." : rule ? "Update Rule" : "Create Rule"}
          </button>
        </div>
      </form>
    </div>
  );
}

// ─── AlertHistory ────────────────────────────────────────────────────────────

function AlertHistory({ entries, rules, loading, error, onAcknowledge }) {
  if (loading) {
    return <div style={styles.loadingText}>Loading alert history...</div>;
  }

  if (error) {
    return <div style={styles.errorBanner}>{error}</div>;
  }

  // Build a map of rule_id → rule name for display
  const ruleNameMap = {};
  rules.forEach((r) => {
    ruleNameMap[r.id] = r.name;
  });

  return (
    <div style={styles.section}>
      <div style={styles.sectionHeader}>
        <h3 style={styles.sectionTitle}>Alert History</h3>
      </div>

      {entries.length === 0 ? (
        <div style={styles.emptyState}>No alert history entries.</div>
      ) : (
        <div style={styles.tableContainer}>
          <div style={styles.tableWrapper}>
            <table style={styles.table}>
              <thead>
                <tr>
                  <th style={styles.th}>Alert Name</th>
                  <th style={styles.th}>Tenant</th>
                  <th style={styles.th}>Fired At</th>
                  <th style={styles.th}>Resolved At</th>
                  <th style={styles.th}>Acknowledged By</th>
                  <th style={styles.th}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((entry) => (
                  <tr key={entry.id} style={styles.tr}>
                    <td style={styles.td}>{ruleNameMap[entry.rule_id] || entry.rule_id}</td>
                    <td style={styles.td}>{entry.tenant_id || "Global"}</td>
                    <td style={styles.td}>{formatTimestamp(entry.fired_at)}</td>
                    <td style={styles.td}>
                      {entry.resolved_at ? formatTimestamp(entry.resolved_at) : (
                        <span style={styles.unresolvedText}>Unresolved</span>
                      )}
                    </td>
                    <td style={styles.td}>
                      {entry.acknowledged_by || (
                        <span style={styles.unackedText}>Not acknowledged</span>
                      )}
                    </td>
                    <td style={styles.td}>
                      {!entry.acknowledged_by && (
                        <button
                          style={styles.ackBtn}
                          onClick={() => onAcknowledge(entry.id)}
                        >
                          Acknowledge
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function formatTimestamp(ts) {
  if (!ts) return "";
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

// ─── Styles ──────────────────────────────────────────────────────────────────

const styles = {
  page: {
    display: "flex",
    flexDirection: "column",
    gap: 24,
  },
  tabBar: {
    display: "flex",
    gap: 4,
    borderBottom: "2px solid #e5e7eb",
    paddingBottom: 0,
  },
  tab: {
    padding: "10px 20px",
    fontSize: 14,
    fontWeight: 500,
    color: "#6b7280",
    backgroundColor: "transparent",
    border: "none",
    borderBottom: "2px solid transparent",
    cursor: "pointer",
    marginBottom: -2,
  },
  tabActive: {
    padding: "10px 20px",
    fontSize: 14,
    fontWeight: 600,
    color: "#2563eb",
    backgroundColor: "transparent",
    border: "none",
    borderBottom: "2px solid #2563eb",
    cursor: "pointer",
    marginBottom: -2,
  },
  section: {
    backgroundColor: "#fff",
    borderRadius: 8,
    border: "1px solid #e5e7eb",
    padding: 20,
  },
  sectionHeader: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 16,
  },
  sectionTitle: {
    fontSize: 16,
    fontWeight: 600,
    color: "#111827",
    margin: 0,
  },
  errorBanner: {
    padding: "12px 16px",
    backgroundColor: "#fef2f2",
    border: "1px solid #fecaca",
    borderRadius: 8,
    color: "#dc2626",
    fontSize: 14,
  },
  validationBanner: {
    padding: "12px 16px",
    backgroundColor: "#fffbeb",
    border: "1px solid #fde68a",
    borderRadius: 8,
    color: "#92400e",
    fontSize: 13,
    marginBottom: 16,
  },
  loadingText: {
    padding: "24px 0",
    textAlign: "center",
    color: "#6b7280",
    fontSize: 14,
  },
  emptyState: {
    padding: "32px 0",
    textAlign: "center",
    color: "#9ca3af",
    fontSize: 14,
  },

  // Table
  tableContainer: {
    overflowX: "auto",
  },
  tableWrapper: {
    minWidth: "100%",
  },
  table: {
    width: "100%",
    borderCollapse: "collapse",
    fontSize: 13,
  },
  th: {
    textAlign: "left",
    padding: "10px 12px",
    borderBottom: "2px solid #e5e7eb",
    fontSize: 12,
    fontWeight: 600,
    color: "#374151",
    textTransform: "uppercase",
    letterSpacing: "0.05em",
    whiteSpace: "nowrap",
  },
  tr: {
    borderBottom: "1px solid #f3f4f6",
  },
  td: {
    padding: "10px 12px",
    color: "#374151",
    whiteSpace: "nowrap",
  },

  // Badge
  badge: {
    display: "inline-block",
    padding: "2px 8px",
    borderRadius: 4,
    fontSize: 11,
    fontWeight: 600,
    textTransform: "uppercase",
    letterSpacing: "0.03em",
  },

  // Rule name with firing dot
  ruleName: {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
  },
  firingDot: {
    display: "inline-block",
    width: 8,
    height: 8,
    borderRadius: "50%",
    backgroundColor: "#dc2626",
  },
  ruleType: {
    fontSize: 12,
    color: "#6b7280",
    fontFamily: "monospace",
  },

  // Action buttons
  actionBtns: {
    display: "flex",
    gap: 8,
  },
  editBtn: {
    padding: "4px 10px",
    fontSize: 12,
    border: "1px solid #d1d5db",
    borderRadius: 4,
    backgroundColor: "#fff",
    color: "#374151",
    cursor: "pointer",
  },
  deleteBtn: {
    padding: "4px 10px",
    fontSize: 12,
    border: "1px solid #fecaca",
    borderRadius: 4,
    backgroundColor: "#fff",
    color: "#dc2626",
    cursor: "pointer",
  },
  ackBtn: {
    padding: "4px 10px",
    fontSize: 12,
    border: "1px solid #bbf7d0",
    borderRadius: 4,
    backgroundColor: "#f0fdf4",
    color: "#16a34a",
    cursor: "pointer",
    fontWeight: 500,
  },
  primaryBtn: {
    padding: "8px 16px",
    fontSize: 13,
    fontWeight: 600,
    border: "none",
    borderRadius: 6,
    backgroundColor: "#2563eb",
    color: "#fff",
    cursor: "pointer",
  },
  cancelBtn: {
    padding: "8px 16px",
    fontSize: 13,
    fontWeight: 500,
    border: "1px solid #d1d5db",
    borderRadius: 6,
    backgroundColor: "#fff",
    color: "#374151",
    cursor: "pointer",
  },

  // Form
  form: {
    display: "flex",
    flexDirection: "column",
    gap: 20,
  },
  formRow: {
    display: "flex",
    flexWrap: "wrap",
    gap: 16,
  },
  formGroup: {
    display: "flex",
    flexDirection: "column",
    gap: 4,
    minWidth: 180,
    flex: 1,
  },
  formLabel: {
    fontSize: 12,
    fontWeight: 600,
    color: "#374151",
    textTransform: "uppercase",
    letterSpacing: "0.05em",
  },
  formInput: {
    padding: "8px 10px",
    border: "1px solid #d1d5db",
    borderRadius: 6,
    fontSize: 13,
    color: "#111827",
    outline: "none",
  },
  formSelect: {
    padding: "8px 10px",
    border: "1px solid #d1d5db",
    borderRadius: 6,
    fontSize: 13,
    color: "#111827",
    backgroundColor: "#fff",
    outline: "none",
  },
  formActions: {
    display: "flex",
    gap: 12,
    justifyContent: "flex-end",
    paddingTop: 8,
  },

  // Toggle
  toggleContainer: {
    display: "flex",
    alignItems: "center",
    height: 34,
  },
  toggleOn: {
    padding: "6px 14px",
    fontSize: 12,
    fontWeight: 600,
    border: "none",
    borderRadius: 4,
    backgroundColor: "#16a34a",
    color: "#fff",
    cursor: "pointer",
  },
  toggleOff: {
    padding: "6px 14px",
    fontSize: 12,
    fontWeight: 600,
    border: "1px solid #d1d5db",
    borderRadius: 4,
    backgroundColor: "#f3f4f6",
    color: "#6b7280",
    cursor: "pointer",
  },

  // History specific
  unresolvedText: {
    color: "#dc2626",
    fontSize: 12,
    fontStyle: "italic",
  },
  unackedText: {
    color: "#9ca3af",
    fontSize: 12,
    fontStyle: "italic",
  },
};
