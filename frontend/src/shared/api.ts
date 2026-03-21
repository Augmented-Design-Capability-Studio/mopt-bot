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
  gemini_key_configured: boolean;
};

/** Text for the problem-config editor: empty string when there is nothing to show. */
export function sessionPanelToConfigText(panel: Session["panel_config"]): string {
  if (panel == null) return "";
  if (typeof panel !== "object" || Array.isArray(panel)) return "";
  if (Object.keys(panel as object).length === 0) return "";
  return JSON.stringify(panel, null, 2);
}

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

function isLooseMessage(x: unknown): x is Record<string, unknown> {
  if (x === null || typeof x !== "object") return false;
  const o = x as Record<string, unknown>;
  return typeof o.id === "number" && typeof o.role === "string" && typeof o.content === "string";
}

function coerceMessage(o: Record<string, unknown>): Message {
  return {
    id: o.id as number,
    created_at: typeof o.created_at === "string" ? o.created_at : "",
    role: o.role as string,
    content: o.content as string,
    visible_to_participant: typeof o.visible_to_participant === "boolean" ? o.visible_to_participant : true,
    kind: typeof o.kind === "string" ? o.kind : "chat",
  };
}

/**
 * POST /sessions/:id/messages should return `{ messages, panel_config? }`.
 * Also accepts a top-level message array (legacy / misconfigured proxies).
 * If the server returns HTML (e.g. SPA fallback when VITE_API_BASE is unset), `parseJson` yields a string — explain that clearly.
 */
export function normalizePostMessagesResponse(data: unknown): PostMessagesResponse {
  if (data == null) {
    throw new Error(
      "Empty response when sending a message. For production builds served separately from the API, set VITE_API_BASE (see frontend/.env.example).",
    );
  }
  if (typeof data === "string") {
    const t = data.trimStart().toLowerCase();
    if (t.startsWith("<!doctype") || t.startsWith("<html") || t.startsWith("<!")) {
      throw new Error(
        "The server returned a web page instead of JSON for the chat API. Set VITE_API_BASE to your API origin when you build or host the frontend away from the backend (see frontend/.env.example).",
      );
    }
    throw new Error(
      "Invalid message response (body is not JSON). Check the API URL and that the backend is running.",
    );
  }
  if (Array.isArray(data)) {
    if (data.length > 0 && !data.every(isLooseMessage)) {
      throw new Error(
        "Invalid message response (expected an object with a messages array or a JSON array of message objects).",
      );
    }
    return {
      messages: (data as Record<string, unknown>[]).map(coerceMessage),
      panel_config: null,
    };
  }
  if (typeof data === "object" && Array.isArray((data as PostMessagesResponse).messages)) {
    const o = data as PostMessagesResponse;
    return {
      messages: o.messages,
      panel_config: o.panel_config ?? null,
    };
  }
  throw new Error(
    "Invalid message response (expected JSON with a messages array). Check the API URL and that the backend is running.",
  );
}

/** @deprecated Use normalizePostMessagesResponse */
export const assertPostMessagesResponse = normalizePostMessagesResponse;

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
