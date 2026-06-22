import type { Step } from "react-joyride";

// Per-page guided tours. Each shows once per browser (first visit) and can be
// relaunched from the ⓘ button by the page title. Targets are stable selectors /
// data-tour anchors present whenever the page renders content.

const RELAUNCH = "Replay this walkthrough anytime with the ⓘ button next to the page title.";

export interface TourDef {
  label: string;
  steps: Step[];
}

export const TOURS: Record<string, TourDef> = {
  headlines: {
    label: "Headlines",
    steps: [
      {
        target: ".headlines-rail",
        placement: "right",
        title: "Your last 10 days",
        content:
          "Each day is listed here, newest first. Pick a date to read that day's brief and stories — greyed-out days don't have a brief yet.",
      },
      {
        target: ".brief-title",
        placement: "bottom",
        title: "The day's headline",
        content:
          "An AI-written summary of the top stories for the selected topic. Switch topics with the tabs above the brief.",
      },
      {
        target: ".story-list",
        placement: "top",
        title: "The stories",
        content:
          "Every story behind the brief, newest first. Use 👍/👎 to tune relevance and ☆ to save one to Favorites.",
      },
      {
        target: ".info-btn",
        placement: "bottom",
        title: "Replay anytime",
        content: RELAUNCH,
      },
    ],
  },

  stories: {
    label: "Stories",
    steps: [
      {
        target: ".filter-search",
        title: "Search everything",
        content:
          "Search across the titles, summaries, and sources of every story in the topics you follow.",
      },
      {
        target: ".filter-controls",
        title: "Filter & sort",
        content:
          "Narrow by topic, source, or date range, flip the sort order, then hit Search to apply.",
      },
      {
        target: "body",
        placement: "center",
        title: "Or just ask",
        content:
          "Prefer to ask? The Chat agent can search and summarize stories for you too — head to Chat and tell it what you're looking for.",
      },
      {
        target: ".info-btn",
        placement: "bottom",
        title: "Replay anytime",
        content: RELAUNCH,
      },
    ],
  },

  topics: {
    label: "Topics",
    steps: [
      {
        target: '[data-tour="topics-create"]',
        title: "Create a topic",
        content:
          "Name any subject and create it — Briefbot discovers sources and starts collecting stories, streaming the setup pipeline as it runs.",
      },
      {
        target: '[data-tour="topics-list"]',
        title: "Your topics",
        content:
          "Subscribe or unsubscribe here. Your subscriptions drive your Headlines brief and the stories you see.",
      },
      {
        target: ".info-btn",
        placement: "bottom",
        title: "Replay anytime",
        content: RELAUNCH,
      },
    ],
  },

  favorites: {
    label: "Favorites",
    steps: [
      {
        target: '[data-tour="fav-search"]',
        title: "Find a saved story",
        content: "Search across everything you've saved, across all folders.",
      },
      {
        target: '[data-tour="fav-folders"]',
        title: "Folders",
        content:
          "Stories you save (the ☆ on any story) land here, organized into folders you create.",
      },
      {
        target: ".info-btn",
        placement: "bottom",
        title: "Replay anytime",
        content: RELAUNCH,
      },
    ],
  },
};
