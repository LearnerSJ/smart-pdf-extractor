import { useState, useEffect, useCallback } from "react";

const API_KEY = "demo-key";

/**
 * Shared API fetch hook with auth header and envelope unwrapping.
 *
 * @param {string} path - API path (e.g. "/v1/jobs/123")
 * @param {object} options - { skip: boolean, pollInterval: number|null }
 * @returns {{ data, loading, error, refetch }}
 */
export function useApi(path, options = {}) {
  const { skip = false, pollInterval = null } = options;
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(!skip);
  const [error, setError] = useState(null);

  const fetchData = useCallback(async () => {
    if (!path) return;
    try {
      setLoading(true);
      const res = await fetch(path, {
        headers: { Authorization: `Bearer ${API_KEY}` },
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${res.status}`);
      }

      const json = await res.json();
      // Unwrap envelope if present
      const unwrapped = json.data !== undefined ? json.data : json;
      setData(unwrapped);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    if (skip) return;
    fetchData();

    if (pollInterval && pollInterval > 0) {
      const interval = setInterval(fetchData, pollInterval);
      return () => clearInterval(interval);
    }
  }, [fetchData, skip, pollInterval]);

  return { data, loading, error, refetch: fetchData };
}

/**
 * POST helper with auth header.
 */
export async function apiPost(path, body, isFormData = false) {
  const headers = { Authorization: `Bearer ${API_KEY}` };
  if (!isFormData) {
    headers["Content-Type"] = "application/json";
  }

  const res = await fetch(path, {
    method: "POST",
    headers,
    body: isFormData ? body : JSON.stringify(body),
  });

  const json = await res.json().catch(() => ({}));

  if (!res.ok) {
    throw new Error(json.detail || `HTTP ${res.status}`);
  }

  return json.data !== undefined ? json.data : json;
}
