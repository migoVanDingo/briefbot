import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Joyride, STATUS, type Step } from "react-joyride";
import { useAuth } from "../state/auth";

// Scripted, zero-cost guided tour shown once per ACCOUNT on a user's first visit
// (server-side flag, 0018 — survives a storage clear / new browser). The agent's
// canned intro lives in the Chat page; this walks the nav so they know the lay of
// the land.
const ONBOARDING_FLAG = "onboarding_done";
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
  const hasFlag = useAuth((s) => s.hasFlag);
  const setFlag = useAuth((s) => s.setFlag);
  const navigate = useNavigate();
  const [run, setRun] = useState(false);

  // The tour shows once per account (the `onboarding_done` flag), independent of
  // the server-side `onboarded` flag — which intentionally stays false through the
  // user's first session so every topic they add builds the first Headlines. We
  // DON'T mark onboarded on tour completion (that would close the brief window
  // too early); we only set the tour-seen flag.
  const needsTour = !!profile && !profile.onboarded && !hasFlag(ONBOARDING_FLAG);

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
      setFlag(ONBOARDING_FLAG); // persist "seen" to the account
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
