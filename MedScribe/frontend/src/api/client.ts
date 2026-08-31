/**
 * Thin fetch wrapper used by every API call in the app.
 *
 * Two things every single request needs, so they live here instead of
 * being repeated at every call site:
 *
 * 1. credentials: "include" -- REQUIRED for the httponly session cookie
 *    (medstt_session) to be sent with requests and accepted from
 *    responses. Without this, the browser will not attach or store the
 *    cookie for cross-origin requests (localhost:5173 -> localhost:8000
 *    counts as cross-origin even on the same machine, since the port
 *    differs), and every request would look unauthenticated even right
 *    after a successful login.
 *
 * 2. Consistent error handling -- the backend returns errors as
 *    { "detail": "..." } (FastAPI's default HTTPException shape). We
 *    normalize that into a thrown ApiError so calling code can just
 *    catch one error type instead of re-parsing response bodies
 *    everywhere.
 */

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
    this.name = "ApiError";
  }
}

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE" | "PUT";
  body?: unknown;
  params?: Record<string, string | number | boolean | undefined>;
}

export async function apiRequest<T>(
  path: string,
  options: RequestOptions = {}
): Promise<T> {
  const { method = "GET", body, params } = options;

  let url = `${API_BASE_URL}${path}`;

  if (params) {
    const searchParams = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined) {
        searchParams.append(key, String(value));
      }
    }
    const queryString = searchParams.toString();
    if (queryString) {
      url += `?${queryString}`;
    }
  }

  const response = await fetch(url, {
    method,
    credentials: "include", // send/receive the httponly session cookie
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });

  // 204 No Content -- some endpoints (if any later) won't return a body
  if (response.status === 204) {
    return undefined as T;
  }

  let data: unknown;
  try {
    data = await response.json();
  } catch {
    data = null;
  }

  if (!response.ok) {
    const detail =
      data && typeof data === "object" && "detail" in data
        ? String((data as { detail: unknown }).detail)
        : `Request failed with status ${response.status}`;
    throw new ApiError(response.status, detail);
  }

  return data as T;
}