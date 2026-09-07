"""Data models for RH Volume Ignition."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
import uuid


class WatchTier(Enum):
    """Token watch tier levels."""
    TIER_0 = 0  # Fresh launches
    TIER_1 = 1  # Active/surfaced tokens
    TIER_2 = 2  # Important actor-touched
    TIER_3 = 3  # Recent winners/prior active
    TIER_4 = 4  # Low-priority background


class WatchReason(Enum):
    """Reason token entered watch universe."""
    FRESH_LAUNCH = "FRESH_LAUNCH"
    ACTIVE_FLOW = "ACTIVE_FLOW"
    IMPORTANT_ACTOR = "IMPORTANT_ACTOR"
    RECENT_WINNER = "RECENT_WINNER"
    REAWAKENING = "REAWAKENING"
    MANUAL_WATCH = "MANUAL_WATCH"


class EventType(Enum):
    """Types of blockchain events."""
    TRANSFER = "Transfer"
    MINT = "Mint"
    BURN = "Burn"
    SWAP = "Swap"
    APPROVAL = "Approval"
    PAIR_CREATED = "PairCreated"
    SYNC = "Sync"
    LIQUIDITY_CHANGE = "LiquidityChange"
    UNKNOWN = "Unknown"


class BudgetState(Enum):
    """RPC budget states."""
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


@dataclass
class RawEvent:
    """Normalized raw blockchain event."""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    block_number: int = 0
    transaction_index: int = 0
    log_index: int = 0
    tx_hash: str = ""
    observed_at: datetime = field(default_factory=datetime.utcnow)
    block_timestamp: Optional[datetime] = None
    source: str = ""  # provider/rpc name
    contract_address: str = ""
    event_type: str = ""
    raw_reference: str = ""


@dataclass
class WatchedToken:
    """Token in the watch universe."""
    token_address: str
    protocol: str = "UNKNOWN"
    first_seen_at: datetime = field(default_factory=datetime.utcnow)
    last_activity_at: datetime = field(default_factory=datetime.utcnow)
    watch_tier: WatchTier = WatchTier.TIER_0
    watch_reason: WatchReason = WatchReason.FRESH_LAUNCH
    activity_score: float = 0.0
    last_market_state_at: Optional[datetime] = None
    
    # Previous tier for reawakening tracking
    previous_tier: Optional[WatchTier] = None


@dataclass
class TierTransition:
    """Record of tier changes."""
    token_address: str
    old_tier: WatchTier
    new_tier: WatchTier
    trigger_type: str
    trigger_value: str
    observed_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class RPCBudget:
    """RPC usage budget tracker."""
    requests_last_minute: int = 0
    requests_last_hour: int = 0
    errors: int = 0
    rate_limited: int = 0  # 429s
    fallback_usage: int = 0
    paid_provider_usage: int = 0
    state: BudgetState = BudgetState.GREEN
    last_reset: datetime = field(default_factory=datetime.utcnow)
    
    # Historical for p50/p95
    request_timestamps: list = field(default_factory=list)
    latency_samples: list = field(default_factory=list)
