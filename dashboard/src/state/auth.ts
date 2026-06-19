import { create } from "zustand";
import type { User } from "firebase/auth";
import type { Me } from "../api";

interface AuthState {
  status: "loading" | "anon" | "authed";
  user: User | null;
  profile: Me | null;
  set: (partial: Partial<AuthState>) => void;
}

export const useAuth = create<AuthState>((set) => ({
  status: "loading",
  user: null,
  profile: null,
  set: (partial) => set(partial),
}));
