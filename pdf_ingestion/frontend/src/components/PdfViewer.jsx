import React, { useState, useEffect, useRef, useCallback } from "react";

/**
 * PDF Viewer component using pdf.js.
 * Renders a PDF page on a canvas and draws highlight overlays for field bounding boxes.
 * Falls back gracefully if pdfjs-dist is not installed.
 *
 * Props:
 *   - jobId: string — job ID to fetch the PDF from /v1/jobs/{id}/pdf
 *   - highlights: Array<{ fieldName, page, x, y, width, height }> — bounding boxes to highlight
 */

let pdfjsLib = null;
let pdfjsLoadAttempted = false;
let pdfjsLoadError = null;

function loadPdfJs() {
  if (pdfjsLoadAttempted) return Promise.resolve(pdfjsLib);
  pdfjsLoadAttempted = true;
  try {
    // Use a variable to prevent Rollup from statically resolving the import.
    // This allows the build to succeed even when pdfjs-dist is not installed.
    const moduleName = ["pdfjs", "dist"].join("-");
    return import(/* @vite-ignore */ moduleName).then((mod) => {
      pdfjsLib = mod;
      pdfjsLib.GlobalWorkerOptions.workerSrc = "";
      return pdfjsLib;
    }).catch((err) => {
      pdfjsLoadError = err;
      return null;
    });
  } catch (err) {
    pdfjsLoadError = err;
    return Promise.resolve(null);
  }
}

const API_KEY = "demo-key";

export default function PdfViewer({ jobId, highlights = [] }) {
  const canvasRef = useRef(null);
  const overlayRef = useRef(null);
  const [pdfDoc, setPdfDoc] = useState(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [totalPages, setTotalPages] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [hoveredHighlight, setHoveredHighlight] = useState(null);
  const [scale, setScale] = useState(1.2);
  const [pdfAvailable, setPdfAvailable] = useState(true);

  // Load pdf.js and the PDF document
  useEffect(() => {
    let cancelled = false;

    async function init() {
      const lib = await loadPdfJs();
      if (cancelled) return;

      if (!lib) {
        setError("PDF viewer requires pdfjs-dist. Run: npm install pdfjs-dist");
        setLoading(false);
        setPdfAvailable(false);
        return;
      }

      try {
        const res = await fetch(`/v1/jobs/${jobId}/pdf`, {
          headers: { Authorization: `Bearer ${API_KEY}` },
        });

        if (!res.ok) {
          setError("PDF not available for this job");
          setLoading(false);
          return;
        }

        const arrayBuffer = await res.arrayBuffer();
        const doc = await lib.getDocument({ data: arrayBuffer }).promise;
        if (cancelled) return;

        setPdfDoc(doc);
        setTotalPages(doc.numPages);
        setLoading(false);
      } catch (err) {
        if (!cancelled) {
          setError(err.message || "Failed to load PDF");
          setLoading(false);
        }
      }
    }

    init();
    return () => { cancelled = true; };
  }, [jobId]);

  // Navigate to highlighted page when highlights change
  useEffect(() => {
    if (highlights.length > 0 && highlights[0].page) {
      setCurrentPage(highlights[0].page);
    }
  }, [highlights]);

  // Render the current page
  const renderPage = useCallback(async () => {
    if (!pdfDoc || !canvasRef.current) return;

    try {
      const page = await pdfDoc.getPage(currentPage);
      const viewport = page.getViewport({ scale });
      const canvas = canvasRef.current;
      const ctx = canvas.getContext("2d");

      canvas.width = viewport.width;
      canvas.height = viewport.height;

      await page.render({ canvasContext: ctx, viewport }).promise;

      // Draw highlights
      if (overlayRef.current) {
        overlayRef.current.style.width = `${viewport.width}px`;
        overlayRef.current.style.height = `${viewport.height}px`;
      }
    } catch (err) {
      console.error("Error rendering PDF page:", err);
    }
  }, [pdfDoc, currentPage, scale]);

  useEffect(() => {
    renderPage();
  }, [renderPage]);

  if (!pdfAvailable) {
    return (
      <div style={styles.fallback}>
        <div style={styles.fallbackIcon}>📄</div>
        <div style={styles.fallbackTitle}>PDF Viewer</div>
        <div style={styles.fallbackMessage}>
          PDF viewer requires <code>pdfjs-dist</code> to be installed.
        </div>
        <div style={styles.fallbackCode}>npm install pdfjs-dist</div>
      </div>
    );
  }

  if (loading) {
    return (
      <div style={styles.loading}>
        <div style={styles.spinner}>⟳</div>
        Loading PDF...
      </div>
    );
  }

  if (error) {
    return (
      <div style={styles.errorPanel}>
        <div style={styles.errorIcon}>⚠</div>
        <div>{error}</div>
      </div>
    );
  }

  // Compute highlight rectangles for current page
  const pageHighlights = highlights.filter(
    (h) => !h.page || h.page === currentPage
  );

  return (
    <div style={styles.container}>
      {/* Toolbar */}
      <div style={styles.toolbar}>
        <button
          onClick={() => setCurrentPage(Math.max(1, currentPage - 1))}
          disabled={currentPage <= 1}
          style={styles.toolBtn}
        >
          ←
        </button>
        <span style={styles.pageInfo}>
          Page {currentPage} / {totalPages}
        </span>
        <button
          onClick={() => setCurrentPage(Math.min(totalPages, currentPage + 1))}
          disabled={currentPage >= totalPages}
          style={styles.toolBtn}
        >
          →
        </button>
        <span style={styles.separator}>|</span>
        <button onClick={() => setScale(Math.max(0.5, scale - 0.2))} style={styles.toolBtn}>−</button>
        <span style={styles.zoomInfo}>{Math.round(scale * 100)}%</span>
        <button onClick={() => setScale(Math.min(3, scale + 0.2))} style={styles.toolBtn}>+</button>
      </div>

      {/* Canvas + overlay */}
      <div style={styles.canvasWrapper}>
        <canvas ref={canvasRef} style={styles.canvas} />
        <div ref={overlayRef} style={styles.overlay}>
          {pageHighlights.map((h, i) => (
            <div
              key={i}
              style={{
                position: "absolute",
                left: `${(h.x || 0) * 100}%`,
                top: `${(h.y || 0) * 100}%`,
                width: `${(h.width || 0.1) * 100}%`,
                height: `${(h.height || 0.02) * 100}%`,
                backgroundColor: "rgba(52, 152, 219, 0.2)",
                border: "2px solid rgba(52, 152, 219, 0.8)",
                borderRadius: "2px",
                cursor: "pointer",
              }}
              onMouseEnter={() => setHoveredHighlight(h)}
              onMouseLeave={() => setHoveredHighlight(null)}
            >
              {hoveredHighlight === h && (
                <div style={styles.tooltip}>{h.fieldName}</div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

const styles = {
  container: {
    display: "flex",
    flexDirection: "column",
    height: "100%",
    minHeight: 400,
    backgroundColor: "var(--color-surface, #f8f8f8)",
  },
  toolbar: {
    display: "flex",
    alignItems: "center",
    gap: "var(--space-2, 8px)",
    padding: "var(--space-2, 8px) var(--space-3, 12px)",
    borderBottom: "1px solid var(--color-border-light, #eee)",
    backgroundColor: "#fff",
  },
  toolBtn: {
    padding: "4px 8px",
    border: "1px solid var(--color-border, #ddd)",
    borderRadius: "var(--border-radius-sm, 4px)",
    backgroundColor: "transparent",
    cursor: "pointer",
    fontSize: "var(--text-sm, 13px)",
  },
  pageInfo: {
    fontSize: "var(--text-sm, 13px)",
    color: "var(--color-text-secondary, #666)",
  },
  zoomInfo: {
    fontSize: "var(--text-xs, 11px)",
    color: "var(--color-text-muted, #999)",
    minWidth: 36,
    textAlign: "center",
  },
  separator: {
    color: "var(--color-border, #ddd)",
    margin: "0 4px",
  },
  canvasWrapper: {
    flex: 1,
    overflow: "auto",
    position: "relative",
    display: "flex",
    justifyContent: "center",
    padding: "var(--space-3, 12px)",
  },
  canvas: {
    boxShadow: "0 2px 8px rgba(0,0,0,0.1)",
  },
  overlay: {
    position: "absolute",
    top: 0,
    left: 0,
    pointerEvents: "none",
  },
  tooltip: {
    position: "absolute",
    top: "-24px",
    left: 0,
    backgroundColor: "var(--color-primary, #2c3e50)",
    color: "#fff",
    padding: "2px 6px",
    borderRadius: "3px",
    fontSize: "11px",
    whiteSpace: "nowrap",
    pointerEvents: "none",
  },
  loading: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: "8px",
    padding: "var(--space-8, 32px)",
    color: "var(--color-text-muted, #999)",
  },
  spinner: {
    animation: "spin 1s linear infinite",
    fontSize: "20px",
  },
  errorPanel: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    padding: "var(--space-8, 32px)",
    color: "var(--color-text-muted, #999)",
    gap: "8px",
  },
  errorIcon: {
    fontSize: "24px",
    color: "var(--color-warning, #f39c12)",
  },
  fallback: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    padding: "var(--space-8, 32px)",
    textAlign: "center",
    gap: "8px",
  },
  fallbackIcon: {
    fontSize: "32px",
    opacity: 0.5,
  },
  fallbackTitle: {
    fontSize: "var(--text-md, 14px)",
    fontWeight: 600,
    color: "var(--color-text-primary, #333)",
  },
  fallbackMessage: {
    fontSize: "var(--text-sm, 13px)",
    color: "var(--color-text-secondary, #666)",
  },
  fallbackCode: {
    fontFamily: "var(--font-mono, monospace)",
    fontSize: "var(--text-sm, 13px)",
    backgroundColor: "rgba(0,0,0,0.05)",
    padding: "4px 8px",
    borderRadius: "4px",
    marginTop: "4px",
  },
};
