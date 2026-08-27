import { useMemo, useState } from "react";
import { BookMarked, ExternalLink, Sparkles } from "lucide-react";
import type { RunEvent } from "@/api/types";
import styles from "./Routes.module.css";

interface ResearchLibraryProps {
  events: RunEvent[];
}

interface CodeRecord {
  repository_url: string;
  pinned_commit: string | null;
  license: string | null;
  verified: boolean;
}

interface PaperRecord {
  paper_id: string;
  title: string;
  authors: string[];
  year: number | null;
  venue: string | null;
  paper_url: string | null;
  license: string | null;
  trust_tier: string;
  retrieved_at: string;
  relevance_notes: string;
  code: CodeRecord[];
}

interface EvidenceMatch {
  paper: PaperRecord;
  score: number;
  match_reasons: string[];
}

function payloadField<T>(payload: Record<string, unknown>, key: string): T | null {
  return key in payload ? (payload[key] as T) : null;
}

export function ResearchLibrary({ events }: ResearchLibraryProps) {
  const [filter, setFilter] = useState<"all" | "curated" | "discovered">("all");

  const cards = useMemo(() => {
    return events
      .filter((event) => event.component_id === "knowledge_mcp" && event.event_type === "completed")
      .map((event) => ({
        runId: event.run_id,
        occurredAt: event.occurred_at,
        sourceMode: payloadField<string>(event.payload, "source_mode"),
        supporting: payloadField<EvidenceMatch[]>(event.payload, "supporting") ?? [],
        contradicting: payloadField<EvidenceMatch[]>(event.payload, "contradicting") ?? [],
        missing: payloadField<string[]>(event.payload, "missing_evidence") ?? [],
      }))
      .reverse();
  }, [events]);

  return (
    <div className={styles.page}>
      <h1>Research Library</h1>
      <p className="text-small">Every citation the Research Agent used to justify an experiment, with its source marker and license.</p>

      <div className={styles.filterBar}>
        {(["all", "curated", "discovered"] as const).map((option) => (
          <button
            key={option}
            type="button"
            className={filter === option ? styles.filterActive : styles.filterButton}
            onClick={() => setFilter(option)}
          >
            {option === "all" ? "All sources" : option === "curated" ? "Curated only" : "Auto-discovered only"}
          </button>
        ))}
      </div>

      {cards.length === 0 ? (
        <p className="text-small">No research evidence has been retrieved yet in this session.</p>
      ) : (
        cards.map((card) => {
          const allMatches = [...card.supporting.map((item) => ({ ...item, relation: "supporting" as const })), ...card.contradicting.map((item) => ({ ...item, relation: "contradicting" as const }))];
          const visible = allMatches.filter((item) => filter === "all" || item.paper.trust_tier === filter);
          return (
            <section key={`${card.runId}-${card.occurredAt}`} className={styles.card}>
              <h2>Evidence for {card.runId}</h2>
              <p className="text-small">Retrieval mode: {card.sourceMode ?? "unknown"}. {card.missing.length > 0 && `Missing: ${card.missing.join("; ")}.`}</p>
              <div className={styles.grid}>
                {visible.map((item) => (
                  <article key={item.paper.paper_id} className={styles.evidenceCard}>
                    <header className={styles.evidenceHeader}>
                      {item.paper.trust_tier === "curated" ? <BookMarked size={16} aria-hidden="true" /> : <Sparkles size={16} aria-hidden="true" />}
                      <span className={styles.evidenceTier}>{item.paper.trust_tier}</span>
                      <span className={styles.evidenceRelation}>{item.relation}</span>
                    </header>
                    <h3>{item.paper.title}</h3>
                    <p className="text-small">{item.paper.authors.join(", ")}{item.paper.year ? ` · ${item.paper.year}` : ""}{item.paper.venue ? ` · ${item.paper.venue}` : ""}</p>
                    <p className="text-small">{item.paper.relevance_notes}</p>
                    <dl className={styles.evidenceMeta}>
                      <dt>License</dt>
                      <dd>{item.paper.license ?? "Unknown"}</dd>
                      <dt>Retrieved</dt>
                      <dd>{new Date(item.paper.retrieved_at).toLocaleString()}</dd>
                      <dt>Match reasons</dt>
                      <dd>{item.match_reasons.join("; ")}</dd>
                    </dl>
                    {item.paper.paper_url && (
                      <a href={item.paper.paper_url} target="_blank" rel="noreferrer" className={styles.evidenceLink}>
                        <ExternalLink size={14} aria-hidden="true" /> Source
                      </a>
                    )}
                    {item.paper.code.length > 0 && (
                      <div className={styles.evidenceCode}>
                        <span className="text-small">Pinned code:</span>
                        {item.paper.code.map((code) => (
                          <a key={code.repository_url} href={code.repository_url} target="_blank" rel="noreferrer" className={styles.evidenceLink}>
                            {code.repository_url.replace("https://github.com/", "")}
                            {code.pinned_commit ? ` @ ${code.pinned_commit.slice(0, 7)}` : " (unpinned — withheld)"}
                          </a>
                        ))}
                      </div>
                    )}
                  </article>
                ))}
              </div>
            </section>
          );
        })
      )}
    </div>
  );
}
