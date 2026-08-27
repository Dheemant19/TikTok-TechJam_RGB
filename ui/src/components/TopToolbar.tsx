import { useState } from "react";
import { NavLink } from "react-router-dom";
import { Menu, Pause, Play, Square, PackageCheck } from "lucide-react";
import * as Popover from "@radix-ui/react-popover";
import { useSnapshot, useSessionControl } from "@/api/queries";
import { ConfirmDialog } from "./ConfirmDialog";
import { PackageDialog } from "./PackageDialog";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import styles from "./TopToolbar.module.css";

const DESTINATIONS = [
  { to: "/", label: "Live Workflow" },
  { to: "/data-profile", label: "Data Profile" },
  { to: "/experiments", label: "Experiments" },
  { to: "/research-library", label: "Research Library" },
  { to: "/resources", label: "Resources" },
  { to: "/final-package", label: "Final Package" },
];

interface TopToolbarProps {
  sessionId: string | null;
}

export function TopToolbar({ sessionId }: TopToolbarProps) {
  const { data: snapshot } = useSnapshot(sessionId);
  const controls = useSessionControl(sessionId ?? "");
  const isNarrow = useMediaQuery("(max-width: 640px)");
  const isTablet = useMediaQuery("(max-width: 900px)");
  const [cancelOpen, setCancelOpen] = useState(false);
  const [packageOpen, setPackageOpen] = useState(false);

  const allowed = new Set(snapshot?.allowed_actions ?? []);
  // Only start/package are disabled on narrow screens to avoid accidental
  // taps; pause/resume/cancel remain available (Plan_UI.md #6.6).
  const packageDisabledOnNarrow = isNarrow;

  return (
    <header className={styles.toolbar}>
      <div className={styles.brand}>RIGOR-RS</div>

      {isTablet ? (
        <Popover.Root>
          <Popover.Trigger asChild>
            <button type="button" className={`pressable ${styles.menuButton}`} aria-label="Open navigation">
              <Menu size={20} aria-hidden="true" />
            </button>
          </Popover.Trigger>
          <Popover.Portal>
            <Popover.Content className={styles.navPopover} align="start" sideOffset={8}>
              <nav aria-label="Destinations">
                {DESTINATIONS.map((destination) => (
                  <NavLink
                    key={destination.to}
                    to={destination.to}
                    end={destination.to === "/"}
                    className={({ isActive }) => `${styles.navLinkDrawer} ${isActive ? styles.navLinkActive : ""}`}
                  >
                    {destination.label}
                  </NavLink>
                ))}
              </nav>
            </Popover.Content>
          </Popover.Portal>
        </Popover.Root>
      ) : (
        <nav className={styles.nav} aria-label="Destinations">
          {DESTINATIONS.map((destination) => (
            <NavLink
              key={destination.to}
              to={destination.to}
              end={destination.to === "/"}
              className={({ isActive }) => `${styles.navLink} ${isActive ? styles.navLinkActive : ""}`}
            >
              {destination.label}
            </NavLink>
          ))}
        </nav>
      )}

      <div className={styles.controls}>
        {sessionId && allowed.has("pause") && (
          <button
            type="button"
            className={`pressable ${styles.controlButton}`}
            onClick={() => snapshot && controls.pause.mutate(snapshot.latest_sequence)}
          >
            <Pause size={16} aria-hidden="true" />
            Pause
          </button>
        )}
        {sessionId && allowed.has("resume") && (
          <button
            type="button"
            className={`pressable ${styles.controlButton}`}
            onClick={() => snapshot && controls.resume.mutate(snapshot.latest_sequence)}
          >
            <Play size={16} aria-hidden="true" />
            Resume
          </button>
        )}
        {sessionId && allowed.has("cancel") && (
          <button
            type="button"
            className={`pressable ${styles.controlButton}`}
            onClick={() => setCancelOpen(true)}
          >
            <Square size={16} aria-hidden="true" />
            Cancel
          </button>
        )}
        {sessionId && allowed.has("package") && (
          <button
            type="button"
            className={`pressable ${styles.controlButtonPrimary}`}
            disabled={packageDisabledOnNarrow}
            onClick={() => setPackageOpen(true)}
          >
            <PackageCheck size={16} aria-hidden="true" />
            Build Final Package
          </button>
        )}
      </div>

      {sessionId && (
        <>
          <ConfirmDialog
            open={cancelOpen}
            onOpenChange={setCancelOpen}
            title="Cancel this run?"
            description="History is preserved and the stable fallback checkpoint remains available. This does not delete any evidence."
            confirmLabel="Cancel run"
            danger
            onConfirm={() => snapshot && controls.cancel.mutate(snapshot.latest_sequence)}
          />
          <PackageDialog
            open={packageOpen}
            onOpenChange={setPackageOpen}
            sessionId={sessionId}
            onConfirm={(confirmation) => controls.packageSubmission.mutate(confirmation)}
          />
        </>
      )}
    </header>
  );
}
