import { create } from "zustand";
import type { TopicTab } from "../api";

// Shared so the mobile hamburger's "Topics" section can read the Headlines tabs
// and switch the active topic (Headlines reads `active` to drive its view).
interface HeadlinesNav {
  topics: TopicTab[];
  active: string;
  setTopics: (t: TopicTab[]) => void;
  setActive: (slug: string) => void;
}

export const useHeadlinesNav = create<HeadlinesNav>((set) => ({
  topics: [],
  active: "",
  setTopics: (topics) => set({ topics }),
  setActive: (active) => set({ active }),
}));
