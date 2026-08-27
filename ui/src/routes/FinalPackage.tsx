import { useState } from "react";
import { CheckCircle2, Lock, XCircle } from "lucide-react";
import type { FinalizationManifest, SessionSnapshot } from "@/api/types";
import { useSessionControl } from "@/api/queries";
import { PackageDialog } from "@/components/PackageDialog";
import styles from "./Routes.module.css";

interface FinalPackageProps {
  sessionId: string | null;
  snapshot: SessionSnapshot | null;
}

export function FinalPackage({ sessionId, snapshot }: FinalPackageProps) {
  const [open, setOpen] = useState(false);
  const [manifest, setManifest] = useState<FinalizationManifest | null>(null);
  const controls = useSessionControl(sessionId ?? "");

  const canPackage = snapshot?.allowed_actions.includes("package") ?? false;
  const alreadyFinalized = snapshot?.finalized ?? false;

  return (
    <div className={styles.page}>
      <h1>Final Package</h1>
      <p className="text-small">Freezes the research frontier and produces the one-way submission artifact. This action cannot be undone.</p>

      <section className={styles.card}>
        <h2>Validation-best receipt</h2>
        {snapshot?.frontier.validation_best ? (
          <dl className={styles.statGrid}>
            <dt>Validation-best run</dt>
            <dd>{snapshot.frontier.validation_best}</dd>
            <dt>Stable fallback</dt>
            <dd>{snapshot.frontier.stable_fallback ?? "—"}</dd>
            <dt>Frontier locked</dt>
            <dd>{snapshot.frontier.locked ? "Yes — convergence or budget reached" : "No — still exploring"}</dd>
          </dl>
        ) : (
          <p className="text-small">No validation-best run has been registered yet.</p>
        )}
      </section>

      <section className={styles.card}>
        <h2>One-way finalization boundary</h2>
        {alreadyFinalized ? (
          <p className={styles.finalizedNotice}>
            <Lock size={16} aria-hidden="true" /> This session has already been finalized. Packaging is disabled.
          </p>
        ) : (
          <>
            <p className="text-small">
              Building the final package replays the full ledger for the validation-best run, re-checks the prediction schema
              with <code>submit.py --check</code>, and hashes the manifest. Once finalized, this session cannot start new experiments.
            </p>
            <button type="button" className="pressable" disabled={!canPackage} onClick={() => setOpen(true)}>
              Build Final Package
            </button>
            {!canPackage && <p className="text-small">Packaging becomes available once the frontier reaches convergence or the budget is exhausted.</p>}
          </>
        )}
      </section>

      {manifest && (
        <section className={styles.card}>
          <h2>Finalization manifest</h2>
          <div className={styles.checklist}>
            <p>{manifest.event_chain_valid ? <CheckCircle2 size={16} aria-hidden="true" /> : <XCircle size={16} aria-hidden="true" />} Ledger event chain verified</p>
            <p>{manifest.test_prediction_passes <= 1 ? <CheckCircle2 size={16} aria-hidden="true" /> : <XCircle size={16} aria-hidden="true" />} Test predictions generated exactly once</p>
            <p>{manifest.schema_check.exit_code === 0 ? <CheckCircle2 size={16} aria-hidden="true" /> : <XCircle size={16} aria-hidden="true" />} Submission schema check passed</p>
          </div>
          <dl className={styles.statGrid}>
            <dt>Experiment</dt>
            <dd>{manifest.experiment_id}</dd>
            <dt>Checkpoint hash</dt>
            <dd className={styles.hash}>{manifest.checkpoint_hash}</dd>
            <dt>Transform state hash</dt>
            <dd className={styles.hash}>{manifest.transform_state_hash}</dd>
            <dt>Predictions hash</dt>
            <dd className={styles.hash}>{manifest.predictions_hash}</dd>
            <dt>Manifest hash</dt>
            <dd className={styles.hash}>{manifest.manifest_hash}</dd>
            <dt>Created</dt>
            <dd>{new Date(manifest.created_at).toLocaleString()}</dd>
          </dl>
          <details>
            <summary>Implementation details</summary>
            <pre className={styles.log}>{manifest.schema_check.stdout}</pre>
          </details>
        </section>
      )}

      {sessionId && (
        <PackageDialog
          open={open}
          onOpenChange={setOpen}
          sessionId={sessionId}
          onConfirm={(confirmation) =>
            controls.packageSubmission.mutate(confirmation, {
              onSuccess: (result) => {
                setManifest(result);
                setOpen(false);
              },
            })
          }
        />
      )}
    </div>
  );
}
