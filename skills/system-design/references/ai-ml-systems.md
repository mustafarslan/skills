# AI, ML and GenAI systems

Last verified: 2026-11 (re-check numbers and provider limits older than 12 months).

## Contents
- [Framing an ML problem](#framing-an-ml-problem)
- [Data and features](#data-and-features)
- [Training pipeline](#training-pipeline)
- [Serving predictions](#serving-predictions)
- [Monitoring and drift](#monitoring-and-drift)
- [Recommendation and ranking systems](#recommendation-and-ranking-systems)
- [RAG: ingestion](#rag-ingestion)
- [RAG: retrieval](#rag-retrieval)
- [Vector index sizing](#vector-index-sizing)
- [LLM serving](#llm-serving)
- [Agents and tool use](#agents-and-tool-use)
- [Safety and guardrails](#safety-and-guardrails)
- [Evaluation](#evaluation)
- [Cost](#cost)
- [Traps](#traps)

## Framing an ML problem
- Business goal → ML objective → label → metric. ("Reduce churn" → predict 30-day churn → label
  from cancellations → precision at the top 5% the retention team can contact.)
- Is ML needed? A rule or a query may do. What is the cost of a wrong prediction (false positive
  vs false negative)?
- Online (per request, latency-bound) vs batch (precomputed) predictions.

## Data and features
- Sources, labels (implicit vs explicit, delayed labels), class imbalance, leakage (features that
  encode the label or the future).
- **Feature store**: one definition of each feature for training (offline, point-in-time correct)
  and serving (online, low latency) - prevents training/serving skew.
- Privacy: PII in features, consent, retention, the right to deletion reaching training sets.

## Training pipeline
- Reproducible: versioned data snapshots, code, config, model artifacts (model registry).
- Validation gates before promotion: offline metrics vs current model, slice metrics (by country,
  device, new users), fairness checks.
- Retraining cadence driven by drift, not the calendar alone.

## Serving predictions
- Batch scoring written to a store vs online inference service (CPU or GPU), with a feature
  fetch on the path - count its latency.
- Multi-stage for large candidate sets: candidate generation (cheap, recall) → ranking (expensive,
  precision) → re-ranking for business rules and diversity.
- Rollout: shadow mode → A/B test (or interleaving for ranking) → ramp; guardrail metrics.
- Fallback when the model service is down: a previous model, a heuristic, a cached result.

## Monitoring and drift
- Data drift (inputs change), concept drift (input → label relation changes), prediction drift.
- Monitor feature distributions, prediction distributions, online business metrics, and label-based
  metrics once labels arrive.
- Feedback loops: the model shapes the data it is later trained on (recommendations); keep some
  exploration.

## Recommendation and ranking systems
- Signals: implicit (clicks, watch time) and explicit (ratings); cold start for new users/items.
- Two-tower embeddings for retrieval + an ANN index; a ranking model on top.
- Freshness: near-real-time features for session behaviour.

## RAG: ingestion
- Parse sources (PDF, HTML, tickets), keep metadata: source URL, timestamps, owner, **access
  control lists** (needed for permission-filtered retrieval).
- Chunk by structure (headings, paragraphs) with a recursive fallback; small chunks (~100-300
  tokens) retrieve precisely but lose context, large ones (1,000+) keep context but blur
  relevance; overlap ~10-15%. Measure on your own eval set.
- Incremental updates and deletes (a deleted document must leave the index); re-embedding when
  the embedding model changes (dual-write a new index, compare recall on a golden set, then
  switch - blue/green).

## RAG: retrieval
- **Hybrid search**: dense vectors + sparse keyword (BM25) in parallel, merged with reciprocal
  rank fusion; dense alone misses exact identifiers, SKUs and names.
- **Permission filtering before ranking/generation**: filter by the user's ACLs in the index
  query, never after generation. Get the ACL semantics right per source:
  - **intersections** (see the trap below);
  - **deny** entries, and what "unknown ACL" means (fail closed: hide the document);
  - **identity-side revocation** (removed from a group, user disabled) - state how fast it takes
    effect (cache invalidation on directory events) separately from document-side ACL sync;
  - a live source check for the most sensitive content if index lag is not acceptable;
  - **over-sharing audit** before launch: org-wide documents with sensitive content become
    findable by everyone the moment search works.
- Residency is not sovereignty: data in an EU region of a US provider may still be reachable
  under US law; name it as a risk when the brief says "must stay in the EU".
- Re-rank the top-k with a cross-encoder; assemble context within the token budget; cite sources.
- Query rewriting for conversational follow-ups.

## Vector index sizing
- Memory ≈ N × (d × bytes_per_dim + M × 16) × 1.2 for HNSW (fp32 = 4 bytes/dim, int8 = 1, binary
  1/8 with rescoring). Product quantization: N × (code bytes + 8). Run the calculator's
  `--vectors/--dim/--hnsw-m/--pq-bytes`.
- HNSW: high recall, low latency, RAM-heavy. IVF-PQ / disk-based ANN: far less RAM, lower recall
  or higher latency. Quantization cuts memory ~3-4x, but the graph does not shrink.
- Filtered search (metadata filters) can wreck recall or latency in some engines; check.

## LLM serving
- Latency: time to first token (stream tokens to mask total time) and tokens per second; budget
  both.
- GPU memory = weights + **KV cache** (grows with batch size × context length); continuous
  batching raises throughput at some latency cost.
- Hosted API vs self-hosted: per-token price, rate limits and data policy vs GPU fleet and ops.
- **Model routing**: a small model for easy requests, a large one for hard ones; fallbacks across
  providers for availability.
- Caching: exact prompt caching, provider prompt-prefix caching, semantic caching (risky for
  personalised or permissioned answers).
- Timeouts and retries are expensive: idempotent requests, budgets per user.

## Agents and tool use
- Bound the loop: max steps, max cost, timeouts; tools with least privilege and confirmation for
  destructive actions.
- Durable state for long-running agents (workflow engine), resumable after failure.
- Observability per step: inputs, tool calls, outputs, cost.

## Safety and guardrails
- Prompt injection (especially indirect, through retrieved documents and tool outputs): treat
  retrieved text as data; restrict what tools an injected instruction could trigger.
- PII and secret leakage in inputs and outputs; output filters; logging policy for prompts.
- Grounding and citations; refusal behaviour; human review for high-stakes actions.

## Evaluation
- Offline: a golden set with expected answers or judgements; retrieval metrics (recall@k,
  precision), generation metrics (faithfulness to context, answer relevance), LLM-as-judge
  calibrated against humans.
- Online: thumbs up/down, task success, escalation rate, A/B tests.
- Regression gate on every prompt, model or index change.

## Cost
- Cost per request = tokens in × price + tokens out × price (+ retrieval, + reranking); estimate
  per user per month at expected usage.
- Levers: shorter prompts and contexts, caching, routing, batching, distilled or quantized models.

## Traps

### ACLs that are intersections are not a principal list
**Seen in:** blind-graded eval `c-rag` (enterprise RAG, 8M documents), 2026-11-02 - the
skill's design flattened ACLs; the no-skill design did not.
**Mistake:** storing each document's readers as one flat list of users and groups.
**Instead:** model sources whose rules combine (Confluence page + ancestor restrictions, Jira
project scheme ∩ issue security level) as synthetic intersection principals or a second filter,
and test with a user who satisfies only one side.
**Why:** a union of the two lists leaks every document guarded by "A and B" to holders of A.
