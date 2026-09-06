"""Paper trading configuration."""
from dataclasses import dataclass


@dataclass
class PaperConfig:
    """Configuration for paper trading."""
    
    # Entry eligibility
    min_confidence_for_entry: float = 0.6
    require_ignition_state: bool = True
    require_not_saturated: bool = True
    min_tradeability_score: float = 0.3
    
    # Position sizing
    max_position_value: float = 1000.0  # USD
    default_position_pct: float = 0.1  # 10% of bankroll
    
    # Risk management
    stop_loss_pct: float = -0.10  # -10%
    max_hold_time_seconds: int = 86400  # 24 hours
    
    # Execution simulation
    estimated_slippage_bps: int = 20  # 20 bps = 0.2%
    estimated_impact_bps: int = 10  # 10 bps = 0.1%
    arrival_time_seconds: int = 5  # assumed 5s to arrive at market
    
    # Exit triggers
    exit_on_saturation: bool = True
    exit_on_fade: bool = True
    exit_on_flow_reversal: bool = True
    exit_on_tradeability_drop: bool = True
    
    # Filtering
    watch_tiers_enabled: bool = True
    store_all_decisions: bool = True  # For debugging/audit


# Default config instance
DEFAULT_CONFIG = PaperConfig()
