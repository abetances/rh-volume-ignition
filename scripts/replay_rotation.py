#!/usr/bin/env python3
"""Replay historical chain data to validate rotation detection with proper decoding."""

import sys
sys.path.insert(0, '.')

from datetime import datetime, timezone
import sqlite3
import ast

from src.signals.flow_analyzer import FlowAnalyzer
from src.signals.flow_processor import FlowProcessor
from src.signals import TradeFlow


def main():
    print("=" * 60)
    print("ROTATION REPLAY VALIDATION (Protocol-Aware Decoding)")
    print("=" * 60)
    
    # Connect to DB
    db_path = "data/rh_volume_ignition.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get raw events sorted by block
    cursor.execute("""
        SELECT event_id, block_number, transaction_index, log_index, tx_hash, 
               observed_at, block_timestamp, source, contract_address, 
               event_type, raw_reference
        FROM raw_events 
        ORDER BY block_number, transaction_index, log_index
        LIMIT 50000
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
        
        # Parse raw_reference
        try:
            if isinstance(raw_ref, str):
                ref_data = ast.literal_eval(raw_ref)
            else:
                ref_data = raw_ref
        except:
            continue
        
        # Build event dict for processor
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
        
        # Parse into TradeFlow
        flow = processor.process_event(event)
        
        if flow:
            # Feed to analyzer
            analyzer.ingest_trade(flow)
        
        if i > 0 and i % 10000 == 0:
            stats = processor.get_stats()
            print(f"  Processed {i}/{len(rows)} events | Buys: {stats['buy']}, Sells: {stats['sell']}")
    
    # Get stats
    stats = processor.get_stats()
    print(f"\n--- PROCESSOR STATS ---")
    print(f"Total events: {len(rows)}")
    print(f"Uniswap V3 swaps: {stats['uniswap_v3_swaps']}")
    print(f"Transfers parsed: {stats['transfers']}")
    print(f"Unknown events: {stats['unknown']}")
    print(f"Decode errors: {stats['decode_errors']}")
    print(f"Buys: {stats['buy']}, Sells: {stats['sell']}")
    
    # Get results
    rotations = analyzer.get_rotation_candidates(limit=100)
    ignition_candidates = analyzer.get_ignition_candidates(limit=100)
    
    print(f"\n{'='*60}")
    print("RESULTS")
    print(f"{'='*60}")
    print(f"Rotation candidates: {len(rotations)}")
    print(f"Ignition candidates: {len(ignition_candidates)}")
    
    # Detailed rotation breakdown
    if rotations:
        print(f"\n--- ROTATION DETAILS ---")
        for r in rotations[:10]:
            delay = getattr(r, 'rotation_delay_seconds', 0)
            print(f"  {r.token_address[:20]} <- {r.source_token[:20]}")
            print(f"    State: {r.rotation_state.value}, Conf: {r.rotation_confidence:.2f}, Score: {r.rotation_score:.1f}")
            print(f"    Actor: {r.actor_id[:16]}..., Delay: {delay:.0f}s")
            
            # Sanity check timestamp
            if delay < 0:
                print(f"    ⚠️ NEGATIVE DELAY DETECTED!")
    
    # Cross-reference: ignitions with rotation
    print(f"\n--- IGNITION + ROTATION ---")
    if ignition_candidates:
        ignitions_with_rotation = 0
        for ign in ignition_candidates:
            token = ign.token_address.lower()
            if token in analyzer._rotation_candidates:
                ignitions_with_rotation += 1
        
        print(f"Ignitions WITH rotation: {ignitions_with_rotation}")
        print(f"Ignitions WITHOUT rotation: {len(ignition_candidates) - ignitions_with_rotation}")
        
        if len(ignition_candidates) > 0:
            lift_pct = (ignitions_with_rotation / len(ignition_candidates)) * 100
            print(f"Rotation lift: {lift_pct:.1f}% of ignitions have rotation signal")
    else:
        print("No ignition candidates detected in replay")
    
    # Sanity checks
    print(f"\n--- SANITY CHECKS ---")
    negative_delays = [r for r in rotations if getattr(r, 'rotation_delay_seconds', 0) < 0]
    print(f"Rotations with negative delay: {len(negative_delays)}")
    
    print(f"\n{'='*60}")
    print("REPLAY COMPLETE")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
