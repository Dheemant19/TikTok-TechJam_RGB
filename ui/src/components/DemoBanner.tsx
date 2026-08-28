export function DemoBanner() {
  return (
    <div
      role="status"
      style={{
        background: "var(--ink-2)",
        borderBottom: "1px solid var(--ink-3)",
        color: "var(--text-1)",
        fontSize: 11.5,
        padding: "var(--space-1) var(--space-5)",
        display: "flex",
        alignItems: "center",
        gap: "var(--space-2)",
      }}
    >
      <span
        aria-hidden
        style={{
          width: 6,
          height: 6,
          borderRadius: "50%",
          background: "var(--status-attention)",
        }}
      />
      Interface demo data — not a completed experiment
    </div>
  );
}
