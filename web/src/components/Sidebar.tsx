import * as Collapsible from "@radix-ui/react-collapsible";
import { ChevronDown, MessageSquare, Plus, Settings2 } from "lucide-react";
import { useState } from "react";
import type { Conversation, Mode } from "../types";

interface Props {
  conversations: Conversation[];
  activeId: string;
  onSelect: (id: string) => void;
  onNew: () => void;
  onClear: () => void;
  mode: Mode;
  onModeChange: (mode: Mode) => void;
}

/** This browser's conversations (stored in localStorage only), plus the advanced answer-mode setting. */
export function Sidebar({ conversations, activeId, onSelect, onNew, onClear, mode, onModeChange }: Props) {
  const [advanced, setAdvanced] = useState(mode !== "annotated");
  const listed = conversations.filter((c) => c.turns.length > 0);
  return (
    <aside className="sidebar" aria-label="Conversations">
      <button type="button" className="button button--secondary sidebar__new" onClick={onNew}>
        <Plus size={18} aria-hidden="true" />
        New conversation
      </button>
      <span className="label sidebar__label">On this device</span>
      {listed.length === 0 ? (
        <p className="sidebar__empty">Your questions will appear here.</p>
      ) : (
        <ul className="sidebar__list">
          {listed.map((c) => (
            <li key={c.id}>
              <button
                type="button"
                className={`sidebar__item${c.id === activeId ? " is-active" : ""}`}
                aria-current={c.id === activeId ? "true" : undefined}
                onClick={() => onSelect(c.id)}
              >
                <MessageSquare size={16} aria-hidden="true" />
                <span>{c.title}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="sidebar__foot">
        <p>History stays in this browser only.</p>
        {listed.length > 0 && (
          <button type="button" className="button button--text" onClick={onClear}>
            Clear history
          </button>
        )}
        <Collapsible.Root open={advanced} onOpenChange={setAdvanced}>
          <Collapsible.Trigger className="details__trigger sidebar__adv">
            <Settings2 size={16} aria-hidden="true" />
            Advanced
            <ChevronDown size={16} aria-hidden="true" className={advanced ? "rot" : ""} />
          </Collapsible.Trigger>
          <Collapsible.Content>
            <label className="field">
              <span className="label">Answer mode</span>
              <select value={mode} onChange={(e) => onModeChange(e.target.value as Mode)} className="select">
                <option value="annotated">Equipment Finder</option>
                <option value="structured">Rules only (no instrument profiles)</option>
              </select>
            </label>
          </Collapsible.Content>
        </Collapsible.Root>
      </div>
    </aside>
  );
}
