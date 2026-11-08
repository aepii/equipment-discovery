/** localStorage that never throws (private windows and blocked storage just don't remember). */
export function load<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

export function save(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* storage full or blocked */
  }
}

export function remove(key: string): void {
  try {
    localStorage.removeItem(key);
  } catch {
    /* blocked */
  }
}

export function newId(): string {
  return crypto.randomUUID().replace(/-/g, "").slice(0, 16);
}

/** Anonymous ID for this browser, used for the per-session model-call limit and logging. */
export function sessionId(): string {
  let id = load<string>("ef.session", "");
  if (!id) {
    id = newId();
    save("ef.session", id);
  }
  return id;
}
