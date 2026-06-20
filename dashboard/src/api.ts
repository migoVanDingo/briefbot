import { auth } from "./firebase";

const BASE = import.meta.env.VITE_API_BASE || "http://localhost:8080";

async function req<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const user = auth.currentUser;
  const token = user ? await user.getIdToken() : null;
  const res = await fetch(`${BASE}${path}`, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(opts.headers || {}),
    },
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`${res.status} ${body}`.trim());
  }
  return (res.status === 204 ? null : await res.json()) as T;
}

export interface Me {
  user: { id: number; email: string; name: string; role: string };
  settings: { email_enabled: boolean; digest_limit: number };
  subscriptions: string[];
}

export interface Topic {
  slug: string;
  name: string;
  description: string;
  subscribed: boolean;
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

export interface ChatMessage {
  id?: string;
  role: "user" | "assistant";
  content: string;
  tool_calls?: ToolCall[];
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
  me: () => req<Me>("/api/me"),
  topics: () => req<{ topics: Topic[] }>("/api/topics").then((d) => d.topics),
  createTopic: (body: { slug: string; name?: string; description?: string }) =>
    req("/api/topics", { method: "POST", body: JSON.stringify(body) }),
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
  streamMessage: async (
    id: string,
    content: string,
    onEvent: (ev: Record<string, unknown>) => void,
  ): Promise<void> => {
    const user = auth.currentUser;
    const token = user ? await user.getIdToken() : null;
    const res = await fetch(`${BASE}/api/conversations/${id}/messages`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ content }),
    });
    if (!res.ok || !res.body) {
      throw new Error(`${res.status} ${await res.text().catch(() => "")}`.trim());
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    for (;;) {
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
  },
};
