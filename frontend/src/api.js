// Thin fetch wrapper: same-origin /api/v1, cookie auth, JSON in/out, throws on non-2xx.
export class ApiError extends Error {
  constructor(status, body) {
    super(body?.error ?? `Request failed (${status})`);
    this.status = status;
    this.details = body?.details;
  }
}

export async function api(method, path, body) {
  const res = await fetch(`/api/v1${path}`, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    credentials: 'same-origin',
  });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { if (res.ok) throw new ApiError(res.status, { error: 'Invalid server response' }); }
  if (!res.ok) throw new ApiError(res.status, data);
  return data;
}

// Resource URLs are faculty-authored: only allow web links, never javascript:/data:.
export const safeUrl = (url) => (/^https?:\/\//i.test(url ?? '') ? url : undefined);
