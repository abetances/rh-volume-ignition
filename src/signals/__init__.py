"""Trade flow models for novel capital and buyer acceleration signals."""

from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Set


class SignalState(Enum):
    """Signal states for volume ignition."""
    QUIET = "QUIET"
    FORMING = "FORMING"
    IGNITION = "IGNITION"
    ACCELERATING = "ACCELERATING"
    SATURATED = "SATURATED"
    FADING = "FADING"


class AccelerationState(Enum):
    """Acceleration direction."""
    DECELERATING = "DECELERATING"
    STABLE = "STABLE"
    ACCELERATING = "ACCELERATING"


@dataclass
class TradeFlow:
    """Normalized trade flow for a single transaction."""
    token_address: str
    wallet: str  # buyer or seller address
    side: str    # "BUY" or "SELL"
    native_amount: float
    usd_value: Optional[float] = None
    block: int = 0
    tx_index: int = 0
    log_index: int = 0
    tx_hash: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)
    source: str = "unknown"
    
    # Inferred
    is_token_to_token: bool = False
    estimated_new_capital: bool = False  # vs recycled


@dataclass
class TokenFlowMetrics:
    """Aggregated flow metrics for a token."""
    token_address: str
    
    # Raw totals (rolling window)
    gross_buy_flow: float = 0.0
    gross_sell_flow: float = 0.0
    
    # Novel capital estimation
    estimated_novel_capital: float = 0.0
    estimated_recycled_capital: float = 0.0
    novel_capital_ratio: float = 0.0  # novel / (novel + recycled)
    
    # Buyer analysis
    raw_buyers: int = 0
    estimated_independent_buyers: int = 0
    independence_ratio: float = 0.0
    independence_confidence: str = "UNKNOWN"  # HIGH, MEDIUM, LOW, UNKNOWN
    
    # Acceleration metrics
    novel_capital_per_second: float = 0.0
    independent_buyers_per_second: float = 0.0
    
    # State
    signal_state: SignalState = SignalState.QUIET
    acceleration: AccelerationState = AccelerationState.STABLE
    
    # Baseline comparison
    vs_baseline_novel_capital: float = 0.0  # ratio vs baseline
    vs_baseline_buyers: float = 0.0
    
    # Timestamps
    window_start: datetime = field(default_factory=datetime.utcnow)
    window_end: datetime = field(default_factory=datetime.utcnow)
    calculated_at: datetime = field(default_factory=datetime.utcnow)
    
    # Evidence
    unique_wallets: Set[str] = field(default_factory=set)
    clustered_wallets: Dict[str, List[str]] = field(default_factory=dict)  # cluster -> members


@dataclass
class AccelerationWindow:
    """Rolling window metrics."""
    window_seconds: int
    
    # Volume metrics
    novel_capital: float = 0.0
    gross_volume: float = 0.0
    recycled_volume: float = 0.0
    
    # Buyer metrics
    raw_buyers: int = 0
    independent_buyers: int = 0
    
    # Rates
    novel_capital_per_second: float = 0.0
    independent_buyers_per_second: float = 0.0
    
    # Acceleration vs prior window
    novel_capital_acceleration: float = 0.0  # ratio: current / prior
    buyer_acceleration: float = 0.0
    
    # Timestamp
    window_end: datetime = field(default_factory=datetime.utcnow)


@dataclass
class IgnitionCandidate:
    """A token that has reached IGNITION or ACCELERATING state."""
    token_address: str
    
    # Token info
    age_seconds: float = 0.0
    market_cap: Optional[float] = None
    liquidity: Optional[float] = None
    
    # Current metrics (15s window)
    novel_capital_15s: float = 0.0
    novel_capital_acceleration_15s: float = 0.0  # ratio
    independent_buyers_15s: int = 0
    buyer_acceleration_15s: float = 0.0  # ratio
    
    # State
    signal_state: SignalState = SignalState.QUIET
    
    # Baseline comparison
    vs_baseline: float = 0.0
    
    # Evidence
    first_seen: datetime = field(default_factory=datetime.utcnow)
    ignition_detected_at: datetime = field(default_factory=datetime.utcnow)
    
    # Reference
    flow_metrics: Optional[TokenFlowMetrics] = None


@dataclass
class FlowSnapshot:
    """Snapshot of flow features at a point in time."""
    token_address: str
    timestamp: datetime
    
    # Window features
    novel_capital_5s: float = 0.0
    novel_capital_15s: float = 0.0
    novel_capital_30s: float = 0.0
    novel_capital_1m: float = 0.0
    novel_capital_5m: float = 0.0
    
    independent_buyers_5s: int = 0
    independent_buyers_15s: int = 0
    independent_buyers_30s: int = 0
    independent_buyers_1m: int = 0
    independent_buyers_5m: int = 0
    
    # Future outcomes (for testing)
    future_volume_30s: Optional[float] = None
    future_volume_2m: Optional[float] = None
    future_volume_5m: Optional[float] = None
    future_mc_change_30s: Optional[float] = None
    future_mc_change_2m: Optional[float] = None
    future_mc_change_5m: Optional[float] = None
    
    # Is this a replay sample
    is_replay: bool = False


@dataclass
class WalletCluster:
    """Cluster of related wallets (likely same funder)."""
    cluster_id: str
    members: List[str] = field(default_factory=list)
    total_volume: float = 0.0
    trade_count: int = 0
    first_seen: datetime = field(default_factory=datetime.utcnow)
    last_activity: datetime = field(default_factory=datetime.utcnow)
    
    # Evidence
    same_block_entries: int = 0
    identical_sizing_count: int = 0
    round_trip_count: int = 0


# Window sizes in seconds
WINDOWS = [5, 15, 30, 60, 300]  # 5s, 15s, 30s, 1m, 5m

# Signal state thresholds (to be tuned from real data)
DEFAULT_THRESHOLDS = {
    "novel_capital_min_ignition": 100.0,  # $100 minimum for ignition
    "independence_min_ratio": 0.5,  # 50% independent for ignition
    "acceleration_min_ratio": 1.5,  # 1.5x prior window for acceleration
    "vs_baseline_min": 2.0,  # 2x baseline for signal
}
