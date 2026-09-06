#!/usr/bin/env python3
"""Validate composite ignition scoring with replay data."""

import sys
sys.path.insert(0, '.')

from datetime import datetime, timezone
import sqlite3
import ast

from src.signals.flow_analyzer import FlowAnalyzer
from src.signals.flow_processor import FlowProcessor
from src.signals import TradeFlow, SignalState, CompositeIgnitionScore


def main():
    print("=" * 60)
    print("COMPOSITE IGNITION VALIDATION")
    print("=" * 60)
    
    # Connect to DB
    db_path = "data/rh_volume_ignition.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get raw events
    cursor.execute("""
        SELECT event_id, block_number, transaction_index, log_index, tx_hash, 
               observed_at, block_timestamp, source, contract_address, 
               event_type, raw_reference
        FROM raw_events 
        ORDER BY block_number, transaction_index, log_index
        LIMIT 30000
    """)
    
    rows = cursor.fetchall()
    print(f"Loaded {len(rows)} events from DB")
    
    # Initialize processor and analyzer
    processor = FlowProcessor()
    analyzer = FlowAnalyzer()
    
    print("\nReplaying events...")
    
    for i, row in enumerate(rows):
        (event_id, block_num, tx_idx, log_idx, tx_hash, 
         observed_at, block_ts, source, contract, event_type, raw_ref) = row
        
        try:
            if isinstance(raw_ref, str):
                ref_data = ast.literal_eval(raw_ref)
            else:
                ref_data = raw_ref
        except:
            continue
        
        event = {
            "event_id": event_id,
            "block_number": block_num,
            "transaction_index": tx_idx,
            "log_index": log_idx,
            "tx_hash": tx_hash,
            "observed_at": observed_at,
            "block_timestamp": block_ts,
            "source": source,
            "contract_address": contract,
            "event_type": event_type,
            "topics": ref_data.get("topics", []),
            "data": ref_data.get("data", "0x0"),
        }
        
        flow = processor.process_event(event)
        if flow:
            analyzer.ingest_trade(flow)
        
        if i > 0 and i % 10000 == 0:
            stats = processor.get_stats()
            print(f"  Processed {i}/{len(rows)} | Buys: {stats['buy']}, Sells: {stats['sell']}")
    
    stats = processor.get_stats()
    print(f"\n--- PROCESSOR STATS ---")
    print(f"Buys: {stats['buy']}, Sells: {stats['sell']}")
    
    # Get composite scores
    print(f"\n--- COMPOSITE IGNITION SCORES ---")
    composites = analyzer.get_composite_candidates(limit=20)
    
    state_counts = {}
    saturation_counts = {}
    
    for c in composites:
        state_counts[c.state.value] = state_counts.get(c.state.value, 0) + 1
        saturation_counts[c.saturation.value] = saturation_counts.get(c.saturation.value, 0) + 1
    
    print(f"\nState distribution:")
    for state, count in sorted(state_counts.items()):
        print(f"  {state}: {count}")
    
    print(f"\nSaturation distribution:")
    for sat, count in sorted(saturation_counts.items()):
        print(f"  {sat}: {count}")
    
    # Show top candidates
    print(f"\n--- TOP CANDIDATES ---")
    for i, c in enumerate(composites[:5]):
        print(f"\n{i+1}. {c.token_address[:20]}...")
        print(f"   Score: {c.score:.1f} | Conf: {c.confidence:.1f}")
        print(f"   State: {c.state.value} | Saturation: {c.saturation.value}")
        print(f"   Novel Capital: ${c.novel_capital_usd:.0f}")
        print(f"   Buyer Quality: {c.buyer_quality:.0f}")
        print(f"   WHY: {c.why_now}")
    
    # Test paper snapshots
    print(f"\n--- PAPER SNAPSHOTS ---")
    if composites:
        top_token = composites[0].token_address
        snapshot = analyzer.create_signal_snapshot(top_token)
        if snapshot:
            print(f"Created snapshot for {top_token[:20]}...")
            print(f"  Score: {snapshot.ignition_score:.1f}")
            print(f"  State: {snapshot.ignition_state.value}")
            print(f"  WHY: {snapshot.why_now}")
        else:
            print(f"Snapshot already exists or score too low for {top_token[:20]}...")
    
    print(f"\n{'='*60}")
    print("VALIDATION COMPLETE")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
