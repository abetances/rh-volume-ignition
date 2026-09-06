"""Paper trading engine core."""
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, field

from .models import (
    PaperPosition,
    PaperTrade,
    ExitReason,
    FilterDecision,
    TokenDecision,
)
from .config import PaperConfig, DEFAULT_CONFIG


@dataclass
class PaperEngine:
    """Paper trading engine - simulates trades without real execution."""
    
    config: PaperConfig = field(default_factory=lambda: DEFAULT_CONFIG)
    
    # State
    positions: Dict[str, PaperPosition] = field(default_factory=dict)
    decisions: List[TokenDecision] = field(default_factory=list)
    completed_trades: List[PaperTrade] = field(default_factory=list)
    
    def evaluate_signal(
        self,
        token_address: str,
        timestamp: datetime,
        state: str,
        saturation: str,
        novel_capital_accel: float,
        buyer_accel: float,
        buyer_quality: float,
        recurring_actor: bool,
        tradeability_trend: str,
        reawakening: bool,
        rotation: bool,
        ignition_score: float,
        confidence: float,
        why_now: str,
    ) -> TokenDecision:
        """Evaluate a signal and record the decision."""
        
        # Determine filter decision
        filter_decision = self._determine_filter_decision(
            state, saturation, ignition_score, confidence, tradeability_trend
        )
        
        # Check paper entry eligibility
        entry_eligible, rejection_reason = self._check_entry_eligibility(
            state, saturation, confidence, tradeability_trend
        )
        
        decision = TokenDecision(
            token_address=token_address,
            timestamp=timestamp,
            state=state,
            saturation=saturation,
            novel_capital_acceleration=novel_capital_accel,
            buyer_acceleration=buyer_accel,
            buyer_quality=buyer_quality,
            recurring_actor_present=recurring_actor,
            tradeability_trend=tradeability_trend,
            reawakening=reawakening,
            rotation_present=rotation,
            ignition_score=ignition_score,
            confidence=confidence,
            filter_decision=filter_decision,
            why_now=why_now,
            paper_entry_eligible=entry_eligible,
            entry_rejection_reason=rejection_reason,
        )
        
        if self.config.store_all_decisions:
            self.decisions.append(decision)
        
        # Auto-enter if eligible
        if entry_eligible and token_address not in self.positions:
            self._enter_paper_position(decision, timestamp)
        
        return decision
    
    def _determine_filter_decision(
        self,
        state: str,
        saturation: str,
        ignition_score: float,
        confidence: float,
        tradeability_trend: str,
    ) -> FilterDecision:
        """Determine what filter decision was made."""
        
        # Map state to decision
        state_map = {
            'QUIET': FilterDecision.SEEN,
            'FORMING_EARLY': FilterDecision.FORMING_EARLY,
            'FORMING': FilterDecision.FORMING,
            'IGNITION': FilterDecision.IGNITION,
            'ACCELERATING': FilterDecision.ACCELERATING,
            'SATURATED': FilterDecision.SATURATED,
            'FADING': FilterDecision.FADING,
        }
        
        if state in state_map:
            return state_map[state]
        
        # Check rejection reasons
        if saturation in ['ALREADY_CROWDED', 'DECELERATING']:
            return FilterDecision.ALREADY_SATURATED
        
        if confidence < 0.3:
            return FilterDecision.CONFIDENCE_INSUFFICIENT
        
        if tradeability_trend == 'declining':
            return FilterDecision.TRADEABILITY_FAILED
        
        return FilterDecision.UNKNOWN
    
    def _check_entry_eligibility(
        self,
        state: str,
        saturation: str,
        confidence: float,
        tradeability_trend: str,
    ) -> tuple[bool, str]:
        """Check if a paper entry should be made."""
        
        # Must be IGNITION (or ACCELERATING as secondary)
        if self.config.require_ignition_state:
            if state not in ['IGNITION', 'ACCELERATING']:
                return False, f"state={state} not ignition"
        
        # Must not be saturated
        if self.config.require_not_saturated:
            if saturation in ['ALREADY_CROWDED', 'DECELERATING']:
                return False, f"saturation={saturation}"
        
        # Confidence threshold
        if confidence < self.config.min_confidence_for_entry:
            return False, f"confidence={confidence:.2f} < {self.config.min_confidence_for_entry}"
        
        # Tradeability
        if tradeability_trend == 'declining':
            return False, "tradeability declining"
        
        return True, ""
    
    def _enter_paper_position(
        self,
        decision: TokenDecision,
        timestamp: datetime,
    ) -> PaperPosition:
        """Enter a paper position."""
        
        trade_id = str(uuid.uuid4())[:8]
        
        # Get entry volume from the decision's metrics
        entry_volume = decision.ignition_score * 1000  # Approximate - would need real volume feed
        
        position = PaperPosition(
            paper_trade_id=trade_id,
            token_address=decision.token_address,
            signal_time=decision.timestamp,
            entry_decision_time=timestamp,
            hypothetical_arrival_time=timestamp + timedelta(seconds=self.config.arrival_time_seconds),
            
            # Simulated execution (would need price feed for real values)
            position_value=self.config.default_position_pct * self.config.max_position_value,
            
            entry_reason=decision.why_now or f"IGNITION signal, confidence={decision.confidence:.2f}",
            entry_volume=entry_volume,
            state="open",
        )
        
        self.positions[decision.token_address] = position
        return position
    
    def update_positions(
        self,
        token_prices: Dict[str, float],
        token_mcaps: Dict[str, float],
        token_liquidity: Dict[str, float],
        current_time: datetime,
        token_volumes: Dict[str, float] = None,
    ) -> List[PaperPosition]:
        """Update position values and check exit conditions.
        
        Args:
            token_prices: current price per token
            token_mcaps: current market cap per token
            token_liquidity: current liquidity per token
            current_time: current timestamp
            token_volumes: windowed volume rate per token (not cumulative)
        """
        
        if token_volumes is None:
            token_volumes = {}
        
        exited = []
        
        for token, position in list(self.positions.items()):
            if position.state != "open":
                continue
            
            # Update current values
            if token in token_prices:
                position.current_price = token_prices[token]
            if token in token_mcaps:
                position.current_mcap = token_mcaps[token]
            if token in token_liquidity:
                position.current_liquidity = token_liquidity[token]
            
            # Update volume metrics (research only - not used for entry/exit)
            if token in token_volumes:
                self._update_volume_metrics(position, token_volumes[token], current_time)
            
            # Calculate P&L
            if position.current_price > 0 and position.executable_entry_price > 0:
                position.paper_return = (position.current_price - position.executable_entry_price) / position.executable_entry_price
                position.paper_pnl = position.position_value * position.paper_return
            
            # Calculate hold time
            position.hold_time_seconds = (current_time - position.entry_decision_time).total_seconds()
            
            # Check exit conditions
            exit_reason = self._check_exit_conditions(position, current_time)
            if exit_reason:
                self._exit_paper_position(position, exit_reason, current_time)
                exited.append(position)
            
            position.updated_at = current_time
        
        return exited
    
    def _update_volume_metrics(
        self,
        position: PaperPosition,
        current_volume: float,
        current_time: datetime,
    ):
        """Track volume metrics for research (not used for entry/exit decisions)."""
        
        entry_time = position.entry_decision_time
        seconds_since_entry = (current_time - entry_time).total_seconds()
        
        # Track max volume at each horizon
        if seconds_since_entry <= 30:
            if current_volume > position.max_volume_30s:
                position.max_volume_30s = current_volume
                position.peak_volume_30s_time = current_time
        
        if seconds_since_entry <= 120:
            if current_volume > position.max_volume_2m:
                position.max_volume_2m = current_volume
                position.peak_volume_2m_time = current_time
        
        if seconds_since_entry <= 300:
            if current_volume > position.max_volume_5m:
                position.max_volume_5m = current_volume
                position.peak_volume_5m_time = current_time
        
        if seconds_since_entry <= 600:
            if current_volume > position.max_volume_10m:
                position.max_volume_10m = current_volume
                position.peak_volume_10m_time = current_time
    
    def _check_exit_conditions(
        self,
        position: PaperPosition,
        current_time: datetime,
    ) -> Optional[ExitReason]:
        """Check if position should be exited."""
        
        # Stop loss
        if position.paper_return <= self.config.stop_loss_pct:
            return ExitReason.STOP_LOSS
        
        # Max hold time
        if position.hold_time_seconds >= self.config.max_hold_time_seconds:
            return ExitReason.MAX_HOLD_TIME
        
        return None
    
    def _exit_paper_position(
        self,
        position: PaperPosition,
        exit_reason: ExitReason,
        exit_time: datetime,
    ) -> PaperTrade:
        """Exit a paper position."""
        
        position.state = "closed"
        position.exit_time = exit_time
        position.exit_reason = exit_reason
        
        # Calculate volume metrics for trade record
        entry_vol = position.entry_volume
        
        # Volume capture ratios and expansion factors
        vol_cap_30s = entry_vol / position.max_volume_30s if position.max_volume_30s > 0 else 0.0
        vol_cap_2m = entry_vol / position.max_volume_2m if position.max_volume_2m > 0 else 0.0
        vol_cap_5m = entry_vol / position.max_volume_5m if position.max_volume_5m > 0 else 0.0
        vol_cap_10m = entry_vol / position.max_volume_10m if position.max_volume_10m > 0 else 0.0
        
        vol_exp_30s = position.max_volume_30s / entry_vol if entry_vol > 0 else 0.0
        vol_exp_2m = position.max_volume_2m / entry_vol if entry_vol > 0 else 0.0
        vol_exp_5m = position.max_volume_5m / entry_vol if entry_vol > 0 else 0.0
        vol_exp_10m = position.max_volume_10m / entry_vol if entry_vol > 0 else 0.0
        
        # Time to peak volume
        def calc_seconds_to_peak(peak_time, entry_time):
            if peak_time and entry_time:
                return (peak_time - entry_time).total_seconds()
            return 0.0
        
        # Create completed trade record
        trade = PaperTrade(
            paper_trade_id=position.paper_trade_id,
            token_address=position.token_address,
            entry_time=position.entry_decision_time,
            entry_price=position.executable_entry_price,
            position_size=position.position_size,
            position_value=position.position_value,
            entry_reason=position.entry_reason,
            exit_time=exit_time,
            exit_price=position.current_price,
            exit_reason=exit_reason,
            realized_pnl=position.paper_pnl,
            realized_return=position.paper_return,
            max_mfe=position.max_favorable_excursion,
            max_mae=position.max_adverse_excursion,
            hold_time_seconds=position.hold_time_seconds,
            
            # Volume metrics (research only)
            entry_volume=entry_vol,
            max_volume_30s=position.max_volume_30s,
            max_volume_2m=position.max_volume_2m,
            max_volume_5m=position.max_volume_5m,
            max_volume_10m=position.max_volume_10m,
            volume_capture_ratio_30s=vol_cap_30s,
            volume_capture_ratio_2m=vol_cap_2m,
            volume_capture_ratio_5m=vol_cap_5m,
            volume_capture_ratio_10m=vol_cap_10m,
            volume_expansion_30s=vol_exp_30s,
            volume_expansion_2m=vol_exp_2m,
            volume_expansion_5m=vol_exp_5m,
            volume_expansion_10m=vol_exp_10m,
            seconds_to_max_volume_30s=calc_seconds_to_peak(position.peak_volume_30s_time, position.entry_decision_time),
            seconds_to_max_volume_2m=calc_seconds_to_peak(position.peak_volume_2m_time, position.entry_decision_time),
            seconds_to_max_volume_5m=calc_seconds_to_peak(position.peak_volume_5m_time, position.entry_decision_time),
            seconds_to_max_volume_10m=calc_seconds_to_peak(position.peak_volume_10m_time, position.entry_decision_time),
        )
        
        self.completed_trades.append(trade)
        return trade
    
    def get_open_positions(self) -> List[PaperPosition]:
        """Get all open positions."""
        return [p for p in self.positions.values() if p.state == "open"]
    
    def get_recent_trades(self, limit: int = 10) -> List[PaperTrade]:
        """Get recent completed trades."""
        return sorted(self.completed_trades, key=lambda t: t.exit_time or t.created_at, reverse=True)[:limit]
    
    def get_statistics(self) -> dict:
        """Get paper trading statistics."""
        trades = self.completed_trades
        if not trades:
            return {
                'total_trades': 0,
                'wins': 0,
                'losses': 0,
                'win_rate': 0.0,
                'median_return': 0.0,
                'median_mfe': 0.0,
                'median_mae': 0.0,
            }
        
        wins = [t for t in trades if t.realized_return > 0]
        losses = [t for t in trades if t.realized_return <= 0]
        returns = [t.realized_return for t in trades]
        mfos = [t.max_mfe for t in trades]
        maes = [t.max_mae for t in trades]
        
        return {
            'total_trades': len(trades),
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': len(wins) / len(trades) * 100,
            'median_return': sorted(returns)[len(returns)//2] * 100,
            'median_mfe': sorted(mfos)[len(mfos)//2] * 100,
            'median_mae': sorted(maes)[len(maes)//2] * 100,
        }
    
    def get_token_timeline(self, token_address: str) -> List[TokenDecision]:
        """Get decision history for a token."""
        return [d for d in self.decisions if d.token_address == token_address]
