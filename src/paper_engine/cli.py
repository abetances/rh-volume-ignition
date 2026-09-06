"""CLI viewer for paper trading status."""
import click
from datetime import datetime
from typing import Optional


def format_pnl(pnl: float, return_pct: float) -> str:
    """Format PnL with color."""
    emoji = "🟢" if pnl >= 0 else "🔴"
    return f"{emoji} ${pnl:,.2f} ({return_pct:+.1f}%)"


def format_time(seconds: float) -> str:
    """Format hold time."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        return f"{seconds/60:.1f}m"
    else:
        return f"{seconds/3600:.1f}h"


def show_positions(positions: list, detailed: bool = False):
    """Show open paper positions."""
    if not positions:
        click.echo("📋 No open paper positions")
        return
    
    click.echo(f"\n📋 OPEN PAPER POSITIONS ({len(positions)})")
    click.echo("=" * 80)
    
    for p in positions:
        pnl_str = format_pnl(p.paper_pnl, p.paper_return * 100)
        hold = format_time(p.hold_time_seconds)
        
        click.echo(f"\n{p.token_address[:20]}...")
        click.echo(f"  Entry: {p.entry_decision_time.strftime('%H:%M:%S')} | State: {p.state} | Hold: {hold}")
        click.echo(f"  PnL: {pnl_str}")
        click.echo(f"  Reason: {p.entry_reason[:60]}...")
        
        if detailed:
            click.echo(f"  Signal: {p.signal_time.strftime('%H:%M:%S')}")
            click.echo(f"  Entry Value: ${p.position_value:,.2f}")


def show_recent_trades(trades: list, limit: int = 10):
    """Show recent paper trades."""
    if not trades:
        click.echo("📋 No completed paper trades")
        return
    
    click.echo(f"\n📋 RECENT PAPER TRADES ({len(trades)})")
    click.echo("=" * 80)
    
    for t in trades[:limit]:
        pnl_str = format_pnl(t.realized_pnl, t.realized_return * 100)
        hold = format_time(t.hold_time_seconds)
        
        exit_reason = t.exit_reason.value if t.exit_reason else "unknown"
        
        click.echo(f"\n{t.token_address[:20]}...")
        click.echo(f"  Entry: {t.entry_time.strftime('%H:%M:%S')} | Exit: {t.exit_time.strftime('%H:%M:%S') if t.exit_time else 'N/A'}")
        click.echo(f"  Return: {pnl_str} | Hold: {hold} | Exit: {exit_reason}")


def show_statistics(stats: dict):
    """Show paper trading statistics."""
    click.echo(f"\n📊 PAPER TRADING STATISTICS")
    click.echo("=" * 80)
    click.echo(f"  Total Trades: {stats['total_trades']}")
    click.echo(f"  Wins: {stats['wins']} | Losses: {stats['losses']}")
    click.echo(f"  Win Rate: {stats['win_rate']:.1f}%")
    click.echo(f"  Median Return: {stats['median_return']:+.1f}%")
    click.echo(f"  Median MFE: {stats['median_mfe']:+.1f}%")
    click.echo(f"  Median MAE: {stats['median_mae']:+.1f}%")


def show_token_timeline(decisions: list, token: str):
    """Show token decision timeline."""
    if not decisions:
        click.echo(f"No decisions found for {token}")
        return
    
    click.echo(f"\n📜 TIMELINE: {token[:20]}...")
    click.echo("=" * 80)
    
    for d in decisions:
        decision_emoji = {
            'SEEN': '👁️',
            'WATCHED': '👀',
            'FORMING_EARLY': '🌱',
            'FORMING': '📈',
            'IGNITION': '🔥',
            'ACCELERATING': '🚀',
            'SATURATED': '⛔',
            'FADING': '📉',
            'INSUFFICIENT_ACCELERATION': '❌',
            'CONFIDENCE_INSUFFICIENT': '❌',
            'TRADEABILITY_FAILED': '❌',
            'ALREADY_SATURATED': '⛔',
        }.get(d.filter_decision.value, '❓')
        
        click.echo(f"\n{d.timestamp.strftime('%H:%M:%S')} {decision_emoji} {d.filter_decision.value}")
        click.echo(f"  State: {d.state} | Saturation: {d.saturation}")
        click.echo(f"  Score: {d.ignition_score:.1f} | Confidence: {d.confidence:.2f}")
        
        if d.paper_entry_eligible:
            click.echo(f"  ✅ Paper Entry Eligible")
        elif d.entry_rejection_reason:
            click.echo(f"  ❌ Entry Rejected: {d.entry_rejection_reason}")
        
        if d.why_now:
            click.echo(f"  WHY: {d.why_now[:80]}...")


def show_filter_summary(decisions: list):
    """Show filter decision summary."""
    from collections import Counter
    
    if not decisions:
        return
    
    counts = Counter(d.filter_decision.value for d in decisions)
    
    click.echo(f"\n🎯 FILTER DECISION SUMMARY")
    click.echo("=" * 80)
    
    for decision, count in counts.most_common():
        click.echo(f"  {decision}: {count}")


@click.group()
def cli():
    """Paper trading visibility CLI."""
    pass


@cli.command()
@click.option('--detailed', '-d', is_flag=True, help='Show detailed position info')
def positions(detailed):
    """Show open paper positions."""
    # This would load from persistence in real implementation
    click.echo("Run with --live flag to see real-time positions")


@cli.command()
@click.option('--limit', '-n', default=10, help='Number of trades to show')
def trades(limit):
    """Show recent paper trades."""
    click.echo("Run with --live flag to see real-time trades")


@cli.command()
def stats():
    """Show paper trading statistics."""
    click.echo("Run with --live flag to see statistics")


@cli.command()
@click.argument('token')
def timeline(token):
    """Show token decision timeline."""
    click.echo(f"Run with --live flag to see timeline for {token}")


if __name__ == '__main__':
    cli()
