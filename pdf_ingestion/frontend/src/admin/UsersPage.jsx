import React, { useState, useCallback } from "react";
import { useFetch } from "./useFetch.js";
import { useAuth } from "./AuthContext.jsx";

/**
 * UsersPage — user management page (Admin only).
 *
 * Sub-components:
 *   - UserList: displays all users with email, role, assigned tenants, is_active status
 *   - UserForm: create/edit user form with role selection and tenant assignment
 *
 * Features:
 *   - Fetches users from GET /v1/admin/users
 *   - Create user via POST /v1/admin/users
 *   - Edit user via PUT /v1/admin/users/{user_id}
 *   - Deactivate user via DELETE /v1/admin/users/{user_id}
 *   - Restrict page visibility to Admin role only
 *   - Role badges with colors (admin=purple, operator=blue, viewer=gray)
 *   - Active/inactive status indicator
 *   - Loading and error states
 */
export default function UsersPage({ apiBaseUrl = "" }) {
  const { user, token, logout } = useAuth();

  // Access control: Admin only
  if (!user || user.role !== "admin") {
    return (
      <div style={styles.accessDenied}>
        <h2 style={styles.accessDeniedTitle}>Access Denied</h2>
        <p style={styles.accessDeniedText}>
          You do not have permission to view this page. Only administrators can manage users.
        </p>
      </div>
    );
  }

  return <UsersPageContent apiBaseUrl={apiBaseUrl} token={token} logout={logout} />;
}

function UsersPageContent({ apiBaseUrl, token, logout }) {
  const [editingUser, setEditingUser] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const [mutating, setMutating] = useState(false);
  const [mutateError, setMutateError] = useState(null);

  // Fetch users
  const usersUrl = `${apiBaseUrl}/v1/admin/users`;
  const { data: usersData, loading, error, refetch } = useFetch(usersUrl);

  const users = usersData?.data?.users || [];

  // Manual mutation helper
  const doMutate = useCallback(async (url, method, body) => {
    setMutating(true);
    setMutateError(null);
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
    setEditingUser(null);
    setShowForm(true);
    setMutateError(null);
  };

  const handleEdit = (u) => {
    setEditingUser(u);
    setShowForm(true);
    setMutateError(null);
  };

  const handleCancelForm = () => {
    setShowForm(false);
    setEditingUser(null);
    setMutateError(null);
  };

  const handleSaveUser = async (userData) => {
    const url = editingUser
      ? `${apiBaseUrl}/v1/admin/users/${editingUser.id}`
      : `${apiBaseUrl}/v1/admin/users`;
    const method = editingUser ? "PUT" : "POST";

    const result = await doMutate(url, method, userData);
    if (result) {
      setShowForm(false);
      setEditingUser(null);
      refetch();
    }
  };

  const handleDeactivate = async (userId) => {
    if (!window.confirm("Are you sure you want to deactivate this user?")) return;
    const result = await doMutate(`${apiBaseUrl}/v1/admin/users/${userId}`, "DELETE");
    if (result) {
      refetch();
    }
  };

  return (
    <div style={styles.page}>
      {mutateError && <div style={styles.errorBanner}>{mutateError}</div>}

      {showForm ? (
        <UserForm
          user={editingUser}
          onSave={handleSaveUser}
          onCancel={handleCancelForm}
          saving={mutating}
        />
      ) : (
        <UserList
          users={users}
          loading={loading}
          error={error}
          onCreateNew={handleCreateNew}
          onEdit={handleEdit}
          onDeactivate={handleDeactivate}
        />
      )}
    </div>
  );
}

// ─── UserList ────────────────────────────────────────────────────────────────

function UserList({ users, loading, error, onCreateNew, onEdit, onDeactivate }) {
  if (loading) {
    return <div style={styles.loadingText}>Loading users...</div>;
  }

  if (error) {
    return <div style={styles.errorBanner}>{error}</div>;
  }

  return (
    <div style={styles.section}>
      <div style={styles.sectionHeader}>
        <h3 style={styles.sectionTitle}>Users</h3>
        <button style={styles.primaryBtn} onClick={onCreateNew}>
          + New User
        </button>
      </div>

      {users.length === 0 ? (
        <div style={styles.emptyState}>No users found.</div>
      ) : (
        <div style={styles.tableContainer}>
          <div style={styles.tableWrapper}>
            <table style={styles.table}>
              <thead>
                <tr>
                  <th style={styles.th}>Email</th>
                  <th style={styles.th}>Role</th>
                  <th style={styles.th}>Assigned Tenants</th>
                  <th style={styles.th}>Status</th>
                  <th style={styles.th}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id} style={styles.tr}>
                    <td style={styles.td}>{u.email}</td>
                    <td style={styles.td}>
                      <RoleBadge role={u.role} />
                    </td>
                    <td style={styles.td}>
                      {u.tenant_ids && u.tenant_ids.length > 0
                        ? u.tenant_ids.join(", ")
                        : <span style={styles.noneText}>None</span>}
                    </td>
                    <td style={styles.td}>
                      <StatusIndicator isActive={u.is_active} />
                    </td>
                    <td style={styles.td}>
                      <div style={styles.actionBtns}>
                        <button style={styles.editBtn} onClick={() => onEdit(u)}>
                          Edit
                        </button>
                        {u.is_active && (
                          <button style={styles.deleteBtn} onClick={() => onDeactivate(u.id)}>
                            Deactivate
                          </button>
                        )}
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

// ─── RoleBadge ───────────────────────────────────────────────────────────────

function RoleBadge({ role }) {
  let badgeStyle = {};

  switch (role) {
    case "admin":
      badgeStyle = { backgroundColor: "#f5f3ff", color: "#7c3aed" };
      break;
    case "operator":
      badgeStyle = { backgroundColor: "#eff6ff", color: "#2563eb" };
      break;
    case "viewer":
    default:
      badgeStyle = { backgroundColor: "#f3f4f6", color: "#6b7280" };
      break;
  }

  return (
    <span style={{ ...styles.badge, ...badgeStyle }}>
      {role}
    </span>
  );
}

// ─── StatusIndicator ─────────────────────────────────────────────────────────

function StatusIndicator({ isActive }) {
  return (
    <span style={styles.statusContainer}>
      <span style={isActive ? styles.statusDotActive : styles.statusDotInactive} />
      <span style={isActive ? styles.statusTextActive : styles.statusTextInactive}>
        {isActive ? "Active" : "Inactive"}
      </span>
    </span>
  );
}

// ─── UserForm ────────────────────────────────────────────────────────────────

function UserForm({ user, onSave, onCancel, saving }) {
  const isEditing = !!user;
  const [email, setEmail] = useState(user?.email || "");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState(user?.role || "viewer");
  const [tenantIdsInput, setTenantIdsInput] = useState(
    user?.tenant_ids ? user.tenant_ids.join(", ") : ""
  );

  const handleSubmit = (e) => {
    e.preventDefault();

    const tenantIds = tenantIdsInput
      .split(",")
      .map((t) => t.trim())
      .filter((t) => t.length > 0);

    if (isEditing) {
      // Update: send role and tenant_ids
      onSave({ role, tenant_ids: tenantIds });
    } else {
      // Create: send email, password, role, tenant_ids
      onSave({ email, password, role, tenant_ids: tenantIds });
    }
  };

  return (
    <div style={styles.section}>
      <div style={styles.sectionHeader}>
        <h3 style={styles.sectionTitle}>{isEditing ? "Edit User" : "Create User"}</h3>
      </div>

      <form onSubmit={handleSubmit} style={styles.form}>
        <div style={styles.formRow}>
          <div style={styles.formGroup}>
            <label style={styles.formLabel}>Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="user@example.com"
              style={styles.formInput}
              required
              disabled={isEditing}
            />
          </div>

          {!isEditing && (
            <div style={styles.formGroup}>
              <label style={styles.formLabel}>Password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Enter password"
                style={styles.formInput}
                required
              />
            </div>
          )}
        </div>

        <div style={styles.formRow}>
          <div style={styles.formGroup}>
            <label style={styles.formLabel}>Role</label>
            <select
              value={role}
              onChange={(e) => setRole(e.target.value)}
              style={styles.formSelect}
            >
              <option value="admin">Admin</option>
              <option value="operator">Operator</option>
              <option value="viewer">Viewer</option>
            </select>
          </div>

          <div style={styles.formGroup}>
            <label style={styles.formLabel}>Tenant IDs (comma-separated)</label>
            <input
              type="text"
              value={tenantIdsInput}
              onChange={(e) => setTenantIdsInput(e.target.value)}
              placeholder="tenant-1, tenant-2"
              style={styles.formInput}
            />
          </div>
        </div>

        <div style={styles.formActions}>
          <button type="button" onClick={onCancel} style={styles.cancelBtn}>
            Cancel
          </button>
          <button type="submit" disabled={saving} style={styles.primaryBtn}>
            {saving ? "Saving..." : isEditing ? "Update User" : "Create User"}
          </button>
        </div>
      </form>
    </div>
  );
}

// ─── Styles ──────────────────────────────────────────────────────────────────

const styles = {
  page: {
    display: "flex",
    flexDirection: "column",
    gap: 24,
  },
  accessDenied: {
    textAlign: "center",
    padding: "60px 24px",
  },
  accessDeniedTitle: {
    fontSize: 24,
    fontWeight: 700,
    color: "#dc2626",
    margin: "0 0 12px 0",
  },
  accessDeniedText: {
    fontSize: 15,
    color: "#6b7280",
    margin: 0,
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

  // Status indicator
  statusContainer: {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
  },
  statusDotActive: {
    display: "inline-block",
    width: 8,
    height: 8,
    borderRadius: "50%",
    backgroundColor: "#16a34a",
  },
  statusDotInactive: {
    display: "inline-block",
    width: 8,
    height: 8,
    borderRadius: "50%",
    backgroundColor: "#d1d5db",
  },
  statusTextActive: {
    fontSize: 12,
    color: "#16a34a",
    fontWeight: 500,
  },
  statusTextInactive: {
    fontSize: 12,
    color: "#9ca3af",
    fontWeight: 500,
  },
  noneText: {
    color: "#9ca3af",
    fontSize: 12,
    fontStyle: "italic",
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
};
