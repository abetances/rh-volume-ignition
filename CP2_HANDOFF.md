# CP2 handoff — GPT Sol / MiniMax

## Current truth (2026-09-06)
CP1 independently accepted code foundation only: 69 tests across three projects; review at /home/neo/rh-factory-control/reviews/CP1_REVIEW.md. All live/running flags remain false. User requested a token-saving priority pass and will assign remaining work to GPT Sol or MiniMax. Do not start additional agents or change model routing on that basis alone.

## Priority patch completed locally, NOT independently accepted or committed
Repo /home/neo/rh-volume-ignition, base 07b897fa77c2f3e2a2fc98d68c7c7b075ba697a2.
- src/scanner/__init__.py: removed transaction-only parser filtering; cache identifies block/transaction/log/transaction hash, retaining multiple logs per transaction.
- Persistence now gates ingestion count and downstream processing. Cache updated only after successful insert; failures remain retryable. Observation stats use aware UTC.
- tests/test_ingestion_persistence.py (new): real temporary SQLite multi-log persistence and restart idempotence; failed-write and exception retry regressions.
- tests/test_source_evidence.py: fixture cache rename.
Verified: PYTHONDONTWRITEBYTECODE=1 venv/bin/python -m pytest -q -p no:cacheprovider => 35 passed, 3 preexisting utcnow warnings. git diff --check passed.
No services, production DBs, credentials, paper/live trades or registry acceptance flags changed. No commit/push pending independent review.

## Important limitations: do not overclaim this patch
This is legacy single-chain dedup/accounting repair, NOT full verified event identity. SQLite still uniquely keys block/tx/log and does not distinguish chains or reorg hashes. insert_event still conflates duplicate/failed writes as False. A retryable cache does NOT ensure durable retry: existing MAX(event block) cursor and 100-block cap can skip gaps. Downstream processing is not transactional/exactly-once: a crash after commit can lose signal delivery. Do not activate the scanner as verified ingestion.

## Next work, priority order
1. Volume verified ingestion: reuse RPCProvider/ProviderManager/Scanner/SQLite. Verify chain 4663 and header timestamp/hash; reject mismatches and removed/reorg logs. Use isolated verified dataset, full chain/block-hash/tx/log identity, explicit inserted/duplicate/error results. Persist contiguous successful range cursor (including empty blocks); failures must block advancement; remove silent 100-block history truncation. Test restart, gaps, retries, hash mismatch, duplicate accounting. Actual source-event lag must replace request-latency-as-lag. Repair missing get_flow_analyzer factory, but inspect automatic paper execution before enabling anything. Keep ingestion-only path non-trading.
2. Indexer /home/neo/rh-onchain-indexer: reuse ProtocolTradeDecoder, ChainIndexer, wallet ledger. Implement v4 pool-ID/currency metadata and signed deltas, token decimals/HIMS quote evidence. Pool/router is never automatically buyer. Resolve deterministic storage path. Bounded resumable BONER/MEME capture with raw receipts/headers; independently verify at least 5 buys AND 5 sells. Incomplete launch coverage => earliest observed, never first buyers.
3. Volume cross-chain adapters AFTER ingestion edits: centralized rate-limited Gecko snapshots for four chains, DEX enrichment, deduplicated monitored pools, source/observation timestamps and missing/stale coverage. Unsupported 1m and independent buyers stay unknown. No UI.
4. Independent review must accept raw replay/live evidence before CP2 commit/push or any live promotion. CP1 review is not CP2 approval. Preserve all unresolved blockers and update factory registry only with accepted evidence.

Read repo AGENTS.md and run scripts/safety_guard.sh --assert-root before volume changes. Factory control inherits /home/neo Git root: never broad-stage. Do not touch unrelated files or existing indexer pycache. Keep tasks bounded to save tokens.
