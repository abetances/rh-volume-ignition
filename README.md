# rh-volume-ignition

Volume-before-volume scanner for Robinhood Chain.

## Purpose

Find tokens where real independent capital and buyer quality are accelerating before raw volume becomes obvious.

## Concept

```
quiet token → independent buyer acceleration → novel capital → capable actor → liquidity improves → volume expands → repricing obvious
```

## Project Isolation

This project is completely isolated from:
- rh-launch-verifier
- Any other RH Intelligence OS
- Any other trading bots

See `.rhvolume-boundary` for project root.

## Providers

- `RH_PUBLIC_RPC` - Broad/cheap log scanning
- `RH_SEQUENCER_FEED` - Low-latency live discovery
- `FALLBACK_RPC` - Targeted/high-priority reads
- `EXTERNAL_MARKET_ENRICHMENT` - Market data enrichment

## Architecture

```
src/
├── ingest/     # Chain data ingestion
├── market/     # Market data handling
├── flows/      # Flow detection
├── actors/     # Actor analysis
├── scoring/    # Scoring engine
├── storage/    # Data storage
├── api/        # API endpoints
├── ui/         # Web UI
└── common/    # Shared utilities
```

## Truthfulness Rules

Never fabricate:
- volume, market cap, liquidity, holders
- wallet ownership, actor identity
- novel capital, rotation, signal confidence

Missing = UNKNOWN with source/observed_at/confidence.
