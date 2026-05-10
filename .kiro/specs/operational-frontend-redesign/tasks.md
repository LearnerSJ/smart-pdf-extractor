# Implementation Plan: Operational Frontend Redesign

## Overview

Rebuild the operational frontend from a monolithic `PdfExtractor.jsx` into a multi-screen React application with four focused views (Job Submission, Job Queue, Results Viewer, Feedback Log), a CSS custom property design system, reusable component library, and client-side routing via React Router v6. Implementation proceeds in layers: foundation → reusable components → screens → property-based tests.

## Tasks

- [x] 1. Foundation: dependencies, design tokens, routing, and AppShell
  - [x] 1.1 Install dependencies and update project configuration
    - Add `react-router-dom` (v6) to dependencies in `package.json`
    - Add `fast-check` and `vitest`, `@testing-library/react`, `@testing-library/jest-dom`, `jsdom` to devDependencies
    - Add a `"test": "vitest --run"` script to `package.json`
    - Create `vitest.config.js` with jsdom environment
    - _Requirements: 11.3, 12.1_

  - [x] 1.2 Create design tokens and global styles
    - Create `src/tokens.css` with CSS custom properties: colour palette (primary dark navy #0F1E3C, off-white #F5F5F0, slate mid-tones #2E4057, #4A6278), status colours (green #2ECC71, amber #F39C12, red #E74C3C), info blue, typography scale (sans-serif: Inter/IBM Plex Sans, monospace: IBM Plex Mono/JetBrains Mono), spacing scale, and compact table row heights
    - Create `src/global.css` with CSS reset, base typography rules, and import of tokens.css
    - Import `global.css` in `src/main.jsx`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

  - [x] 1.3 Create the useApi hook
    - Create `src/hooks/useApi.js` implementing `useApi(path, options?)` returning `{ data, loading, error, refetch }`
    - Handle base URL prepending (empty for Vite proxy), Authorization header (Bearer demo-key), JSON parsing with envelope unwrapping (.data if present), and error extraction from response body
    - _Requirements: 2.6, 3.10, 4.4, 9.1_

  - [x] 1.4 Create AppShell layout component
    - Create `src/components/AppShell.jsx` with left sidebar (200px), header area ("PDF Ingestion" title, "Document extraction for reconciliation" subtitle), and main content area
    - Implement navigation links for all six routes (Submit Job, Job Queue, Results, Feedback, Delivery, Redaction)
    - Use `useLocation()` to highlight the active nav link by matching route prefix
    - Style with CSS module or inline styles using design tokens
    - _Requirements: 1.6, 11.1, 11.2, 11.5_

  - [x] 1.5 Set up routing in App.jsx
    - Rewrite `src/App.jsx` to use `BrowserRouter`, `Routes`, `Route` from react-router-dom
    - Wrap routes in `<AppShell>` component
    - Define routes: `/submit`, `/queue`, `/results/:id`, `/feedback`, `/settings/delivery`, `/settings/redaction`, and redirect `/` to `/submit`
    - Redirect `/results` (no id) to `/queue`
    - Mount existing `DeliverySettings` and `RedactionSettings` components at their settings routes
    - _Requirements: 11.3, 11.4_

- [x] 2. Reusable component library
  - [x] 2.1 Implement ConfidenceBadge component
    - Create `src/components/ConfidenceBadge.jsx`
    - Render pill-shaped badge with value formatted to 2 decimal places
    - Apply colour logic: green (≥0.90), amber (0.70–0.89), red (<0.70) using CSS custom properties
    - _Requirements: 12.1_

  - [x] 2.2 Implement JobStatusBadge component
    - Create `src/components/JobStatusBadge.jsx`
    - Render badge with text and background colour mapped to status: queued (slate), processing (blue), complete (green), failed (red), abstained (amber)
    - _Requirements: 12.4_

  - [x] 2.3 Implement SchemaTypeTag component
    - Create `src/components/SchemaTypeTag.jsx`
    - Render tag with formatted label: bank_statement → "Bank Statement", custody_statement → "Custody Statement", swift_confirm → "SWIFT Confirm", unknown → "Unknown"
    - _Requirements: 12.5_

  - [x] 2.4 Implement MonospaceField component
    - Create `src/components/MonospaceField.jsx`
    - Render `<span>` with monospace font and subtle background tint (#f1f5f9)
    - _Requirements: 12.3_

  - [x] 2.5 Implement ProvenanceTooltip component
    - Create `src/components/ProvenanceTooltip.jsx`
    - Render hover-triggered tooltip (CSS :hover + absolute positioning) showing page number, bbox in monospace (four comma-separated coordinates), source rail label, and extraction rule name
    - _Requirements: 12.2_

  - [x] 2.6 Implement AbstentionRow component
    - Create `src/components/AbstentionRow.jsx`
    - Render table row with amber left border and light amber background tint
    - Display: field name or table_id, reason code, detail text, and VLM attempted indicator
    - _Requirements: 12.6, 7.3_

  - [x] 2.7 Implement CorrectionModal component
    - Create `src/components/CorrectionModal.jsx`
    - Render centered overlay with backdrop, field name display, current value display, editable input for corrected value, and submit/cancel buttons
    - Disable submit when trimmed corrected value is empty
    - POST to `/v1/feedback/{jobId}` with field_name, original_value, corrected_value
    - On success: call onSuccess callback and close; on error: display error message and stay open
    - _Requirements: 12.7, 10.1, 10.2, 10.3, 10.4, 10.5_

  - [x] 2.8 Implement DataTable component
    - Create `src/components/DataTable.jsx`
    - Accept `columns` (array of {key, label, align, render}) and `rows` props
    - Render compact table with sticky header, horizontal scroll, hover highlight on rows
    - Support optional `onRowClick` handler
    - _Requirements: 1.5, 3.1_

- [ ] 3. Checkpoint - Ensure foundation and components work
  - Ensure all tests pass, ask the user if questions arise.

- [-] 4. Job Submission Screen
  - [x] 4.1 Implement JobSubmissionScreen
    - Create `src/screens/JobSubmissionScreen.jsx`
    - Implement drag-and-drop upload zone accepting PDF files only
    - Implement file browse button as alternative to drag-and-drop
    - Validate file type (reject non-PDF with inline error "Only PDF files are accepted")
    - Validate file size (reject >50 MB with inline error "File exceeds maximum size of 50 MB")
    - Implement schema type override toggle: auto-detect (default), bank_statement, custody_statement, swift_confirm
    - On submit: POST to `/v1/extract` with file and optional schema_type
    - Display progress indicator during upload, disable submit button
    - On success: display job_id and navigate to `/queue?highlight={job_id}`
    - On error: display error code and message from API response
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9_

  - [ ]* 4.2 Write unit tests for JobSubmissionScreen
    - Test file type validation rejects non-PDF
    - Test file size validation rejects >50 MB
    - Test submit button disabled during upload
    - Test successful submission navigates to queue
    - _Requirements: 2.3, 2.4, 2.8, 2.7_

- [-] 5. Job Queue Screen
  - [x] 5.1 Implement JobQueueScreen
    - Create `src/screens/JobQueueScreen.jsx`
    - Fetch job list from API and render in DataTable with columns: job_id (MonospaceField), schema_type (SchemaTypeTag), status (JobStatusBadge), pages, submitted_at, completed_at, overall_confidence (ConfidenceBadge)
    - Implement filter controls: schema_type multi-select, status multi-select, date range for submitted_at
    - Apply AND logic for all active filters
    - Implement row click navigation to `/results/{job_id}`
    - Implement polling at 5-second interval for non-terminal jobs with resilience (continue on transient errors, warn after 3 consecutive failures)
    - Support `?highlight={job_id}` query param to highlight newly submitted job
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11_

  - [ ]* 5.2 Write property test for AND-filter correctness
    - **Property 1: AND-filter correctness**
    - Extract `filterJobs(jobs, filters)` as a pure function
    - Use fast-check to generate random arrays of job objects and random filter combinations
    - Assert: filtered result contains only jobs satisfying ALL active criteria AND contains every job that satisfies all criteria
    - Minimum 100 iterations
    - **Validates: Requirements 3.8**

  - [ ]* 5.3 Write unit tests for JobQueueScreen
    - Test table renders all columns with correct components
    - Test filter application reduces visible rows
    - Test row click navigates to results
    - Test polling stops for terminal statuses
    - _Requirements: 3.1, 3.8, 3.9, 3.10_

- [-] 6. Results Viewer Screen
  - [x] 6.1 Implement ResultsViewerScreen - header and metadata
    - Create `src/screens/ResultsViewerScreen.jsx`
    - Fetch result data from `/v1/results/{id}` and progress from `/v1/jobs/{id}/progress` (if processing)
    - Render header bar: doc_id (MonospaceField), schema_type (SchemaTypeTag), pipeline_version (MonospaceField), status (JobStatusBadge)
    - Render confidence summary bar: mean_confidence (ConfidenceBadge), fields_extracted count, fields_abstained count, vlm_used_count
    - Show progress indicator with stage and percentage when status is "processing"
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

  - [ ] 6.2 Implement Results Viewer - fields panel
    - Render fields panel listing all extracted fields with columns: field_name, value, confidence (ConfidenceBadge), vlm_used flag, provenance indicator
    - Render financial identifier fields (iban, isin, bic, swift_code, account_number, doc_hash) using MonospaceField
    - Show ProvenanceTooltip on hover over provenance indicator
    - Show VLM indicator icon/label when vlm_used is true
    - Open CorrectionModal on field value click, pre-populated with current value
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [ ] 6.3 Implement Results Viewer - tables panel
    - Render tables panel listing all extracted tables with table_id, type, page_range
    - Render each table with column headers and row data in scrollable DataTable
    - Display triangulation metadata: score (ConfidenceBadge), verdict (colour-coded text), winning method
    - Highlight table header red for "hard_flag" verdict, amber for "soft_flag"
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [ ] 6.4 Implement Results Viewer - abstentions panel
    - Render abstentions panel listing all abstention entries using AbstentionRow component
    - Display success message "Full extraction — no abstentions" when array is empty
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

  - [ ] 6.5 Implement Results Viewer - validation checks tab
    - Render validation checks tab with pass/fail indicator
    - When all pass: display success indicator with summary message
    - When failures exist: group by validator_name, display each group with validator label, failure count, and individual failure details (field_name, error_code, detail)
    - Display total failure count as badge on tab header
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

  - [ ]* 6.6 Write property test for validation failure grouping integrity
    - **Property 4: Validation failure grouping integrity**
    - Extract `groupByValidator(failures)` as a pure function
    - Use fast-check to generate random arrays of failure objects with random validator_names
    - Assert: (a) every failure in a group has same validator_name, (b) union of all groups equals original list, (c) no failure in more than one group
    - Minimum 100 iterations
    - **Validates: Requirements 8.3**

  - [ ]* 6.7 Write property test for financial identifier monospace rendering
    - **Property 6: Financial identifier monospace rendering**
    - Extract `isFinancialIdentifier(fieldName)` as a pure function
    - Use fast-check to generate random field names from known identifier set + random non-identifier names
    - Assert: function returns true for known identifiers and false for non-identifiers
    - Minimum 100 iterations
    - **Validates: Requirements 5.3**

- [ ] 7. Checkpoint - Ensure screens render correctly
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 8. Feedback Screen
  - [ ] 8.1 Implement FeedbackScreen
    - Create `src/screens/FeedbackScreen.jsx`
    - Fetch feedback entries from API and render in DataTable with columns: job_id (MonospaceField), field_name, original_value, corrected_value, submitted_by, submitted_at
    - Implement filter controls for job_id and date range
    - Implement CSV export button that generates and downloads CSV file with headers matching table columns
    - Handle special characters in CSV (commas, double quotes, newlines, Unicode) with proper escaping
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_

  - [ ]* 8.2 Write property test for CSV export round-trip
    - **Property 3: CSV export round-trip**
    - Extract `exportCSV(entries)` and `parseCSV(csvString)` as pure functions
    - Use fast-check to generate random feedback entries with special characters (commas, double quotes, newlines, Unicode)
    - Assert: `parseCSV(exportCSV(entries))` produces values equivalent to original entries
    - Minimum 100 iterations
    - **Validates: Requirements 9.4**

  - [ ]* 8.3 Write unit tests for FeedbackScreen
    - Test table renders all columns
    - Test CSV export downloads file
    - Test filters reduce visible rows
    - _Requirements: 9.1, 9.4, 9.5_

- [ ] 9. Property-based tests for reusable components
  - [ ]* 9.1 Write property test for ConfidenceBadge colour threshold mapping
    - **Property 2: ConfidenceBadge colour threshold mapping**
    - Extract `getConfidenceColour(value)` as a pure function
    - Use fast-check to generate random floats in [0, 1] with bias toward boundaries (0.70, 0.90)
    - Assert: green for ≥0.90, amber for 0.70–0.89, red for <0.70
    - Minimum 100 iterations
    - **Validates: Requirements 12.1**

  - [ ]* 9.2 Write property test for CorrectionModal submit button enablement
    - **Property 5: Correction submit button enablement**
    - Extract `isSubmitEnabled(value)` as a pure function
    - Use fast-check to generate random strings including whitespace-only, empty, and mixed content
    - Assert: submit disabled if and only if trimmed value is empty
    - Minimum 100 iterations
    - **Validates: Requirements 10.5**

- [ ] 10. Integration wiring and final polish
  - [ ] 10.1 Wire all screens into App.jsx and verify navigation flows
    - Ensure all route imports are correct and screens render within AppShell
    - Verify navigation between screens works (submit → queue → results → feedback)
    - Verify redirect from `/` to `/submit` and from `/results` (no id) to `/queue`
    - Verify existing DeliverySettings and RedactionSettings still mount correctly
    - _Requirements: 11.1, 11.2, 11.3, 11.4_

  - [ ]* 10.2 Write integration tests for navigation flows
    - Test navigation from submit to queue after job creation
    - Test navigation from queue row click to results
    - Test redirect from `/results` to `/queue`
    - Test active nav link highlighting
    - _Requirements: 11.1, 11.2, 11.3, 11.4_

- [ ] 11. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Pure utility functions are extracted from components to enable property-based testing
- The existing admin/ directory and DeliverySettings/RedactionSettings components remain untouched
- All API calls go through the Vite proxy (no base URL needed) as configured in vite.config.js
