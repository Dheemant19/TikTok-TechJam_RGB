import { useEffect, useState } from "react";

/** Forces a 1s re-render while `active`, to keep an elapsed-time label live. */
export function useElapsedTick(active: boolean): void {
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!active) return;
    const id = window.setInterval(() => setTick((value) => value + 1), 1000);
    return () => window.clearInterval(id);
  }, [active]);
}
