import { useState } from "react";
import ThumbUpOutlined from "@mui/icons-material/ThumbUpAltOutlined";
import ThumbUpFilled from "@mui/icons-material/ThumbUpAlt";
import ThumbDownOutlined from "@mui/icons-material/ThumbDownAltOutlined";
import ThumbDownFilled from "@mui/icons-material/ThumbDownAlt";
import StarBorder from "@mui/icons-material/StarBorder";
import Star from "@mui/icons-material/Star";
import { api } from "../api";
import { useToasts } from "../state/toasts";
import { timeAgo } from "../lib/format";

// A story that can be voted on / saved. Used on Stories and Headlines.
export interface StoryLike {
  item_id: string;
  title: string;
  url: string | null;
  source_name: string;
  summary?: string | null;
  published_at?: string | null;
  fetched_at?: string | null;
  feedback_vote?: number | null;
}

export function StoryRow({ story }: { story: StoryLike }) {
  const push = useToasts((s) => s.push);
  const [vote, setVote] = useState<number>(story.feedback_vote ?? 0);
  const [saved, setSaved] = useState(false);

  const doVote = async (v: number) => {
    const next = vote === v ? 0 : v;
    try {
      await api.setFeedback(story.item_id, next);
      setVote(next);
    } catch (e) {
      push(String(e), "error");
    }
  };

  const save = async () => {
    if (!story.url) return;
    try {
      await api.addFavorite({
        title: story.title,
        url: story.url,
        item_id: story.item_id,
      });
      setSaved(true);
      push("Saved to favorites", "success");
    } catch (e) {
      push(String(e), "error");
    }
  };

  const when = story.published_at ?? story.fetched_at;

  return (
    <li className="story">
      <a
        href={story.url ?? "#"}
        target="_blank"
        rel="noreferrer"
        className="story-title"
      >
        {story.title}
      </a>
      {story.summary ? <p className="story-blurb">{story.summary}</p> : null}
      <div className="story-foot">
        <span className="chip">{story.source_name}</span>
        {when ? <span className="muted small">{timeAgo(when)}</span> : null}
        <span className="story-actions">
          {story.item_id ? (
            <>
              <button
                className={`icon-act${vote === 1 ? " up" : ""}`}
                onClick={() => doVote(1)}
                aria-label="Thumbs up"
                title="Helpful"
              >
                {vote === 1 ? (
                  <ThumbUpFilled fontSize="small" />
                ) : (
                  <ThumbUpOutlined fontSize="small" />
                )}
              </button>
              <button
                className={`icon-act${vote === -1 ? " down" : ""}`}
                onClick={() => doVote(-1)}
                aria-label="Thumbs down"
                title="Not helpful"
              >
                {vote === -1 ? (
                  <ThumbDownFilled fontSize="small" />
                ) : (
                  <ThumbDownOutlined fontSize="small" />
                )}
              </button>
            </>
          ) : null}
          <button
            className={`icon-act${saved ? " star" : ""}`}
            onClick={save}
            disabled={!story.url}
            aria-label="Save to favorites"
            title="Save to favorites"
          >
            {saved ? <Star fontSize="small" /> : <StarBorder fontSize="small" />}
          </button>
        </span>
      </div>
    </li>
  );
}
