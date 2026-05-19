/**
 * CSV export and parse utilities for feedback entries.
 * Handles special characters: commas, double quotes, newlines, and Unicode.
 */

const FEEDBACK_HEADERS = [
  "job_id",
  "field_name",
  "original_value",
  "corrected_value",
  "submitted_by",
  "submitted_at",
];

/**
 * Escape a single CSV field value according to RFC 4180.
 * - If the value contains a comma, double quote, or newline, wrap in double quotes.
 * - Double quotes within the value are escaped by doubling them.
 */
function escapeField(value) {
  const str = value == null ? "" : String(value);
  // Always quote fields to safely handle commas, quotes, newlines, and Unicode
  return '"' + str.replace(/"/g, '""') + '"';
}

/**
 * Export an array of feedback entries to a CSV string.
 *
 * @param {Array<Object>} entries - Array of feedback entry objects
 * @returns {string} CSV string with headers and rows
 */
export function exportCSV(entries) {
  const headerLine = FEEDBACK_HEADERS.map(escapeField).join(",");
  const rows = entries.map((entry) =>
    FEEDBACK_HEADERS.map((key) => escapeField(entry[key])).join(",")
  );
  return [headerLine, ...rows].join("\r\n");
}

/**
 * Parse a CSV string back into an array of objects.
 * Handles quoted fields with embedded commas, double quotes, and newlines.
 *
 * @param {string} csvString - CSV string to parse
 * @returns {Array<Object>} Array of objects with keys from the header row
 */
export function parseCSV(csvString) {
  const rows = parseCSVRows(csvString);
  if (rows.length === 0) return [];

  const headers = rows[0];
  const result = [];
  for (let i = 1; i < rows.length; i++) {
    const row = rows[i];
    const obj = {};
    for (let j = 0; j < headers.length; j++) {
      obj[headers[j]] = j < row.length ? row[j] : "";
    }
    result.push(obj);
  }
  return result;
}

/**
 * Parse CSV string into a 2D array of field values.
 * Implements RFC 4180 parsing with support for:
 * - Quoted fields containing commas, newlines, and double quotes
 * - Unquoted fields
 * - CRLF and LF line endings
 */
function parseCSVRows(csvString) {
  const rows = [];
  let currentRow = [];
  let currentField = "";
  let inQuotes = false;
  let i = 0;

  while (i < csvString.length) {
    const char = csvString[i];

    if (inQuotes) {
      if (char === '"') {
        // Check for escaped quote (double quote)
        if (i + 1 < csvString.length && csvString[i + 1] === '"') {
          currentField += '"';
          i += 2;
        } else {
          // End of quoted field
          inQuotes = false;
          i++;
        }
      } else {
        currentField += char;
        i++;
      }
    } else {
      if (char === '"') {
        inQuotes = true;
        i++;
      } else if (char === ",") {
        currentRow.push(currentField);
        currentField = "";
        i++;
      } else if (char === "\r") {
        // Handle CRLF
        currentRow.push(currentField);
        currentField = "";
        rows.push(currentRow);
        currentRow = [];
        i++;
        if (i < csvString.length && csvString[i] === "\n") {
          i++;
        }
      } else if (char === "\n") {
        currentRow.push(currentField);
        currentField = "";
        rows.push(currentRow);
        currentRow = [];
        i++;
      } else {
        currentField += char;
        i++;
      }
    }
  }

  // Handle last field and row
  if (currentField !== "" || currentRow.length > 0) {
    currentRow.push(currentField);
    rows.push(currentRow);
  }

  return rows;
}
