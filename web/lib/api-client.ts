/**
 * Type-safe API client powered by openapi-fetch.
 *
 * All request/response types are auto-generated from the backend's
 * OpenAPI schema (web/lib/gen/openapi.d.ts). Zero hand-written type
 * definitions needed.
 *
 * API keys are stored as encrypted httpOnly cookies — the browser sends
 * them automatically; no client-side header injection needed.
 */
import createClient from "openapi-fetch";
import type { paths } from "./gen/openapi";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL !== undefined
    ? process.env.NEXT_PUBLIC_API_URL.replace(/\/+$/, "")
    : "http://localhost:8100";

const API_TOKEN = process.env.NEXT_PUBLIC_API_TOKEN || "";

export const api = createClient<paths>({
  baseUrl: API_URL,
  headers: API_TOKEN ? { Authorization: `Bearer ${API_TOKEN}` } : {},
  credentials: "include",
});

// Handle auth errors via middleware
api.use({
  async onResponse({ response }) {
    if (!response.ok) {
      let detail = `请求失败 (${response.status})`;
      try {
        const body = await response.clone().json();
        if (body?.detail) detail = body.detail;
      } catch {
        // ignore parse failure
      }
      console.error(`[api] ${response.status} ${response.url} → ${detail}`);
    }
    return response;
  },
});

/** Base URL for non-openapi-fetch uses (SSE EventSource, audio URLs). */
export function getApiUrl(): string {
  return API_URL;
}
