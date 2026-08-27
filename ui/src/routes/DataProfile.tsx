import { useArtifact } from "@/api/queries";
import { useProfilerArtifacts } from "@/hooks/useProfilerArtifacts";
import { BarChart } from "@/charts/BarChart";
import { LineChart } from "@/charts/LineChart";
import { DataTable } from "@/charts/DataTable";
import type { RunEvent } from "@/api/types";
import styles from "./Routes.module.css";

interface DataProfileProps {
  events: RunEvent[];
}

interface SplitStat {
  split: string;
  rows: number;
  users: number;
  videos: number;
  long_view_rate: number;
}

interface LabelGroupRow {
  split: string;
  label_group: string;
  users: number;
}

interface InteractionRow {
  split: string;
  min: number;
  median: number;
  mean: number;
  p95: number;
  max: number;
}

interface DailyDriftRow {
  split: string;
  date: number;
  rows: number;
  long_view_rate: number;
}

interface WatchTimeCensoring {
  rows: number;
  completed_or_censored: number;
  median_watch_fraction: number;
}

interface ProfileDocument {
  split_stats: SplitStat[];
  label_groups: LabelGroupRow[];
  interactions_per_user: InteractionRow[];
  missing_by_field: Record<string, number>;
  cardinalities: Record<string, number>;
  duplicate_exposure_rate: number;
  watch_time_censoring: WatchTimeCensoring;
  temporal_drift: DailyDriftRow[];
  auxiliary_label_correlations: Record<string, number | null>;
}

interface TransformSplitReceipt {
  rows: number;
  content_hash: string;
  taints: string[];
  unknown_counts: number[];
}

interface TransformReceiptDocument {
  receipt_id: string;
  source_hash: string;
  transform_state_hash: string;
  splits: Record<string, TransformSplitReceipt>;
  join_expansion_ratio: number;
  row_order_preserved: boolean;
}

export function DataProfile({ events }: DataProfileProps) {
  const { profileArtifactId, visualizationArtifactId, transformReceiptArtifactId } = useProfilerArtifacts(events);
  const profile = useArtifact(profileArtifactId);
  const transformReceipt = useArtifact(transformReceiptArtifactId);
  void visualizationArtifactId; // reserved: aggregate charts below already read from profile.json directly

  if (!profileArtifactId) {
    return (
      <div className={styles.page}>
        <h1>Data Profile</h1>
        <p className="text-small">The Data Profiler has not produced a profile yet in this session.</p>
      </div>
    );
  }

  const document = profile.data?.content as ProfileDocument | undefined;
  const transform = transformReceipt.data?.content as TransformReceiptDocument | undefined;

  return (
    <div className={styles.page}>
      <h1>Data Profile</h1>
      <p className="text-small">Aggregate diagnostics only — the browser never receives raw interaction rows.</p>

      {!document ? (
        <p className="text-small">Loading profile…</p>
      ) : (
        <div className={styles.grid}>
          <BarChart
            title="Rows and long_view rate by split"
            xAxisLabel="Split"
            yAxisLabel="Rows"
            categories={document.split_stats.map((row) => row.split)}
            series={[{ name: "Rows", values: document.split_stats.map((row) => row.rows) }]}
          />
          <BarChart
            title="Users by label group"
            xAxisLabel="Split"
            yAxisLabel="Users"
            categories={[...new Set(document.label_groups.map((row) => row.split))]}
            series={["all_negative", "mixed", "all_positive"].map((group) => ({
              name: group,
              values: [...new Set(document.label_groups.map((row) => row.split))].map(
                (split) => document.label_groups.find((row) => row.split === split && row.label_group === group)?.users ?? 0,
              ),
            }))}
          />
          <LineChart
            title="Daily volume and label-rate drift"
            xAxisLabel="Date"
            yAxisLabel="Rows"
            categories={document.temporal_drift.map((row) => String(row.date))}
            series={[{ name: "Rows", values: document.temporal_drift.map((row) => row.rows) }]}
          />
          <LineChart
            title="Daily long_view rate"
            xAxisLabel="Date"
            yAxisLabel="Rate"
            categories={document.temporal_drift.map((row) => String(row.date))}
            series={[{ name: "long_view rate", values: document.temporal_drift.map((row) => row.long_view_rate) }]}
          />

          <section className={styles.card}>
            <h2>Interactions per user</h2>
            <DataTable
              caption="Interactions per user by split"
              columns={["Split", "Min", "Median", "Mean", "P95", "Max"]}
              rows={document.interactions_per_user.map((row) => [row.split, row.min, row.median, row.mean.toFixed(1), row.p95, row.max])}
            />
          </section>

          <section className={styles.card}>
            <h2>Missing or malformed values by field</h2>
            <DataTable
              caption="Missing values by field"
              columns={["Field", "Missing count"]}
              rows={Object.entries(document.missing_by_field).map(([field, count]) => [field, count])}
            />
          </section>

          <section className={styles.card}>
            <h2>Feature cardinality and unseen-ID rate</h2>
            <DataTable
              caption="Cardinality and unseen-ID rate"
              columns={["Field", "Distinct values (dev)", "Unseen-ID rate (validation)"]}
              rows={Object.entries(document.cardinalities).map(([field, count]) => {
                const fieldIndex = transform ? ["user_id", "video_id", "author_id", "tab", "dur_bucket"].indexOf(field) : -1;
                const validSplit = transform?.splits.valid;
                const unseenRate =
                  fieldIndex >= 0 && validSplit ? (validSplit.unknown_counts[fieldIndex] / validSplit.rows).toFixed(4) : "—";
                return [field, count, unseenRate];
              })}
            />
          </section>

          <section className={styles.card}>
            <h2>Watch-time censoring (play_time_ms vs. duration_ms)</h2>
            <DataTable
              caption="Watch time censoring summary"
              columns={["Rows", "Completed or censored", "Median watch fraction"]}
              rows={[
                [
                  document.watch_time_censoring.rows,
                  document.watch_time_censoring.completed_or_censored,
                  document.watch_time_censoring.median_watch_fraction.toFixed(3),
                ],
              ]}
            />
          </section>

          <section className={styles.card}>
            <h2>Duplicate user/video exposure rate</h2>
            <p>{(document.duplicate_exposure_rate * 100).toFixed(2)}% of exposures are duplicate (user, video, date) triples.</p>
          </section>

          <section className={styles.card}>
            <h2>Auxiliary-label correlation with long_view</h2>
            <DataTable
              caption="Auxiliary label correlation"
              columns={["Signal", "Correlation"]}
              rows={Object.entries(document.auxiliary_label_correlations).map(([signal, value]) => [
                signal,
                value === null ? "—" : value.toFixed(3),
              ])}
            />
          </section>

          {transform && (
            <section className={styles.card}>
              <h2>Frozen train-only preprocessing receipt</h2>
              <p className="text-small">Fitted on train only; validation/test reuse this state without refitting.</p>
              <DataTable
                caption="Transform lineage"
                columns={["Stage", "Hash"]}
                rows={[
                  ["Source data", transform.source_hash],
                  ["Fitted transform state", transform.transform_state_hash],
                  ...Object.entries(transform.splits).map(([split, receipt]) => [`${split} materialization`, receipt.content_hash]),
                ]}
              />
            </section>
          )}
        </div>
      )}
    </div>
  );
}
