import { auth } from "./firebase";

const BASE = import.meta.env.VITE_API_BASE || "http://localhost:8080";
// Exposed so <img> tags can build absolute URLs for the public image route (0024).
export const API_BASE = BASE;

// Prefer FastAPI's `{detail: ...}` for a clean toast (e.g. a moderation reason).
async function errMessage(res: Response): Promise<string> {
  const body = await res.text().catch(() => "");
  try {
    const j = JSON.parse(body);
    if (j && j.detail) return String(j.detail);
  } catch {
    /* not JSON */
  }
  return body || `${res.status}`;
}

// bbv2 auth (0019): the dashboard authenticates with an HttpOnly session cookie,
// not a Bearer token. We exchange the Firebase ID token once (see `api.exchange`)
// and thereafter send `credentials: "include"`. When the short-lived access token
// has expired the API returns 401; we transparently hit /api/auth/session to
// refresh (single-flight so concurrent requests share one refresh) and retry once.
let refreshing: Promise<boolean> | null = null;
function refreshSession(): Promise<boolean> {
  if (!refreshing) {
    refreshing = fetch(`${BASE}/api/auth/session`, { credentials: "include" })
      .then((r) => r.ok)
      .catch(() => false)
      .finally(() => {
        refreshing = null;
      });
  }
  return refreshing;
}

async function req<T>(path: string, opts: RequestInit = {}, retry = true): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...opts,
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
  });
  if (res.status === 401 && retry && (await refreshSession())) {
    return req<T>(path, opts, false);
  }
  if (!res.ok) throw new Error(await errMessage(res));
  return (res.status === 204 ? null : await res.json()) as T;
}

// Shared SSE reader: POSTs a body and invokes onEvent for each `data:` event.
// Used for both chat streaming and topic provisioning.
async function streamSSE(
  path: string,
  body: unknown,
  onEvent: (ev: Record<string, unknown>) => void,
  signal?: AbortSignal,
  retry = true,
): Promise<void> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
    signal,
  });
  if (res.status === 401 && retry && (await refreshSession())) {
    return streamSSE(path, body, onEvent, signal, false);
  }
  if (!res.ok || !res.body) throw new Error(await errMessage(res));
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    if (signal?.aborted) break; // component unmounted — stop reading
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      const line = chunk.split("\n").find((l) => l.startsWith("data:"));
      if (line) {
        try {
          onEvent(JSON.parse(line.slice(5).trim()));
        } catch {
          /* ignore malformed event */
        }
      }
    }
  }
}

export * from "./api.types";

// Types used by the client below are also imported locally (noUnusedLocals).
import type {
  Brief, BriefDay, ChatMessage, CollectStats, ConversationMeta, DiscoverStats,
  DiscoveryRun, Favorite, Folder, Item, LlmMetrics, Me, PlacementDecision, Profile,
  ProvisionRun, ScheduleDefaults, SchedulePatch, Settings, Source, Story,
  StoryFilters, Topic, TopicSchedule, TopicTab, UsageStats, UserDetail, UserMetrics,
} from "./api.types";

export const api = {
  // Trade the current Firebase ID token for a bbv2 session cookie (0019). Called
  // once after sign-in, before any other API call.
  exchange: async () => {
    const user = auth.currentUser;
    if (!user) throw new Error("not signed in");
    const token = await user.getIdToken();
    const res = await fetch(`${BASE}/api/auth/exchange`, {
      method: "POST",
      credentials: "include",
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) throw new Error(await errMessage(res));
    return res.json();
  },
  // Revoke the bbv2 session server-side; the caller then signs out of Firebase.
  logout: () =>
    fetch(`${BASE}/api/auth/logout`, { method: "POST", credentials: "include" }).catch(
      () => undefined,
    ),
  me: () => req<Me>("/api/me"),
  usage: () => req<UsageStats>("/api/usage"),
  markOnboarded: () => req("/api/me/onboarded", { method: "POST" }),
  // Server-persisted UI state (0018).
  patchPreferences: (body: { theme?: string; accent?: string }) =>
    req("/api/preferences", { method: "PATCH", body: JSON.stringify(body) }),
  setFlag: (flag: string) =>
    req(`/api/flags/${encodeURIComponent(flag)}`, { method: "PUT" }),
  clearFlag: (flag: string) =>
    req(`/api/flags/${encodeURIComponent(flag)}`, { method: "DELETE" }),
  topicRundown: (slug: string) =>
    req<{ rundown: Brief | null; reason?: string }>(
      `/api/topics/${slug}/rundown`,
      { method: "POST" },
    ),
  setTopicCadence: (
    slug: string,
    body: { discover_interval_min?: number | null; collect_interval_min?: number | null },
  ) =>
    req(`/api/topics/${slug}/cadence`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  setSourceCadence: (id: number, collect_interval_min: number | null) =>
    req(`/api/sources/${id}/cadence`, {
      method: "PATCH",
      body: JSON.stringify({ collect_interval_min }),
    }),
  // Admin scheduling + caps (0020)
  adminSchedule: () =>
    req<{ defaults: ScheduleDefaults; topics: TopicSchedule[] }>("/api/admin/schedule"),
  setTopicSchedule: (slug: string, body: SchedulePatch) =>
    req(`/api/topics/${slug}/schedule`, { method: "PATCH", body: JSON.stringify(body) }),
  resetTopicSchedule: (slug: string) =>
    req(`/api/topics/${slug}/schedule/reset`, { method: "POST" }),
  resetAllSchedules: () =>
    req<{ reset: number }>("/api/admin/schedule/reset", { method: "POST" }),
  // Admin metrics (0021)
  adminLlmMetrics: (range = "30d") =>
    req<LlmMetrics>(`/api/admin/metrics/llm?range=${encodeURIComponent(range)}`),
  adminUserMetrics: () => req<UserMetrics>("/api/admin/metrics/users"),
  adminUserDetail: (id: number, range = "30d") =>
    req<UserDetail>(
      `/api/admin/metrics/users/${id}?range=${encodeURIComponent(range)}`,
    ),
  profile: () => req<Profile>("/api/profile"),
  generateAvatar: (prompt: string) =>
    req<{ ok: boolean; status: string }>("/api/profile/avatar", {
      method: "POST",
      body: JSON.stringify({ prompt }),
    }),
  resetAvatar: () => req<{ ok: boolean }>("/api/profile/avatar", { method: "DELETE" }),
  // Public avatar URL (identicon by default, generated image when ready). Cache-bust
  // param lets the UI force a refetch after a generation completes.
  avatarUrl: (userId: number, v?: string | number) =>
    `${BASE}/api/avatar/${userId}${v != null ? `?v=${encodeURIComponent(String(v))}` : ""}`,
  topics: () => req<{ topics: Topic[] }>("/api/topics").then((d) => d.topics),
  createTopic: (body: { slug: string; name?: string; description?: string }) =>
    req<{ ok: boolean; slug: string; existed: boolean }>("/api/topics", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  // Start a background provision run (0023) → returns its id; poll `provisioning`.
  provisionTopic: (slug: string) =>
    req<{ run_id: string }>(`/api/topics/${slug}/provision`, { method: "POST" }),
  // The caller's active + just-finished runs (optionally filtered to a conversation).
  provisioning: (conversation?: string) =>
    req<{ runs: ProvisionRun[] }>(
      `/api/provisioning${conversation ? `?conversation=${encodeURIComponent(conversation)}` : ""}`,
    ).then((d) => d.runs),
  // On-demand source discovery (0030): poll the user's search runs + commit one.
  discoveries: (conversation?: string) =>
    req<{ runs: DiscoveryRun[] }>(
      `/api/discoveries${conversation ? `?conversation=${encodeURIComponent(conversation)}` : ""}`,
    ).then((d) => d.runs),
  commitDiscovery: (runId: string) =>
    req<PlacementDecision>(`/api/discoveries/${runId}/commit`, { method: "POST" }),
  subscribe: (slug: string) =>
    req(`/api/topics/${slug}/subscribe`, { method: "POST" }),
  unsubscribe: (slug: string) =>
    req(`/api/topics/${slug}/subscribe`, { method: "DELETE" }),
  headlines: (limit = 50) =>
    req<{ items: Item[] }>(`/api/headlines?limit=${limit}`).then((d) => d.items),
  topicItems: (slug: string, limit = 50) =>
    req<{ items: Item[] }>(`/api/topics/${slug}/items?limit=${limit}`).then(
      (d) => d.items,
    ),
  getSettings: () => req<Settings>("/api/settings"),
  putSettings: (body: Partial<Settings>) =>
    req("/api/settings", { method: "PUT", body: JSON.stringify(body) }),
  discover: (slug: string) =>
    req<DiscoverStats>(`/api/topics/${slug}/discover`, { method: "POST" }),
  collect: (slug: string) =>
    req<CollectStats>(`/api/topics/${slug}/collect`, { method: "POST" }),
  sources: (slug: string, status: "active" | "candidate" | "managed") =>
    req<{ sources: Source[] }>(
      `/api/topics/${slug}/sources?status=${status}`,
    ).then((d) => d.sources),
  approve: (id: number) =>
    req(`/api/sources/${id}/approve`, { method: "POST" }),
  approveAll: (slug: string) =>
    req<{ ok: boolean; approved: number }>(
      `/api/topics/${slug}/sources/approve-all`,
      { method: "POST" },
    ),
  reject: (id: number) => req(`/api/sources/${id}/reject`, { method: "POST" }),
  disableSource: (id: number) => req(`/api/sources/${id}/disable`, { method: "POST" }),
  enableSource: (id: number) => req(`/api/sources/${id}/enable`, { method: "POST" }),
  deleteSource: (id: number) => req(`/api/sources/${id}`, { method: "DELETE" }),
  storySources: () =>
    req<{ sources: string[] }>("/api/stories/sources").then((d) => d.sources),
  queryStories: (filters: StoryFilters = {}) =>
    req<{ items: Story[] }>("/api/stories", {
      method: "POST",
      body: JSON.stringify(filters),
    }).then((d) => d.items),
  setFeedback: (item_id: string, vote: number) =>
    req("/api/stories/feedback", {
      method: "POST",
      body: JSON.stringify({ item_id, vote }),
    }),
  // Fire-and-forget click beacon (0021) — never blocks navigation, ignores errors.
  recordClick: (item_id: string) => {
    try {
      fetch(`${BASE}/api/stories/click`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ item_id }),
        keepalive: true,
      }).catch(() => {});
    } catch {
      /* ignore */
    }
  },
  briefs: () => req<{ briefs: Brief[]; topics: TopicTab[] }>("/api/briefs"),
  topicBriefs: (slug: string) =>
    req<{ days: BriefDay[] }>(`/api/topics/${slug}/briefs`).then((d) => d.days),
  // The stories behind a day's brief (its persisted sources), not a date query —
  // so a next-day-labelled brief still shows the items it was built from.
  briefStories: (slug: string, date: string) =>
    req<{ items: Story[] }>(
      `/api/topics/${slug}/briefs/${encodeURIComponent(date)}/stories`,
    ).then((d) => d.items),
  generateBrief: (slug: string) =>
    req<{ ok: boolean; title: string }>(`/api/topics/${slug}/brief`, {
      method: "POST",
    }),
  favoriteFolders: () =>
    req<{ folders: Folder[] }>("/api/favorites/folders").then((d) => d.folders),
  createFolder: (name: string) =>
    req<{ id: string; name: string }>("/api/favorites/folders", {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  favoriteItems: (folderId: string) =>
    req<{ folder: { id: string; name: string }; items: Favorite[] }>(
      `/api/favorites/items?folder_id=${encodeURIComponent(folderId)}`,
    ),
  searchFavorites: (q: string) =>
    req<{ items: Favorite[] }>(
      `/api/favorites/search?q=${encodeURIComponent(q)}`,
    ).then((d) => d.items),
  addFavorite: (fav: {
    title: string;
    url: string;
    item_id?: string | null;
    folder_id?: string;
  }) =>
    req<{ id: string; folder_id: string }>("/api/favorites/items", {
      method: "POST",
      body: JSON.stringify(fav),
    }),
  removeFavorite: (id: string) =>
    req(`/api/favorites/items?favorite_id=${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
  listConversations: () =>
    req<{ conversations: ConversationMeta[] }>("/api/conversations").then(
      (d) => d.conversations,
    ),
  createConversation: () =>
    req<{ id: string }>("/api/conversations", { method: "POST" }),
  getConversation: (id: string) =>
    req<{ id: string; title: string | null; messages: ChatMessage[] }>(
      `/api/conversations/${id}`,
    ),
  renameConversation: (id: string, title: string) =>
    req(`/api/conversations/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    }),
  deleteConversation: (id: string) =>
    req(`/api/conversations/${id}`, { method: "DELETE" }),
  // SSE: stream a chat turn. Calls onEvent for each {type, ...} server event.
  streamMessage: (
    id: string,
    content: string,
    onEvent: (ev: Record<string, unknown>) => void,
    signal?: AbortSignal,
  ) => streamSSE(`/api/conversations/${id}/messages`, { content }, onEvent, signal),
};
