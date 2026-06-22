import { create } from "zustand";
import { initialTheme, applyTheme, type ThemeName } from "../theme";
import { api } from "../api";

interface ThemeState {
  theme: ThemeName;
  toggle: () => void;
  // Apply the server's saved theme once `/api/me` resolves (0018). DB wins over
  // the localStorage mirror; a null server value means "follow OS" → keep cached.
  hydrate: (serverTheme: string | null | undefined) => void;
}

export const useThemeStore = create<ThemeState>((set, get) => ({
  theme: initialTheme(),
  toggle: () => {
    const next: ThemeName = get().theme === "dark" ? "light" : "dark";
    applyTheme(next);
    set({ theme: next });
    // Write through to the DB so the choice follows the user to other devices.
    // Optimistic — a failed save just means it isn't persisted yet; the visible
    // theme already changed and the localStorage mirror covers this session.
    api.patchPreferences({ theme: next }).catch(() => {});
  },
  hydrate: (serverTheme) => {
    if (serverTheme === "light" || serverTheme === "dark") {
      if (serverTheme !== get().theme) {
        applyTheme(serverTheme);
        set({ theme: serverTheme });
      }
    }
  },
}));
