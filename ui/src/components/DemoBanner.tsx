import styles from "./DemoBanner.module.css";

/** Shown on every page while viewing the bundled fixture, never just one route (Plan_UI.md #7.3). */
export function DemoBanner() {
  return <div className={styles.banner}>Interface demo data — not a completed experiment</div>;
}
