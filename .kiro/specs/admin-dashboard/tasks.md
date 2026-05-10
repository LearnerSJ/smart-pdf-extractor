# Implementation Plan: Admin Dashboard

## Overview

This plan implements the Admin Dashboard as an extension of the existing FastAPI backend and React frontend. Tasks are ordered by dependency: database schema first, then auth/RBAC, then services (usage, logs, alerts), then frontend, and finally integration wiring.

## Tasks

- [x] 1. Database schema and models for admin dashboard
  - [x] 1.1 Create Alembic migration for new admin dashboard tables
    - Add `dashboard_users` table with id, email, password_hash, role, is_active, created_at, updated_at
    - Add `role_assignments` table with id, user_id, tenant_id, created_at and unique constraint on (user_id, tenant_id)
    - Add `alert_rules` table with id, name, rule_type, tenant_id, config (JSONB), notification_channel, notification_target, enabled, state, last_evaluated_at, created_by, created_at, updated_at
    - Add `alert_history` table with id, rule_id, tenant_id, fired_at, resolved_at, notification_sent, acknowledged_by, acknowledged_at, context (JSONB)
    - Add `structured_logs` table with id, timestamp, severity, event_name, tenant_id, job_id, trace_id, message, fields (JSONB) and indexes on trace_id, (tenant_id, timestamp), (severity, timestamp), job_id
    - Add `token_revocations` table with id, jti, revoked_at, expires_at and unique constraint on jti
    - _Requirements: 5.1, 5.7, 6.5, 7.1, 8.1, 3.1_

  - [x] 1.2 Create SQLAlchemy ORM models for new tables
    - Add `DashboardUser`, `RoleAssignment`, `AlertRule`, `AlertHistory`, `StructuredLog`, `TokenRevocation` models in a new `db/admin_models.py` file
    - Define relationships between DashboardUser ↔ RoleAssignment, AlertRule ↔ AlertHistory, DashboardUser ↔ AlertHistory (acknowledged_by)
    - _Requirements: 5.1, 5.7, 7.1, 8.1_

  - [ ]* 1.3 Write unit tests for ORM model instantiation and relationships
    - Test model creation with valid data
    - Test relationship navigation
    - _Requirements: 5.1, 7.1_

- [x] 2. JWT authentication system
  - [x] 2.1 Implement JWT utility functions
    - Create `api/admin/auth_utils.py` with `create_access_token(user_id, email, role, tenant_ids)`, `decode_token(token)`, `hash_password(password)`, `verify_password(password, hash)`
    - Use HS256 algorithm, configurable expiration (default 8 hours)
    - Include `jti` (JWT ID) claim for revocation support
    - _Requirements: 6.2, 6.3, 6.4_

  - [ ]* 2.2 Write property test for JWT claims round-trip
    - **Property 9: JWT claims round-trip**
    - Generate random user profiles (email, role, tenant_ids), encode to JWT, decode, verify claims match
    - **Validates: Requirements 6.2**

  - [ ]* 2.3 Write property test for JWT rejection of invalid tokens
    - **Property 10: JWT rejection for invalid tokens**
    - Generate expired, malformed, and wrong-key tokens, verify all are rejected
    - **Validates: Requirements 6.3**

  - [x] 2.4 Implement auth routes (`api/routes/admin_auth.py`)
    - `POST /v1/admin/auth/login` — validate email/password, return JWT
    - `POST /v1/admin/auth/logout` — add jti to token_revocations table
    - `POST /v1/admin/auth/refresh` — issue new token if current token is valid
    - _Requirements: 6.1, 6.2, 6.5_

  - [x] 2.5 Implement user management routes
    - `POST /v1/admin/users` — create user (Admin only)
    - `GET /v1/admin/users` — list users (Admin only)
    - `PUT /v1/admin/users/{user_id}` — update user role and tenant assignments
    - `DELETE /v1/admin/users/{user_id}` — deactivate user
    - _Requirements: 5.7, 6.1_

  - [ ]* 2.6 Write unit tests for auth login/logout flow
    - Test valid login returns JWT
    - Test invalid credentials return 401
    - Test logout invalidates token
    - Test expired token returns 401
    - _Requirements: 6.1, 6.2, 6.3, 6.5_

- [x] 3. RBAC middleware
  - [x] 3.1 Implement RBAC middleware (`api/middleware/rbac.py`)
    - Create `Permission` enum (READ, WRITE, ADMIN)
    - Create `require_permission` FastAPI dependency that decodes JWT, checks role, and verifies tenant assignment
    - Admin: full access to all tenants; Operator: read/write on assigned tenants; Viewer: read-only on assigned tenants
    - Return 403 for insufficient permissions or unassigned tenant access
    - _Requirements: 5.2, 5.3, 5.4, 5.5, 5.6_

  - [ ]* 3.2 Write property test for RBAC access control
    - **Property 7: RBAC access control**
    - Generate random users with roles and tenant assignments, verify access decisions match the permission matrix
    - **Validates: Requirements 5.2, 5.3, 5.4, 5.5, 5.6**

  - [ ]* 3.3 Write property test for role assignment persistence round-trip
    - **Property 8: Role assignment persistence round-trip**
    - Generate random role assignments, persist them, verify access reflects the new assignment
    - **Validates: Requirements 5.7**

- [x] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Usage service
  - [x] 5.1 Implement usage query service (`api/routes/admin_usage.py`)
    - `GET /v1/admin/usage` — paginated list of VLM usage records with filters (tenant_id, job_id, model_id, time range)
    - `GET /v1/admin/usage/summary` — aggregated totals with cost computation
    - `GET /v1/admin/usage/timeseries` — bucketed time-series data with granularity (day, week, month)
    - Apply RBAC: scope results to assigned tenants for non-Admin users
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6_

  - [ ]* 5.2 Write property test for usage filter correctness
    - **Property 1: Usage filter correctness**
    - Generate random VLM usage records, apply random filter combinations, verify only matching records returned and no matching record excluded
    - **Validates: Requirements 1.1, 1.2, 1.3, 1.5**

  - [ ]* 5.3 Write property test for cost computation accuracy
    - **Property 2: Cost computation accuracy**
    - Generate random token counts and per-token rates, verify cost = input_tokens * input_rate / 1000 + output_tokens * output_rate / 1000
    - **Validates: Requirements 1.4**

  - [ ]* 5.4 Write property test for time granularity bucketing
    - **Property 3: Time granularity bucketing**
    - Generate random timestamps, verify each record assigned to exactly one bucket with correct calendar-aligned boundaries
    - **Validates: Requirements 1.6**

- [x] 6. Log sink and log query service
  - [x] 6.1 Implement log sink processor (`api/middleware/log_sink.py`)
    - Create structlog processor `db_log_sink` that writes log entries to `structured_logs` table
    - Integrate into existing structlog configuration as an additional processor
    - Preserve existing stdout JSON output (dual output)
    - _Requirements: 3.1, 3.2, 3.3_

  - [x] 6.2 Implement log query routes (`api/routes/admin_logs.py`)
    - `GET /v1/admin/logs` — paginated log query with filters (tenant_id, job_id, trace_id, severity, time range)
    - `GET /v1/admin/logs/trace/{trace_id}` — all logs for a trace in chronological order
    - Enforce severity level filtering (debug < info < warning < error < critical)
    - Pagination with configurable page size (default 50, max 200)
    - Apply RBAC: scope results to assigned tenants for non-Admin users
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [ ]* 6.3 Write property test for log filter and ordering
    - **Property 4: Log filter and ordering**
    - Generate random log entries, apply random filter combinations, verify correctness and chronological ordering
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**

  - [ ]* 6.4 Write property test for severity level filtering
    - **Property 5: Severity level filtering**
    - Generate random log entries with severities, apply severity filter, verify only entries at or above the level are returned
    - **Validates: Requirements 3.4**

  - [ ]* 6.5 Write property test for pagination invariants
    - **Property 6: Pagination invariants**
    - Generate random result sets, paginate with random page sizes (1–200), verify no duplicates/omissions and page size limits
    - **Validates: Requirements 3.6**

  - [ ]* 6.6 Write property test for combined filter AND logic
    - **Property 19: Combined filter AND logic**
    - Generate random log entries, apply N filters simultaneously, verify result equals intersection of individual filters
    - **Validates: Requirements 4.4**

- [x] 7. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Alert engine
  - [x] 8.1 Implement alert rule CRUD routes (`api/routes/admin_alerts.py`)
    - `GET /v1/admin/alerts/rules` — list all alert rules
    - `POST /v1/admin/alerts/rules` — create alert rule with validation
    - `PUT /v1/admin/alerts/rules/{id}` — update alert rule
    - `DELETE /v1/admin/alerts/rules/{id}` — delete alert rule
    - `GET /v1/admin/alerts/history` — list alert history
    - `POST /v1/admin/alerts/{alert_id}/ack` — acknowledge a firing alert
    - Return 422 for invalid rule parameters with descriptive errors
    - _Requirements: 7.1, 8.1, 10.2, 10.3, 10.5_

  - [ ]* 8.2 Write property test for alert rule persistence round-trip
    - **Property 11: Alert rule persistence round-trip**
    - Generate random valid alert rules, create and read back, verify all fields match
    - **Validates: Requirements 7.1, 8.1**

  - [ ]* 8.3 Write property test for alert rule validation
    - **Property 18: Alert rule validation**
    - Generate invalid alert rule submissions (missing fields, bad thresholds, unsupported channels), verify 422 response
    - **Validates: Requirements 10.5**

  - [x] 8.4 Implement alert evaluation engine (`pipeline/alerts/engine.py`)
    - Create `AlertEngine` class with `start()`, `stop()`, `evaluate_all_rules()` methods
    - Implement `evaluate_budget_rule()` — sum tokens for tenant in billing period, compare to threshold
    - Implement `evaluate_error_rate_rule()` — count failed/total jobs in evaluation window
    - Implement `handle_circuit_breaker_event()` — event-driven notification on state transitions
    - Run as async background task with configurable interval (default 60s)
    - Track rule state (idle → firing → resolved) to prevent duplicate notifications
    - _Requirements: 7.2, 7.4, 7.5, 8.2, 8.3, 8.4, 8.5, 9.1, 9.2, 9.4_

  - [x] 8.5 Implement notification dispatcher (`pipeline/alerts/notifier.py`)
    - Create `NotificationDispatcher` with `send_webhook(url, payload)` and `send_email(to, subject, body)` methods
    - Handle delivery failures gracefully (log error, mark as notification_failed)
    - _Requirements: 7.3, 8.2_

  - [ ]* 8.6 Write property test for budget threshold detection
    - **Property 12: Budget threshold detection**
    - Generate random usage sequences and thresholds, verify notification emitted if and only if cumulative tokens cross threshold
    - **Validates: Requirements 7.2**

  - [ ]* 8.7 Write property test for alert notification idempotence
    - **Property 13: Alert notification idempotence**
    - Generate repeated evaluations of a firing rule, verify at most one notification per breach period
    - **Validates: Requirements 7.5, 8.5**

  - [ ]* 8.8 Write property test for disabled rules produce no notifications
    - **Property 14: Disabled rules produce no notifications**
    - Generate disabled rules with threshold conditions met, verify no notifications emitted
    - **Validates: Requirements 7.4**

  - [ ]* 8.9 Write property test for error rate calculation and threshold detection
    - **Property 15: Error rate calculation and threshold detection**
    - Generate random job sequences (success/failure) and thresholds, verify notification logic
    - **Validates: Requirements 8.2**

  - [ ]* 8.10 Write property test for error rate recovery notification
    - **Property 16: Error rate recovery notification**
    - Generate sequences where error rate drops below threshold, verify exactly one recovery notification
    - **Validates: Requirements 8.4**

  - [ ]* 8.11 Write property test for circuit breaker state transition notifications
    - **Property 17: Circuit breaker state transition notifications**
    - Generate state transitions (closed→open, open→closed), verify correct notifications emitted
    - **Validates: Requirements 9.1, 9.2**

- [x] 9. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Backend integration and wiring
  - [x] 10.1 Register admin routes in FastAPI app
    - Mount all admin route modules under `/v1/admin/` prefix in `api/main.py`
    - Add RBAC middleware dependency to protected routes
    - Wire alert engine startup/shutdown to FastAPI lifespan events
    - _Requirements: 5.2, 6.1_

  - [x] 10.2 Add admin dashboard configuration to `api/config.py`
    - Add JWT settings (secret_key, algorithm, expiration_hours)
    - Add alert evaluation interval setting
    - Add token cost rate settings (per_1k_input, per_1k_output)
    - Add SMTP settings (host, port, from address)
    - _Requirements: 6.4, 7.3, 8.3_

  - [x] 10.3 Integrate log sink into existing structlog configuration
    - Add `db_log_sink` processor to the existing structlog processor chain
    - Ensure dual output: existing stdout JSON + new database writes
    - _Requirements: 3.1_

  - [ ]* 10.4 Write integration tests for full auth flow
    - Test login → access protected endpoint → logout → verify rejection
    - Test RBAC enforcement across different roles
    - _Requirements: 6.1, 6.2, 6.3, 6.5, 5.2, 5.5_

- [x] 11. Frontend - Login and layout
  - [x] 11.1 Create admin login page component
    - Build `LoginPage` with email/password form
    - Handle login API call, store JWT in memory
    - Display error messages for invalid credentials
    - _Requirements: 6.1_

  - [x] 11.2 Create authenticated dashboard layout
    - Build `DashboardLayout` with sidebar navigation
    - Create `AuthContext` for auth state management
    - Implement `useFetch` hook with automatic JWT injection
    - Add route protection (redirect to login if unauthenticated)
    - _Requirements: 6.2, 6.3_

- [x] 12. Frontend - Usage page
  - [x] 12.1 Implement usage page with chart and table
    - Build `UsagePage` with `UsageFilters`, `UsageChart`, and `UsageTable` components
    - Display time-series chart of token consumption
    - Display breakdown table with job_id, schema_type, model_id, input_tokens, output_tokens, total_tokens, estimated_cost, timestamp
    - Support time granularity selection (day, week, month)
    - Support model filter
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

- [x] 13. Frontend - Logs page
  - [x] 13.1 Implement log viewer page
    - Build `LogsPage` with `LogFilters`, `LogTable`, and `LogDetailPanel` components
    - Display log entries in table with columns: timestamp, severity, event_name, tenant_id, job_id, trace_id, message
    - Implement expandable detail view showing all structured fields as key-value pairs
    - Implement trace_id click to filter by trace
    - Support combined filters with AND logic
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

- [x] 14. Frontend - Alerts page
  - [x] 14.1 Implement alerts management page
    - Build `AlertsPage` with `AlertRuleList`, `AlertRuleForm`, and `AlertHistory` components
    - Display alert rules with status (enabled, disabled, firing, resolved)
    - Implement create/edit alert rule form with validation
    - Implement alert acknowledgment action
    - Display alert history with columns: alert_name, tenant_id, fired_at, resolved_at, acknowledged_by
    - Display circuit breaker visual indicator for affected tenants
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 9.3_

- [x] 15. Frontend - Users page (Admin only)
  - [x] 15.1 Implement user management page
    - Build `UsersPage` with `UserList` and `UserForm` components
    - Display user list with email, role, assigned tenants
    - Implement create/edit user form with role selection and tenant assignment
    - Restrict page visibility to Admin role only
    - _Requirements: 5.7_

- [x] 16. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Property-based tests use the `hypothesis` library with `@settings(max_examples=100)` minimum
- Checkpoints ensure incremental validation at logical boundaries
- The backend uses Python (FastAPI + SQLAlchemy async), frontend uses React with inline styles
- All admin routes are prefixed with `/v1/admin/` to separate from existing tenant API routes
