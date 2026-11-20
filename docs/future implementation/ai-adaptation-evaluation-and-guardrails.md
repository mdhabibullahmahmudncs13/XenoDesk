# Agent Workspace AI adaptation, evaluation, and guardrails

The current Workspace uses configurable Ollama models, deterministic FAQ and read-tool routing, and tenant-scoped pgvector retrieval. The repository contains targeted behavior tests and chat usage events. A model-training pipeline and a benchmark for generated answers are future work. Implement the evaluation harness first so that changes to prompts, retrieval, guardrails, and model weights can be compared against the same baseline.

## 1. Evaluation and quality measurement

1. Add a standalone harness under `backend/evals/`. Seed synthetic businesses and their FAQ entries, ads, and retrieval chunks. Keep fixture prompts and expected outputs under version control. Start with 50 English, Bangla, and mixed-language cases covering FAQ matches, verified counts, grounded answers, missing evidence, write requests, provider failure, and privacy and tenant isolation.
2. Exercise the real [Workspace chat endpoint](../../backend/xenovarients/api/workspace.py) with disposable databases and an authenticated test principal. Use deterministic fake Ollama responses in regular CI to check route selection, references, abstention, isolation, and failure behavior. Run a separate opt-in benchmark against local Ollama for generated-answer quality. Record model identity, fixture revision, retrieval settings, and prompt revision with each report.
3. Score deterministic routes by exact match. Measure retrieval recall at the configured top K using labeled chunk IDs. Score grounded answers against the evidence and report abstention accuracy for questions with insufficient data. Use a human rubric for correctness, faithfulness, and language quality. If the dataset grows, pilot Ragas or an LLM judge on synthetic or cleared fixtures and compare its scores against human labels before using them as a release gate.
4. Report quality by route and language, along with p50/p95 latency and failure counts. Reuse `AiUsageEvent` for operational diagnostics. The current generated-answer pathway sets token counts and estimated cost to zero. Capture provider-reported usage when available before using those values for cost comparisons. Require all deterministic privacy and authorization cases to pass. Set quality targets after recording the baseline, and rerun the benchmark for prompt, retrieval, or model changes.

## 2. Market Intelligence fine-tuning

**Status:** Planned. Train a dedicated LoRA adapter to turn verified sourcing snapshots into clear English and Bangla market briefs. The adapter should explain recorded price ranges, demand signals, freshness, and source coverage and abstain when evidence is missing. The existing research pipeline remains responsible for collecting signals and computing figures. Product facts continue to come from the current snapshot at inference time.

1. Benchmark the base model on snapshot-to-brief tasks. Reuse the payload shape produced by [market research](../../backend/xenovarients/platform/market/research.py). Include fresh, stale, partial, and unavailable signals.
2. Build an offline dataset of licensed, synthetic, or approved snapshot-to-brief examples with customer identifiers removed. Each target brief includes source references, dates and any limitations. Hold out product families and capture periods, and keep paraphrases of the same snapshot in one split. Record provenance and the exact base checkpoint.
3. Train the adapter with Hugging Face PEFT and validate it against the exact compatible Ollama serving base. Register it under a dedicated model tag. Add an optional `MARKET_INTELLIGENCE_CHAT_MODEL` in [backend configuration](../../backend/xenovarients/core/config.py) and use it only on a Market Intelligence summary path. Load the snapshot through the authenticated [sourcing API](../../backend/xenovarients/api/sourcing.py) and pass approved snapshot fields to the model. Return the original snapshot when the setting is disabled or summary generation fails. [PEFT documentation](https://huggingface.co/docs/peft/package_reference/lora) · [Ollama Modelfile reference](https://docs.ollama.com/modelfile)
4. Compare the candidate to the base model on price and currency accuracy, source attribution, freshness labels, abstention, bilingual clarity, and latency. Hold back any candidate that invents prices or demand figures on the release set. Roll back by disabling the dedicated setting.

## 3. Guardrails, safety, and privacy

1. Extend [the LLM guard](../../backend/xenovarients/platform/llm/guard.py) to sanitize data before both Ollama calls. Keep the existing deterministic routing inputs, but sanitize chat text before sending it to chat or embeddings. Sanitize evidence on ingestion where feasible and again before passing it to a model. Apply the same handling to future MCP responses. Test Bangla and English identifier formats. Define retention and access for raw chat records separately because the chat route currently persists the user's original message.
2. Preserve [tenant-scoped retrieval](../../backend/xenovarients/platform/vector/store.py), backend role checks, and the read-tool allowlist. Treat user input and retrieved content as untrusted. Encode retrieved content so record text cannot imitate prompt delimiters. Keep all changes and sends behind authorized API workflows. Test refusal behavior with multilingual intent fixtures, untrusted instructions in retrieved data, unsupported requests, and two seeded tenants.
3. Validate generated responses at the Ollama boundary. Add a typed answer result with an answer or abstention and a bounded list of evidence IDs. Accept references only from the tenant-scoped retrieval results. Handle invalid JSON, unknown references, output PII, and provider errors with a safe fallback and a low-cardinality outcome code. Evidence-ID checks establish reference validity. Use the evaluation rubric to measure whether each claim follows from its evidence.
4. Add moderation only for a defined product policy. Document the categories, expected responses, language coverage, and fallback behavior. Measure false refusals on legitimate FAQ and sourcing questions before enabling blocking. Keep raw prompts, retrieved records, and credentials out of telemetry.

## 4. Measure which questions need a model

Extend the existing chat usage events in [the Workspace handler](../../backend/xenovarients/api/workspace.py). Record the actual route and outcome for FAQ, blocked request, deterministic lookup, successful model answer, and model-unavailable fallback. Calculate the share of eligible questions answered by FAQ or verified lookups, along with latency and fallback rate by route. Verify that FAQ and deterministic lookup cases make zero Ollama calls and that an unavailable model is counted as a fallback. Use aggregate counts and exclude raw questions and retrieved data from telemetry.

## Rollout checks

- Compare each change against the versioned baseline and run authorization and privacy cases before release.
- Verify a model-service outage returns the safe fallback and a correctly classified usage event.
- Verify no raw customer identifiers leave Workspace across the tested chat and embedding payloads.
- Keep the baseline model selectable and make optional benchmark and training dependencies independent of API startup.
