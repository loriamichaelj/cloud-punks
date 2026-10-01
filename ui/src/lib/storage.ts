// Every localStorage access goes through here and is wrapped in try/catch: storage can be
// blocked (private mode, policy), full or corrupt, and the app must keep working without it.

export function readText(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function writeText(key: string, value: string): boolean {
  try {
    window.localStorage.setItem(key, value);
    return true;
  } catch {
    return false;
  }
}

export function removeKey(key: string): void {
  try {
    window.localStorage.removeItem(key);
  } catch {
    // nothing to do: the value simply stays where it is
  }
}

/** Parsed JSON, or null when absent, unreadable or not JSON. The caller validates the shape. */
export function readJson(key: string): unknown {
  const text = readText(key);
  if (text === null) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return null;
  }
}

export function writeJson(key: string, value: unknown): boolean {
  return writeText(key, JSON.stringify(value));
}
