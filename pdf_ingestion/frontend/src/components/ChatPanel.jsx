import React, { useState, useEffect, useRef, useCallback } from "react";
import { apiPost } from "../hooks/useApi";

/**
 * Document-scoped chat panel for reviewing extraction results and triggering re-extraction.
 *
 * Props:
 *   jobId        — the job identifier used for API calls and sessionStorage key
 *   filename     — original document filename shown in the welcome message
 *   onPendingSchema(pendingSchemaId) — called when a re-extraction produces a pending schema
 */
export default function ChatPanel({ jobId, filename, onPendingSchema }) {
  const storageKey = `chat_history_${jobId}`;

  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);

  const inputRef = useRef(null);
  const bottomRef = useRef(null);

  // ── On mount: restore from sessionStorage or push welcome message ──────────
  useEffect(() => {
    try {
      const stored = sessionStorage.getItem(storageKey);
      if (stored) {
        const parsed = JSON.parse(stored);
        if (Array.isArray(parsed) && parsed.length > 0) {
          setMessages(parsed);
          return;
        }
      }
    } catch {
      // ignore parse errors
    }
    const welcome = {
      role: "assistant",
      content: `I can help you review the extraction results for ${filename}. Describe any issues you see with the extracted fields or tables.`,
    };
    setMessages([welcome]);
  }, [jobId]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Persist messages to sessionStorage whenever they change ────────────────
  useEffect(() => {
    if (messages.length === 0) return;
    try {
      sessionStorage.setItem(storageKey, JSON.stringify(messages));
    } catch {
      // quota exceeded — silently ignore
    }
  }, [messages, storageKey]);

  // ── Auto-scroll to bottom when new messages arrive ─────────────────────────
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const buildHistory = useCallback(
    (currentMessages) =>
      currentMessages.map(({ role, content }) => ({ role, content })),
    []
  );

  // ── Send a message ─────────────────────────────────────────────────────────
  const handleSend = useCallback(async () => {
    const trimmed = input.trim();
    if (!trimmed || loading) return;

    const userMessage = { role: "user", content: trimmed };
    const nextMessages = [...messages, userMessage];
    setMessages(nextMessages);
    setInput("");
    setLoading(true);

    try {
      const history = buildHistory(messages);
      const response = await apiPost(`/v1/jobs/${jobId}/chat`, {
        message: trimmed,
        history,
      });
      const assistantMessage = {
        role: "assistant",
        content: response.reply,
        actionButtons: response.action_buttons ?? null,
      };
      setMessages((prev) => [...prev, assistantMessage]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `Sorry, something went wrong: ${err.message}` },
      ]);
    } finally {
      setLoading(false);
    }
  }, [input, loading, messages, jobId, buildHistory]);

  const handleKeyDown = useCallback(
    (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend]
  );

  // ── Action button handlers ─────────────────────────────────────────────────
  const handleReextractTable = useCallback(
    async (messageIndex, tableId) => {
      setLoading(true);
      try {
        const body = tableId != null ? { table_id: tableId } : {};
        const response = await apiPost(`/v1/jobs/${jobId}/reextract-table`, body);
        if (response.pending_schema_id) {
          onPendingSchema?.(response.pending_schema_id);
        }
        setMessages((prev) =>
          prev.map((msg, idx) =>
            idx === messageIndex ? { ...msg, actionButtons: null } : msg
          )
        );
        const warnings = response.validation_warnings?.length
          ? " Warnings: " + response.validation_warnings.join("; ")
          : "";
        setMessages((prev) => [
          ...prev,
          {
            role: "assistant",
            content: tableId
              ? `Re-extraction complete for table ${tableId}.${warnings}`
              : `Re-extraction complete for all tables.${warnings}`,
          },
        ]);
      } catch (err) {
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: `Re-extraction failed: ${err.message}` },
        ]);
      } finally {
        setLoading(false);
      }
    },
    [jobId, onPendingSchema]
  );

  const handleAcceptOutput = useCallback((messageIndex) => {
    setMessages((prev) =>
      prev.map((msg, idx) =>
        idx === messageIndex ? { ...msg, actionButtons: null } : msg
      )
    );
  }, []);

  const handleAskAnother = useCallback(() => {
    inputRef.current?.focus();
  }, []);

  const renderActionButton = useCallback(
    (btn, messageIndex) => {
      const { label, action, table_id } = btn;
      if (action === "reextract_table") {
        return (
          <button key={label} style={styles.actionBtn} disabled={loading}
            onClick={() => handleReextractTable(messageIndex, table_id)}>
            {label}
          </button>
        );
      }
      if (action === "reextract_all") {
        return (
          <button key={label} style={styles.actionBtn} disabled={loading}
            onClick={() => handleReextractTable(messageIndex, null)}>
            {label}
          </button>
        );
      }
      if (action === "accept") {
        return (
          <button key={label} style={{ ...styles.actionBtn, ...styles.actionBtnSecondary }}
            onClick={() => handleAcceptOutput(messageIndex)}>
            {label}
          </button>
        );
      }
      if (action === "ask_again") {
        return (
          <button key={label} style={{ ...styles.actionBtn, ...styles.actionBtnSecondary }}
            onClick={handleAskAnother}>
            {label}
          </button>
        );
      }
      return <button key={label} style={styles.actionBtn} disabled>{label}</button>;
    },
    [loading, handleReextractTable, handleAcceptOutput, handleAskAnother]
  );

  return (
    <div style={styles.container}>
      <div style={styles.messageList}>
        {messages.map((msg, idx) => {
          const isUser = msg.role === "user";
          return (
            <div key={idx} style={{ ...styles.messageRow, justifyContent: isUser ? "flex-end" : "flex-start" }}>
              <div style={styles.messageGroup}>
                <div style={{ ...styles.bubble, ...(isUser ? styles.bubbleUser : styles.bubbleAssistant) }}>
                  {msg.content}
                </div>
                {!isUser && msg.actionButtons && msg.actionButtons.length > 0 && (
                  <div style={styles.actionButtons}>
                    {msg.actionButtons.map((btn) => renderActionButton(btn, idx))}
                  </div>
                )}
              </div>
            </div>
          );
        })}
        {loading && (
          <div style={{ ...styles.messageRow, justifyContent: "flex-start" }}>
            <div style={{ ...styles.bubble, ...styles.bubbleAssistant }}>
              <span style={{ color: "var(--color-text-muted)" }}>Thinking…</span>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div style={styles.inputArea}>
        <input
          ref={inputRef}
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Describe an issue with the extracted data…"
          disabled={loading}
          style={{ ...styles.input, ...(loading ? styles.inputDisabled : {}) }}
        />
        <button
          onClick={handleSend}
          disabled={loading || !input.trim()}
          style={{ ...styles.sendBtn, opacity: loading || !input.trim() ? 0.5 : 1 }}
        >
          Send
        </button>
      </div>
    </div>
  );
}

const styles = {
  container: { display: "flex", flexDirection: "column", height: "100%", minHeight: 400, backgroundColor: "var(--color-surface)", borderRadius: "var(--border-radius)", overflow: "hidden" },
  messageList: { flex: 1, overflowY: "auto", padding: "var(--space-4)", display: "flex", flexDirection: "column", gap: "var(--space-3)" },
  messageRow: { display: "flex", width: "100%" },
  messageGroup: { display: "flex", flexDirection: "column", maxWidth: "72%", gap: "var(--space-2)" },
  bubble: { padding: "var(--space-3) var(--space-4)", borderRadius: "var(--border-radius)", fontSize: "var(--text-md)", lineHeight: 1.5, wordBreak: "break-word" },
  bubbleUser: { backgroundColor: "var(--color-info)", color: "#fff", borderBottomRightRadius: 2, alignSelf: "flex-end" },
  bubbleAssistant: { backgroundColor: "#fff", color: "var(--color-text-primary)", border: "1px solid var(--color-border-light)", borderBottomLeftRadius: 2 },
  actionButtons: { display: "flex", flexWrap: "wrap", gap: "var(--space-2)", paddingLeft: "var(--space-1)" },
  actionBtn: { padding: "var(--space-1) var(--space-3)", backgroundColor: "var(--color-info)", color: "#fff", fontSize: "var(--text-sm)", fontWeight: 600, borderRadius: "var(--border-radius-sm)", cursor: "pointer", border: "none" },
  actionBtnSecondary: { backgroundColor: "transparent", color: "var(--color-text-secondary)", border: "1px solid var(--color-border)" },
  inputArea: { display: "flex", gap: "var(--space-2)", padding: "var(--space-3) var(--space-4)", borderTop: "1px solid var(--color-border-light)", backgroundColor: "var(--color-surface)" },
  input: { flex: 1, padding: "var(--space-2) var(--space-3)", border: "1px solid var(--color-border)", borderRadius: "var(--border-radius-sm)", fontSize: "var(--text-md)", fontFamily: "inherit", backgroundColor: "#fff", color: "var(--color-text-primary)", outline: "none" },
  inputDisabled: { backgroundColor: "var(--color-surface)", cursor: "not-allowed" },
  sendBtn: { padding: "var(--space-2) var(--space-5)", backgroundColor: "var(--color-info)", color: "#fff", fontWeight: 600, fontSize: "var(--text-md)", borderRadius: "var(--border-radius-sm)", border: "none", cursor: "pointer", whiteSpace: "nowrap" },
};
