import React from "react";

/**
 * Integration Guide — provides clear sections for anyone to integrate
 * their product with the PDF Parser API.
 */
export default function DeliverySettings() {
  return (
    <div style={styles.page}>
      <h1 style={styles.title}>Integration Guide</h1>
      <p style={styles.subtitle}>
        Connect your application to the PDF Ingestion API for automated document extraction.
      </p>

      {/* Quick Start */}
      <Section title="Quick Start">
        <p>Submit a PDF and get structured data back in 3 steps:</p>
        <CodeBlock>{`# 1. Upload a PDF
curl -X POST http://localhost:8000/v1/extract \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -F "file=@statement.pdf"

# Response: { "data": { "job_id": "abc-123", "status": "processing" } }

# 2. Poll for completion
curl http://localhost:8000/v1/jobs/abc-123 \\
  -H "Authorization: Bearer YOUR_API_KEY"

# Response: { "data": { "status": "complete" } }

# 3. Get results
curl http://localhost:8000/v1/results/abc-123 \\
  -H "Authorization: Bearer YOUR_API_KEY"

# Response: { "data": { "output": { "fields": {...}, "accounts": [...] } } }`}</CodeBlock>
      </Section>

      {/* Authentication */}
      <Section title="Authentication">
        <p>All requests require a Bearer token in the Authorization header:</p>
        <CodeBlock>{`Authorization: Bearer YOUR_API_KEY`}</CodeBlock>
        <p style={styles.note}>
          Contact your administrator to obtain an API key. Each key is scoped to a tenant
          with configurable VLM access and redaction settings.
        </p>
      </Section>

      {/* Endpoints */}
      <Section title="API Endpoints">
        <EndpointCard
          method="POST"
          path="/v1/extract"
          description="Submit a PDF for extraction. Returns immediately with a job_id."
          params={[
            { name: "file", type: "multipart", required: true, desc: "PDF file (max 100 MB)" },
            { name: "schema_type", type: "string", required: false, desc: "Override auto-detection: bank_statement, custody_statement, swift_confirm" },
            { name: "batch_id", type: "string", required: false, desc: "Group related documents" },
          ]}
        />
        <EndpointCard
          method="GET"
          path="/v1/jobs/{job_id}"
          description="Check job status. Poll until status is 'complete', 'partial', or 'failed'."
          params={[]}
        />
        <EndpointCard
          method="GET"
          path="/v1/jobs/{job_id}/progress"
          description="Real-time progress with page counts, current stage, and ETA."
          params={[]}
        />
        <EndpointCard
          method="GET"
          path="/v1/results/{job_id}"
          description="Get the full extraction result including fields, accounts, tables, and validation."
          params={[]}
        />
        <EndpointCard
          method="POST"
          path="/v1/feedback/{job_id}"
          description="Submit a correction for an extracted field value."
          params={[
            { name: "field_name", type: "string", required: true, desc: "Name of the field to correct" },
            { name: "original_value", type: "string", required: true, desc: "The incorrectly extracted value" },
            { name: "corrected_value", type: "string", required: true, desc: "The correct value" },
          ]}
        />
      </Section>

      {/* Response Format */}
      <Section title="Response Format">
        <p>All responses follow a standard envelope:</p>
        <CodeBlock>{`{
  "data": { ... },          // The response payload
  "meta": {
    "request_id": "uuid",   // Trace ID for debugging
    "timestamp": "ISO 8601"
  },
  "error": null             // Error details if request failed
}`}</CodeBlock>
      </Section>

      {/* Extraction Output */}
      <Section title="Extraction Output Structure">
        <CodeBlock>{`{
  "output": {
    "doc_id": "sha256:...",
    "schema_type": "bank_statement",
    "status": "complete",
    "fields": {
      "institution": { "value": "UBS", "confidence": 0.95, "vlm_used": true },
      "account_number": { "value": "CH59...", "confidence": 0.92 },
      "accounts": { "value": [...] }
    },
    "abstentions": [...],
    "validation": { "passed": true, "failures": [] }
  }
}`}</CodeBlock>
      </Section>

      {/* Error Codes */}
      <Section title="Error Codes">
        <table style={styles.errorTable}>
          <thead>
            <tr><th>Code</th><th>Meaning</th></tr>
          </thead>
          <tbody>
            <tr><td><code>ERR_AUTH_001</code></td><td>Missing API key</td></tr>
            <tr><td><code>ERR_AUTH_002</code></td><td>Invalid API key</td></tr>
            <tr><td><code>ERR_INGESTION_001</code></td><td>File too large</td></tr>
            <tr><td><code>ERR_INGESTION_002</code></td><td>Not a valid PDF</td></tr>
            <tr><td><code>ERR_INGESTION_003</code></td><td>Password-protected PDF</td></tr>
            <tr><td><code>ERR_EXTRACT_003</code></td><td>Extraction failed</td></tr>
            <tr><td><code>ERR_VLM_003</code></td><td>LLM returned null</td></tr>
            <tr><td><code>ERR_VLM_005</code></td><td>LLM service unavailable</td></tr>
          </tbody>
        </table>
      </Section>

      {/* Rate Limits */}
      <Section title="Rate Limits & Best Practices">
        <ul style={styles.list}>
          <li>Maximum file size: 100 MB</li>
          <li>Concurrent requests: 10 per tenant</li>
          <li>Poll interval: 2–5 seconds recommended</li>
          <li>Use <code>batch_id</code> to group related documents for easier tracking</li>
          <li>Use <code>schema_type</code> override when you know the document type — improves accuracy</li>
          <li>Check <code>validation.passed</code> in results to verify extraction quality</li>
        </ul>
      </Section>
    </div>
  );
}

function Section({ title, children }) {
  return (
    <div style={styles.section}>
      <h2 style={styles.sectionTitle}>{title}</h2>
      {children}
    </div>
  );
}

function CodeBlock({ children }) {
  return (
    <pre style={styles.codeBlock}>
      <code>{children}</code>
    </pre>
  );
}

function EndpointCard({ method, path, description, params }) {
  return (
    <div style={styles.endpoint}>
      <div style={styles.endpointHeader}>
        <span style={{ ...styles.method, backgroundColor: method === "POST" ? "var(--color-success)" : "var(--color-info)" }}>
          {method}
        </span>
        <code style={styles.path}>{path}</code>
      </div>
      <p style={styles.endpointDesc}>{description}</p>
      {params.length > 0 && (
        <table style={styles.paramTable}>
          <thead><tr><th>Parameter</th><th>Type</th><th>Required</th><th>Description</th></tr></thead>
          <tbody>
            {params.map((p) => (
              <tr key={p.name}>
                <td><code>{p.name}</code></td>
                <td>{p.type}</td>
                <td>{p.required ? "Yes" : "No"}</td>
                <td>{p.desc}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

const styles = {
  page: { maxWidth: 720 },
  title: { fontSize: "var(--text-xl)", fontWeight: 700, color: "var(--color-text-primary)", marginBottom: "var(--space-1)" },
  subtitle: { fontSize: "var(--text-md)", color: "var(--color-text-secondary)", marginBottom: "var(--space-6)" },
  section: { marginBottom: "var(--space-8)" },
  sectionTitle: { fontSize: "var(--text-lg)", fontWeight: 600, color: "var(--color-text-primary)", marginBottom: "var(--space-3)", paddingBottom: "var(--space-2)", borderBottom: "1px solid var(--color-border-light)" },
  codeBlock: { backgroundColor: "var(--color-primary)", color: "var(--color-text-inverse)", padding: "var(--space-4)", borderRadius: "var(--border-radius)", fontSize: "var(--text-sm)", fontFamily: "var(--font-mono)", overflow: "auto", marginTop: "var(--space-2)", marginBottom: "var(--space-3)", lineHeight: 1.6 },
  note: { fontSize: "var(--text-sm)", color: "var(--color-text-muted)", marginTop: "var(--space-2)" },
  endpoint: { backgroundColor: "#fff", border: "1px solid var(--color-border-light)", borderRadius: "var(--border-radius)", padding: "var(--space-4)", marginBottom: "var(--space-3)" },
  endpointHeader: { display: "flex", alignItems: "center", gap: "var(--space-2)", marginBottom: "var(--space-2)" },
  method: { padding: "2px 8px", borderRadius: "3px", fontSize: "var(--text-xs)", fontWeight: 700, color: "#fff" },
  path: { fontFamily: "var(--font-mono)", fontSize: "var(--text-md)", color: "var(--color-text-primary)" },
  endpointDesc: { fontSize: "var(--text-sm)", color: "var(--color-text-secondary)", marginBottom: "var(--space-2)" },
  paramTable: { width: "100%", fontSize: "var(--text-sm)" },
  errorTable: { width: "100%", fontSize: "var(--text-sm)" },
  list: { paddingLeft: "var(--space-5)", fontSize: "var(--text-md)", color: "var(--color-text-secondary)", lineHeight: 2 },
};
