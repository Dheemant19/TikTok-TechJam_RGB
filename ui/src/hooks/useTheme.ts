import { useEffect, useState } from "react";

export type Theme = "light" | "dark";

const STORAGE_KEY = "flowstate-theme";

function readTheme(): Theme {
  if (typeof document === "undefined") return "light";
  const current = document.documentElement.dataset.theme;
  return current === "dark" ? "dark" : "light";
}

/** Reads and toggles the app's theme, kept in sync with the pre-paint
 * inline script in index.html so there is never a flash of the wrong mode. */
export function useTheme() {
  const [theme, setTheme] = useState<Theme>(readTheme);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      window.localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      // Storage may be unavailable (private mode, disabled cookies); the
      // in-memory theme still applies for this session.
    }
  }, [theme]);

  const toggleTheme = () => setTheme((current) => (current === "dark" ? "light" : "dark"));

  return { theme, toggleTheme };
}
