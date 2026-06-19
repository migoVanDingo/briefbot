import { create } from "zustand";

export interface Toast {
  id: string;
  message: string;
  tone: "info" | "success" | "error";
}

interface ToastsState {
  toasts: Toast[];
  push: (message: string, tone?: Toast["tone"]) => void;
  dismiss: (id: string) => void;
}

let counter = 0;

export const useToasts = create<ToastsState>((set) => ({
  toasts: [],
  push: (message, tone = "info") =>
    set((s) => ({
      toasts: [...s.toasts, { id: `t${++counter}`, message, tone }],
    })),
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}));
