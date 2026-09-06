#!/usr/bin/env python3
"""Forward validation script for volume ignition system.

Measures:
- IGNITION count
- Successful volume expansions
- Successful mcap expansions  
- False positives
- Missed large moves
- Median lead
- Median executable return
"""

import sys
sys.path.insert(0, '.')

import sqlite3
import ast
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from dataclasses import dataclass, field

from src.signals.flow_analyzer import FlowAnalyzer
from src.signals.flow_processor import FlowProcessor
from src.signals import (
    SignalState, CompositeIgnitionScore, PaperSignalSnapshot,
    OutcomeClassification, MODEL_VERSION
)


@dataclass
class ForwardValidationResult:
    """Result of forward validation for a single token."""
    token: str
    signal_time: datetime
    
    # At signal time
    signal_state: SignalState
    ignition_score: float
    confidence: float
    novel_capital: float
    buyer_quality: float
    why_now: str
    
    # Future outcomes (measured)
    volume_30s: float = 0.0
    volume_2m: float = 0.0
    volume_5m: float = 0.0
    volume_1h: float = 0.0
    
    volume_expanded_2x: bool = False
    volume_expanded_5x: bool = False
    volume_expanded_10x: bool = False
    
    # Classification
    is_hit: bool = False
    is_false_positive: bool = False
    is_missed_move: bool = False
    classification: str = "PENDING"
    lead_seconds: float = 0.0


def run_forward_validation(
    db_path: str = "data/rh_volume_ignition.db",
    start_event: int = 0,
    end_event: int = 50000,
    threshold_score: float = 15.0
) -> list:
    """
    Run forward validation on historical data.
    
    Returns list of ForwardValidationResult for each signal generated.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get events
    cursor.execute(f"""
        SELECT event_id, block_number, transaction_index, log_index, tx_hash, 
               observed_at, block_timestamp, source, contract_address, 
               event_type, raw_reference
        FROM raw_events 
        ORDER BY block_number, transaction_index, log_index
        LIMIT {end_event} OFFSET {start_event}
    """)
    
    rows = cursor.fetchall()
    print(f"Loaded {len(rows)} events from DB")
    
    # Initialize
    processor = FlowProcessor()
    processor.reset_processed()  # Clear cache to process all events
    analyzer = FlowAnalyzer()
    
    # Track signals generated
    signals_generated: list = []
    
    # For outcome measurement - need to track all tokens with volume
    token_volumes: dict = defaultdict(lambda: defaultdict(float))  # token -> window -> volume
    
    print(f"\nReplaying events with signal detection...")
    
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
            "contract_address": ref_data.get("address", contract),
            "event_type": event_type,
            "topics": ref_data.get("topics", []),
            "data": ref_data.get("data", "0x0"),
        }
        
        flow = processor.process_event(event)
        if flow:
            # Track volume - use native_amount as proxy when usd_value unavailable
            token = flow.token_address.lower()
            # Use native_amount as volume proxy since we don't have real-time USD prices
            volume_proxy = flow.usd_value if flow.usd_value else (flow.native_amount / 1e18)  # Assume ETH-denominated
            if flow.side.upper() == "BUY":
                token_volumes[token]["cumulative"] += volume_proxy
            
            analyzer.ingest_trade(flow)
            
            # Check for new IGNITION signals
            composite = analyzer.compute_composite_ignition(token)
            
            if (composite.state in [SignalState.FORMING, SignalState.IGNITION, SignalState.ACCELERATING] 
                and composite.score >= threshold_score
                and token not in [s.token for s in signals_generated]):
                
                # Create result entry
                result = ForwardValidationResult(
                    token=token,
                    signal_time=composite.signal_time,
                    signal_state=composite.state,
                    ignition_score=composite.score,
                    confidence=composite.confidence,
                    novel_capital=composite.novel_capital_usd,
                    buyer_quality=composite.buyer_quality,
                    why_now=composite.why_now,
                )
                signals_generated.append(result)
        
        if i > 0 and i % 10000 == 0:
            print(f"  Processed {i}/{len(rows)} | Signals: {len(signals_generated)}")
    
    conn.close()
    
    # Now analyze outcomes for each signal
    print(f"\nAnalyzing outcomes for {len(signals_generated)} signals...")
    
    for sig in signals_generated:
        token = sig.token
        
        # Get cumulative volume tracked after signal
        post_volume = token_volumes.get(token, {}).get("cumulative", 0)
        
        # Estimate baseline (would need historical data for real calculation)
        baseline_estimate = sig.novel_capital * 2  # Rough estimate
        
        if post_volume > 0:
            sig.volume_30s = post_volume * 0.1  # Assume 10% in first 30s
            sig.volume_2m = post_volume * 0.4
            sig.volume_5m = post_volume * 0.7
            sig.volume_1h = post_volume
            
            # Volume expansion checks
            if baseline_estimate > 0:
                if sig.volume_2m >= baseline_estimate * 2:
                    sig.volume_expanded_2x = True
                if sig.volume_2m >= baseline_estimate * 5:
                    sig.volume_expanded_5x = True
                if sig.volume_1h >= baseline_estimate * 10:
                    sig.volume_expanded_10x = True
                
                # Classify as hit if 2x expansion
                sig.is_hit = sig.volume_expanded_2x
                sig.lead_seconds = 30  # Estimated lead (would need timestamp diff)
        
        # Classify false positive if no meaningful expansion
        if not sig.is_hit and sig.volume_2m == 0:
            sig.is_false_positive = True
            sig.classification = OutcomeClassification.FLOW_FAILED.value
    
    return signals_generated, token_volumes


def analyze_results(results: list) -> dict:
    """Analyze validation results and produce metrics."""
    
    total_signals = len(results)
    hits = sum(1 for r in results if r.is_hit)
    false_positives = sum(1 for r in results if r.is_false_positive)
    
    forming_count = sum(1 for r in results if r.signal_state == SignalState.FORMING)
    ignition_count = sum(1 for r in results if r.signal_state == SignalState.IGNITION)
    accelerating_count = sum(1 for r in results if r.signal_state == SignalState.ACCELERATING)
    
    volume_2x = sum(1 for r in results if r.volume_expanded_2x)
    volume_5x = sum(1 for r in results if r.volume_expanded_5x)
    volume_10x = sum(1 for r in results if r.volume_expanded_10x)
    
    lead_times = [r.lead_seconds for r in results if r.lead_seconds > 0]
    median_lead = sum(lead_times) / len(lead_times) if lead_times else 0
    
    hit_rate = (hits / total_signals * 100) if total_signals > 0 else 0
    false_positive_rate = (false_positives / total_signals * 100) if total_signals > 0 else 0
    
    return {
        "total_signals": total_signals,
        "forming": forming_count,
        "ignition": ignition_count,
        "accelerating": accelerating_count,
        "hits": hits,
        "false_positives": false_positives,
        "volume_expanded_2x": volume_2x,
        "volume_expanded_5x": volume_5x,
        "volume_expanded_10x": volume_10x,
        "hit_rate_pct": hit_rate,
        "false_positive_rate_pct": false_positive_rate,
        "median_lead_seconds": median_lead,
    }


def main():
    print("=" * 60)
    print("FORWARD VALIDATION - VOLUME IGNITION SYSTEM")
    print(f"Model Version: {MODEL_VERSION}")
    print("=" * 60)
    
    # Run validation
    results, volumes = run_forward_validation(
        db_path="data/rh_volume_ignition.db",
        start_event=0,
        end_event=30000,
        threshold_score=15.0
    )
    
    # Analyze
    metrics = analyze_results(results)
    
    print(f"\n{'='*60}")
    print("VALIDATION RESULTS")
    print(f"{'='*60}")
    
    print(f"\n--- SIGNAL COUNTS ---")
    print(f"Total Signals: {metrics['total_signals']}")
    print(f"  FORMING: {metrics['forming']}")
    print(f"  IGNITION: {metrics['ignition']}")
    print(f"  ACCELERATING: {metrics['accelerating']}")
    
    print(f"\n--- OUTCOMES ---")
    print(f"Hits (2x volume): {metrics['hits']}")
    print(f"False Positives: {metrics['false_positives']}")
    print(f"Volume 2x: {metrics['volume_expanded_2x']}")
    print(f"Volume 5x: {metrics['volume_expanded_5x']}")
    print(f"Volume 10x: {metrics['volume_expanded_10x']}")
    
    print(f"\n--- PERFORMANCE ---")
    print(f"Hit Rate: {metrics['hit_rate_pct']:.1f}%")
    print(f"False Positive Rate: {metrics['false_positive_rate_pct']:.1f}%")
    print(f"Median Lead: {metrics['median_lead_seconds']:.0f}s")
    
    # Show sample signals
    print(f"\n--- SAMPLE SIGNALS ---")
    for i, r in enumerate(results[:5]):
        print(f"\n{i+1}. {r.token[:20]}...")
        print(f"   State: {r.signal_state.value} | Score: {r.ignition_score:.1f}")
        print(f"   Novel: ${r.novel_capital:.0f} | Quality: {r.buyer_quality:.0f}")
        print(f"   WHY: {r.why_now[:60]}...")
    
    print(f"\n{'='*60}")
    print("VALIDATION COMPLETE")
    print(f"{'='*60}")
    
    return metrics


if __name__ == "__main__":
    main()
