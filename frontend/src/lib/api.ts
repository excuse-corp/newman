export function getApiBase() {
  if (import.meta.env.VITE_API_BASE) {
    return import.meta.env.VITE_API_BASE;
  }
  return window.location.origin;
}

export function withApiCredentials(init?: RequestInit): RequestInit {
  return {
    credentials: "include",
    ...init,
  };
}

export async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, withApiCredentials(init));
  const text = await response.text();
  let payload: unknown = null;

  if (text) {
    try {
      payload = JSON.parse(text) as unknown;
    } catch {
      payload = null;
    }
  }

  if (!response.ok) {
    let message = `请求失败：${response.status}`;
    if (payload && typeof payload === "object" && payload !== null) {
      const nestedError =
        "error" in payload && payload.error && typeof payload.error === "object" ? payload.error : null;
      const detail =
        "detail" in payload
          ? payload.detail
          : "message" in payload
            ? payload.message
            : nestedError && "message" in nestedError
              ? nestedError.message
              : null;
      if (typeof detail === "string" && detail.trim()) {
        message = detail;
      }
    }
    throw new Error(message);
  }

  return payload as T;
}
