import { useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { motion } from "motion/react";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import styles from "./ConfirmDialog.module.css";

interface PackageDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  sessionId: string;
  onConfirm: (confirmation: string) => void;
}

/** Package freezes the research frontier — requires typing the session ID, not just a click. */
export function PackageDialog({ open, onOpenChange, sessionId, onConfirm }: PackageDialogProps) {
  const reducedMotion = useReducedMotion();
  const [typed, setTyped] = useState("");
  const matches = typed === sessionId;

  return (
    <Dialog.Root
      open={open}
      onOpenChange={(next) => {
        if (!next) setTyped("");
        onOpenChange(next);
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay asChild>
          <motion.div className={styles.overlay} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: reducedMotion ? 0.001 : 0.15 }} />
        </Dialog.Overlay>
        <Dialog.Content asChild>
          <motion.div
            className={styles.content}
            initial={reducedMotion ? { opacity: 0 } : { opacity: 0, scale: 0.96 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={reducedMotion ? { opacity: 0 } : { opacity: 0, scale: 0.96 }}
            transition={reducedMotion ? { duration: 0.15 } : { type: "spring", bounce: 0, duration: 0.32 }}
          >
            <Dialog.Title className={styles.title}>Build the final package</Dialog.Title>
            <Dialog.Description className={styles.description}>
              This freezes the research frontier for good. After this, no further experiments can change the
              submission. Type the session ID <strong>{sessionId}</strong> to confirm.
            </Dialog.Description>
            <input
              value={typed}
              onChange={(event) => setTyped(event.target.value)}
              placeholder={sessionId}
              aria-label="Type the session ID to confirm"
              style={{
                width: "100%",
                padding: "0.625rem 0.75rem",
                borderRadius: "var(--radius-sm)",
                border: "1px solid var(--color-border)",
                marginBottom: "1.5rem",
                fontFamily: "ui-monospace, monospace",
              }}
            />
            <div className={styles.actions}>
              <Dialog.Close asChild>
                <button type="button" className={`pressable ${styles.secondaryButton}`}>
                  Cancel
                </button>
              </Dialog.Close>
              <button
                type="button"
                disabled={!matches}
                className={`pressable ${styles.primaryButton}`}
                style={{ opacity: matches ? 1 : 0.4, cursor: matches ? "pointer" : "not-allowed" }}
                onClick={() => {
                  onConfirm(typed);
                  onOpenChange(false);
                }}
              >
                Build final package
              </button>
            </div>
          </motion.div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
