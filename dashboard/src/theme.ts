// Single source of theme tokens → injected CSS variables. Light and dark use
// distinct accents (not just inverted neutrals). Restrained radii (no pills).

export type ThemeName = "light" | "dark";

interface Tokens {
  bg: string;
  surface: string;
  surface2: string;
  border: string;
  text: string;
  dim: string;
  accent: string;
  accent2: string;
  pos: string;
  neg: string;
}

const tokens: Record<ThemeName, Tokens> = {
  dark: {
    bg: "#0f1115",
    surface: "#171a21",
    surface2: "#1e222b",
    border: "#262b36",
    text: "#e6e9ef",
    dim: "#9aa3b2",
    accent: "#7c5cff",
    accent2: "#22d3ee",
    pos: "#34d399",
    neg: "#fb7185",
  },
  light: {
    bg: "#f6f8fb",
    surface: "#ffffff",
    surface2: "#eef1f6",
    border: "#e3e7ee",
    text: "#1a1f2b",
    dim: "#5b6472",
    accent: "#2563eb",
    accent2: "#60a5fa",
    pos: "#059669",
    neg: "#e11d48",
  },
};

const VARS: [keyof Tokens, string][] = [
  ["bg", "--bg"],
  ["surface", "--surface"],
  ["surface2", "--surface2"],
  ["border", "--border"],
  ["text", "--text"],
  ["dim", "--dim"],
  ["accent", "--accent"],
  ["accent2", "--accent2"],
  ["pos", "--pos"],
  ["neg", "--neg"],
];

function block(t: Tokens): string {
  return VARS.map(([k, v]) => `  ${v}: ${t[k]};`).join("\n");
}

export function themeStyleSheet(): string {
  return [
    `:root,\n[data-theme="dark"] {\n${block(tokens.dark)}\n}`,
    `[data-theme="light"] {\n${block(tokens.light)}\n}`,
  ].join("\n");
}

const KEY = "bbv2.theme";

// The DB is the source of truth for a signed-in user's theme (0018). The
// localStorage mirror is a NON-authoritative cache used only to paint the right
// theme on the very first frame, before `/api/me` resolves — otherwise we'd flash
// the OS default. `themeStore.hydrate` swaps in the server value once it arrives.

export function osTheme(): ThemeName {
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

export function initialTheme(): ThemeName {
  try {
    const saved = localStorage.getItem(KEY);
    if (saved === "light" || saved === "dark") return saved;
  } catch {
    /* private mode — fall through to OS */
  }
  return osTheme();
}

export function applyTheme(theme: ThemeName): void {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    /* private mode — the in-memory store still holds it for this session */
  }
}
