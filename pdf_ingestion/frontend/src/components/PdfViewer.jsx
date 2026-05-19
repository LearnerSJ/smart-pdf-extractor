import React, { useState, useEffect, useRef, useCallback } from "react";
import * as pdfjsLib from "pdfjs-dist";
import { clampPage } from "../utils/syncUtils";

pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.mjs",
  import.meta.url
).toString();

const API_KEY = "demo-key";

export default function PdfViewer({
  jobId,
  highlights = [],
  currentPage,
  onPageChange,
  onTotalPages,
}) {
  const canvasRef = useRef(null);
  const overlayRef = useRef(null);
  const containerRef = useRef(null);
  const renderTaskRef = useRef(null);
  const [pdfDoc, setPdfDoc] = useState(null);
  const [totalPages, setTotalPages] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [hoveredHighlight, setHoveredHighlight] = useState(null);
  const [containerWidth, setContainerWidth] = useState(0);
  const [zoomLevel, setZoomLevel] = useState(1.0); // 1.0 = fit width

  // Load PDF
  useEffect(() => {
    let cancelled = false;
    async function init() {
      try {
        const res = await fetch(`/v1/jobs/${jobId}/pdf`, {
          headers: { Authorization: `Bearer ${API_KEY}` },
        });
        if (!res.ok) { setError("PDF not available"); setLoading(false); return; }
        const buf = await res.arrayBuffer();
        const doc = await pdfjsLib.getDocument({ data: buf }).promise;
        if (cancelled) return;
        setPdfDoc(doc);
        setTotalPages(doc.numPages);
        if (onTotalPages) onTotalPages(doc.numPages);
        setLoading(false);
      } catch (err) {
        if (!cancelled) { setError(err.message); setLoading(false); }
      }
    }
    init();
    return () => { cancelled = true; };
  }, [jobId]);

  // Observe container width
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) {
        if (e.contentRect.width > 0) setContainerWidth(e.contentRect.width);
      }
    });
    ro.observe(el);
    // Measure immediately (ResizeObserver callback is async)
    const w = el.getBoundingClientRect().width;
    if (w > 0) setContainerWidth(w);
    return () => ro.disconnect();
  }, [loading]); // re-run when loading changes (container appears)

  // Render page
  const renderPage = useCallback(async () => {
    if (!pdfDoc || !canvasRef.current || containerWidth === 0) {
      // If container width not yet measured, try measuring directly
      if (containerRef.current && containerWidth === 0) {
        const w = containerRef.current.getBoundingClientRect().width;
        if (w > 0) { setContainerWidth(w); return; }
      }
      return;
    }

    if (renderTaskRef.current) {
      try { renderTaskRef.current.cancel(); } catch {}
      renderTaskRef.current = null;
    }

    const safePage = clampPage(currentPage, totalPages);
    try {
      const page = await pdfDoc.getPage(safePage);
      const canvas = canvasRef.current;
      const ctx = canvas.getContext("2d");

      const natural = page.getViewport({ scale: 1 });
      const fitScale = (containerWidth - 24) / natural.width;
      const scale = fitScale * zoomLevel;
      const viewport = page.getViewport({ scale });

      canvas.width = viewport.width;
      canvas.height = viewport.height;

      const task = page.render({ canvasContext: ctx, viewport });
      renderTaskRef.current = task;
      await task.promise;
      renderTaskRef.current = null;

      if (overlayRef.current) {
        overlayRef.current.style.width = `${viewport.width}px`;
        overlayRef.current.style.height = `${viewport.height}px`;
      }
    } catch (err) {
      if (err?.name === "RenderingCancelledException") return;
      if (err?.message?.includes("multiple render()")) return;
      setError(err.message);
    }
  }, [pdfDoc, currentPage, totalPages, containerWidth, zoomLevel]);

  useEffect(() => { renderPage(); }, [renderPage]);

  if (loading) return <div style={styles.center}>Loading PDF...</div>;
  if (error) return (
    <div style={styles.center}>
      <span>⚠ {error}</span>
      <button onClick={() => setError(null)} style={styles.btn}>Retry</button>
    </div>
  );

  const pageHighlights = highlights.filter((h) => !h.page || h.page === currentPage);
  const zoomPct = Math.round(zoomLevel * 100);

  return (
    <div style={styles.root}>
      {/* Toolbar */}
      <div style={styles.toolbar}>
        <button onClick={() => onPageChange(currentPage - 1)} disabled={currentPage <= 1} style={styles.btn}>←</button>
        <input
          type="number" min={1} max={totalPages} value={currentPage}
          onChange={(e) => { const v = parseInt(e.target.value, 10); if (!isNaN(v)) onPageChange(v); }}
          onKeyDown={(e) => { if (e.key === "Enter") e.target.blur(); }}
          style={styles.pageInput}
        />
        <span style={styles.label}>/ {totalPages}</span>
        <button onClick={() => onPageChange(currentPage + 1)} disabled={currentPage >= totalPages} style={styles.btn}>→</button>
        <span style={styles.sep}>|</span>
        <button onClick={() => setZoomLevel((z) => Math.max(0.5, z - 0.25))} style={styles.btn}>−</button>
        <span style={styles.label}>{zoomPct}%</span>
        <button onClick={() => setZoomLevel((z) => Math.min(3, z + 0.25))} style={styles.btn}>+</button>
        <button onClick={() => setZoomLevel(1.0)} style={styles.btn} title="Fit width">⊡</button>
      </div>

      {/* Canvas area */}
      <div ref={containerRef} style={styles.canvasArea}>
        <canvas ref={canvasRef} style={styles.canvas} />
        <div ref={overlayRef} style={styles.overlay}>
          {pageHighlights.map((h, i) => (
            <div key={i} style={{
              position: "absolute",
              left: `${(h.x || 0) * 100}%`, top: `${(h.y || 0) * 100}%`,
              width: `${(h.width || 0.1) * 100}%`, height: `${(h.height || 0.02) * 100}%`,
              backgroundColor: "rgba(52,152,219,0.2)", border: "2px solid rgba(52,152,219,0.8)",
              borderRadius: "2px", cursor: "pointer",
            }}
              onMouseEnter={() => setHoveredHighlight(h)}
              onMouseLeave={() => setHoveredHighlight(null)}
            >
              {hoveredHighlight === h && <div style={styles.tooltip}>{h.fieldName}</div>}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

const styles = {
  root: { display: "flex", flexDirection: "column", height: "100%", overflow: "hidden", backgroundColor: "#f8f8f8" },
  toolbar: { display: "flex", alignItems: "center", gap: 6, padding: "6px 10px", borderBottom: "1px solid #eee", backgroundColor: "#fff", flexShrink: 0 },
  btn: { padding: "4px 8px", border: "1px solid #ddd", borderRadius: 4, background: "transparent", cursor: "pointer", fontSize: 13 },
  label: { fontSize: 12, color: "#666" },
  sep: { color: "#ddd", margin: "0 4px" },
  pageInput: { width: 40, padding: "3px 4px", border: "1px solid #ddd", borderRadius: 4, fontSize: 13, textAlign: "center" },
  canvasArea: { flex: 1, overflow: "auto", padding: 12, minHeight: 0 },
  canvas: { display: "block", boxShadow: "0 2px 8px rgba(0,0,0,0.1)" },
  overlay: { position: "absolute", top: 12, left: 12, pointerEvents: "none" },
  tooltip: { position: "absolute", top: -24, left: 0, backgroundColor: "#2c3e50", color: "#fff", padding: "2px 6px", borderRadius: 3, fontSize: 11, whiteSpace: "nowrap", pointerEvents: "none" },
  center: { display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: 32, gap: 8, color: "#999" },
};
