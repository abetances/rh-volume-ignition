# Volume Ignition — CP1 foundation repair

Status: PASS_CODE_FOUNDATION_ONLY. Not live.
Base HEAD: 0950447. Accepted checkpoint commit recorded in factory registry.

## Changes
- Corrected stale local project boundary to /home/neo/rh-volume-ignition; safety guard passes.
- Replaced provider-origin eval with JSON parsing and bounded, literal-only historical Python-dict parsing. Invalid payloads cannot generate signals.
- Source timestamps accept explicit UTC/offset ISO or integer/hex epoch. Unknown/invalid/naive source times are rejected, not replaced with ingestion clock time.
- Unknown source timestamps increment scanner coverage counter. Provider name and explicitly UNVERIFIED chain identity preserved in new raw-reference ingestion metadata.
- RawEvent no longer defaults source time to now; flow decoder also rejects missing source times.
- Historical SQLite untouched; no provenance relabeling, no service startup.

## Verification
`PYTHONDONTWRITEBYTECODE=1 venv/bin/python -m pytest -p no:cacheprovider tests -q`
Includes existing eight rotation tests and malicious-input, legacy JSON/dict parsing, source-time preservation, missing-time and decoder rejection regressions.
Test dependencies pytest/python-dotenv/requests installed only in local venv. Tracked venv files restored after installation; dependency packaging cleanup is separate.

## Remaining activation blockers / minimum CP2
1. Pin and verify provider eth_chainId (RH mainnet expected 4663), then fetch matching block headers for logs lacking blockTimestamp. Validate header hash against log blockHash, cache per block, and persist chain identity/coverage in a new dataset; do not blend unverified historical rows.
2. Restore missing get_flow_analyzer factory (scanner lazy property/API currently reference nonexistent function), then startup/import smoke check.
3. Validate actual protocol decoders and quote valuations before buys/sells or dollar volume claims. Parent research identifies BONER v4 BONER/HIMS pool; existing ETH/18-decimal assumptions cannot establish native/dollar flow.
4. Fix transaction-only dedup (currently loses multiple logs within one tx), durable cursor/gap behavior, and insertion-success accounting before live coverage claims. Provider request latency is currently called ingest_lag_ms; it is not event lag.
5. Replay >=5 evidenced buys/sells and prove a live source→persist→deterministic evidence path with timestamps, block/tx/log identity, and truthful missing-coverage flags.

Independent code-foundation acceptance only. No live/tradeability claims.

## CP1 acceptance

Independent reviewer: /root/cp1_reviewer. Final verdict: PASS (code foundation only).
Evidence: /home/neo/rh-factory-control/reviews/CP1_REVIEW.md.
Exact accepted commit and remote verification are recorded in the factory project_registry.json after commit.
Running: false. Data live: false. Existing activation blockers remain open.
