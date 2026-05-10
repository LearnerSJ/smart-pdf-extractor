import { useState, useCallback, useEffect, useRef } from "react";
import { useAuth } from "./AuthContext.jsx";

/**
 * useFetch — custom hook for API calls with automatic JWT injection.
 *
 * - Automatically injects Authorization: Bearer <token> header
 * - Handles 401 responses by triggering logout
 * - Returns { data, loading, error, refetch }
 *
 * @param {string} url — API endpoint URL
 * @param {object} [options] — fetch options (method, body, etc.)
 * @param {boolean} [options.manual] — if true, don't fetch on mount
 */
export function useFetch(url, options = {}) {
  const { token, logout } = useAuth();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(!options.manual);
  const [error, setError] = useState(null);
  const abortRef = useRef(null);

  const fetchData = useCallback(
    async (overrideUrl) => {
      const targetUrl = overrideUrl || url;
      if (!targetUrl) return;

      // Abort any in-flight request
      if (abortRef.current) {
        abortRef.current.abort();
      }
      const controller = new AbortController();
      abortRef.current = controller;

      setLoading(true);
      setError(null);

      try {
        const headers = {
          "Content-Type": "application/json",
          ...(options.headers || {}),
        };

        if (token) {
          headers["Authorization"] = `Bearer ${token}`;
        }

        const response = await fetch(targetUrl, {
          method: options.method || "GET",
          headers,
          body: options.body ? JSON.stringify(options.body) : undefined,
          signal: controller.signal,
        });

        if (response.status === 401) {
          logout();
          setError("Session expired. Please log in again.");
          return;
        }

        if (!response.ok) {
          const body = await response.json().catch(() => ({}));
          throw new Error(
            body.detail || body.message || `Request failed (${response.status})`
          );
        }

        const result = await response.json();
        setData(result);
      } catch (err) {
        if (err.name !== "AbortError") {
          setError(err.message);
        }
      } finally {
        setLoading(false);
      }
    },
    [url, token, logout, options.method, options.body, options.headers]
  );

  useEffect(() => {
    if (!options.manual) {
      fetchData();
    }
    return () => {
      if (abortRef.current) {
        abortRef.current.abort();
      }
    };
  }, [fetchData, options.manual]);

  return { data, loading, error, refetch: fetchData };
}
