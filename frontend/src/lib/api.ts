const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8001";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

/**
 * Thin fetch wrapper for the TrailMind API. Auth is a bearer token in the
 * Authorization header (see app/security.py's get_current_user) — never a cookie —
 * so this works the same whether the frontend and API share an origin or not.
 */
export async function apiFetch<T>(
  path: string,
  options: { method?: string; body?: unknown; token?: string | null } = {},
): Promise<T> {
  const { method = "GET", body, token } = options;
  const isFormData = body instanceof FormData;
  const headers: Record<string, string> = {};
  // A FormData body (file upload) sets its own multipart Content-Type with a
  // boundary — the browser derives that from the FormData instance itself, so we
  // must NOT set Content-Type ourselves or the boundary gets lost.
  if (body !== undefined && !isFormData) headers["Content-Type"] = "application/json";
  if (token) headers.Authorization = `Bearer ${token}`;

  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : isFormData ? body : JSON.stringify(body),
  });

  if (response.status === 204) return undefined as T;

  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const message =
      (payload && typeof payload.detail === "string" && payload.detail) ||
      `Request failed (${response.status})`;
    throw new ApiError(message, response.status);
  }
  return payload as T;
}
