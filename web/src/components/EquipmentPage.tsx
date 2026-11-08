import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, MapPin, MessageSquareText, Search, User, X } from "lucide-react";
import { motion } from "motion/react";
import { useId, useMemo, useState } from "react";
import { getEquipment } from "../api";
import type { Instrument } from "../types";

/** "School of Dentistry – Light Microscopy Core" -> "School of Dentistry". */
function school(location: string): string {
  return location.split(/\s+[–-]\s+/)[0].trim();
}

function matches(item: Instrument, words: string[]): boolean {
  const text = [item.id, item.name, item.manufacturer, item.model, item.location, item.contact, ...item.techniques]
    .join(" ")
    .toLowerCase();
  return words.every((word) => text.includes(word));
}

function InstrumentTile({ item, onAsk }: { item: Instrument; onAsk: (question: string) => void }) {
  return (
    <motion.article
      layout="position"
      className="card tile"
      aria-label={`${item.name} (${item.id})`}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.18 }}
    >
      <header className="card__strip">
        <span className="id-tag">{item.id}</span>
        {item.demo_instrument && <span className="pill">Demo instrument</span>}
      </header>
      <div className="card__body">
        <h3 className="card__title card__title--sm">{item.name}</h3>
        <p className="mono card__model">{[item.manufacturer, item.model].filter(Boolean).join(" ")}</p>
        <p className="tile__line">
          <MapPin size={16} aria-hidden="true" />
          {item.location}
        </p>
        <p className="tile__line">
          <User size={16} aria-hidden="true" />
          {item.contact}
        </p>
        {item.techniques.length > 0 && (
          <div className="tile__group">
            <span className="label">Typical techniques</span>
            <ul className="tags">
              {item.techniques.map((t) => (
                <li key={t} className="tag">
                  {t}
                </li>
              ))}
            </ul>
          </div>
        )}
        {item.installed.length > 0 && (
          <div className="tile__group">
            <span className="label">Installed</span>
            <ul className="chips">
              {item.installed.map((a) => (
                <li key={a} className="chip chip--installed">
                  <CheckCircle2 size={16} aria-hidden="true" />
                  {a}
                </li>
              ))}
            </ul>
          </div>
        )}
        <button
          type="button"
          className="button button--secondary tile__ask"
          onClick={() => onAsk(`What can I measure with the ${item.name}, ${item.manufacturer} ${item.model}?`)}
        >
          <MessageSquareText size={18} aria-hidden="true" />
          Ask about this instrument
        </button>
      </div>
    </motion.article>
  );
}

/** All instruments on campus, with search and filters by school and technique. */
export function EquipmentPage({ onAsk }: { onAsk: (question: string) => void }) {
  const equipment = useQuery({ queryKey: ["equipment"], queryFn: getEquipment, staleTime: Infinity });
  const [query, setQuery] = useState("");
  const [schoolFilter, setSchoolFilter] = useState("");
  const [technique, setTechnique] = useState("");
  const ids = { search: useId(), school: useId(), technique: useId() };

  const items = equipment.data ?? [];
  const schools = useMemo(() => [...new Set(items.map((i) => school(i.location)))].sort(), [items]);
  const techniques = useMemo(() => [...new Set(items.flatMap((i) => i.techniques))].sort(), [items]);
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  const shown = items.filter(
    (i) =>
      matches(i, words) &&
      (!schoolFilter || school(i.location) === schoolFilter) &&
      (!technique || i.techniques.includes(technique)),
  );
  const filtered = Boolean(query || schoolFilter || technique);

  return (
    <div className="browse">
      <header className="browse__head">
        <h1 className="start__title">Equipment on campus</h1>
        <p className="start__intro">
          Every instrument Equipment Finder can recommend. Techniques are typical for each model; confirm the
          configuration with the contact.
        </p>
      </header>

      <div className="filters" role="search">
        <label className="field filters__search" htmlFor={ids.search}>
          <span className="label">Search</span>
          <span className="input-icon">
            <Search size={18} aria-hidden="true" />
            <input
              id={ids.search}
              type="search"
              value={query}
              placeholder="Instrument, model, technique, contact…"
              onChange={(e) => setQuery(e.target.value)}
            />
          </span>
        </label>
        <label className="field" htmlFor={ids.school}>
          <span className="label">Location</span>
          <select id={ids.school} className="select" value={schoolFilter} onChange={(e) => setSchoolFilter(e.target.value)}>
            <option value="">All locations</option>
            {schools.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label className="field" htmlFor={ids.technique}>
          <span className="label">Technique</span>
          <select id={ids.technique} className="select" value={technique} onChange={(e) => setTechnique(e.target.value)}>
            <option value="">All techniques</option>
            {techniques.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="browse__count" aria-live="polite">
        <span>
          {equipment.isLoading
            ? "Loading equipment…"
            : `Showing ${shown.length} of ${items.length} instruments`}
        </span>
        {filtered && (
          <button
            type="button"
            className="button button--text"
            onClick={() => {
              setQuery("");
              setSchoolFilter("");
              setTechnique("");
            }}
          >
            <X size={16} aria-hidden="true" />
            Clear filters
          </button>
        )}
      </div>

      {equipment.isError && (
        <div className="doc doc--error" role="alert">
          <p>The equipment list couldn't be loaded.</p>
          <button type="button" className="button button--secondary" onClick={() => void equipment.refetch()}>
            Try again
          </button>
        </div>
      )}
      {!equipment.isLoading && shown.length === 0 && !equipment.isError && (
        <p className="browse__empty">No instrument matches. Try fewer words, or describe your problem on the Ask page.</p>
      )}
      <div className="tiles">
        {shown.map((item) => (
          <InstrumentTile key={item.id} item={item} onAsk={onAsk} />
        ))}
      </div>
    </div>
  );
}
