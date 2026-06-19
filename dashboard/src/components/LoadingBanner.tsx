import { useCyclingPhrase } from "../lib/useCyclingPhrase";

export function LoadingBanner({ phrases }: { phrases: string[] }) {
  const phrase = useCyclingPhrase(phrases, true);
  return (
    <div className="loading-banner" role="status" aria-live="polite">
      <span className="spinner" aria-hidden />
      {/* key={phrase} replays the fade-in on each change */}
      <span key={phrase} className="loading-text">
        {phrase}
      </span>
    </div>
  );
}
