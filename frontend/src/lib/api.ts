export type ApiState<T> =
  | { status: "loading" }
  | { status: "ready"; data: T }
  | { status: "error"; message: string };

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8001";

export function setAccessToken(token: string): void {
  window.localStorage.setItem("xenovarients_access_token", token);
}

export function clearAccessToken(): void {
  window.localStorage.removeItem("xenovarients_access_token");
}

export async function fetchApi<T>(path: string, init?: RequestInit): Promise<T> {
  const token =
    typeof window === "undefined"
      ? undefined
      : window.localStorage.getItem("xenovarients_access_token");
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init?.headers,
    },
    credentials: "include",
  });
  if (!response.ok) {
    throw new Error(`Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export type RealtimeEvent = { id: string; type: string; data: unknown };

export function subscribeToEvents(
  onEvent: (event: RealtimeEvent) => void,
  onError?: () => void,
): () => void {
  const controller = new AbortController();
  const token = window.localStorage.getItem("xenovarients_access_token");
  void fetch(`${API_BASE}/api/v1/events/stream`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    signal: controller.signal,
  }).then(async (response) => {
    if (!response.ok || !response.body) throw new Error("Realtime stream unavailable.");
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (!controller.signal.aborted) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split("\n\n");
      buffer = frames.pop() ?? "";
      for (const frame of frames) {
        const line = frame.split("\n").find((item) => item.startsWith("data: "));
        if (!line) continue;
        try {
          onEvent(JSON.parse(line.slice(6)) as RealtimeEvent);
        } catch {
          onError?.();
        }
      }
    }
  }).catch(() => {
    if (!controller.signal.aborted) onError?.();
  });
  return () => controller.abort();
}
