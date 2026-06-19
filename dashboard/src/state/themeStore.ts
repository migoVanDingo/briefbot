import { create } from "zustand";
import { initialTheme, applyTheme, type ThemeName } from "../theme";

interface ThemeState {
  theme: ThemeName;
  toggle: () => void;
}

export const useThemeStore = create<ThemeState>((set, get) => ({
  theme: initialTheme(),
  toggle: () => {
    const next: ThemeName = get().theme === "dark" ? "light" : "dark";
    applyTheme(next);
    set({ theme: next });
  },
}));
