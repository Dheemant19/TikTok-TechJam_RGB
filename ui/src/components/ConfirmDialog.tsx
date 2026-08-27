import * as Dialog from "@radix-ui/react-dialog";
import { motion } from "motion/react";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import styles from "./ConfirmDialog.module.css";

interface ConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  confirmLabel: string;
  onConfirm: () => void;
  danger?: boolean;
}

export function ConfirmDialog({ open, onOpenChange, title, description, confirmLabel, onConfirm, danger }: ConfirmDialogProps) {
  const reducedMotion = useReducedMotion();
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay asChild>
          <motion.div
            className={styles.overlay}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: reducedMotion ? 0.001 : 0.15 }}
          />
        </Dialog.Overlay>
        <Dialog.Content asChild>
          <motion.div
            className={styles.content}
            initial={reducedMotion ? { opacity: 0 } : { opacity: 0, scale: 0.96 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={reducedMotion ? { opacity: 0 } : { opacity: 0, scale: 0.96 }}
            transition={reducedMotion ? { duration: 0.15 } : { type: "spring", bounce: 0, duration: 0.32 }}
          >
            <Dialog.Title className={styles.title}>{title}</Dialog.Title>
            <Dialog.Description className={styles.description}>{description}</Dialog.Description>
            <div className={styles.actions}>
              <Dialog.Close asChild>
                <button type="button" className={`pressable ${styles.secondaryButton}`}>
                  Keep running
                </button>
              </Dialog.Close>
              <button
                type="button"
                className={`pressable ${danger ? styles.dangerButton : styles.primaryButton}`}
                onClick={() => {
                  onConfirm();
                  onOpenChange(false);
                }}
              >
                {confirmLabel}
              </button>
            </div>
          </motion.div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
