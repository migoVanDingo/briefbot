import { create } from "zustand";
import type { User } from "firebase/auth";
import { api, type Me } from "../api";

interface AuthState {
  status: "loading" | "anon" | "authed";
  user: User | null;
  profile: Me | null;
  set: (partial: Partial<AuthState>) => void;
  // Server-persisted UI flags (0018) live on `profile.flags`. These read/write
  // them so tours/onboarding survive a storage clear or a new browser.
  hasFlag: (flag: string) => boolean;
  setFlag: (flag: string) => void;
  clearFlag: (flag: string) => void;
  // RBAC (0019): does the signed-in user hold this capability? Owner holds '*'.
  can: (capability: string) => boolean;
}

export const useAuth = create<AuthState>((set, get) => ({
  status: "loading",
  user: null,
  profile: null,
  set: (partial) => set(partial),
  hasFlag: (flag) => !!get().profile?.flags.includes(flag),
  setFlag: (flag) => {
    const profile = get().profile;
    if (!profile || profile.flags.includes(flag)) return;
    // Optimistic: update in-memory so the tour doesn't re-arm this session, then
    // persist. A failed write just means it may re-show on a future load.
    set({ profile: { ...profile, flags: [...profile.flags, flag] } });
    api.setFlag(flag).catch(() => {});
  },
  clearFlag: (flag) => {
    const profile = get().profile;
    if (!profile) return;
    set({ profile: { ...profile, flags: profile.flags.filter((f) => f !== flag) } });
    api.clearFlag(flag).catch(() => {});
  },
  can: (capability) => {
    const caps = get().profile?.user.capabilities ?? [];
    return caps.includes("*") || caps.includes(capability);
  },
}));
