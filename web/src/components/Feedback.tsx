import { ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { sendFeedback } from "../api";
import type { Card } from "../types";

const RATINGS = ["Good", "Partly", "Wrong"] as const;

/** "Was this helpful?" thumbs, then an optional comment and per-instrument ratings. */
export function Feedback({ answerId, cards }: { answerId: string; cards: Card[] }) {
  const [overall, setOverall] = useState<"good" | "bad" | null>(null);
  const [comment, setComment] = useState("");
  const [ratings, setRatings] = useState<Record<string, string>>({});
  const [state, setState] = useState<"open" | "sending" | "sent">("open");

  async function submit() {
    if (!overall) return;
    setState("sending");
    try {
      await sendFeedback({ answer_id: answerId, overall, comment, instrument_ratings: ratings });
      setState("sent");
      toast.success("Thanks for the feedback");
    } catch (error) {
      setState("open");
      toast.error(error instanceof Error ? error.message : "Couldn't send the feedback.");
    }
  }

  if (state === "sent") return <p className="feedback__done">Thanks for the feedback.</p>;

  return (
    <div className="feedback">
      <div className="feedback__ask" role="group" aria-label="Was this helpful?">
        <span>Was this helpful?</span>
        <button
          type="button"
          className={`icon-button${overall === "good" ? " is-on" : ""}`}
          aria-label="Helpful"
          aria-pressed={overall === "good"}
          onClick={() => setOverall("good")}
        >
          <ThumbsUp size={20} aria-hidden="true" />
        </button>
        <button
          type="button"
          className={`icon-button${overall === "bad" ? " is-on" : ""}`}
          aria-label="Not helpful"
          aria-pressed={overall === "bad"}
          onClick={() => setOverall("bad")}
        >
          <ThumbsDown size={20} aria-hidden="true" />
        </button>
      </div>
      {overall && (
        <form
          className="feedback__form"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <label className="field">
            <span className="label">Comment (optional)</span>
            <textarea rows={2} value={comment} onChange={(e) => setComment(e.target.value)} maxLength={4000} />
          </label>
          {cards.length > 0 && (
            <fieldset className="ratings">
              <legend className="label">Each instrument (optional)</legend>
              {cards.map((card) => (
                <div key={card.id} className="rating-row" role="radiogroup" aria-label={`${card.name} rating`}>
                  <span className="rating-row__name">
                    <span className="mono">{card.id}</span> {card.name}
                  </span>
                  <span className="segmented">
                    {RATINGS.map((rating) => (
                      <button
                        key={rating}
                        type="button"
                        role="radio"
                        aria-checked={ratings[card.id] === rating}
                        className={ratings[card.id] === rating ? "is-on" : ""}
                        onClick={() => setRatings({ ...ratings, [card.id]: rating })}
                      >
                        {rating}
                      </button>
                    ))}
                  </span>
                </div>
              ))}
            </fieldset>
          )}
          <button type="submit" className="button button--primary" disabled={state === "sending"}>
            {state === "sending" ? "Sending…" : "Send feedback"}
          </button>
        </form>
      )}
    </div>
  );
}
