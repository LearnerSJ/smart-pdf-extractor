# Requirements Document

## Introduction

The Admin Dashboard is a separate operational visibility and control layer for the PDF Ingestion Pipeline. It provides usage tracking, structured log viewing, role-based access control, and alerting capabilities to platform operators and tenant administrators. The dashboard surfaces token consumption metrics, cost attribution, correlated logs, and proactive alerts for budget thresholds and error rate anomalies.

## Glossary

- **Dashboard_API**: The FastAPI backend service exposing admin dashboard endpoints for usage, logs, RBAC, and alerts.
- **Dashboard_UI**: The React frontend application rendering admin dashboard views.
- **Usage_Tracker**: The component responsible for aggregating and querying token consumption and cost data from VLM usage records.
- **Log_Viewer**: The component responsible for querying, filtering, and presenting structured log entries with trace correlation.
- **RBAC_Engine**: The component responsible for enforcing role-based access control across dashboard resources.
- **Alert_Manager**: The component responsible for evaluating alert rules, detecting threshold breaches, and dispatching notifications.
- **Admin**: A user role with full read/write access to all tenants and all dashboard features including RBAC management.
- **Operator**: A user role with read/write access scoped to assigned tenants, including alert acknowledgment and log viewing.
- **Viewer**: A user role with read-only access scoped to assigned tenants.
- **Circuit_Breaker**: A fault-tolerance mechanism that opens when error rates exceed a threshold, preventing further requests to a failing downstream service.
- **Tenant**: An authenticated API consumer in the PDF ingestion system, identified by a unique id and API key.
- **Token_Budget**: The per-job maximum token allocation for VLM calls, tracked via input and output token counts.

## Requirements

### Requirement 1: Usage Data Aggregation

**User Story:** As an Admin, I want to view token consumption aggregated by tenant, job, and model, so that I can attribute costs and identify high-usage patterns.

#### Acceptance Criteria

1. WHEN a usage query is submitted with a tenant_id filter, THE Usage_Tracker SHALL return aggregated token counts (input_tokens, output_tokens, total_tokens) for that tenant within the specified time range.
2. WHEN a usage query is submitted with a job_id filter, THE Usage_Tracker SHALL return per-call token consumption records for that specific job.
3. WHEN a usage query is submitted with a model_id filter, THE Usage_Tracker SHALL return aggregated token counts grouped by the specified model.
4. THE Usage_Tracker SHALL compute cost attribution by multiplying token counts by the configured per-token rate for each model.
5. WHEN a usage query specifies a time range, THE Usage_Tracker SHALL return only records with timestamps within that range (inclusive of start, exclusive of end).
6. THE Usage_Tracker SHALL support grouping results by day, week, or month granularity.

### Requirement 2: Usage Dashboard Display

**User Story:** As an Operator, I want to see usage metrics visualized in charts and tables, so that I can quickly identify trends and anomalies.

#### Acceptance Criteria

1. WHEN the usage page is loaded, THE Dashboard_UI SHALL display a time-series chart of total token consumption for the selected tenant over the selected time range.
2. WHEN the usage page is loaded, THE Dashboard_UI SHALL display a breakdown table showing token consumption per job with columns: job_id, schema_type, model_id, input_tokens, output_tokens, total_tokens, estimated_cost, timestamp.
3. WHEN a user selects a different time granularity (day, week, month), THE Dashboard_UI SHALL re-render the chart with data aggregated at the selected granularity.
4. WHEN a user applies a model filter, THE Dashboard_UI SHALL update all displayed metrics to reflect only the selected model.

### Requirement 3: Structured Log Querying

**User Story:** As an Operator, I want to search and filter structured logs by trace_id, tenant, job, and error level, so that I can diagnose pipeline issues efficiently.

#### Acceptance Criteria

1. WHEN a log query is submitted with a trace_id, THE Log_Viewer SHALL return all log entries sharing that trace_id in chronological order.
2. WHEN a log query is submitted with a tenant_id filter, THE Log_Viewer SHALL return only log entries associated with that tenant.
3. WHEN a log query is submitted with a job_id filter, THE Log_Viewer SHALL return only log entries associated with that job.
4. WHEN a log query is submitted with a severity filter (debug, info, warning, error, critical), THE Log_Viewer SHALL return only log entries at or above the specified severity level.
5. WHEN a log query is submitted with a time range, THE Log_Viewer SHALL return only log entries with timestamps within that range.
6. THE Log_Viewer SHALL return log entries paginated with a configurable page size (default 50, maximum 200).

### Requirement 4: Log Viewer Display

**User Story:** As an Operator, I want to view correlated logs in a structured format with expandable detail, so that I can trace request flows across pipeline stages.

#### Acceptance Criteria

1. WHEN the log viewer page is loaded, THE Dashboard_UI SHALL display log entries in a table with columns: timestamp, severity, event_name, tenant_id, job_id, trace_id, and message.
2. WHEN a user clicks on a log entry, THE Dashboard_UI SHALL expand the entry to show all structured fields as key-value pairs.
3. WHEN a user clicks on a trace_id link, THE Dashboard_UI SHALL filter the view to show all log entries sharing that trace_id.
4. WHEN a user applies multiple filters simultaneously, THE Dashboard_UI SHALL combine filters with AND logic and update results.

### Requirement 5: Role-Based Access Control

**User Story:** As an Admin, I want to assign roles (Admin, Operator, Viewer) to users with tenant-scoped permissions, so that access to dashboard features is restricted appropriately.

#### Acceptance Criteria

1. THE RBAC_Engine SHALL enforce three roles: Admin, Operator, and Viewer.
2. THE RBAC_Engine SHALL grant Admin role full read and write access to all tenants and all dashboard resources.
3. THE RBAC_Engine SHALL grant Operator role read and write access only to tenants explicitly assigned to that Operator.
4. THE RBAC_Engine SHALL grant Viewer role read-only access only to tenants explicitly assigned to that Viewer.
5. WHEN a user without Admin role attempts to access a tenant not assigned to them, THE RBAC_Engine SHALL return a 403 Forbidden response.
6. WHEN a Viewer attempts a write operation (create, update, delete) on any resource, THE RBAC_Engine SHALL return a 403 Forbidden response.
7. WHEN an Admin creates or updates a user role assignment, THE RBAC_Engine SHALL persist the assignment and enforce it on subsequent requests.

### Requirement 6: Dashboard User Authentication

**User Story:** As a platform operator, I want to authenticate to the admin dashboard with credentials separate from tenant API keys, so that dashboard access is independently secured.

#### Acceptance Criteria

1. THE Dashboard_API SHALL authenticate users via email and password credentials.
2. WHEN valid credentials are submitted, THE Dashboard_API SHALL return a signed JWT token with the user's role and tenant assignments encoded in claims.
3. WHEN an invalid or expired JWT is presented, THE Dashboard_API SHALL return a 401 Unauthorized response.
4. THE Dashboard_API SHALL expire JWT tokens after a configurable duration (default 8 hours).
5. WHEN a user logs out, THE Dashboard_API SHALL invalidate the session token.

### Requirement 7: Budget Threshold Alerts

**User Story:** As an Admin, I want to configure budget threshold alerts per tenant, so that I am notified before a tenant exceeds their allocated token budget.

#### Acceptance Criteria

1. WHEN an Admin creates a budget alert rule, THE Alert_Manager SHALL persist the rule with fields: tenant_id, threshold_tokens, notification_channel, and enabled status.
2. WHEN cumulative token consumption for a tenant crosses the configured threshold within the current billing period, THE Alert_Manager SHALL emit a notification to the configured channel.
3. THE Alert_Manager SHALL support notification channels: webhook and email.
4. WHEN a budget alert rule is disabled, THE Alert_Manager SHALL stop evaluating that rule until re-enabled.
5. THE Alert_Manager SHALL not emit duplicate notifications for the same threshold breach within a single billing period.

### Requirement 8: Error Rate Spike Alerts

**User Story:** As an Operator, I want to be alerted when error rates spike for a tenant or globally, so that I can respond to pipeline degradation quickly.

#### Acceptance Criteria

1. WHEN an Admin creates an error rate alert rule, THE Alert_Manager SHALL persist the rule with fields: tenant_id (or global), error_rate_threshold_percent, evaluation_window_minutes, and notification_channel.
2. WHEN the error rate (failed jobs / total jobs) within the evaluation window exceeds the configured threshold, THE Alert_Manager SHALL emit a notification.
3. THE Alert_Manager SHALL evaluate error rate rules at a configurable interval (default every 60 seconds).
4. WHEN the error rate returns below the threshold, THE Alert_Manager SHALL emit a recovery notification.
5. THE Alert_Manager SHALL not emit repeated firing notifications for the same rule while the condition persists (fire once, then recovery).

### Requirement 9: Circuit Breaker State Alerts

**User Story:** As an Operator, I want to be notified when a circuit breaker opens or closes, so that I can take action on downstream service failures.

#### Acceptance Criteria

1. WHEN a circuit breaker transitions from closed to open state, THE Alert_Manager SHALL emit a notification indicating the affected service and tenant.
2. WHEN a circuit breaker transitions from open to closed state, THE Alert_Manager SHALL emit a recovery notification.
3. WHILE a circuit breaker is in open state, THE Dashboard_UI SHALL display a visual indicator on the affected tenant's status panel.
4. THE Alert_Manager SHALL log all circuit breaker state transitions with timestamp, tenant_id, service_name, and previous/new state.

### Requirement 10: Alert Management Interface

**User Story:** As an Admin, I want to view, create, edit, and acknowledge alerts through the dashboard, so that I can manage operational alerting without direct database access.

#### Acceptance Criteria

1. WHEN the alerts page is loaded, THE Dashboard_UI SHALL display all alert rules with their current status (enabled, disabled, firing, resolved).
2. WHEN an Admin creates a new alert rule via the UI, THE Dashboard_API SHALL validate the rule parameters and persist the rule.
3. WHEN an Operator acknowledges a firing alert, THE Dashboard_API SHALL record the acknowledgment with user_id and timestamp.
4. WHEN the alert history page is loaded, THE Dashboard_UI SHALL display past alert firings with columns: alert_name, tenant_id, fired_at, resolved_at, acknowledged_by.
5. IF an alert rule with invalid parameters is submitted, THEN THE Dashboard_API SHALL return a 422 response with a descriptive validation error.
