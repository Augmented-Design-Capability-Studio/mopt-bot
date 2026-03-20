function apiBase(): string {
  if (import.meta.env.VITE_API_BASE) return import.meta.env.VITE_API_BASE.replace(/\/$/, "");
  if (import.meta.env.DEV) return "/api";
  return "";
}

export class ApiError extends Error {
  status: number;
  body: string;
  constructor(status: number, body: string) {
    super(`HTTP ${status}`);
    this.status = status;
    this.body = body;
  }
}

async function parseJson(res: Response): Promise<unknown> {
  const text = await res.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

export async function apiFetch<T>(
  path: string,
  token: string,
  init: RequestInit = {},
): Promise<T> {
  const url = `${apiBase()}${path.startsWith("/") ? path : `/${path}`}`;
  const headers: Record<string, string> = {
    Authorization: `Bearer ${token}`,
    ...(init.headers as Record<string, string> | undefined),
  };
  if (init.body !== undefined && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  const res = await fetch(url, { ...init, headers });
  const data = await parseJson(res);
  if (!res.ok) {
    const msg = typeof data === "object" && data && "detail" in data
      ? String((data as { detail: unknown }).detail)
      : String(data);
    throw new ApiError(res.status, msg);
  }
  return data as T;
}

export type Session = {
  id: string;
  created_at: string;
  updated_at: string;
  workflow_mode: string;
  status: string;
  panel_config: Record<string, unknown> | null;
  optimization_allowed: boolean;
  gemini_model: string | null;
};

export type Message = {
  id: number;
  created_at: string;
  role: string;
  content: string;
  visible_to_participant: boolean;
  kind: string;
};

export type PostMessagesResponse = {
  messages: Message[];
  panel_config: Record<string, unknown> | null;
};

/** Avoid React crashes if the proxy returns HTML or an old array-shaped body. */
export function assertPostMessagesResponse(data: unknown): PostMessagesResponse {
  if (
    data === null ||
    typeof data !== "object" ||
    Array.isArray(data) ||
    !("messages" in data) ||
    !Array.isArray((data as PostMessagesResponse).messages)
  ) {
    throw new Error(
      "Invalid message response from server (expected JSON with a messages array). Check the API URL and that the backend is running.",
    );
  }
  const o = data as PostMessagesResponse;
  return {
    messages: o.messages,
    panel_config: o.panel_config ?? null,
  };
}

export type RunResult = {
  id: number;
  created_at: string;
  run_type: string;
  ok: boolean;
  cost: number | null;
  reference_cost: number | null;
  error_message: string | null;
  result: Record<string, unknown> | null;
};
