# Requirements Document

## Introduction

The Operational Frontend Redesign rebuilds the existing React + Vite operational frontend for the PDF ingestion and extraction service. The current implementation (PdfExtractor.jsx) provides basic upload, progress, and results display in a single monolithic component. This redesign decomposes the UI into four focused MVP screens — Job Submission, Job Queue / Status Monitor, Results Viewer, and Feedback & Corrections Log — with a professional visual language built for trust in regulated environments. The target users are reconciliation engineers and compliance reviewers who need data-dense, audit-grade interfaces with zero ambiguity about extraction confidence and provenance.

## Glossary

- **Frontend_App**: The React + Vite single-page application served from `pdf_ingestion/frontend/src/`, consuming the existing FastAPI backend API.
- **Job_Submission_Screen**: The screen responsible for file upload and extraction job creation via `POST /v1/extract`.
- **Job_Queue_Screen**: The screen displaying a filterable table of recent extraction jobs with status, schema type, and confidence.
- **Results_Viewer_Screen**: The screen displaying detailed extraction output for a single job including fields, tables, abstentions, confidence, and validation checks.
- **Feedback_Screen**: The screen displaying a table of correction and feedback entries submitted against extraction results.
- **ConfidenceBadge**: A colour-coded pill component displaying a numeric confidence value (0.00–1.00) with green (#2ECC71) for ≥0.90, amber (#F39C12) for 0.70–0.89, and red (#E74C3C) for <0.70.
- **ProvenanceTooltip**: A hover-triggered tooltip displaying page number, bounding box coordinates, source rail (native/ocr/vlm), and extraction rule for a field.
- **MonospaceField**: A styled inline display component using monospace typography for financial identifiers (IBANs, ISINs, BICs, document hashes).
- **JobStatusBadge**: A colour-coded badge component displaying job status (queued, processing, complete, failed, abstained).
- **SchemaTypeTag**: A labelled tag component indicating document schema type (bank_statement, custody_statement, swift_confirm, unknown).
- **AbstentionRow**: An amber-highlighted table row displaying a field or table that the pipeline could not extract, with reason code and detail.
- **CorrectionModal**: A modal dialog for submitting inline corrections against extracted field values.
- **Design_System**: The shared set of colour tokens, typography scales, spacing, and component primitives used across all screens.

## Requirements

### Requirement 1: Design System Foundation

**User Story:** As a reconciliation engineer, I want a consistent, professional visual language across all screens, so that I can trust the interface and scan data efficiently.

#### Acceptance Criteria

1. THE Design_System SHALL define a colour palette with primary dark navy (#0F1E3C), off-white (#F5F5F0), and slate mid-tones (#2E4057, #4A6278).
2. THE Design_System SHALL define status colours mapping green (#2ECC71) to agreement/success, amber (#F39C12) to soft_flag/warning, and red (#E74C3C) to hard_flag/error.
3. THE Design_System SHALL use a sans-serif typeface (Inter or IBM Plex Sans) for all UI text.
4. THE Design_System SHALL use a monospace typeface (IBM Plex Mono or JetBrains Mono) for financial identifiers including IBANs, ISINs, BICs, bounding box coordinates, and document hashes.
5. THE Design_System SHALL define a medium-high density layout where tables are the primary UX surface with compact row heights and minimal whitespace between data elements.
6. THE Design_System SHALL provide a shared navigation shell with a sidebar or top bar enabling navigation between the four MVP screens.

### Requirement 2: Job Submission Screen

**User Story:** As a reconciliation engineer, I want to upload PDF documents and submit extraction jobs, so that I can initiate the ingestion pipeline.

#### Acceptance Criteria

1. THE Job_Submission_Screen SHALL provide a drag-and-drop upload zone that accepts PDF files only.
2. THE Job_Submission_Screen SHALL provide a file browse button as an alternative to drag-and-drop.
3. WHEN a non-PDF file is dropped or selected, THE Job_Submission_Screen SHALL display an inline error message indicating only PDF files are accepted.
4. WHEN a file exceeding 50 MB is selected, THE Job_Submission_Screen SHALL display an inline error message indicating the maximum file size.
5. THE Job_Submission_Screen SHALL provide a schema type override toggle with options: auto-detect (default), bank_statement, custody_statement, swift_confirm.
6. WHEN the user submits a file, THE Job_Submission_Screen SHALL send a POST request to `/v1/extract` with the file and optional schema_type parameter.
7. WHEN the API returns a job_id, THE Job_Submission_Screen SHALL display the job_id and navigate the user to the Job Queue Screen with the new job highlighted.
8. WHILE a file is uploading, THE Job_Submission_Screen SHALL display a progress indicator and disable the submit button.
9. IF the upload request fails, THEN THE Job_Submission_Screen SHALL display the error code and message from the API response envelope.

### Requirement 3: Job Queue and Status Monitor Screen

**User Story:** As a reconciliation engineer, I want to view all recent extraction jobs in a filterable table, so that I can monitor pipeline throughput and identify failures.

#### Acceptance Criteria

1. THE Job_Queue_Screen SHALL display a table with columns: job_id, schema_type, status, pages, submitted_at, completed_at, and overall_confidence.
2. THE Job_Queue_Screen SHALL render the status column using the JobStatusBadge component with values: queued, processing, complete, failed, abstained.
3. THE Job_Queue_Screen SHALL render the schema_type column using the SchemaTypeTag component.
4. THE Job_Queue_Screen SHALL render the overall_confidence column using the ConfidenceBadge component.
5. THE Job_Queue_Screen SHALL provide a filter control for schema_type allowing selection of one or more schema types.
6. THE Job_Queue_Screen SHALL provide a filter control for status allowing selection of one or more statuses.
7. THE Job_Queue_Screen SHALL provide a date range filter for submitted_at.
8. WHEN filters are applied, THE Job_Queue_Screen SHALL display only jobs matching all active filter criteria (AND logic).
9. WHEN a user clicks a job row, THE Job_Queue_Screen SHALL navigate to the Results Viewer Screen for that job.
10. THE Job_Queue_Screen SHALL poll the backend at a configurable interval (default 5 seconds) to refresh job statuses for non-terminal jobs.
11. THE Job_Queue_Screen SHALL render the job_id column using the MonospaceField component.

### Requirement 4: Results Viewer — Header and Metadata

**User Story:** As a compliance reviewer, I want to see document metadata and extraction status at a glance, so that I can quickly assess extraction quality.

#### Acceptance Criteria

1. THE Results_Viewer_Screen SHALL display a header bar containing: doc_id, schema_type (as SchemaTypeTag), pipeline_version, and job status (as JobStatusBadge).
2. THE Results_Viewer_Screen SHALL display a confidence summary bar showing: mean_confidence (as ConfidenceBadge), fields_extracted count, fields_abstained count, and vlm_used_count.
3. THE Results_Viewer_Screen SHALL render the doc_id and pipeline_version using the MonospaceField component.
4. WHEN the job status is "processing", THE Results_Viewer_Screen SHALL display a progress indicator with current stage and percentage from the `/v1/jobs/{id}/progress` endpoint.

### Requirement 5: Results Viewer — Fields Panel

**User Story:** As a reconciliation engineer, I want to inspect each extracted field with its confidence and provenance, so that I can verify extraction accuracy.

#### Acceptance Criteria

1. THE Results_Viewer_Screen SHALL display a fields panel listing all extracted fields with columns: field_name, value, confidence (as ConfidenceBadge), vlm_used flag, and provenance indicator.
2. WHEN a user hovers over a provenance indicator, THE Results_Viewer_Screen SHALL display a ProvenanceTooltip showing page number, bounding box coordinates, source rail, and extraction rule.
3. THE Results_Viewer_Screen SHALL render field values that are financial identifiers (IBANs, ISINs, BICs) using the MonospaceField component.
4. WHEN a field has vlm_used set to true, THE Results_Viewer_Screen SHALL display a visual indicator (icon or label) distinguishing VLM-extracted fields from rule-based fields.
5. WHEN a user clicks a field value, THE Results_Viewer_Screen SHALL open the CorrectionModal pre-populated with the current field value.

### Requirement 6: Results Viewer — Tables Panel

**User Story:** As a reconciliation engineer, I want to view extracted transaction and position tables with per-row provenance, so that I can verify tabular data against source documents.

#### Acceptance Criteria

1. THE Results_Viewer_Screen SHALL display a tables panel listing all extracted tables with their table_id, type, and page_range.
2. THE Results_Viewer_Screen SHALL render each table with column headers and row data in a scrollable table component.
3. THE Results_Viewer_Screen SHALL display triangulation metadata for each table showing: score (as ConfidenceBadge), verdict (agreement/soft_flag/hard_flag as colour-coded text), and winning method.
4. WHEN a table verdict is "hard_flag", THE Results_Viewer_Screen SHALL highlight the table header with the red status colour.
5. WHEN a table verdict is "soft_flag", THE Results_Viewer_Screen SHALL highlight the table header with the amber status colour.

### Requirement 7: Results Viewer — Abstentions Panel

**User Story:** As a compliance reviewer, I want to see all fields and tables the pipeline could not extract, so that I can identify gaps requiring manual review.

#### Acceptance Criteria

1. THE Results_Viewer_Screen SHALL display an abstentions panel listing all abstention entries.
2. THE Results_Viewer_Screen SHALL render each abstention using the AbstentionRow component with amber highlighting.
3. THE AbstentionRow SHALL display: field name or table_id, reason code (from the error registry), detail text, and whether VLM was attempted.
4. WHEN there are zero abstentions, THE Results_Viewer_Screen SHALL display a success message indicating full extraction.

### Requirement 8: Results Viewer — Validation Checks Tab

**User Story:** As a compliance reviewer, I want to see validation check results grouped by validator, so that I can assess data integrity.

#### Acceptance Criteria

1. THE Results_Viewer_Screen SHALL provide a validation checks tab displaying all validation results.
2. WHEN all validation checks pass, THE Results_Viewer_Screen SHALL display a success indicator with a summary message.
3. WHEN validation failures exist, THE Results_Viewer_Screen SHALL group failures by validator_name and display each group with: validator label, failure count, and individual failure details (field_name, error_code, detail).
4. THE Results_Viewer_Screen SHALL display the total count of validation failures as a badge on the validation tab header.

### Requirement 9: Feedback and Corrections Log

**User Story:** As a reconciliation engineer, I want to view all feedback and corrections submitted against extraction results, so that I can track data quality improvements.

#### Acceptance Criteria

1. THE Feedback_Screen SHALL display a table of feedback entries with columns: job_id, field_name, original_value, corrected_value, submitted_by, submitted_at.
2. THE Feedback_Screen SHALL render the job_id column using the MonospaceField component.
3. THE Feedback_Screen SHALL provide a CSV export button that downloads all visible feedback entries as a CSV file.
4. WHEN the CSV export button is clicked, THE Feedback_Screen SHALL generate a CSV file with headers matching the table columns and download it to the user's device.
5. THE Feedback_Screen SHALL provide filter controls for job_id and date range.

### Requirement 10: Correction Submission

**User Story:** As a reconciliation engineer, I want to submit corrections for incorrectly extracted field values, so that feedback is captured for pipeline improvement.

#### Acceptance Criteria

1. WHEN the CorrectionModal is opened, THE CorrectionModal SHALL display the field name, current extracted value, and an editable input for the corrected value.
2. WHEN the user submits a correction, THE CorrectionModal SHALL send a POST request to `/v1/feedback/{job_id}` with the field_name, original_value, and corrected_value.
3. WHEN the correction is successfully submitted, THE CorrectionModal SHALL close and display a success notification.
4. IF the correction submission fails, THEN THE CorrectionModal SHALL display the error message from the API response and remain open.
5. THE CorrectionModal SHALL require the corrected_value to be non-empty before enabling the submit button.

### Requirement 11: Responsive Navigation and Layout

**User Story:** As a reconciliation engineer, I want consistent navigation between screens, so that I can move efficiently between job submission, monitoring, and review tasks.

#### Acceptance Criteria

1. THE Frontend_App SHALL provide a persistent navigation element (sidebar or top bar) visible on all screens with links to: Job Submission, Job Queue, Results Viewer, and Feedback Log.
2. THE Frontend_App SHALL highlight the currently active screen in the navigation element.
3. THE Frontend_App SHALL use client-side routing to navigate between screens without full page reloads.
4. WHEN the Results Viewer is accessed without a job_id parameter, THE Frontend_App SHALL redirect to the Job Queue Screen.
5. THE Frontend_App SHALL display the application title "PDF Ingestion" and a subtitle "Document extraction for reconciliation" in the navigation header area.

### Requirement 12: Reusable Component Library

**User Story:** As a developer, I want a set of reusable UI components with consistent styling, so that new screens can be built quickly with visual consistency.

#### Acceptance Criteria

1. THE ConfidenceBadge SHALL render a pill-shaped badge displaying a numeric value (0.00–1.00) with background colour: green (#2ECC71) for values ≥0.90, amber (#F39C12) for values 0.70–0.89, and red (#E74C3C) for values below 0.70.
2. THE ProvenanceTooltip SHALL render on hover and display: page number, bounding box as four comma-separated coordinates in monospace, source rail label, and extraction rule name.
3. THE MonospaceField SHALL render its content using the configured monospace typeface with a subtle background tint to distinguish it from surrounding text.
4. THE JobStatusBadge SHALL render a badge with text and background colour mapped to status: queued (slate), processing (blue), complete (green), failed (red), abstained (amber).
5. THE SchemaTypeTag SHALL render a tag with the schema type label formatted as: "Bank Statement", "Custody Statement", "SWIFT Confirm", or "Unknown".
6. THE AbstentionRow SHALL render with an amber (#F39C12) left border and light amber background tint.
7. THE CorrectionModal SHALL render as a centered overlay with a backdrop, containing the field context, an editable input, and submit/cancel buttons.
