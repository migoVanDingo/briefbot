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
  user: { id: number; email: string; name: string };
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

export interface Settings {
  email_enabled: boolean;
  digest_limit: number;
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
};
