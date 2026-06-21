import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Joyride, STATUS, type Step } from "react-joyride";
import { useAuth } from "../state/auth";

// Scripted, zero-cost guided tour shown once per browser on a user's first visit.
// The agent's canned intro lives in the Chat page; this walks the nav so they know
// the lay of the land.
const TOUR_KEY = "bbv2_tour_done";
const STEPS: Step[] = [
  {
    target: '[data-tour="chat"]',
    title: "Start here — just ask",
    content:
      "This is Briefbot. Tell it what you want to follow and it'll set up a topic for you. It can also search your stories and summarize articles or papers — anything the app does, you can just ask for.",
  },
  {
    target: '[data-tour="headlines"]',
    title: "Headlines — your morning brief",
    content:
      "A daily summary of what's happening across the topics you follow, generated overnight and emailed to you so it's ready when you wake up.",
  },
  {
    target: '[data-tour="stories"]',
    title: "Stories",
    content:
      "Browse and search every story we've collected for your topics — filter by topic, source, or date.",
  },
  {
    target: '[data-tour="topics"]',
    title: "Topics",
    content:
      "Create and manage the topics you follow. New topics run a quick source-discovery pipeline before stories start flowing in.",
  },
  {
    target: '[data-tour="favorites"]',
    title: "Favorites",
    content: "Save any story into folders to come back to later.",
  },
];

export function OnboardingTour() {
  const profile = useAuth((s) => s.profile);
  const navigate = useNavigate();
  const [run, setRun] = useState(false);

  // The tour shows once per browser (localStorage), independent of the server-side
  // `onboarded` flag — which intentionally stays false through the user's first
  // session so every topic they add builds the first Headlines. We DON'T mark
  // onboarded on tour completion (that would close the brief window too early).
  const seen = typeof localStorage !== "undefined" && localStorage.getItem(TOUR_KEY);
  const needsTour = !!profile && !profile.onboarded && !seen;

  useEffect(() => {
    if (needsTour) {
      navigate("/chat"); // first visit starts in chat with the agent's intro
      setRun(true);
    }
  }, [needsTour, navigate]);

  if (!needsTour) return null;

  // v3 uses onEvent; the tour status flips to finished/skipped when it ends.
  const onEvent = (data: { status: string }) => {
    if (data.status === STATUS.FINISHED || data.status === STATUS.SKIPPED) {
      setRun(false);
      try {
        localStorage.setItem(TOUR_KEY, "1");
      } catch {
        /* private mode — fine, it just may re-show */
      }
    }
  };

  return (
    <Joyride
      steps={STEPS}
      run={run}
      continuous
      onEvent={onEvent}
      options={{
        primaryColor: "#7c5cff",
        zIndex: 10000,
        showProgress: true,
        skipBeacon: true,
        buttons: ["skip", "back", "primary"],
      }}
    />
  );
}
