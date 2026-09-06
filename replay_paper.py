#!/usr/bin/env python3
"""Replay scanner with paper trading engine integration."""
import sys
sys.path.insert(0, '.')

import sqlite3
import ast
from datetime import datetime, timedelta
from collections import defaultdict

from src.signals.flow_analyzer import FlowAnalyzer
from src.signals.flow_processor import FlowProcessor
from src.signals import SignalState
from src.paper_engine import PaperEngine, PaperConfig


def main():
    db_path = 'data/rh_volume_ignition.db'
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT event_id, block_number, block_timestamp, event_type, raw_reference, tx_hash
        FROM raw_events
        ORDER BY block_timestamp, log_index
        LIMIT 50000
    ''')
    rows = cursor.fetchall()

    analyzer = FlowAnalyzer()
    processor = FlowProcessor()
    paper = PaperEngine(PaperConfig())
    
    # Track volumes per token (windowed - rate, not cumulative)
    token_volumes = defaultdict(float)
    
    print(f"Processing {len(rows)} events...")
    
    signals_processed = 0
    token_decisions = 0
    
    for i, row in enumerate(rows):
        event_id, block_num, block_ts, event_type, raw_ref, tx_hash = row
        
        try:
            ref = ast.literal_eval(raw_ref) if isinstance(raw_ref, str) else raw_ref
        except:
            continue
        
        ts = datetime.fromisoformat(block_ts.replace('Z', '+00:00'))
        token = ref.get('address', '').lower()
        
        event = {
            'event_id': event_id,
            'block_number': block_num,
            'block_timestamp': block_ts,
            'contract_address': token,
            'topics': ref.get('topics', []),
            'data': ref.get('data', '0x0'),
            'tx_hash': tx_hash,
        }
        
        flow = processor.process_event(event)
        
        if flow and flow.native_amount > 0:
            # Track windowed volume rate (last 30s)
            token_volumes[token] = flow.native_amount
            
            analyzer.ingest_trade(flow)
            composite = analyzer.compute_composite_ignition(token)
            
            # Extract component values from list
            novel_cap = 0.0
            buyer_acc = 0.0
            if composite.components and isinstance(composite.components, list):
                for c in composite.components:
                    if c.name == 'novel_capital':
                        novel_cap = c.value
                    elif c.name == 'buyer_acceleration':
                        buyer_acc = c.value
            
            # Feed to paper engine
            paper.evaluate_signal(
                token_address=token,
                timestamp=ts,
                state=composite.state.value,
                saturation=composite.saturation.value,
                novel_capital_accel=novel_cap,
                buyer_accel=buyer_acc,
                buyer_quality=composite.buyer_quality,
                recurring_actor=composite.recurring_actor_present,
                tradeability_trend=composite.tradeability_trend.value if composite.tradeability_trend else "unknown",
                reawakening=composite.reawakening_state.value != "none" if composite.reawakening_state else False,
                rotation=composite.rotation_present,
                ignition_score=composite.score,
                confidence=composite.confidence,
                why_now=composite.why_now or "",
            )
            
            token_decisions += 1
            
            # Check for signals
            alertable = [SignalState.FORMING_EARLY, SignalState.FORMING, SignalState.IGNITION, SignalState.ACCELERATING]
            if composite.state in alertable and composite.score >= 5.0:
                signals_processed += 1
            
            # Update positions with volume data
            paper.update_positions(
                token_prices={},
                token_mcaps={},
                token_liquidity={},
                current_time=ts,
                token_volumes=dict(token_volumes),
            )
        
        if i > 0 and i % 10000 == 0:
            print(f"  {i}/{len(rows)} | Signals: {signals_processed} | Decisions: {token_decisions}")

    conn.close()
    
    # Close any remaining open positions
    for token, pos in list(paper.positions.items()):
        if pos.state == "open":
            paper._exit_paper_position(pos, ExitReason.MAX_HOLD_TIME, datetime.utcnow())
    
    # Results
    print("\n" + "="*60)
    print("REPLAY RESULTS")
    print("="*60)
    print(f"Events processed: {len(rows)}")
    print(f"Token decisions: {token_decisions}")
    print(f"Signals: {signals_processed}")
    print(f"\nPaper Positions:")
    print(f"  Open: {len(paper.get_open_positions())}")
    print(f"  Completed: {len(paper.completed_trades)}")
    
    # Filter decisions summary
    from collections import Counter
    decisions = [d.filter_decision.value for d in paper.decisions]
    print(f"\nFilter Decision Summary:")
    for dec, count in Counter(decisions).most_common(10):
        print(f"  {dec}: {count}")
    
    # Paper trade stats
    stats = paper.get_statistics()
    print(f"\nPaper Trading Stats:")
    print(f"  Total Trades: {stats['total_trades']}")
    print(f"  Wins: {stats['wins']} | Losses: {stats['losses']}")
    print(f"  Win Rate: {stats['win_rate']:.1f}%")
    print(f"  Median Return: {stats['median_return']:+.1f}%")
    
    # Volume metrics
    trades_with_volume = [t for t in paper.completed_trades if t.entry_volume > 0]
    if trades_with_volume:
        print(f"\nVolume Metrics (research):")
        
        vol_exp_2m = [t.volume_expansion_2m for t in trades_with_volume if t.volume_expansion_2m > 0]
        if vol_exp_2m:
            print(f"  Median Volume Expansion 2m: {sorted(vol_exp_2m)[len(vol_exp_2m)//2]:.2f}x")
        
        sec_to_peak = [t.seconds_to_max_volume_2m for t in trades_with_volume if t.seconds_to_max_volume_2m > 0]
        if sec_to_peak:
            print(f"  Median Seconds to Peak 2m: {sorted(sec_to_peak)[len(sec_to_peak)//2]:.0f}s")
    
    # Sample trades
    print(f"\n--- SAMPLE PAPER TRADES ---")
    for t in paper.completed_trades[:5]:
        reason = t.exit_reason.value if t.exit_reason else "unknown"
        ret = t.realized_return * 100
        print(f"  {t.token_address[:16]}... entry={t.entry_time.strftime('%H:%M')} exit={t.exit_time.strftime('%H:%M') if t.exit_time else 'N/A'} ret={ret:+.1f}% {reason}")


if __name__ == '__main__':
    from src.paper_engine.models import ExitReason
    main()
