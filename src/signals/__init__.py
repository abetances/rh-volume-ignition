"""Trade flow models for novel capital and buyer acceleration signals."""

from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, List, Dict, Set, Any, Callable


class SignalState(Enum):
    """Signal states for volume ignition."""
    QUIET = "QUIET"
    FORMING_EARLY = "FORMING_EARLY"  # Early detection, before peak
    FORMING = "FORMING"
    IGNITION = "IGNITION"
    ACCELERATING = "ACCELERATING"
    SATURATED = "SATURATED"  # Negative state - volume already peaked
    FADING = "FADING"


class AccelerationState(Enum):
    """Acceleration direction."""
    DECELERATING = "DECELERATING"
    STABLE = "STABLE"
    ACCELERATING = "ACCELERATING"


class TradeabilityTrend(Enum):
    """Tradeability improvement trend."""
    DETERIORATING = "DETERIORATING"
    STABLE = "STABLE"
    IMPROVING = "IMPROVING"
    RAPIDLY_IMPROVING = "RAPIDLY_IMPROVING"
    UNKNOWN = "UNKNOWN"


class ReawakeningState(Enum):
    """Reawakening state for dormant tokens."""
    DORMANT = "DORMANT"
    WAKING = "WAKING"
    REAWAKENING = "REAWAKENING"
    ACTIVE = "ACTIVE"


class LiquiditySource(Enum):
    """Source of liquidity data."""
    BONDING_CURVE = "BONDING_CURVE"
    AMM_POOL = "AMM_POOL"
    UNKNOWN = "UNKNOWN"


class RotationState(Enum):
    """Rotation detection state."""
    UNKNOWN = "UNKNOWN"
    POSSIBLE_ROTATION = "POSSIBLE_ROTATION"
    PROBABLE_ROTATION = "PROBABLE_ROTATION"
    STRONG_ROTATION = "STRONG_ROTATION"
    REJECTED = "REJECTED"  # False rotation


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
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc)) # type: ignore
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
    
    # Acceleration ratios (current vs prior window)
    novel_capital_acceleration: float = 0.0  # ratio: current / prior
    buyer_acceleration: float = 0.0
    
    # State
    signal_state: SignalState = SignalState.QUIET
    acceleration: AccelerationState = AccelerationState.STABLE
    
    # Baseline comparison
    vs_baseline_novel_capital: float = 0.0  # ratio vs baseline
    vs_baseline_buyers: float = 0.0
    
    # Timestamps
    window_start: datetime = field(default_factory=lambda: datetime.now(timezone.utc)) # type: ignore
    window_end: datetime = field(default_factory=lambda: datetime.now(timezone.utc)) # type: ignore
    calculated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc)) # type: ignore
    
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
    window_end: datetime = field(default_factory=lambda: datetime.now(timezone.utc)) # type: ignore


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
    
    # Tradeability (liquidity improvement)
    tradeability_trend: TradeabilityTrend = TradeabilityTrend.UNKNOWN
    liquidity_current: Optional[float] = None
    liquidity_change_pct: float = 0.0
    buy_impact_bps: int = 0
    sell_impact_bps: int = 0
    
    # Reawakening
    reawakening_state: ReawakeningState = ReawakeningState.DORMANT
    prior_activity_hours: float = 0.0
    reawakening_trigger: str = ""
    
    # State
    signal_state: SignalState = SignalState.QUIET
    
    # Baseline comparison
    vs_baseline: float = 0.0
    
    # Evidence
    first_seen: datetime = field(default_factory=lambda: datetime.now(timezone.utc)) # type: ignore
    ignition_detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc)) # type: ignore
    
    # Reference
    flow_metrics: Optional[TokenFlowMetrics] = None
    liquidity_metrics: Any = None  # LiquidityMetrics, set after class definition
    
    # Why now (human-readable reason)
    why_now: str = ""


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
    first_seen: datetime = field(default_factory=lambda: datetime.now(timezone.utc)) # type: ignore
    last_activity: datetime = field(default_factory=lambda: datetime.now(timezone.utc)) # type: ignore
    
    # Evidence
    same_block_entries: int = 0
    identical_sizing_count: int = 0
    round_trip_count: int = 0


# Window sizes in seconds
WINDOWS = [5, 15, 30, 60, 300]  # 5s, 15s, 30s, 1m, 5m

# Liquidity tracking windows
LIQUIDITY_WINDOWS = [15, 30, 60, 300]  # 15s, 30s, 1m, 5m


@dataclass
class LiquidityMetrics:
    """Liquidity and execution surface metrics for a token."""
    token_address: str
    
    # Liquidity source
    source: LiquiditySource = LiquiditySource.UNKNOWN
    
    # Bonding curve metrics (if applicable)
    curve_native_balance: float = 0.0
    curve_progress: float = 0.0  # 0-1
    estimated_buy_impact: float = 0.0  # % price impact for 1 ETH buy
    estimated_sell_impact: float = 0.0  # % price impact for 1 ETH sell
    current_mcap: float = 0.0
    
    # AMM/pool metrics (if applicable)
    pool_liquidity: float = 0.0
    reserve_native: float = 0.0
    reserve_token: float = 0.0
    
    # Derived
    exit_depth_native: float = 0.0  # how much can be sold at <5% impact
    buy_impact_bps: int = 0  # basis points for 1% of pool
    sell_impact_bps: int = 0
    
    # Timestamps
    calculated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc)) # type: ignore
    data_age_seconds: float = 0.0
    
    # Confidence
    is_stale: bool = True
    is_estimated: bool = True


@dataclass
class LiquidityWindow:
    """Rolling window of liquidity metrics."""
    window_seconds: int
    
    # Depth metrics
    depth_native: float = 0.0
    depth_change_pct: float = 0.0  # vs prior window
    
    # Impact metrics
    buy_impact_bps: int = 0
    sell_impact_bps: int = 0
    buy_impact_change_pct: float = 0.0
    sell_impact_change_pct: float = 0.0
    
    # Exit capacity
    exit_depth_native: float = 0.0
    exit_capacity_change_pct: float = 0.0
    
    # Timestamp
    window_end: datetime = field(default_factory=lambda: datetime.now(timezone.utc)) # type: ignore


@dataclass
class ReawakeningEvent:
    """Reawakening detection for dormant tokens."""
    token_address: str
    
    # State transition
    prior_state: ReawakeningState = ReawakeningState.DORMANT
    new_state: ReawakeningState = ReawakeningState.REAWAKENING
    
    # Trigger
    trigger: str = ""  # e.g., "buyer_rate_jump", "depth_increase", "mcap_breakout"
    trigger_value: float = 0.0
    baseline_value: float = 0.0
    current_value: float = 0.0
    
    # Context
    buyer_rate_baseline: float = 0.0
    buyer_rate_current: float = 0.0
    capital_baseline: float = 0.0
    capital_current: float = 0.0
    depth_baseline: float = 0.0
    depth_current: float = 0.0
    
    # Timing
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc)) # type: ignore
    prior_activity_at: Optional[datetime] = None
    
    # Signal combination
    combined_with_ignition: bool = False
    tradeability_trend: TradeabilityTrend = TradeabilityTrend.UNKNOWN


@dataclass
class RotationCandidate:
    """A token with detected capital rotation from another token."""
    token_address: str  # destination token
    
    # Rotation metadata
    rotation_state: RotationState = RotationState.UNKNOWN
    rotation_confidence: float = 0.0
    rotation_score: float = 0.0
    
    # Source token
    source_token: str = ""
    source_token_state: str = ""  # prior state (e.g., "runner", "ignition", "high_volume")
    
    # Actor info
    actor_id: str = ""  # wallet or cluster that rotated
    is_cluster: bool = False
    
    # Amounts
    source_exit_amount_usd: float = 0.0
    destination_entry_amount_usd: float = 0.0
    
    # Timing
    source_exit_at: Optional[datetime] = None
    destination_entry_at: Optional[datetime] = None
    rotation_delay_seconds: float = 0.0
    
    # Evidence
    evidence_refs: List[str] = field(default_factory=list)  # tx hashes
    rejection_reason: str = ""  # if REJECTED
    
    # Follow-through
    independent_follow_through: bool = False
    follow_through_buyers: int = 0
    follow_through_capital: float = 0.0
    
    # Prior runner boost
    is_prior_runner: bool = False
    is_prior_ignition: bool = False
    prior_runner_hours_ago: float = 0.0
    
    # Timestamps
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc)) # type: ignore
    why_now: str = ""

# Signal state thresholds (to be tuned from real data)
DEFAULT_THRESHOLDS = {
    "novel_capital_min_ignition": 100.0,  # $100 minimum for ignition
    "independence_min_ratio": 0.5,  # 50% independent for ignition
    "acceleration_min_ratio": 1.5,  # 1.5x prior window for acceleration
    "vs_baseline_min": 2.0,  # 2x baseline for signal
    # Liquidity thresholds
    "depth_improvement_min_pct": 0.20,  # 20% improvement for IMPROVING
    "depth_improvement_rapid_pct": 0.50,  # 50% for RAPIDLY_IMPROVING
    # Reawakening thresholds
    "reawakening_buyer_jump_min": 3.0,  # 3x baseline buyers
    "reawakening_capital_jump_min": 5.0,  # 5x baseline capital
    "reawakening_depth_jump_min": 1.5,  # 1.5x baseline depth
    "dormant_baseline_trades": 10,  # trades to establish dormancy
    "dormant_time_hours": 24,  # hours of inactivity for dormancy
    # Rotation thresholds
    "rotation_exit_min_usd": 100.0,  # min exit to count as material
    "rotation_entry_min_usd": 50.0,  # min entry to count as material
    "rotation_max_delay_seconds": 300,  # 5 min max delay for strong rotation
    "rotation_probable_delay_seconds": 900,  # 15 min for probable
    "rotation_min_confidence": 0.5,  # min confidence for POSSIBLE
    "dust_threshold_usd": 10.0,  # below this = dust, reject
    "cluster_internal_min_pct": 0.8,  # >80% same cluster = internal transfer
    # Prior runner weighting
    "prior_runner_hours": 24,  # within 24h = recent runner
    "prior_ignition_hours": 6,  # within 6h = recent ignition
    "prior_runner_boost": 2.0,  # 2x weight for prior runner
}


class VolumeSaturation(Enum):
    """Volume saturation state."""
    BEFORE_VOLUME = "BEFORE_VOLUME"       # Early signal, raw volume not saturated
    VOLUME_EXPANDING = "VOLUME_EXPANDING"  # Volume is growing
    ALREADY_CROWDED = "ALREADY_CROWDED"   # Volume obvious, edge consumed


@dataclass
class IgnitionComponent:
    """Individual component of composite ignition score."""
    name: str                    # e.g., "novel_capital", "buyer_quality"
    value: float                 # Raw value
    normalized: float            # 0-1 normalized
    weight: float              # Weight in composite
    evidence_refs: List[str] = field(default_factory=list)


@dataclass
class CompositeIgnitionScore:
    """Composite ignition score combining multiple signals."""
    token_address: str
    score: float                # 0-100 composite score
    confidence: float           # 0-100 confidence
    state: SignalState          # QUIET, FORMING, IGNITION, ACCELERATING, SATURATED, FADING
    saturation: VolumeSaturation  # BEFORE_VOLUME, VOLUME_EXPANDING, ALREADY_CROWDED
    
    # Component breakdown
    components: List[IgnitionComponent] = field(default_factory=list)
    
    # Primary signals
    novel_capital_usd: float = 0.0
    novel_capital_per_second: float = 0.0
    independent_buyer_rate: float = 0.0   # % change
    buyer_quality: float = 0.0             # 0-100
    
    # Secondary signals
    recurring_actor_present: bool = False
    tradeability_trend: TradeabilityTrend = TradeabilityTrend.UNKNOWN
    rotation_present: bool = False
    reawakening_state: ReawakeningState = ReawakeningState.DORMANT
    
    # Evidence
    why_now: str = ""
    evidence_refs: List[str] = field(default_factory=list)
    
    # Timestamps
    signal_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc)) # type: ignore
    calculated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc)) # type: ignore
    
    # Velocity/acceleration metrics
    velocity_ratio: float = 1.0  # Recent volume / prior volume (non-overlapping)
    acceleration: float = 0.0  # Change in velocity over time


@dataclass
class PaperSignalSnapshot:
    """Immutable snapshot of signal at IGNITION detection time."""
    # Immutable ID
    signal_id: str
    
    # Token identity
    token_address: str
    symbol: str = ""
    
    # Signal time
    signal_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc)) # type: ignore
    
    # Token state at signal time
    token_age_seconds: float = 0.0
    market_cap_usd: float = 0.0
    liquidity_usd: float = 0.0
    curve_depth_usd: float = 0.0
    
    # Flow metrics at signal time
    current_volume_30s: float = 0.0
    current_volume_2m: float = 0.0
    novel_capital: float = 0.0
    independent_buyers: int = 0
    buyer_quality: float = 0.0
    
    # Signal state
    ignition_state: SignalState = SignalState.QUIET
    actor_state: str = ""
    tradeability_trend: TradeabilityTrend = TradeabilityTrend.UNKNOWN
    rotation_state: RotationState = RotationState.UNKNOWN
    
    # Composite score
    ignition_score: float = 0.0
    confidence: float = 0.0
    
    # Explanation
    why_now: str = ""
    
    # Arrival-time modeling
    processing_latency_ms: int = 0
    manual_latency_seconds: int = 60  # Default: assume 1 min manual review
    
    # Outcome checkpoints (filled later)
    outcomes: Dict[str, Dict] = field(default_factory=dict)
    
    # Outcome classification
    outcome_classification: str = ""  # PENDING, SUCCESS, FLOW_FAILED, etc.


@dataclass
class OutcomeCheckpoint:
    """Outcome measurement at specific time horizon."""
    horizon: str                # e.g., "+30s", "+2m", "+5m", "+10m", "+30m", "+1h", "+4h", "+24h"
    measured_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc)) # type: ignore
    
    # Volume metrics
    volume_usd: float = 0.0
    volume_expansion_x: float = 0.0  # vs signal time
    
    # Market cap metrics
    market_cap_usd: float = 0.0
    market_cap_expansion_x: float = 0.0
    max_market_cap_usd: float = 0.0
    
    # Price metrics
    price_usd: float = 0.0
    price_change_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    
    # Liquidity
    liquidity_usd: float = 0.0
    
    # Theoretical vs executable
    theoretical_return_pct: float = 0.0
    executable_return_pct: float = 0.0
    entry_price_executable: float = 0.0
    slippage_bps: float = 0.0


# Outcome classification labels
class OutcomeClassification(Enum):
    """Classification of signal outcome."""
    PENDING = "PENDING"
    SUCCESS_VOLUME_EXPANSION = "SUCCESS_VOLUME_EXPANSION"
    FLOW_FAILED = "FLOW_FAILED"              # No volume expansion
    BUYERS_WERE_RECYCLED = "BUYERS_WERE_RECYCLED"
    ACTOR_FALSE_ALPHA = "ACTOR_FALSE_ALPHA"
    LIQUIDITY_DID_NOT_IMPROVE = "LIQUIDITY_DID_NOT_IMPROVE"
    ROTATION_FALSE = "ROTATION_FALSE"
    IGNITION_TOO_LATE = "IGNITION_TOO_LATE"
    IMMEDIATE_FADE = "IMMEDIATE_FADE"


# Model version for forward validation
MODEL_VERSION = "v1.0"
MODEL_CREATED_AT = "2026-09-05"

# Forward validation results (checkpoint-07)
VALIDATION_SAMPLE_SIZE = 30000
VALIDATION_SIGNALS = 1059
VALIDATION_HIT_RATE = None  # Measurement pending

# Production thresholds (selected after checkpoint-07)
IGNITION_THRESHOLD = 15.0  # Minimum score for FORMING
IGNITION_THRESHOLD_HIGH = 25.0  # Minimum score for IGNITION state
CONFIDENCE_THRESHOLD = 60.0  # Minimum confidence for high-priority alert

# Alert cooldown to prevent spam (seconds)
ALERT_COOLDOWN_SECONDS = 300  # 5 minutes

# Early ignition thresholds
EARLY_IGNITION_THRESHOLD = 8.0  # Lower threshold for FORMING_EARLY
EARLY_IGNITION_VELOCITY_MIN = 1.3  # Minimum velocity (acceleration ratio)
SATURATION_PEAK_RATIO = 0.7  # Current >70% of recent peak = SATURATED
VOLUME_STALL_RATIO = 0.4  # Post/pre below this = DECELERATING
VOLUME_RISING_THRESHOLD = 0.2  # Current >20% of peak = RISING

# Composite score weights (tunable)
COMPOSITE_WEIGHTS = {
    # Primary (40% total)
    "novel_capital": 0.20,
    "buyer_acceleration": 0.10,
    "buyer_quality": 0.10,
    
    # Secondary confirmation (20% total)
    "recurring_actor": 0.05,
    "tradeability": 0.05,
    "rotation": 0.05,
    "reawakening": 0.05,
    
    # Volume freshness (40%)
    "volume_freshness": 0.40,  # Penalize if already crowded
}
