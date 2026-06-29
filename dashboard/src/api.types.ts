// Shared TypeScript types for the bbv2 API client.
// Split out of api.ts to keep that file under the 600-line cap (mirrors the
// backend dashboard_api split). Re-exported from api.ts for compatibility.

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
  is_saved: boolean;
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
  // Per-topic Grok Imagine header image (0024).
  image_status: "none" | "pending" | "ready" | "error";
  image_url: string | null;
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

// A durable provisioning run (0023) — polled from /api/provisioning.
export interface ProvisionRun {
  id: string;
  slug: string;
  name: string;
  stage: string | null;
  status: "running" | "done" | "error";
  failed: boolean;
  error: string | null;
  surface: "chat" | "topics";
  conversation_id: string | null;
  message_id: string | null;
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
  last_error?: string | null; // why an auto-dropped source was disabled (0029)
}

// Admin scheduling (0020) — "run every <period> starting <date> at <time>".
export type DiscoverPeriod = "day" | "week" | "month" | "year";
export interface TopicSchedule {
  slug: string;
  name: string;
  discover: {
    period: DiscoverPeriod | null; // null → using the default cadence
    start_date: string | null; // YYYY-MM-DD
    at_min: number | null; // minutes into day (UTC)
  };
  collect: { interval_min: number | null };
  caps: { max_sources: number | null; max_stories_per_source: number | null };
  last_discovered_at: string | null;
}
export interface ScheduleDefaults {
  discover_interval_min: number;
  collect_interval_min: number;
  max_sources: number;
  max_stories_per_source: number;
  window_min: number;
}
// -1 (or "") clears a field back to its default; omit a field to leave unchanged.
export interface SchedulePatch {
  discover_period?: DiscoverPeriod | "";
  discover_start_date?: string; // YYYY-MM-DD or "" to clear
  discover_at_min?: number;
  collect_interval_min?: number;
  max_sources?: number;
  max_stories_per_source?: number;
}

// Admin metrics (0021)
export interface UsageBucket {
  input: number;
  output: number;
  cost: number;
  calls: number;
}
export interface LlmMetrics {
  range: string;
  since: string;
  overall: UsageBucket & { images?: number };
  by_model: (UsageBucket & { model: string })[];
  by_purpose: (UsageBucket & { purpose: string; label: string; description: string })[];
  by_topic: (UsageBucket & { name: string; slug: string | null; kind?: string })[];
  by_day: (UsageBucket & { date: string })[];
  images: { count: number; cost: number; unit_price: number };
  trend: { prev_cost: number; delta_pct: number | null };
  prices: Record<string, { in: number; out: number }>;
}

export interface UserDetail {
  range: string;
  since: string;
  user: {
    id: number;
    name: string;
    email: string;
    role: string;
    status: string;
    last_login_at: string | null;
    created_at: string;
  };
  usage: {
    tokens: number;
    cost: number;
    by_purpose: { purpose: string; label: string; tokens: number; cost: number; calls: number }[];
  };
  access: { logins: number; active_days: number };
  subscriptions: { slug: string; name: string }[];
  feedback: {
    up: number;
    down: number;
    recent: { item_id: string; title: string; vote: number; source_name: string; url: string | null }[];
  };
}
export interface UserMetricRow {
  id: number;
  name: string;
  email: string;
  role: string;
  status: string;
  last_login_at: string | null;
  tokens: number;
  topics: number;
  clicks: number;
  votes: number;
  saves: number;
  chats: number;
}
export interface UserMetrics {
  users: UserMetricRow[];
  totals: { user_count: number; avg_topics: number; active_users: number };
}

export interface UsageWindow {
  tokens: number;
  cost: number;
}
export interface Profile {
  user: {
    id: number;
    name: string;
    email: string;
    role: string;
    avatar_status: "none" | "pending" | "ready" | "error";
    member_since: string | null;
  };
  avatars_enabled: boolean;
  subscriptions: { slug: string; name: string }[];
  usage: { day: UsageWindow; week: UsageWindow; month: UsageWindow; year: UsageWindow; all: UsageWindow };
}

// On-demand source discovery (0030): a background web search surfaced in chat.
export interface DiscoveryArticle {
  title: string;
  url: string;
}
export interface DiscoveryCandidate {
  name: string;
  url: string;
  sample_articles: DiscoveryArticle[];
}
export interface DiscoveryWebResult {
  title: string;
  url: string;
  snippet: string;
}
export interface DiscoveryRun {
  id: string;
  query: string;
  stage: string | null;
  status: "running" | "done" | "error";
  failed: boolean;
  error: string | null;
  message_id: string | null;
  conversation_id: string | null;
  committed: boolean;
  candidates: DiscoveryCandidate[];
  web_results: DiscoveryWebResult[];
}
export interface PlacementDecision {
  mode: "existing" | "new";
  created_new: boolean;
  topics: { slug: string; name: string; score: number }[];
  sources_added: number;
  scores: { slug: string; name: string; score: number }[];
  query: string;
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
  reviewed?: number; // items the relevance review scanned (0024 fix)
  dropped?: number; // off-topic items the review filtered out
}
