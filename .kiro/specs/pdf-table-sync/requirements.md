# Requirements Document

## Introduction

This feature adds bidirectional synchronisation between the PDF viewer (left panel) and the extracted data tables panel (right panel) in the PDF ingestion frontend. Currently, `PdfViewer` manages its own `currentPage` state internally and `ResultsTablesPanel` is unaware of which page the user is viewing. The feature lifts page state to the shared parent (`ResultsViewerScreen`), making `PdfViewer` a controlled component, and wires both panels together so that navigating in one panel automatically updates the other. A "Show all tables" toggle lets users opt out of page-filtered views.

## Glossary

- **ResultsViewerScreen**: The parent screen component that renders `PdfViewer` and `ResultsTablesPanel` side by side when `showPdfViewer` is true.
- **PdfViewer**: The controlled PDF rendering component that accepts `currentPage` and `onPageChange` props instead of managing page state internally.
- **ResultsTablesPanel**: The panel that displays extracted tables; receives `currentPage`, `onTableClick`, and `showAllTables` props for synchronisation.
- **Table**: An extracted data object with fields `table_id`, `type`, `page_range: number[]`, `headers`, `rows`, and `triangulation`.
- **page_range**: An array of page numbers (1-indexed) indicating which PDF pages a table spans.
- **Active Page**: The currently displayed PDF page number, owned by `ResultsViewerScreen`.
- **Page-Filtered View**: The default mode where `ResultsTablesPanel` shows only tables whose `page_range` includes the Active Page.
- **Show All Tables Toggle**: A UI control that switches `ResultsTablesPanel` from Page-Filtered View to showing all tables regardless of Active Page.
- **Sync_Controller**: The logical synchronisation layer within `ResultsViewerScreen` that connects page changes from `PdfViewer` to `ResultsTablesPanel` and vice versa.

---

## Requirements

### Requirement 1: Lift Page State to Parent

**User Story:** As a developer, I want `PdfViewer` to be a controlled component, so that `ResultsViewerScreen` can share the current page with other panels.

#### Acceptance Criteria

1. THE `ResultsViewerScreen` SHALL own a `currentPage` state variable initialised to `1`.
2. WHEN `ResultsViewerScreen` renders `PdfViewer`, THE `ResultsViewerScreen` SHALL pass `currentPage` and an `onPageChange` callback as props to `PdfViewer`.
3. THE `PdfViewer` SHALL accept `currentPage` and `onPageChange` as props and SHALL use the prop value to determine which page to render.
4. WHEN the user triggers a page navigation action inside `PdfViewer` (previous, next, or direct jump), THE `PdfViewer` SHALL call `onPageChange` with the new page number instead of updating internal state.
5. IF `PdfViewer` receives a `currentPage` prop value less than `1`, THEN THE `PdfViewer` SHALL clamp the rendered page to `1` without affecting prop values that are already within the valid range.
6. IF `PdfViewer` receives a `currentPage` prop value greater than `totalPages`, THEN THE `PdfViewer` SHALL clamp the rendered page to `totalPages` so the user remains near their intended location.
7. THE `PdfViewer` SHALL preserve all existing functionality: zoom controls, highlight overlays, provenance tooltips, and PDF loading behaviour.

---

### Requirement 2: PDF Viewer → Tables Panel Synchronisation

**User Story:** As a user, I want the tables panel to automatically highlight and scroll to tables on the current PDF page, so that I can immediately see which data was extracted from the page I am viewing.

#### Acceptance Criteria

1. WHEN the Active Page changes, THE `ResultsTablesPanel` SHALL update its display to reflect tables whose `page_range` includes the new Active Page, and SHALL simultaneously apply a visual highlight (distinct border or background) to all matching tables.
2. WHEN the Active Page changes and at least one table's `page_range` includes that page, THE `ResultsTablesPanel` SHALL scroll the first matching table into view.
3. WHEN the Active Page changes and no table's `page_range` includes that page, THE `ResultsTablesPanel` SHALL display a "No tables on this page" message in place of the table list.
4. WHILE the Show All Tables Toggle is enabled, THE `ResultsTablesPanel` SHALL display all tables regardless of the Active Page and SHALL NOT display the "No tables on this page" message.

---

### Requirement 3: Tables Panel → PDF Viewer Synchronisation

**User Story:** As a user, I want to click on a table in the tables panel and have the PDF viewer jump to the relevant page, so that I can visually verify the extracted data against the source document.

#### Acceptance Criteria

1. WHEN the user clicks on a table in `ResultsTablesPanel`, THE `Sync_Controller` SHALL set the Active Page to the first element of that table's `page_range`.
2. WHEN the user clicks on a table whose `page_range` is empty, THE `Sync_Controller` SHALL leave the Active Page unchanged.
3. WHEN the Active Page is updated via a table click and `PdfViewer` fails to render the new page, THE `PdfViewer` SHALL retry rendering and SHALL display an error state if rendering cannot be completed after retrying.
4. THE `ResultsTablesPanel` SHALL provide a visually distinct clickable affordance (cursor, hover state) on each table block to indicate it is interactive.

---

### Requirement 4: Show All Tables Toggle

**User Story:** As a user, I want a toggle to disable page-filtering and see all extracted tables at once, so that I can review the full extraction output without navigating page by page.

#### Acceptance Criteria

1. THE `ResultsTablesPanel` SHALL render a "Show all tables" toggle control when at least one table exists.
2. WHEN the "Show all tables" toggle is off (default), THE `ResultsTablesPanel` SHALL operate in Page-Filtered View.
3. WHEN the user activates the "Show all tables" toggle, THE `ResultsTablesPanel` SHALL display all tables regardless of the Active Page.
4. WHEN the user deactivates the "Show all tables" toggle, THE `ResultsTablesPanel` SHALL return to Page-Filtered View using the current Active Page.
5. THE `ResultsTablesPanel` SHALL preserve the toggle state across Active Page changes (toggling on does not reset when the page changes).

---

### Requirement 5: Page Bounds Invariant

**User Story:** As a developer, I want the Active Page to always remain within valid bounds, so that the PDF viewer never attempts to render a non-existent page.

#### Acceptance Criteria

1. THE `Sync_Controller` SHALL ensure the Active Page is always an integer in the range `[1, totalPages]` after any navigation or synchronisation event, including table click requests that would otherwise produce a valid page number.
2. WHILE the PDF document is not yet loaded (`totalPages` is `0`), THE `Sync_Controller` SHALL keep the Active Page at `1` and SHALL reject any navigation attempts until the PDF finishes loading.
3. WHEN a table click would set the Active Page to a value outside `[1, totalPages]`, THE `Sync_Controller` SHALL clamp the value to the nearest valid bound.

---

### Requirement 6: Preservation of Existing Functionality

**User Story:** As a developer, I want the synchronisation changes to be non-breaking, so that all existing features continue to work correctly after the refactor.

#### Acceptance Criteria

1. THE `ResultsViewerScreen` SHALL continue to render the field correction workflow, including the `CorrectionModal`, without modification to its behaviour.
2. THE `ResultsViewerScreen` SHALL continue to render VLM badges, provenance tooltips, and the "View in PDF" source button on field rows.
3. THE `ResultsViewerScreen` SHALL continue to render the export buttons (CSV and Excel) with unchanged behaviour.
4. THE `ResultsViewerScreen` SHALL continue to render the `ResultsAbstentionsPanel` and `ResultsValidationPanel` tabs with unchanged behaviour.
5. WHEN `showPdfViewer` is `false`, THE `ResultsViewerScreen` SHALL not render `PdfViewer` and SHALL always render the full-width content panel as a fallback, even if individual tab content fails to load.
6. WHILE `showPdfViewer` is `false`, THE `PdfViewer` SHALL NOT call `onPageChange` in response to `highlights` prop changes, since the viewer is not rendered.

---

### Requirement 7: Accessibility

**User Story:** As a user relying on assistive technology, I want all synchronisation controls to be keyboard-navigable and screen-reader-friendly, so that I can use the feature without a mouse.

#### Acceptance Criteria

1. THE "Show all tables" toggle SHALL have an accessible label readable by screen readers (e.g., `aria-label` or associated `<label>`).
2. THE clickable table blocks in `ResultsTablesPanel` SHALL have `role="button"` or be implemented as `<button>` elements so they are reachable via keyboard Tab navigation.
3. WHEN a table block receives keyboard focus and the user presses Enter or Space, THE `Sync_Controller` SHALL trigger the same page-jump behaviour as a mouse click; keypresses on elements outside table blocks SHALL be handled by their respective interface elements and SHALL NOT trigger table synchronisation.
4. THE `PdfViewer` navigation buttons (previous page, next page, zoom in, zoom out) SHALL have descriptive `aria-label` attributes.
