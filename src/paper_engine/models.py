"""Paper trading data models."""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class ExitReason(Enum):
    """Reasons for paper exit."""
    SIGNAL_FADE = "signal_fade"
    FLOW_REVERSAL = "flow_reversal"
    TRADEABILITY_DETERIORATION = "tradeability_deterioration"
    SATURATION = "saturation"
    STOP_LOSS = "stop_loss"
    MAX_HOLD_TIME = "max_hold_time"
    MANUAL = "manual"


class WatchReason(Enum):
    """Why a token is being watched."""
    MANUAL = "manual"
    NOVEL_CAPITAL = "novel_capital"
    BUYER_ACCELERATION = "buyer_acceleration"
    ROTATION = "rotation"
    REAWAKENING = "reawakening"
    FORMING_EARLY = "forming_early"
    IGNITION = "ignition"


class FilterDecision(Enum):
    """Filter decision for a token."""
    # Positive
    SEEN = "seen"
    WATCHED = "watched"
    FORMING_EARLY = "forming_early"
    FORMING = "forming"
    IGNITION = "ignition"
    ACCELERATING = "accelerating"
    SATURATED = "saturated"  # Negative but tracked
    FADING = "fading"
    
    # Explicit rejections
    INSUFFICIENT_ACCELERATION = "insufficient_acceleration"
    BUYER_INDEPENDENCE_INSUFFICIENT = "buyer_independence_insufficient"
    CONFIDENCE_INSUFFICIENT = "confidence_insufficient"
    TRADEABILITY_FAILED = "tradeability_failed"
    ALREADY_SATURATED = "already_saturated"
    SIGNAL_FADED = "signal_faded"
    DATA_INCOMPLETE = "data_incomplete"
    UNKNOWN = "unknown"


@dataclass
class OutcomeObservation:
    """Immutable outcome tracking that continues after position exit.
    
    Tracks volume and price at fixed horizons after paper entry,
    independent of whether the position is still open.
    """
    token_address: str
    entry_decision_time: datetime
    
    # Horizon: +30 seconds
    volume_30s: float = 0.0
    price_30s: float = 0.0
    
    # Horizon: +2 minutes
    volume_2m: float = 0.0
    price_2m: float = 0.0
    
    # Horizon: +5 minutes  
    volume_5m: float = 0.0
    price_5m: float = 0.0
    
    # Horizon: +10 minutes
    volume_10m: float = 0.0
    price_10m: float = 0.0
    
    # Peak volume tracking (max observed within horizon)
    max_volume_30s: float = 0.0
    max_volume_2m: float = 0.0
    max_volume_5m: float = 0.0
    max_volume_10m: float = 0.0
    
    # Timestamps of peak
    peak_volume_30s_time: Optional[datetime] = None
    peak_volume_2m_time: Optional[datetime] = None
    peak_volume_5m_time: Optional[datetime] = None
    peak_volume_10m_time: Optional[datetime] = None
    
    # Volume window definition used
    volume_window_seconds: int = 30  # e.g., volume_rate_30s
    
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class TokenDecision:
    """Complete decision record for a token at a point in time."""
    token_address: str
    timestamp: datetime
    
    # Current state
    state: str
    saturation: str
    
    # Metrics at decision time
    novel_capital_acceleration: float = 0.0
    buyer_acceleration: float = 0.0
    buyer_quality: float = 0.0
    recurring_actor_present: bool = False
    tradeability_trend: str = "unknown"
    reawakening: bool = False
    rotation_present: bool = False
    
    # Score components
    ignition_score: float = 0.0
    confidence: float = 0.0
    
    # Decision
    filter_decision: FilterDecision = FilterDecision.UNKNOWN
    
    # Why now text
    why_now: str = ""
    
    # Position decision
    paper_entry_eligible: bool = False
    entry_rejection_reason: str = ""


@dataclass
class PaperPosition:
    """Paper trading position."""
    paper_trade_id: str
    token_address: str
    
    # Entry
    signal_time: datetime
    entry_decision_time: datetime
    hypothetical_arrival_time: datetime
    
    quoted_entry_price: float = 0.0
    executable_entry_price: float = 0.0
    estimated_slippage: float = 0.0
    estimated_impact: float = 0.0
    
    position_size: float = 0.0  # in token units
    position_value: float = 0.0  # in USD
    
    entry_mcap: float = 0.0
    entry_liquidity: float = 0.0
    entry_reason: str = ""
    entry_state: str = ""  # State at entry (IGNITION, ACCELERATING, etc.)
    
    # Current state
    current_price: float = 0.0
    current_mcap: float = 0.0
    current_liquidity: float = 0.0
    
    # Volume metrics at entry (windowed rate, not cumulative)
    entry_volume: float = 0.0
    
    # Max volume observed after entry
    max_volume_30s: float = 0.0
    max_volume_2m: float = 0.0
    max_volume_5m: float = 0.0
    max_volume_10m: float = 0.0
    
    # Timestamps for volume peaks
    peak_volume_30s_time: Optional[datetime] = None
    peak_volume_2m_time: Optional[datetime] = None
    peak_volume_5m_time: Optional[datetime] = None
    peak_volume_10m_time: Optional[datetime] = None
    
    # P&L
    paper_pnl: float = 0.0
    paper_return: float = 0.0
    
    # MFE/MAE
    max_favorable_excursion: float = 0.0  # % gain from entry
    max_adverse_excursion: float = 0.0   # % loss from entry
    
    # State
    state: str = "open"
    hold_time_seconds: float = 0.0
    
    # Exit
    exit_time: Optional[datetime] = None
    exit_reason: Optional[ExitReason] = None
    exit_price: float = 0.0
    
    # Timestamps for timeline
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass 
class PaperTrade:
    """Completed paper trade record."""
    paper_trade_id: str
    token_address: str
    
    # Entry
    entry_time: datetime
    entry_price: float
    position_size: float
    position_value: float
    entry_reason: str
    
    # Exit
    exit_time: Optional[datetime] = None
    exit_price: float = 0.0
    exit_reason: Optional[ExitReason] = None
    
    # Realized
    realized_pnl: float = 0.0
    realized_return: float = 0.0
    
    # Price-based metrics
    max_mfe: float = 0.0  # % - best price vs entry
    max_mae: float = 0.0  # % - worst price vs entry
    hold_time_seconds: float = 0.0
    
    # VOLUME METRICS - research only, not used for entry/exit decisions
    entry_volume: float = 0.0  # volume at entry time (windowed rate)
    
    # Max volume after entry at different horizons
    max_volume_30s: float = 0.0
    max_volume_2m: float = 0.0
    max_volume_5m: float = 0.0
    max_volume_10m: float = 0.0
    
    # Volume capture ratio = volume_at_entry / max_volume_within_horizon
    volume_capture_ratio_30s: float = 0.0
    volume_capture_ratio_2m: float = 0.0
    volume_capture_ratio_5m: float = 0.0
    volume_capture_ratio_10m: float = 0.0
    
    # Volume expansion = max_volume_within_horizon / volume_at_entry
    volume_expansion_30s: float = 0.0
    volume_expansion_2m: float = 0.0
    volume_expansion_5m: float = 0.0
    volume_expansion_10m: float = 0.0
    
    # Time to peak volume
    seconds_to_max_volume_30s: float = 0.0
    seconds_to_max_volume_2m: float = 0.0
    seconds_to_max_volume_5m: float = 0.0
    seconds_to_max_volume_10m: float = 0.0
    
    created_at: datetime = field(default_factory=datetime.utcnow)
