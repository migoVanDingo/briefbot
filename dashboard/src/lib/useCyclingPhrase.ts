import { useEffect, useRef, useState } from "react";

function shuffle<T>(arr: T[]): T[] {
  const a = arr.slice();
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

/**
 * Cycle through `phrases` at random while `active`, never repeating one until
 * every phrase has been shown (shuffle-bag). Returns the current phrase.
 */
export function useCyclingPhrase(
  phrases: string[],
  active: boolean,
  intervalMs = 5000,
): string {
  const bag = useRef<string[]>([]);
  const [phrase, setPhrase] = useState(phrases[0] ?? "");

  useEffect(() => {
    if (!active || phrases.length === 0) return;

    const draw = () => {
      if (bag.current.length === 0) bag.current = shuffle(phrases);
      return bag.current.pop() as string;
    };

    bag.current = shuffle(phrases);
    setPhrase(draw());
    const id = setInterval(() => setPhrase(draw()), intervalMs);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, intervalMs]);

  return phrase;
}
