# Plan_MCP.md — Research Knowledge MCP

## Context
Implement the complete local Research Knowledge MCP described by `MCP_KNOWLEDGE_LAYER_v1.svg` and Architecture v3. It supplies bounded, source-linked paper and code evidence to the Research Agent and Code & Recovery Agent; it never controls training, changes competition rules, or becomes a source of benchmark labels. The service starts from the human-curated 25-paper JSON, expands through OpenAlex and GitHub only within configured caps, sanitizes all external text, and remains useful offline from its local SQLite store.

The repository currently contains the architecture documents but no MCP source, Python package scaffold, or curated-paper JSON. Create the implementation under the shared `src/rigor_rs/` package defined in Plan_Workflow.md; keep the human-owned seed file at `data/research/curated_papers.json`.

## Approach

### 1. Establish a free, local-first MCP stack and package boundary
1. Use Python 3.12 with `uv` for environment and lockfile management. Add the official Python MCP SDK/FastMCP, Pydantic v2, HTTPX, and PyYAML. Use standard-library `sqlite3`, `asyncio`, `hashlib`, and `urllib.parse` wherever they are sufficient.
2. Use one SQLite database at `state/knowledge.sqlite3` in WAL mode. Enable SQLite FTS5 for BM25 keyword retrieval and `sqlite-vec` for the vector index. If the Windows environment cannot load `sqlite-vec`, use the pre-decided compatibility backend: store float32 embeddings as blobs and run deterministic NumPy cosine search over this bounded corpus; retain the same repository and MCP interfaces.
3. Generate local embeddings with `fastembed` and `sentence-transformers/all-MiniLM-L6-v2` at 384 dimensions. Pin the downloaded model revision and its file hashes in `state/models/manifest.json`; no Bedrock call is used for embeddings. This keeps retrieval free after the one-time model download and separates research-library cost from agent-token cost.
4. Organize code by behavior:
   - `src/rigor_rs/knowledge/models.py` — Pydantic input/output and stored-record models.
   - `src/rigor_rs/knowledge/store.py` and `schema.sql` — transactions, append-only ingestion events, FTS, vectors, and migrations.
   - `src/rigor_rs/knowledge/providers/openalex.py`, `github.py`, and `papers_with_code.py` — replaceable read-only adapters.
   - `src/rigor_rs/knowledge/ingestion.py` — curated, scheduled, and on-demand ingestion through one queue.
   - `src/rigor_rs/knowledge/sanitize.py` — text normalization, prompt-injection flags, and quarantine decisions.
   - `src/rigor_rs/knowledge/retrieval.py` — hybrid ranking and evidence assembly.
   - `src/rigor_rs/knowledge/cache.py` and `budgets.py` — canonical query cache, request/document/token caps, rate limits, and bounded backoff.
   - `src/rigor_rs/mcp/server.py` — the only MCP-facing tool definitions.
   - `src/rigor_rs/cli/knowledge.py` — human-only ingestion, validation, status, and reindex commands.
5. Run the MCP over stdio for the local LangChain/LangGraph clients. Add optional loopback-only Streamable HTTP transport for MCP Inspector and development; do not bind it beyond `127.0.0.1` and do not add a hosted service.

### 2. Keep the curated JSON, but turn it into a validated source manifest
1. Keep JSON as the best human-editable source for the 25 curated papers: it is reviewable, version-controlled, and easy to diff. Do not query this JSON directly during agent runs; ingest it into SQLite and generate the BM25/vector indexes.
2. Replace the loose object shape with a versioned document:
   ```json
   {
     "schema_version": 1,
     "papers": [
       {
         "paper_id": "stable-kebab-id",
         "title": "Exact title",
         "authors": ["Name"],
         "year": 2024,
         "venue": "Venue",
         "priority_areas": ["ranking_loss"],
         "relevance_notes": "Why this can inform a KuaiRand experiment",
         "keywords": ["BPR", "within-user ranking"],
         "identifiers": {"doi": null, "arxiv_id": null, "openalex_id": null},
         "paper_url": "https://...",
         "abstract": null,
         "license": null,
         "github_repositories": [
           {"url": "https://github.com/owner/repo", "commit": null, "license": null}
         ]
       }
     ]
   }
   ```
3. Require `paper_id`, `title`, `year`, at least one `priority_area`, `relevance_notes`, `keywords`, and either a stable identifier or `paper_url`. Normalize DOI/arXiv/OpenAlex IDs and reject duplicate identifiers. Preserve the user’s original priority areas and notes as `trust_tier="curated"`; API enrichment must not overwrite them.
4. Do not put actual repository code in the JSON or knowledge database. Resolve GitHub URLs to an exact default-branch commit SHA, repository license, stars, topics, and retrieval timestamp. The Code Agent later checks out that exact commit inside an isolated experiment worktree and records hashes for files it actually uses.
5. During curated ingestion, enrich missing title/authors/abstract/identifiers/license from OpenAlex when possible. If no licensed abstract is available, index the title, keywords, and relevance notes and set `content_completeness="metadata_only"`; do not scrape arbitrary PDFs to hide the gap.
6. Add `python -m rigor_rs.cli knowledge validate --file data/research/curated_papers.json` and `... knowledge ingest-curated`. Validation must print field-level errors without mutating SQLite. Ingestion is idempotent by normalized identifier plus content hash and appends an ingestion event even when a record is unchanged.

### 3. Implement all source adapters behind one narrow interface
1. Define `KnowledgeProvider.search(query, filters, limit)`, `get_work(identifier)`, and optional `get_citations(identifier, direction, limit)`. Provider responses return normalized records and raw response hashes; downstream code never depends on provider-native JSON.
2. OpenAlex is the primary paper source:
   - support work search, exact work lookup, citation expansion, retraction flag, open-access/license metadata, canonical DOI/arXiv/OpenAlex IDs, and reconstructed abstract where supplied by OpenAlex;
   - send a configured contact email in the polite-pool request parameter when provided;
   - never fetch hidden benchmark data or use OpenAlex content as model training data.
3. GitHub is the code-discovery source:
   - use official REST search endpoints in read-only mode;
   - search repositories first and code only when a tool explicitly asks for it;
   - capture repository URL, exact commit SHA, license, stars, topics, source URL, and response hash;
   - do not execute, import, or clone retrieved code inside the MCP service.
4. Keep Papers-with-Code disabled by default because the architecture marks its API optional/legacy. Implement its provider interface as configured-unavailable until the project owner supplies and verifies a stable endpoint; a disabled provider must return a typed `provider_unavailable` result and must not block OpenAlex/GitHub/local retrieval.
5. All outbound calls use provider-specific timeouts, rate buckets, and bounded retry for timeout, `429`, and `5xx`. Retry at most three times with server `Retry-After` respected; log the original failure, each attempt, and final fallback to cached/local evidence. Do not retry `4xx` input/auth errors except `429`.

### 4. Route every ingestion path through one durable queue
1. Implement a SQLite-backed ingestion queue with states `pending | processing | succeeded | rejected | failed`, unique normalized work key, source, requested query, attempt count, lease timestamp, and last error. This avoids Redis/Celery and remains restart-safe on one machine.
2. Feed the same queue from:
   - curated JSON ingestion;
   - scheduled OpenAlex discovery by configured priority area;
   - on-demand cache misses from MCP tools.
3. Expose `python -m rigor_rs.cli knowledge ingest-scheduled --once`. The main workflow scheduler may invoke it weekly; do not require a permanently running cron service. A repeated command must resume expired leases and never duplicate a stored paper.
4. Process each record in this fixed order: normalize identity → license/retraction gate → sanitize text → extract metadata → resolve code links → generate embedding → content hash → atomic storage/index update → append ingestion receipt.
5. Reject retracted works by default. Store a minimal rejection receipt with identifier, source, reason, and response hash, but do not index the content. For unknown or restrictive licenses, store link/metadata that may legally be retained; do not store or return full text.

### 5. Treat external material as evidence, never instructions
1. Store `raw_content_hash`, sanitized text, sanitizer flags, and `sanitizer_version`; do not store raw full text unless license permits and the architecture needs it.
2. Normalize Unicode, remove control/bidirectional-hidden characters, discard hidden HTML/CSS text, cap each field’s length, and flag instruction-like phrases that attempt to address an agent, request secrets, override rules, or invoke tools.
3. A flag does not silently rewrite scientific statements. Quarantine high-risk records from prompt-facing tools and return metadata plus `quarantined=true`; low-risk records return sanitized text plus flags. Every Research Agent prompt wraps evidence as quoted data with an explicit rule that quoted content cannot issue instructions.
4. Code comments and README text go through the same sanitizer before snippets can be returned. Repository metadata and pinned links remain available even when prose is quarantined.
5. The Research Agent may cite evidence but cannot raise its authority above organizer configuration or measured results. Each response includes `trust_tier`, source, retrieval timestamp, content hash, and license.

### 6. Build the knowledge schema and append-only receipts
1. Create normalized tables:
   - `papers`: canonical IDs, title, authors JSON, venue, year, abstract, license, retracted, trust tier, completeness, sanitized flags, content hash, retrieved time.
   - `paper_identifiers`: paper ID plus DOI/arXiv/OpenAlex identifier with uniqueness constraints.
   - `code_implementations`: repository URL, pinned commit, license, stars, topics JSON, linked paper ID, source URL, content hash, retrieved time.
   - `citation_edges`: source paper, target paper, relation, provider.
   - `paper_fts`: FTS5 title, abstract, keywords, priority areas, and relevance notes.
   - `paper_vectors`: paper ID, embedding model ID/revision, dimension, vector.
   - `query_cache`: canonical key, provider, serialized request/response references, creation/expiry, hit count.
   - `ingestion_queue` and append-only `ingestion_events`.
   - `provider_usage`: request count, documents returned, bytes, error/retry counts by session/experiment/provider.
2. Use foreign keys and transactions. Updates to a paper create a new content-version row and move the current pointer atomically; never rewrite the ingestion event that explains an earlier version.
3. Mirror only receipt IDs, tool name, query hash, selected evidence IDs, timing, and provider usage into the main run ledger. Do not copy the whole knowledge database or full paper text into experiment logs.

### 7. Implement canonical caching, caps, and hybrid retrieval
1. Build the cache key exactly from `provider + normalized_query + canonical_filters + cutoff_date + result_limit`. Normalize whitespace/case without stemming away technical tokens, sort filter keys and list values, and hash canonical UTF-8 JSON with SHA-256.
2. Enforce independent per-session and per-experiment caps loaded from `configs/budgets/competition.yaml`:
   - outbound provider requests;
   - returned documents;
   - MCP response characters;
   - Bedrock tokens remain enforced by the workflow’s LLM budget, not guessed by MCP.
   Cache hits consume returned-document/response-size budgets but not outbound-request budget.
3. Search FTS5 BM25 and vector similarity independently, then combine ranks with reciprocal-rank fusion `score = Σ 1/(60 + rank)`. Use `trust_tier=curated` only as a deterministic tie-breaker when relevance ranks are otherwise equal; do not let curation override a clearly irrelevant result.
4. Apply filters before final ranking: year range, venue, priority area, trust tier, retraction exclusion, license availability, and code availability. Return why each record matched: exact terms, semantic similarity, curated note, or citation expansion.
5. On no relevant local result and available request budget, perform one bounded OpenAlex fetch, ingest/index the result, and rerun local search. On outage/cap exhaustion, return the best local results with `source_mode="local_fallback"`; never fabricate a citation.

### 8. Expose the exact MCP tool surface
Implement these FastMCP tools with Pydantic validation, maximum limits from config, and structured errors:
1. `search_evidence(query: str, semantic: bool = true, filters: EvidenceFilters | None = None, max_results: int = 8) -> EvidenceSearchResult`.
2. `get_paper(paper_id: str) -> PaperRecord` — metadata, abstract when permitted, provenance, sanitizer flags, and linked code summaries.
3. `get_fulltext(paper_id: str) -> FullTextResult` — only stored licensed full text; otherwise return `available=false` and the lawful source link. Do not fetch arbitrary PDFs during the tool call.
4. `search_code(query: str, language: str = "Python", min_stars: int = 0, max_results: int = 5) -> CodeSearchResult`.
5. `get_code_for_paper(paper_id: str) -> CodeForPaperResult` — pinned repository/commit/license metadata, never an unpinned branch.
6. `expand_citations(work_id: str, direction: Literal["cites", "cited_by"], max_results: int = 10) -> CitationExpansionResult`.
7. `get_research_card(hypothesis: str, max_evidence: int = 6) -> ResearchCard` — deterministic retrieval result containing supporting, contradicting, and missing-evidence sections plus source IDs. The Research Agent performs any Bedrock summarization outside MCP so this tool has no hidden LLM cost.
8. Keep `submit_curated_paper` human-only as the CLI validation/ingestion path; do not register it as an agent-callable MCP tool.
9. Every response includes `request_id`, `cache_status`, `source_mode`, selected record IDs, provenance, cap usage, and warnings. Errors use `invalid_request | not_found | provider_unavailable | budget_exhausted | quarantined | transient_failure`; never return a fake empty success when a provider failed.

### 9. Connect MCP to LangChain agents and the UI without coupling it to training
1. Register MCP tools with the Research Agent for evidence search/research cards and with the Code & Recovery Agent only for code search/pinned implementation lookup. Do not expose ingestion, database, arbitrary URL fetch, shell, or write tools.
2. Before each agent call, the context compiler selects bounded MCP results and logs only evidence IDs and hashes. After the call, validate every cited evidence ID exists in the tool response.
3. Publish MCP tool-call lifecycle events to the main event ledger: queued, cache/local/live source, provider usage, selected evidence IDs, duration, warning/failure. Plan_UI.md displays these through the `Find Research Evidence` node and Research Library route.
4. MCP unavailability pauses only new LLM planning if no local evidence is adequate. Deterministic preprocessing, training, evaluation, replay, and finalization continue without MCP.

## Critical files & anchors
- `docs/architecture/diagrams/MCP_KNOWLEDGE_LAYER_v1.svg` — source adapters, ingestion queue, processing chain, store, serving layer, and exact tool names around lines 33–307.
- `docs/architecture/ARCHITECTURE_v3_kuairand.md` — canonical cache/caps, curated corpus, local GitHub adapter, optional Papers-with-Code, and MCP-to-agent roles around lines 62–117 and 134–143.
- `docs/architecture/Design-Decision.md` — hybrid retrieval, curation limits, cache key, provider status, and code provenance around lines 13–34 and 89–101.
- `docs/architecture/ARCHITECTURE_v2_kuairand.md` — authority/capability rules and optional evidence gateway; v3 overrides any obsolete task metrics.
- `AGENTS.md` — competition data, baseline, logging, resource, and no-hidden-test constraints already loaded as repository policy.

## Verification
1. Validate the owner-provided 25-paper JSON. Expect exactly 25 unique `paper_id` values, no duplicate normalized identifiers, field-level errors for malformed records, and zero SQLite writes during validation.
2. Ingest the file twice. Expect the second run to create an `unchanged` receipt but no duplicate paper, FTS, vector, identifier, or code row.
3. Search an exact term such as `GAUC`, a semantic query such as `loss aligned with within-user ranking`, and a filtered priority area. Expect relevant curated results, matching-reason fields, stable ordering, valid citations, and identical cached results for canonically equivalent queries.
4. Simulate a local miss with OpenAlex enabled. Expect one bounded provider fetch, sanitizer/license processing, index update, then a locally served result. Repeat the query and expect zero outbound requests. Exhaust the request cap and expect `budget_exhausted` or local fallback with truthful metadata.
5. Inject hidden Unicode, HTML-hidden instructions, “ignore prior rules,” secret requests, and tool-invocation text into provider fixtures. Expect flags/quarantine and no unsafe text in prompt-facing MCP responses.
6. Test retracted, unknown-license, missing-abstract, absent-code, deleted-repository, GitHub `401`, `429`, timeout, and OpenAlex outage fixtures. Expect the prescribed typed result, bounded attempts, append-only receipts, and no fabricated metadata.
7. Run MCP Inspector against loopback transport and call all seven agent tools. Validate input limits, output schemas, provenance, hashes, and that `submit_curated_paper` is absent.
8. Run a LangChain integration smoke where the Research Agent calls `search_evidence` and cites returned IDs; reject an answer that cites an ID not present in the tool response. Run an offline smoke with network disabled and confirm curated local retrieval still works.
9. Compare `provider_usage`, cache events, and selected evidence IDs against the main run-ledger mirror for the same request ID; they must agree exactly.

## Required from the project owner
- Add the curated 25-paper source as `data/research/curated_papers.json` using the schema above. Existing priority areas, relevance notes, year, venue, keywords, paper links, and GitHub links are retained; add stable IDs and titles, while ingestion can enrich missing abstracts/identifiers/licenses.
- Provide `GITHUB_TOKEN` with public-repository read permission if live GitHub search is enabled. Do not paste it into YAML, commands, logs, or the UI.
- Provide `OPENALEX_MAILTO` for polite-pool requests. OpenAlex does not require a paid key in this architecture.
- Provide a stable Papers-with-Code endpoint only if that optional adapter should be enabled; otherwise it remains disabled.
- Permit the one-time download of the pinned local embedding model. No vector database account, Redis, hosted search service, or paid MCP platform is required.

## Assumptions & contingencies
- External evidence is optional and lower-authority than organizer configuration and measured runs. If all providers are unavailable, the Research Agent uses the curated local store and records the outage.
- The corpus remains small enough for local SQLite. If it grows beyond practical local vector scanning and `sqlite-vec` is unavailable, stop automatic expansion at the configured document cap rather than introducing a hosted vector database.
- Actual repository code remains outside the paper JSON and knowledge DB. If a GitHub link lacks a resolvable commit or license, return it as unverified metadata and prevent the Code Agent from using it.

