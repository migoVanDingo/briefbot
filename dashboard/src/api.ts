import { auth } from "./firebase";

const BASE = import.meta.env.VITE_API_BASE || "http://localhost:8080";

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

export interface Me {
  user: { id: number; email: string; name: string; role: string; capabilities: string[] };
  settings: { email_enabled: boolean; digest_limit: number };
  // Per-user UI state persisted server-side (0018), not localStorage.
  preferences: { theme: "light" | "dark" | null; accent: string | null };
  flags: string[];
  subscriptions: string[];
  onboarded: boolean;
  greeting: string;
}

export interface Topic {
  slug: string;
  name: string;
  description: string;
  subscribed: boolean;
  // Admin-only cadence context (present when the caller is an admin).
  discover_interval_min?: number | null;
  collect_interval_min?: number | null;
  last_discovered_at?: string | null;
}

export interface Item {
  item_id: string;
  title: string;
  url: string | null;
  canonical_url: string | null;
  source_name: string;
  published_at: string | null;
  fetched_at: string;
  summary: string | null;
  score: number;
}

export interface Story extends Item {
  feedback_vote: number | null;
}

export interface StoryFilters {
  search?: string;
  source?: string;
  topic?: string;
  from?: string;
  to?: string;
  order?: "asc" | "desc";
  limit?: number;
}

export interface Trending {
  label: string;
  trend_score: number;
  item_count: number;
  representative_title: string | null;
  representative_url: string | null;
}

export interface BriefSource {
  title: string;
  url: string | null;
  source_name: string;
  item_id?: string | null;
}

export interface Brief {
  topic_slug: string;
  topic_name: string;
  date: string;
  title: string;
  summary: string;
  trending: Trending[];
  sources: BriefSource[];
}

export interface TopicTab {
  slug: string;
  name: string;
}

// One calendar day in the Headlines date rail: the topic's brief for that day,
// or null if none was generated.
export interface BriefDay {
  date: string;
  brief: Brief | null;
}

export interface Folder {
  id: string;
  name: string;
  count: number;
}

export interface Favorite {
  id: string;
  item_id: string | null;
  title: string;
  url: string;
}

export interface ConversationMeta {
  id: string;
  title: string | null;
  message_count: number | null;
  created_at?: string;
  updated_at?: string;
}

export interface ToolCall {
  name: string;
  summary: string;
}

export interface TopicProgress {
  slug: string;
  name?: string;
  stage: string | null;
  failed?: boolean;
}

export interface ChatMessage {
  id?: string;
  role: "user" | "assistant";
  content: string;
  tool_calls?: ToolCall[];
  // Live topic-provisioning pipelines (one per topic) when this turn ran
  // create_topic — possibly several in a row (e.g. "sports, crypto, world news").
  topics?: TopicProgress[];
}

export interface UsageStats {
  interactions: number;
  tokens_used: number;
  limit: number;
  window_s: number;
  resets_in: number;
  enabled: boolean;
  blocked: boolean;
}

export interface Settings {
  email_enabled: boolean;
  digest_limit: number;
}

export interface Source {
  id: number;
  name: string;
  url: string;
  type: string;
  status: string;
  collect_interval_min?: number | null;
  last_collected_at?: string | null;
}

export interface DiscoverStats {
  queries: number;
  results: number;
  homepages: number;
  candidates: number;
  errors: number;
  added: string[];
}

export interface CollectStats {
  sources: number;
  feeds: number;
  items: number;
  new: number;
  not_modified: number;
  errors: number;
}

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
  topics: () => req<{ topics: Topic[] }>("/api/topics").then((d) => d.topics),
  createTopic: (body: { slug: string; name?: string; description?: string }) =>
    req<{ ok: boolean; slug: string; existed: boolean }>("/api/topics", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  provisionTopic: (
    slug: string,
    onEvent: (ev: Record<string, unknown>) => void,
    signal?: AbortSignal,
  ) => streamSSE(`/api/topics/${slug}/provision`, {}, onEvent, signal),
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
  sources: (slug: string, status: "active" | "candidate") =>
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
  briefs: () => req<{ briefs: Brief[]; topics: TopicTab[] }>("/api/briefs"),
  topicBriefs: (slug: string) =>
    req<{ days: BriefDay[] }>(`/api/topics/${slug}/briefs`).then((d) => d.days),
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
