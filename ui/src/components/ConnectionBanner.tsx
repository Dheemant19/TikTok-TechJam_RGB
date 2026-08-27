import { AnimatePresence, motion } from "motion/react";
import { WifiOff } from "lucide-react";
import type { ConnectionState } from "@/api/useEventStream";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import styles from "./ConnectionBanner.module.css";

interface ConnectionBannerProps {
  connection: ConnectionState;
}

/** Shown on SSE loss while the last verified snapshot is preserved (Plan_UI.md #7.2). */
export function ConnectionBanner({ connection }: ConnectionBannerProps) {
  const reducedMotion = useReducedMotion();
  const visible = connection === "reconnecting";

  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          className={styles.banner}
          role="status"
          initial={reducedMotion ? { opacity: 0 } : { opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={reducedMotion ? { opacity: 0 } : { opacity: 0, y: -8 }}
          transition={reducedMotion ? { duration: 0.15 } : { type: "spring", bounce: 0, duration: 0.32 }}
        >
          <WifiOff size={16} aria-hidden="true" />
          <span>Reconnecting to the live run — showing the last verified state.</span>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
