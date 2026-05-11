/**
 * localStorage-backed chat history. Keeps the last N turns so a refresh
 * doesn't lose context — no Supabase, no backend persistence.
 */
import type { ChatPayload, ChatTurn } from "./dispatch-types";

const KEY = "crl_chat_history_v1";
const MAX_TURNS = 50;

function safeUuid(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

export function loadHistory(): ChatTurn[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as ChatTurn[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function saveHistory(turns: ChatTurn[]): void {
  if (typeof window === "undefined") return;
  try {
    const trimmed = turns.slice(-MAX_TURNS);
    window.localStorage.setItem(KEY, JSON.stringify(trimmed));
  } catch {
    // localStorage full or disabled — silently no-op
  }
}

export function makeTurn(
  role: "user" | "assistant",
  content: string,
  payload: ChatPayload | null = null,
): ChatTurn {
  return {
    id: safeUuid(),
    role,
    content,
    payload,
    created_at: new Date().toISOString(),
  };
}

export function clearHistory(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    /* noop */
  }
}
