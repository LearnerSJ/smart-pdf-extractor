import React, { useState, useRef } from "react";

const API_KEY = "demo-key";

const ENDPOINTS = [
  {
    method: "POST",
    path: "/v1/extract",
    description: "Submit a PDF for extraction. Returns a job ID for polling.",
    params: [
      { name: "file", type: "File (multipart)", required: true, desc: "PDF file to process" },
      { name: "schema_type", type: "string", required: false, desc: "Override auto-detection (bank_statement, custody_statement, swift_confirm)" },
      { name: "batch_id", type: "string", required: false, desc: "Group multiple files into a batch" },
    ],
  },
  {
    method: "GET",
    path: "/v1/jobs/{id}",
    description: "Get job status and metadata.",
    params: [],
  },
  {
    method: "GET",
    path: "/v1/jobs/{id}/progress",
    description: "Get real-time progress (pages processed, ETA).",
    params: [],
  },
  {
    method: "GET",
    path: "/v1/results/{id}",
    description: "Get extraction results once job is complete.",
    params: [],
  },
  {
    method: "POST",
    path: "/v1/jobs/{id}/cancel",
    description: "Cancel a running job.",
    params: [],
  },
];

const CURL_EXAMPLE = `# Submit a PDF for extraction
curl -X POST http://localhost:8000/v1/extract \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -F "file=@statement.pdf" \\
  -F "schema_type=bank_statement"

# Check job status
curl http://localhost:8000/v1/jobs/{JOB_ID} \\
  -H "Authorization: Bearer YOUR_API_KEY"

# Get results
curl http://localhost:8000/v1/results/{JOB_ID} \\
  -H "Authorization: Bearer YOUR_API_KEY"`;

const PYTHON_EXAMPLE = `import requests

API_URL = "http://localhost:8000"
API_KEY = "YOUR_API_KEY"
headers = {"Authorization": f"Bearer {API_KEY}"}

# Submit PDF
with open("statement.pdf", "rb") as f:
    resp = requests.post(
        f"{API_URL}/v1/extract",
        headers=headers,
        files={"file": ("statement.pdf", f, "application/pdf")},
        data={"schema_type": "bank_statement"},
    )
    job = resp.json()["data"]
    print(f"Job ID: {job['job_id']}")

# Poll for completion
import time
while True:
    status_resp = requests.get(
        f"{API_URL}/v1/jobs/{job['job_id']}",
        headers=headers,
    )
    status = status_resp.json()["data"]["status"]
    if status in ("complete", "partial", "failed"):
        break
    time.sleep(2)

# Get results
results = requests.get(
    f"{API_URL}/v1/results/{job['job_id']}",
    headers=headers,
).json()["data"]
print(results["output"])`;

const JS_EXAMPLE = `const API_URL = "http://localhost:8000";
const API_KEY = "YOUR_API_KEY";

// Submit PDF
const formData = new FormData();
formData.append("file", fileInput.files[0]);
formData.append("schema_type", "bank_statement");

const submitRes = await fetch(\`\${API_URL}/v1/extract\`, {
  method: "POST",
  headers: { Authorization: \`Bearer \${API_KEY}\` },
  body: formData,
});
const { data: job } = await submitRes.json();
console.log("Job ID:", job.job_id);

// Poll for completion
let status = "processing";
while (status === "processing") {
  await new Promise(r => setTimeout(r, 2000));
  const statusRes = await fetch(
    \`\${API_URL}/v1/jobs/\${job.job_id}\`,
    { headers: { Authorization: \`Bearer \${API_KEY}\` } }
  );
  const statusData = await statusRes.json();
  status = statusData.data.status;
}

// Get results
const resultRes = await fetch(
  \`\${API_URL}/v1/results/\${job.job_id}\`,
  { headers: { Authorization: \`Bearer \${API_KEY}\` } }
);
const { data: result } = await resultRes.json();
console.log(result.output);`;

const WEBHOOK_EXAMPLE = `# Webhook Setup (coming soon)
# 
# Configure a webhook URL to receive notifications when jobs complete:
#
# POST /v1/webhooks
# {
#   "url": "https://your-app.com/webhook/pdf-results",
#   "events": ["job.complete", "job.failed"],
#   "secret": "your-webhook-secret"
# }
#
# Webhook payload:
# {
#   "event": "job.complete",
#   "job_id": "abc-123",
#   "timestamp": "2024-01-15T10:30:00Z",
#   "result_url": "/v1/results/abc-123"
# }`;

export default function IntegrationGuideScreen() {
  const [copiedId, setCopiedId] = useState(null);
  const [tryItFile, setTryItFile] = useState(null);
  const [tryItResponse, setTryItResponse] = useState(null);
  const [tryItLoading, setTryItLoading] = useState(false);
  const tryItFileRef = useRef(null);

  const copyToClipboard = (text, id) => {
    navigator.clipboard.writeText(text).then(() => {
      setCopiedId(id);
      setTimeout(() => setCopiedId(null), 2000);
    });
  };

  const handleTryIt = async () => {
    if (!tryItFile) return;
    setTryItLoading(true);
    setTryItResponse(null);

    try {
      const formData = new FormData();
      formData.append("file", tryItFile);

      const res = await fetch("/v1/extract", {
        method: "POST",
        headers: { Authorization: `Bearer ${API_KEY}` },
        body: formData,
      });
      const json = await res.json();
      setTryItResponse(JSON.stringify(json, null, 2));
    } catch (err) {
      setTryItResponse(JSON.stringify({ error: err.message }, null, 2));
    } finally {
      setTryItLoading(false);
    }
  };

  return (
    <div style={styles.page}>
      <h1 style={styles.title}>Integration Guide</h1>
      <p style={styles.subtitle}>
        Connect your application to the PDF extraction API. All endpoints require an API key via the Authorization header.
      </p>

      {/* Endpoints Reference */}
      <section style={styles.section}>
        <h2 style={styles.sectionTitle}>API Endpoints</h2>
        <div style={styles.endpointList}>
          {ENDPOINTS.map((ep, i) => (
            <div key={i} style={styles.endpoint}>
              <div style={styles.endpointHeader}>
                <span style={{ ...styles.methodBadge, backgroundColor: ep.method === "POST" ? "var(--color-info)" : "var(--color-success)" }}>
                  {ep.method}
                </span>
                <code style={styles.endpointPath}>{ep.path}</code>
              </div>
              <p style={styles.endpointDesc}>{ep.description}</p>
              {ep.params.length > 0 && (
                <div style={styles.paramTable}>
                  {ep.params.map((p, j) => (
                    <div key={j} style={styles.paramRow}>
                      <code style={styles.paramName}>{p.name}</code>
                      <span style={styles.paramType}>{p.type}</span>
                      {p.required && <span style={styles.requiredBadge}>required</span>}
                      <span style={styles.paramDesc}>{p.desc}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </section>

      {/* Code Examples */}
      <section style={styles.section}>
        <h2 style={styles.sectionTitle}>Code Examples</h2>

        <CodeBlock
          title="cURL"
          code={CURL_EXAMPLE}
          id="curl"
          copiedId={copiedId}
          onCopy={copyToClipboard}
        />
        <CodeBlock
          title="Python"
          code={PYTHON_EXAMPLE}
          id="python"
          copiedId={copiedId}
          onCopy={copyToClipboard}
        />
        <CodeBlock
          title="JavaScript (fetch)"
          code={JS_EXAMPLE}
          id="js"
          copiedId={copiedId}
          onCopy={copyToClipboard}
        />
        <CodeBlock
          title="Webhook Setup"
          code={WEBHOOK_EXAMPLE}
          id="webhook"
          copiedId={copiedId}
          onCopy={copyToClipboard}
        />
      </section>

      {/* Try It */}
      <section style={styles.section}>
        <h2 style={styles.sectionTitle}>Try It</h2>
        <p style={styles.tryItDesc}>
          Upload a PDF to test the API and see the raw JSON response.
        </p>
        <div style={styles.tryItRow}>
          <button onClick={() => tryItFileRef.current?.click()} style={styles.tryItFileBtn}>
            {tryItFile ? tryItFile.name : "Choose PDF..."}
          </button>
          <input
            ref={tryItFileRef}
            type="file"
            accept=".pdf"
            onChange={(e) => setTryItFile(e.target.files[0])}
            style={{ display: "none" }}
          />
          <button
            onClick={handleTryIt}
            disabled={!tryItFile || tryItLoading}
            style={styles.tryItSendBtn}
          >
            {tryItLoading ? "Sending..." : "Send Request"}
          </button>
        </div>
        {tryItResponse && (
          <pre style={styles.tryItResponse}>{tryItResponse}</pre>
        )}
      </section>
    </div>
  );
}

function CodeBlock({ title, code, id, copiedId, onCopy }) {
  return (
    <div style={styles.codeBlock}>
      <div style={styles.codeHeader}>
        <span style={styles.codeTitle}>{title}</span>
        <button
          onClick={() => onCopy(code, id)}
          style={styles.copyBtn}
        >
          {copiedId === id ? "✓ Copied" : "Copy"}
        </button>
      </div>
      <pre style={styles.codeContent}>{code}</pre>
    </div>
  );
}

const styles = {
  page: {
    maxWidth: 800,
    margin: "0 auto",
  },
  title: {
    fontSize: "var(--text-xl)",
    fontWeight: 700,
    color: "var(--color-text-primary)",
    marginBottom: "var(--space-2)",
  },
  subtitle: {
    fontSize: "var(--text-md)",
    color: "var(--color-text-secondary)",
    marginBottom: "var(--space-6)",
  },
  section: {
    marginBottom: "var(--space-8)",
  },
  sectionTitle: {
    fontSize: "var(--text-lg)",
    fontWeight: 600,
    color: "var(--color-text-primary)",
    marginBottom: "var(--space-4)",
    paddingBottom: "var(--space-2)",
    borderBottom: "1px solid var(--color-border-light)",
  },
  endpointList: {
    display: "flex",
    flexDirection: "column",
    gap: "var(--space-3)",
  },
  endpoint: {
    padding: "var(--space-3) var(--space-4)",
    backgroundColor: "#fff",
    border: "1px solid var(--color-border-light)",
    borderRadius: "var(--border-radius)",
  },
  endpointHeader: {
    display: "flex",
    alignItems: "center",
    gap: "var(--space-2)",
    marginBottom: "var(--space-2)",
  },
  methodBadge: {
    padding: "2px 8px",
    borderRadius: "var(--border-radius-sm)",
    color: "#fff",
    fontSize: "var(--text-xs)",
    fontWeight: 700,
    textTransform: "uppercase",
  },
  endpointPath: {
    fontFamily: "var(--font-mono)",
    fontSize: "var(--text-md)",
    color: "var(--color-text-primary)",
    fontWeight: 500,
  },
  endpointDesc: {
    fontSize: "var(--text-sm)",
    color: "var(--color-text-secondary)",
    margin: 0,
  },
  paramTable: {
    marginTop: "var(--space-2)",
    borderTop: "1px solid var(--color-border-light)",
    paddingTop: "var(--space-2)",
  },
  paramRow: {
    display: "flex",
    alignItems: "center",
    gap: "var(--space-2)",
    padding: "var(--space-1) 0",
    fontSize: "var(--text-sm)",
  },
  paramName: {
    fontFamily: "var(--font-mono)",
    fontSize: "var(--text-sm)",
    color: "var(--color-info)",
    fontWeight: 500,
    minWidth: 80,
  },
  paramType: {
    fontSize: "var(--text-xs)",
    color: "var(--color-text-muted)",
    minWidth: 100,
  },
  requiredBadge: {
    fontSize: "var(--text-xs)",
    color: "var(--color-error)",
    fontWeight: 600,
  },
  paramDesc: {
    fontSize: "var(--text-xs)",
    color: "var(--color-text-secondary)",
  },
  codeBlock: {
    marginBottom: "var(--space-4)",
    border: "1px solid var(--color-border-light)",
    borderRadius: "var(--border-radius)",
    overflow: "hidden",
  },
  codeHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    padding: "var(--space-2) var(--space-3)",
    backgroundColor: "var(--color-surface)",
    borderBottom: "1px solid var(--color-border-light)",
  },
  codeTitle: {
    fontSize: "var(--text-sm)",
    fontWeight: 600,
    color: "var(--color-text-primary)",
  },
  copyBtn: {
    padding: "2px 8px",
    fontSize: "var(--text-xs)",
    backgroundColor: "transparent",
    border: "1px solid var(--color-border)",
    borderRadius: "var(--border-radius-sm)",
    cursor: "pointer",
    color: "var(--color-text-secondary)",
  },
  codeContent: {
    padding: "var(--space-3) var(--space-4)",
    margin: 0,
    fontSize: "var(--text-sm)",
    fontFamily: "var(--font-mono)",
    backgroundColor: "#1e1e2e",
    color: "#cdd6f4",
    overflow: "auto",
    lineHeight: 1.5,
  },
  tryItDesc: {
    fontSize: "var(--text-sm)",
    color: "var(--color-text-secondary)",
    marginBottom: "var(--space-3)",
  },
  tryItRow: {
    display: "flex",
    gap: "var(--space-2)",
    marginBottom: "var(--space-3)",
  },
  tryItFileBtn: {
    padding: "var(--space-2) var(--space-3)",
    border: "1px solid var(--color-border)",
    borderRadius: "var(--border-radius-sm)",
    backgroundColor: "#fff",
    cursor: "pointer",
    fontSize: "var(--text-sm)",
    color: "var(--color-text-secondary)",
  },
  tryItSendBtn: {
    padding: "var(--space-2) var(--space-4)",
    backgroundColor: "var(--color-info)",
    color: "#fff",
    border: "none",
    borderRadius: "var(--border-radius-sm)",
    cursor: "pointer",
    fontSize: "var(--text-sm)",
    fontWeight: 600,
  },
  tryItResponse: {
    padding: "var(--space-3)",
    backgroundColor: "#1e1e2e",
    color: "#cdd6f4",
    borderRadius: "var(--border-radius)",
    fontSize: "var(--text-sm)",
    fontFamily: "var(--font-mono)",
    overflow: "auto",
    maxHeight: 400,
    lineHeight: 1.4,
    margin: 0,
  },
};
