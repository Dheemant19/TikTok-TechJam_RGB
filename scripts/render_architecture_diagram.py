import os
import subprocess

dot_source = """
digraph RIGOR_RS {
    graph [
        rankdir="TB",
        nodesep="0.4",
        ranksep="0.5",
        splines="polyline",
        fontname="Helvetica",
        fontsize="14",
        bgcolor="#ffffff",
        compound=true,
        dpi=300
    ];

    node [
        fontname="Helvetica",
        fontsize="10",
        shape="box",
        style="filled,rounded",
        margin="0.15,0.1"
    ];

    edge [
        fontname="Helvetica",
        fontsize="9",
        color="#475569",
        arrowsize="0.75"
    ];

    // STORAGE & DATA LAYER
    subgraph cluster_storage {
        label="🗄️  DATA & STORAGE LAYER (KuaiRand-Pure)";
        style="filled,rounded";
        fillcolor="#f8fafc";
        color="#cbd5e1";
        fontsize="12";
        fontcolor="#1e293b";

        d_train [
            fillcolor="#e2e8f0",
            color="#94a3b8",
            label=<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="1">
                <TR><TD><B>Train Features &amp; Labels</B></TD></TR>
                <TR><TD ALIGN="LEFT"><FONT COLOR="#64748b" POINT-SIZE="8">• log_standard_4_08_to_4_21</FONT></TD></TR>
                <TR><TD ALIGN="LEFT"><FONT COLOR="#64748b" POINT-SIZE="8">• user &amp; video features</FONT></TD></TR>
            </TABLE>>
        ];

        d_val [
            fillcolor="#e2e8f0",
            color="#94a3b8",
            label=<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="1">
                <TR><TD><B>Validation Split (50%)</B></TD></TR>
                <TR><TD ALIGN="LEFT"><FONT COLOR="#64748b" POINT-SIZE="8">• log_standard_4_22_to_5_08</FONT></TD></TR>
                <TR><TD ALIGN="LEFT"><FONT COLOR="#64748b" POINT-SIZE="8">• Click ground-truth for NDCG/Recall</FONT></TD></TR>
            </TABLE>>
        ];

        d_test [
            fillcolor="#fee2e2",
            color="#f87171",
            label=<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="1">
                <TR><TD><B>🔒 Sealed Test Split (50%)</B></TD></TR>
                <TR><TD ALIGN="LEFT"><FONT COLOR="#b91c1c" POINT-SIZE="8">• No access during development</FONT></TD></TR>
                <TR><TD ALIGN="LEFT"><FONT COLOR="#b91c1c" POINT-SIZE="8">• Used 1x for final inference</FONT></TD></TR>
            </TABLE>>
        ];

        ledger [
            fillcolor="#f1f5f9",
            color="#94a3b8",
            label=<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="1">
                <TR><TD><B>📊 Run Ledger (SQLite)</B></TD></TR>
                <TR><TD ALIGN="LEFT"><FONT COLOR="#475569" POINT-SIZE="8">• Append-only experiment logs</FONT></TD></TR>
                <TR><TD ALIGN="LEFT"><FONT COLOR="#475569" POINT-SIZE="8">• Code diffs, tokens, GPU hours</FONT></TD></TR>
            </TABLE>>
        ];

        ckpt_store [
            fillcolor="#f1f5f9",
            color="#94a3b8",
            label=<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="1">
                <TR><TD><B>💾 Checkpoint Storage</B></TD></TR>
                <TR><TD ALIGN="LEFT"><FONT COLOR="#475569" POINT-SIZE="8">• Validation-best model weights</FONT></TD></TR>
                <TR><TD ALIGN="LEFT"><FONT COLOR="#475569" POINT-SIZE="8">• Stable fallback checkpoints</FONT></TD></TR>
            </TABLE>>
        ];
    }

    // LLM REASONING LAYER
    subgraph cluster_agents {
        label="🧠  LLM REASONING LAYER";
        style="filled,rounded";
        fillcolor="#eff6ff";
        color="#93c5fd";
        fontsize="12";
        fontcolor="#1e40af";

        ra [
            fillcolor="#dbeafe",
            color="#3b82f6",
            label=<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="2">
                <TR><TD><B>1. Research Agent ('The Scientist')</B></TD></TR>
                <TR><TD ALIGN="LEFT"><FONT COLOR="#1e3a8a"><B>IN:</B> Diagnostics, Ledger History, Budget</FONT></TD></TR>
                <TR><TD ALIGN="LEFT"><FONT COLOR="#1e40af"><B>OUT:</B> Pre-Registered Experiment Contract</FONT></TD></TR>
                <TR><TD ALIGN="LEFT"><FONT COLOR="#64748b" POINT-SIZE="8">• Formulates 1 single causal hypothesis</FONT></TD></TR>
                <TR><TD ALIGN="LEFT"><FONT COLOR="#64748b" POINT-SIZE="8">• Predicts ΔNDCG@10 &amp; ΔRecall@50</FONT></TD></TR>
            </TABLE>>
        ];

        ca [
            fillcolor="#dbeafe",
            color="#3b82f6",
            label=<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="2">
                <TR><TD><B>2. Code &amp; Recovery Agent ('The Coder')</B></TD></TR>
                <TR><TD ALIGN="LEFT"><FONT COLOR="#1e3a8a"><B>IN:</B> Approved Contract, Source Code, Errors</FONT></TD></TR>
                <TR><TD ALIGN="LEFT"><FONT COLOR="#1e40af"><B>OUT:</B> Isolated Git Diff Patch &amp; Tests</FONT></TD></TR>
                <TR><TD ALIGN="LEFT"><FONT COLOR="#64748b" POINT-SIZE="8">• Modifies model / feature code</FONT></TD></TR>
                <TR><TD ALIGN="LEFT"><FONT COLOR="#64748b" POINT-SIZE="8">• Fixes syntax &amp; shape bugs locally</FONT></TD></TR>
            </TABLE>>
        ];
    }

    // DETERMINISTIC KERNEL & EXECUTION
    subgraph cluster_kernel {
        label="⚙️  DETERMINISTIC INTEGRITY KERNEL & EXECUTION ENGINE";
        style="filled,rounded";
        fillcolor="#f0fdf4";
        color="#86efac";
        fontsize="12";
        fontcolor="#166534";

        profiler [
            fillcolor="#dcfce7",
            color="#22c55e",
            label=<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="2">
                <TR><TD><B>Data Profiler &amp; Diagnostics</B></TD></TR>
                <TR><TD ALIGN="LEFT"><FONT COLOR="#14532d"><B>IN:</B> Raw training tables</FONT></TD></TR>
                <TR><TD ALIGN="LEFT"><FONT COLOR="#15803d"><B>OUT:</B> Sparsity, stats, watch-time distributions</FONT></TD></TR>
            </TABLE>>
        ];

        proxy_gate [
            fillcolor="#fef9c3",
            color="#eab308",
            label=<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="2">
                <TR><TD><B>Proxy Gate (Fast Subsample Check)</B></TD></TR>
                <TR><TD ALIGN="LEFT"><FONT COLOR="#713f12"><B>IN:</B> Code patch + 5% stratified sample</FONT></TD></TR>
                <TR><TD ALIGN="LEFT"><FONT COLOR="#854d0e"><B>OUT:</B> Pass (promote to full) / Fast Reject</FONT></TD></TR>
            </TABLE>>
        ];

        train_exec [
            fillcolor="#dcfce7",
            color="#22c55e",
            label=<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="2">
                <TR><TD><B>Training &amp; Inference Engine</B></TD></TR>
                <TR><TD ALIGN="LEFT"><FONT COLOR="#14532d"><B>IN:</B> Approved patch + Full Train Split</FONT></TD></TR>
                <TR><TD ALIGN="LEFT"><FONT COLOR="#15803d"><B>OUT:</B> Validation Predictions + Checkpoints</FONT></TD></TR>
            </TABLE>>
        ];

        evaluator [
            fillcolor="#dcfce7",
            color="#22c55e",
            label=<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="2">
                <TR><TD><B>Official KuaiRand Evaluator</B></TD></TR>
                <TR><TD ALIGN="LEFT"><FONT COLOR="#14532d"><B>IN:</B> Predictions + Validation Split</FONT></TD></TR>
                <TR><TD ALIGN="LEFT"><FONT COLOR="#15803d"><B>OUT:</B> Signed Metric Receipt (NDCG@10, Recall@50)</FONT></TD></TR>
            </TABLE>>
        ];

        recovery [
            fillcolor="#fee2e2",
            color="#ef4444",
            label=<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="2">
                <TR><TD><B>Auto-Recovery Controller</B></TD></TR>
                <TR><TD ALIGN="LEFT"><FONT COLOR="#7f1d1d"><B>IN:</B> CUDA OOM, NaN Loss, Timeouts</FONT></TD></TR>
                <TR><TD ALIGN="LEFT"><FONT COLOR="#991b1b"><B>OUT:</B> Batch half, Mixed Precision, Rollback</FONT></TD></TR>
            </TABLE>>
        ];

        watchdog [
            fillcolor="#dcfce7",
            color="#22c55e",
            label=<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="2">
                <TR><TD><B>Convergence &amp; Budget Watchdog</B></TD></TR>
                <TR><TD ALIGN="LEFT"><FONT COLOR="#14532d"><B>IN:</B> Metric receipt, Token &amp; GPU Counters</FONT></TD></TR>
                <TR><TD ALIGN="LEFT"><FONT COLOR="#15803d"><B>OUT:</B> Next Loop Route / Finalize Signal</FONT></TD></TR>
            </TABLE>>
        ];

        finalizer [
            fillcolor="#fef3c7",
            color="#f59e0b",
            label=<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="2">
                <TR><TD><B>Finalizer &amp; Packaging</B></TD></TR>
                <TR><TD ALIGN="LEFT"><FONT COLOR="#78350f"><B>IN:</B> Best Model + Sealed Test Features</FONT></TD></TR>
                <TR><TD ALIGN="LEFT"><FONT COLOR="#92400e"><B>OUT:</B> Submission predictions.csv &amp; Audit Log</FONT></TD></TR>
            </TABLE>>
        ];
    }

    submission [
        fillcolor="#fef08a",
        color="#ca8a04",
        shape="box",
        style="filled,rounded",
        label=<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="2">
            <TR><TD><B>🏆 FINAL SUBMISSION ARTIFACT</B></TD></TR>
            <TR><TD ALIGN="CENTER"><FONT COLOR="#713f12" POINT-SIZE="9">• predictions.csv (NDCG@10 &amp; Recall@50)</FONT></TD></TR>
            <TR><TD ALIGN="CENTER"><FONT COLOR="#713f12" POINT-SIZE="9">• Full Reproducible Audit Log &amp; Diff Receipts</FONT></TD></TR>
        </TABLE>>
    ];

    // PIPELINE EDGES
    d_train -> profiler [label=" Read raw data", color="#64748b"];
    profiler -> ra [label=" 1. Diagnostics profile", color="#2563eb", penwidth=1.5];
    ledger -> ra [label=" Past experiment memory", color="#64748b"];

    ra -> ca [label=" 2. Approved Contract\\n(Hypothesis & Targets)", color="#2563eb", penwidth=2.0];
    ca -> proxy_gate [label=" 3. Code Diff Patch", color="#2563eb", penwidth=1.5];

    proxy_gate -> train_exec [label=" Passed filter (Promoted)", color="#16a34a", penwidth=1.5];
    proxy_gate -> ledger [style="dashed", label=" Fast rejected", color="#dc2626"];

    d_train -> train_exec [label=" Train split", color="#64748b"];
    train_exec -> evaluator [label=" Val predictions", color="#16a34a", penwidth=1.5];
    d_val -> evaluator [label=" Ground truth", color="#64748b"];

    train_exec -> recovery [style="dashed", label=" Crash / OOM / NaN", color="#ef4444", penwidth=1.2];
    recovery -> train_exec [style="dashed", label=" Auto-tune parameters", color="#ef4444"];
    recovery -> ca [style="dashed", label=" If code bug", color="#ef4444"];

    evaluator -> watchdog [label=" 4. Signed Metric Receipt", color="#16a34a", penwidth=1.5];
    watchdog -> ledger [label=" Log run & diff", color="#64748b"];
    watchdog -> ckpt_store [label=" Save checkpoint", color="#64748b"];

    watchdog -> ra [label=" 5. Loop (If not converged)", color="#2563eb", penwidth=2.0];
    watchdog -> finalizer [label=" 6. Converged / Budget reached", color="#d97706", penwidth=2.0];

    ckpt_store -> finalizer [label=" Best Model weights", color="#64748b"];
    d_test -> finalizer [label=" Test features only", color="#dc2626"];
    finalizer -> submission [label=" 🏆 Generate package", color="#ca8a04", penwidth=2.0];
}
"""

os.makedirs("docs/architecture/diagrams", exist_ok=True)
with open("docs/architecture/diagrams/rigor-rs-kuairand-architecture.dot", "w") as f:
    f.write(dot_source)

# Compile to PNG and SVG
subprocess.run(["/opt/homebrew/bin/dot", "-Tpng", "docs/architecture/diagrams/rigor-rs-kuairand-architecture.dot", "-o", "docs/architecture/diagrams/rigor-rs-kuairand-architecture.png"], check=True)
subprocess.run(["/opt/homebrew/bin/dot", "-Tsvg", "docs/architecture/diagrams/rigor-rs-kuairand-architecture.dot", "-o", "docs/architecture/diagrams/rigor-rs-kuairand-architecture.svg"], check=True)

print("Successfully generated PNG and SVG diagrams.")
