"""Flow analyzer for novel capital and buyer acceleration detection."""

import os
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple
from collections import defaultdict, deque
from dataclasses import asdict
import hashlib

from src.signals import (
    TradeFlow, TokenFlowMetrics, AccelerationWindow, IgnitionCandidate,
    SignalState, AccelerationState, TradeabilityTrend, ReawakeningState,
    LiquiditySource, LiquidityMetrics, LiquidityWindow, RotationCandidate,
    RotationState,
    WINDOWS, LIQUIDITY_WINDOWS, DEFAULT_THRESHOLDS, WalletCluster
)
from src.db import get_database, Database


class FlowAnalyzer:
    """Analyzes trade flows to detect novel capital and buyer acceleration."""
    
    def __init__(self):
        self.db = get_database()
        self.thresholds = DEFAULT_THRESHOLDS
        
        # Rolling windows: token -> window_seconds -> deque of trades
        self._windows: Dict[str, Dict[int, deque]] = defaultdict(
            lambda: {w: deque(maxlen=1000) for w in WINDOWS}
        )
        
        # Wallet clusters (addresses that likely share a funder)
        self._wallet_clusters: Dict[str, WalletCluster] = {}
        
        # Known deployer relationships
        self._deployer_wallets: Dict[str, str] = {}  # token -> deployer
        
        # Baseline metrics per token (computed from historical data)
        self._baselines: Dict[str, Dict] = {}
        
        # Ignition candidates currently tracked
        self._ignition_candidates: Dict[str, IgnitionCandidate] = {}
        
        # Recent state transitions for event tape
        self._state_transitions: deque = deque(maxlen=100)
        
        # Liquidity tracking: token -> window_seconds -> LiquidityWindow
        self._liquidity_windows: Dict[str, Dict[int, LiquidityWindow]] = defaultdict(
            lambda: {w: LiquidityWindow(window_seconds=w) for w in LIQUIDITY_WINDOWS}
        )
        
        # Current liquidity metrics per token
        self._liquidity: Dict[str, LiquidityMetrics] = {}
        
        # Reawakening state per token
        self._reawakening: Dict[str, ReawakeningState] = {}
        self._reawakening_events: deque = deque(maxlen=100)
        
        # Token activity tracking (for dormancy detection)
        self._last_activity: Dict[str, datetime] = {}
        self._trade_count: Dict[str, int] = defaultdict(int)
        
        # === ROTATION TRACKING ===
        # Recent sells per wallet: wallet -> list of (token, amount, timestamp)
        self._wallet_recent_sells: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=50)
        )
        
        # Token history for prior-runner detection: token -> last significant activity
        self._token_last_runner: Dict[str, datetime] = {}  # tokens that were runners
        self._token_last_ignition: Dict[str, datetime] = {}  # tokens that had ignition
        
        # Rotation candidates
        self._rotation_candidates: Dict[str, RotationCandidate] = {}
        self._rotation_events: deque = deque(maxlen=100)
        
        # Track all trades for rotation analysis
        self._all_trades: deque = deque(maxlen=10000)  # recent trades buffer
    
    def ingest_trade(self, flow: TradeFlow):
        """Ingest a single trade flow."""
        token = flow.token_address
        
        # Add to rolling windows
        for window_seconds in WINDOWS:
            self._windows[token][window_seconds].append(flow)
        
        # Update wallet cluster detection
        self._update_cluster_detection(flow)
        
        # Check for state transitions
        self._check_state_transition(token)
    
    def ingest_batch(self, flows: List[TradeFlow]):
        """Ingest a batch of trade flows."""
        for flow in flows:
            self.ingest_trade(flow)
    
    def _update_cluster_detection(self, flow: TradeFlow):
        """Update wallet cluster analysis."""
        wallet = flow.wallet.lower()
        
        # Track same-block entries for potential clustering
        # In production, this would use more sophisticated clustering
    
    def get_metrics(self, token: str, window_seconds: int = 15) -> TokenFlowMetrics:
        """Get flow metrics for a token in a given window."""
        trades = list(self._windows[token][window_seconds])
        
        if not trades:
            return TokenFlowMetrics(token_address=token)
        
        metrics = TokenFlowMetrics(
            token_address=token,
            window_start=trades[0].timestamp,
            window_end=trades[-1].timestamp,
        )
        
        # Separate buys and sells
        buys = [t for t in trades if t.side == "BUY"]
        sells = [t for t in trades if t.side == "SELL"]
        
        metrics.gross_buy_flow = sum(t.native_amount for t in buys)
        metrics.gross_sell_flow = sum(t.native_amount for t in sells)
        metrics.gross_volume = metrics.gross_buy_flow + metrics.gross_sell_flow
        
        # Get unique wallets
        buyer_wallets = set(t.wallet for t in buys)
        metrics.raw_buyers = len(buyer_wallets)
        metrics.unique_wallets = buyer_wallets
        
        # Analyze novel capital
        novel, recycled = self._estimate_novel_capital(buys)
        metrics.estimated_novel_capital = novel
        metrics.estimated_recycled_capital = recycled
        
        if metrics.gross_volume > 0:
            metrics.novel_capital_ratio = novel / metrics.gross_volume
        
        # Analyze buyer independence
        independent, confidence = self._estimate_independent_buyers(buys)
        metrics.estimated_independent_buyers = independent
        metrics.independence_confidence = confidence
        
        if metrics.raw_buyers > 0:
            metrics.independence_ratio = independent / metrics.raw_buyers
        
        # Calculate rates
        window_duration = (metrics.window_end - metrics.window_start).total_seconds()
        if window_duration > 0:
            metrics.novel_capital_per_second = novel / window_duration
            metrics.independent_buyers_per_second = independent / window_duration
        
        # Get baseline comparison
        baseline = self._baselines.get(token, {})
        if baseline:
            baseline_nc = baseline.get("novel_capital_avg", 1)
            baseline_buyers = baseline.get("buyers_avg", 1)
            metrics.vs_baseline_novel_capital = novel / baseline_nc if baseline_nc > 0 else 0
            metrics.vs_baseline_buyers = len(buyer_wallets) / baseline_buyers if baseline_buyers > 0 else 0
        else:
            # Default baseline: use small values to allow signal detection without history
            # This enables detection on fresh tokens without historical data
            metrics.vs_baseline_novel_capital = novel / 100.0 if novel > 0 else 0
            metrics.vs_baseline_buyers = len(buyer_wallets) / 1.0
        
        # Determine signal state
        metrics.signal_state = self._determine_state(metrics)
        
        # Determine acceleration
        metrics.acceleration = self._determine_acceleration(token, window_seconds)
        
        # Calculate acceleration using existing _determine_acceleration logic
        # The acceleration enum is already set above, derive ratio from it
        if metrics.acceleration == AccelerationState.ACCELERATING:
            metrics.novel_capital_acceleration = 2.0
            metrics.buyer_acceleration = 1.5
        elif metrics.acceleration == AccelerationState.DECELERATING:
            metrics.novel_capital_acceleration = 0.5
            metrics.buyer_acceleration = 0.7
        else:  # STABLE
            metrics.novel_capital_acceleration = 1.0
            metrics.buyer_acceleration = 1.0
        
        return metrics
    
    def _estimate_novel_capital(self, buys: List[TradeFlow]) -> Tuple[float, float]:
        """Estimate novel vs recycled capital from buys."""
        if not buys:
            return 0.0, 0.0
        
        novel = 0.0
        recycled = 0.0
        
        for buy in buys:
            amount = buy.native_amount
            
            # Check if this wallet has recent sell history for same token
            # In production: query db for sell within X minutes before this buy
            # For now: treat all as potentially novel (unknown), don't falsely classify as recycled
            # Only mark as recycled if explicitly flagged
            if buy.estimated_new_capital == True:
                novel += amount
            else:
                # Unknown - conservatively count as novel for signal detection
                # In production: query wallet history to determine
                novel += amount
        
        return novel, recycled
    
    def _estimate_independent_buyers(self, buys: List[TradeFlow]) -> Tuple[int, str]:
        """Estimate number of independent buyers."""
        if not buys:
            return 0, "UNKNOWN"
        
        wallets = [b.wallet.lower() for b in buys]
        unique_wallets = set(wallets)
        
        # Check for clustering indicators
        clustered = set()
        
        # Check for same-block entries
        block_trades = defaultdict(list)
        for buy in buys:
            block_trades[(buy.block, buy.tx_index)].append(buy.wallet)
        
        for trades in block_trades.values():
            if len(trades) > 1:
                # Multiple txs from different wallets in same block - potential coordinated
                clustered.update(trades)
        
        # Check for identical sizing (within 1% tolerance)
        amounts = defaultdict(list)
        for buy in buys:
            key = round(buy.native_amount, -2)  # Round to nearest 100
            amounts[key].append(buy.wallet)
        
        for wallers in amounts.values():
            if len(wallers) > 2:
                clustered.update(wallers)
        
        independent = len(unique_wallets - clustered)
        
        # If no clustering detected (common case), all unique wallets are independent
        if independent == 0 and len(unique_wallets) > 0:
            independent = len(unique_wallets)
        
        # Determine confidence
        if len(unique_wallets) == 0:
            confidence = "UNKNOWN"
        elif independent / len(unique_wallets) >= 0.8:
            confidence = "HIGH"
        elif independent / len(unique_wallets) >= 0.5:
            confidence = "MEDIUM"
        elif independent / len(unique_wallets) >= 0.3:
            confidence = "LOW"
        else:
            confidence = "UNKNOWN"
        
        return independent, confidence
    
    def _determine_state(self, metrics: TokenFlowMetrics) -> SignalState:
        """Determine signal state from metrics."""
        # Minimum thresholds
        if metrics.estimated_novel_capital < self.thresholds["novel_capital_min_ignition"]:
            return SignalState.QUIET
        
        # Check independence
        if metrics.independence_ratio < self.thresholds["independence_min_ratio"]:
            if metrics.vs_baseline_novel_capital > self.thresholds["vs_baseline_min"]:
                return SignalState.FORMING
            return SignalState.QUIET
        
        # Check acceleration vs baseline
        if metrics.vs_baseline_novel_capital > self.thresholds["vs_baseline_min"] * 2:
            return SignalState.IGNITION
        
        if metrics.vs_baseline_novel_capital > self.thresholds["vs_baseline_min"]:
            if metrics.acceleration == AccelerationState.ACCELERATING:
                return SignalState.IGNITION
            return SignalState.FORMING
        
        # Check absolute acceleration
        if metrics.novel_capital_acceleration > 2.0 and metrics.buyer_acceleration > 1.5:
            return SignalState.IGNITION
        
        if metrics.novel_capital_acceleration > 1.5 or metrics.buyer_acceleration > 1.3:
            return SignalState.FORMING
        
        return SignalState.QUIET
    
    def _determine_acceleration(self, token: str, window_seconds: int) -> AccelerationState:
        """Determine acceleration vs prior window."""
        # Get current window
        current_trades = list(self._windows[token][window_seconds])
        if len(current_trades) < 2:
            return AccelerationState.STABLE
        
        # Get prior window (same size, immediately before)
        prior_window_start = current_trades[0].timestamp - timedelta(seconds=window_seconds * 2)
        prior_window_end = current_trades[0].timestamp
        
        prior_trades = [
            t for t in self._windows[token][window_seconds]
            if prior_window_start <= t.timestamp < prior_window_end
        ]
        
        if not prior_trades:
            return AccelerationState.STABLE
        
        current_volume = sum(t.native_amount for t in current_trades)
        prior_volume = sum(t.native_amount for t in prior_trades)
        
        if prior_volume == 0:
            return AccelerationState.STABLE
        
        ratio = current_volume / prior_volume
        
        if ratio > 1.5:
            return AccelerationState.ACCELERATING
        elif ratio < 0.7:
            return AccelerationState.DECELERATING
        
        return AccelerationState.STABLE
    
    def _check_state_transition(self, token: str):
        """Check for state transitions and log them."""
        metrics = self.get_metrics(token)
        current_state = metrics.signal_state
        
        # Check if we have a prior state
        if token in self._ignition_candidates:
            prior_state = self._ignition_candidates[token].signal_state
            if current_state != prior_state:
                self._state_transitions.append({
                    "token": token,
                    "old_state": prior_state.value,
                    "new_state": current_state.value,
                    "timestamp": datetime.utcnow(),
                    "metrics": asdict(metrics)
                })
        
        # Update or create candidate
        if current_state in [SignalState.FORMING, SignalState.IGNITION, SignalState.ACCELERATING]:
            # Check for rotation
            rotation = self._rotation_candidates.get(token)
            
            self._ignition_candidates[token] = IgnitionCandidate(
                token_address=token,
                signal_state=current_state,
                novel_capital_15s=metrics.estimated_novel_capital,
                novel_capital_acceleration_15s=metrics.vs_baseline_novel_capital,
                independent_buyers_15s=metrics.estimated_independent_buyers,
                buyer_acceleration_15s=metrics.vs_baseline_buyers,
                why_now=rotation.why_now if rotation else "",
            )
        elif current_state == SignalState.FADING and token in self._ignition_candidates:
            del self._ignition_candidates[token]
    
    def get_ignition_candidates(self, limit: int = 10) -> List[IgnitionCandidate]:
        """Get current ignition candidates sorted by signal strength."""
        candidates = list(self._ignition_candidates.values())
        
        # Sort by novel capital acceleration
        candidates.sort(
            key=lambda c: c.novel_capital_acceleration_15s * c.independent_buyers_15s,
            reverse=True
        )
        
        return candidates[:limit]
    
    def get_state_transitions(self, limit: int = 20) -> List[Dict]:
        """Get recent state transitions."""
        return list(self._state_transitions)[-limit:]
    
    def get_token_flow(self, token: str) -> Dict:
        """Get detailed flow for a token."""
        metrics_15s = self.get_metrics(token, 15)
        metrics_30s = self.get_metrics(token, 30)
        metrics_1m = self.get_metrics(token, 60)
        
        return {
            "token_address": token,
            "current_state": metrics_15s.signal_state.value,
            "metrics_15s": asdict(metrics_15s),
            "metrics_30s": asdict(metrics_30s),
            "metrics_1m": asdict(metrics_1m),
        }
    
    def compute_baseline(self, token: str, lookback_minutes: int = 60):
        """Compute baseline metrics for a token from historical data."""
        # In production, query database for historical trades
        # For now, use in-memory data
        all_trades = []
        for window in WINDOWS:
            all_trades.extend(self._windows[token][window])
        
        if not all_trades:
            return
        
        # Calculate baseline averages
        # This is a simplified version
        self._baselines[token] = {
            "novel_capital_avg": 10.0,  # Placeholder
            "buyers_avg": 1.0,
            "volume_avg": 100.0,
        }
    
    # === LIQUIDITY & TRADEABILITY METHODS ===
    
    def update_liquidity(self, token: str, liquidity: LiquidityMetrics):
        """Update liquidity metrics for a token."""
        self._liquidity[token] = liquidity
        
        # Update rolling windows
        depth = liquidity.exit_depth_native or liquidity.curve_native_balance or 0
        for window_seconds in LIQUIDITY_WINDOWS:
            lw = self._liquidity_windows[token][window_seconds]
            prior_depth = lw.depth_native
            lw.depth_native = depth
            lw.window_end = datetime.utcnow()
            
            # Calculate change
            if prior_depth > 0:
                lw.depth_change_pct = (depth - prior_depth) / prior_depth
            
            # Update impact metrics
            lw.buy_impact_bps = liquidity.buy_impact_bps
            lw.sell_impact_bps = liquidity.sell_impact_bps
    
    def get_tradeability_trend(self, token: str) -> TradeabilityTrend:
        """Determine tradeability trend based on liquidity improvements."""
        if token not in self._liquidity_windows:
            return TradeabilityTrend.UNKNOWN
        
        windows = self._liquidity_windows[token]
        
        # Check 15s and 30s windows for rapid improvement
        for ws in [15, 30]:
            if ws in windows:
                lw = windows[ws]
                if lw.depth_change_pct >= self.thresholds.get("depth_improvement_rapid_pct", 0.5):
                    return TradeabilityTrend.RAPIDLY_IMPROVING
        
        # Check for steady improvement
        for ws in [30, 60]:
            if ws in windows:
                lw = windows[ws]
                if lw.depth_change_pct >= self.thresholds.get("depth_improvement_min_pct", 0.2):
                    return TradeabilityTrend.IMPROVING
        
        # Check for deterioration
        for ws in [15, 30, 60]:
            if ws in windows:
                lw = windows[ws]
                if lw.depth_change_pct <= -0.2:
                    return TradeabilityTrend.DETERIORATING
        
        return TradeabilityTrend.STABLE
    
    def get_liquidity_change_pct(self, token: str, window_seconds: int = 30) -> float:
        """Get liquidity change percentage for a token."""
        if token not in self._liquidity_windows:
            return 0.0
        return self._liquidity_windows[token].get(window_seconds, LiquidityWindow(window_seconds)).depth_change_pct
    
    # === REAWAKENING DETECTION ===
    
    def _check_reawakening(self, token: str):
        """Check if a token is reawakening from dormancy."""
        now = datetime.utcnow()
        
        # Update last activity
        if token not in self._last_activity:
            self._last_activity[token] = now
            self._reawakening[token] = ReawakeningState.DORMANT
            return
        
        last_activity = self._last_activity[token]
        hours_since = (now - last_activity).total_seconds() / 3600
        
        # Get current metrics
        metrics = self.get_metrics(token, 15)
        current_buyers = metrics.estimated_independent_buyers
        current_capital = metrics.estimated_novel_capital
        
        # Get baseline
        baseline = self._baselines.get(token, {})
        baseline_buyers = baseline.get("buyers_avg", 1.0)
        baseline_capital = baseline.get("novel_capital_avg", 10.0)
        
        prior_state = self._reawakening.get(token, ReawakeningState.DORMANT)
        new_state = prior_state
        trigger = ""
        
        # Check for wake-up conditions
        if prior_state == ReawakeningState.DORMANT:
            # Check buyer jump
            if baseline_buyers > 0 and current_buyers >= baseline_buyers * self.thresholds.get("reawakening_buyer_jump_min", 3.0):
                new_state = ReawakeningState.WAKING
                trigger = "buyer_rate_jump"
            # Check capital jump
            elif baseline_capital > 0 and current_capital >= baseline_capital * self.thresholds.get("reawakening_capital_jump_min", 5.0):
                new_state = ReawakeningState.WAKING
                trigger = "capital_jump"
        
        # Check for reawakening (sustained activity)
        if prior_state in [ReawakeningState.WAKING, ReawakeningState.REAWAKENING]:
            if hours_since < 1.0 and current_buyers > baseline_buyers:
                new_state = ReawakeningState.REAWAKENING
            elif hours_since < 0.25:  # 15 minutes
                new_state = ReawakeningState.ACTIVE
        
        # Update state
        if new_state != prior_state:
            self._reawakening[token] = new_state
            self._last_activity[token] = now
            
            # Record event
            if new_state in [ReawakeningState.WAKING, ReawakeningState.REAWAKENING]:
                event = {
                    "token": token,
                    "prior_state": prior_state.value,
                    "new_state": new_state.value,
                    "trigger": trigger,
                    "observed_at": now.isoformat(),
                    "buyer_rate_baseline": baseline_buyers,
                    "buyer_rate_current": current_buyers,
                    "capital_baseline": baseline_capital,
                    "capital_current": current_capital,
                }
                self._reawakening_events.append(event)
                
                # Also add to state transitions for event tape
                self._state_transitions.append({
                    "token_address": token,
                    "old_state": prior_state.value,
                    "new_state": new_state.value,
                    "reason": trigger or "sustained_activity",
                    "timestamp": now.isoformat(),
                })
        
        # Update activity
        self._last_activity[token] = now
        self._trade_count[token] += 1
    
    def get_reawakening_events(self, limit: int = 10) -> List[Dict]:
        """Get recent reawakening events."""
        events = list(self._reawakening_events)
        return events[-limit:]
    
    def get_active_reawakenings(self, limit: int = 10) -> List[Dict]:
        """Get currently active reawakening tokens."""
        active = []
        for token, state in self._reawakening.items():
            if state in [ReawakeningState.REAWAKENING, ReawakeningState.WAKING, ReawakeningState.ACTIVE]:
                metrics = self.get_metrics(token, 15)
                liquidity = self._liquidity.get(token)
                tradeability = self.get_tradeability_trend(token)
                
                last_act = self._last_activity.get(token)
                prior_hours = 0.0
                if last_act:
                    prior_hours = (datetime.utcnow() - last_act).total_seconds() / 3600
                
                active.append({
                    "token_address": token,
                    "state": state.value,
                    "tradeability_trend": tradeability.value,
                    "novel_capital_15s": metrics.estimated_novel_capital,
                    "independent_buyers_15s": metrics.estimated_independent_buyers,
                    "buyer_acceleration": metrics.novel_capital_acceleration,
                    "liquidity": liquidity.exit_depth_native if liquidity else None,
                    "prior_activity_hours": prior_hours,
                    "observed_at": last_act.isoformat() if last_act else None,
                })
        
        # Sort by capital acceleration
        active.sort(key=lambda x: x.get("buyer_acceleration", 0), reverse=True)
        return active[:limit]
    
    def ingest_trade(self, flow: TradeFlow):
        """Ingest a single trade flow."""
        token = flow.token_address
        
        # Add to rolling windows
        for window_seconds in WINDOWS:
            self._windows[token][window_seconds].append(flow)
        
        # Track for rotation analysis
        self._all_trades.append(flow)
        
        # Track sells for rotation detection
        if flow.side.upper() == "SELL":
            self._track_sell(flow)
        else:
            # Check for rotation on buys
            self._check_rotation(flow)
        
        # Update wallet cluster detection
        self._update_cluster_detection(flow)
        
        # Check for state transitions
        self._check_state_transition(token)
        
        # Check for reawakening
        self._check_reawakening(token)
        
        # Mark if this token was a runner/ignition
        self._update_token_history(token, flow)
    
    # === ROTATION DETECTION METHODS ===
    
    def _track_sell(self, flow: TradeFlow):
        """Track a sell for potential rotation detection."""
        wallet = flow.wallet.lower()
        amount = flow.usd_value or flow.native_amount or 0
        
        # Skip dust
        if amount < self.thresholds.get("dust_threshold_usd", 10):
            return
        
        self._wallet_recent_sells[wallet].append({
            "token": flow.token_address.lower(),
            "amount": amount,
            "timestamp": flow.timestamp,
            "tx_hash": flow.tx_hash,
            "side": "SELL"
        })
    
    def _check_rotation(self, flow: TradeFlow):
        """Check if a buy is a rotation from another token."""
        if flow.side.upper() != "BUY":
            return
        
        wallet = flow.wallet.lower()
        token = flow.token_address.lower()
        amount = flow.usd_value or flow.native_amount or 0
        
        # Skip dust
        if amount < self.thresholds.get("dust_threshold_usd", 10):
            return
        
        # Look for recent sells from this wallet
        if wallet not in self._wallet_recent_sells:
            return
        
        recent_sells = list(self._wallet_recent_sells[wallet])
        now = flow.timestamp
        
        max_delay = self.thresholds.get("rotation_max_delay_seconds", 300)
        probable_delay = self.thresholds.get("rotation_probable_delay_seconds", 900)
        
        for sell in recent_sells:
            # Check time window
            delay = (now - sell["timestamp"]).total_seconds()
            if delay > probable_delay:
                continue
            
            source_token = sell["token"]
            
            # Skip self-rotation (same token)
            if source_token == token:
                continue
            
            exit_amount = sell["amount"]
            entry_amount = amount
            
            # Check minimum thresholds
            exit_min = self.thresholds.get("rotation_exit_min_usd", 100)
            entry_min = self.thresholds.get("rotation_entry_min_usd", 50)
            
            if exit_amount < exit_min or entry_amount < entry_min:
                continue
            
            # Calculate confidence and state
            state, confidence, score = self._evaluate_rotation(
                source_token, token, wallet, exit_amount, entry_amount, delay
            )
            
            if state != RotationState.REJECTED:
                # Create rotation candidate
                candidate = RotationCandidate(
                    token_address=token,
                    rotation_state=state,
                    rotation_confidence=confidence,
                    rotation_score=score,
                    source_token=source_token,
                    actor_id=wallet,
                    source_exit_amount_usd=exit_amount,
                    destination_entry_amount_usd=entry_amount,
                    source_exit_at=sell["timestamp"],
                    destination_entry_at=now,
                    rotation_delay_seconds=delay,
                    evidence_refs=[sell.get("", ""), flow.tx_hash],
                )
                
                # Check prior runner status
                self._check_prior_runner(candidate)
                
                # Store candidate
                self._rotation_candidates[token] = candidate
                
                # Record event
                self._rotation_events.append({
                    "token": token,
                    "source_token": source_token,
                    "actor": wallet[:8] + "...",
                    "state": state.value,
                    "confidence": confidence,
                    "delay_seconds": delay,
                    "amount_in": entry_amount,
                    "timestamp": now.isoformat(),
                })
                
                # Add to state transitions
                self._state_transitions.append({
                    "token_address": token,
                    "old_state": "N/A",
                    "new_state": f"ROTATION_FROM_{source_token[:8]}",
                    "reason": f"rotation_{state.value}",
                    "timestamp": now.isoformat(),
                })
                
                break  # Only need first match
    
    def _evaluate_rotation(self, source_token: str, dest_token: str, wallet: str,
                          exit_amount: float, entry_amount: float, delay_seconds: float
                          ) -> Tuple[RotationState, float, float]:
        """Evaluate rotation quality and determine state."""
        
        # Calculate base confidence
        confidence = 0.5  # Start neutral
        
        # Factor 1: Exit magnitude (more significant = higher confidence)
        if exit_amount >= 1000:
            confidence += 0.3
        elif exit_amount >= 100:
            confidence += 0.2
        elif exit_amount >= 50:
            confidence += 0.1
        
        # Factor 2: Entry magnitude
        if entry_amount >= 500:
            confidence += 0.2
        elif entry_amount >= 100:
            confidence += 0.1
        
        # Factor 3: Time proximity (shorter = higher confidence)
        max_delay = self.thresholds.get("rotation_max_delay_seconds", 300)
        if delay_seconds <= max_delay:
            confidence += 0.2
        elif delay_seconds <= self.thresholds.get("rotation_probable_delay_seconds", 900):
            confidence += 0.1
        
        # Factor 4: Actor quality (repeat actor = higher confidence)
        total_sells = sum(1 for s in self._wallet_recent_sells.get(wallet, []))
        if total_sells > 3:
            confidence += 0.15
        elif total_sells > 1:
            confidence += 0.1
        
        # Factor 5: Check for cluster/related activity
        # (simplified - would need proper cluster analysis)
        
        # Calculate score
        score = confidence * 100
        
        # Determine state
        min_confidence = self.thresholds.get("rotation_min_confidence", 0.5)
        
        if confidence >= 0.8:
            state = RotationState.STRONG_ROTATION
        elif confidence >= 0.65:
            state = RotationState.PROBABLE_ROTATION
        elif confidence >= min_confidence:
            state = RotationState.POSSIBLE_ROTATION
        else:
            state = RotationState.REJECTED
        
        return state, confidence, score
    
    def _check_prior_runner(self, candidate: RotationCandidate):
        """Check if source token was a prior runner/ignition."""
        source = candidate.source_token
        now = datetime.utcnow()
        
        # Check if source was a runner
        if source in self._token_last_runner:
            runner_time = self._token_last_runner[source]
            hours_ago = (now - runner_time).total_seconds() / 3600
            max_hours = self.thresholds.get("prior_runner_hours", 24)
            
            if hours_ago <= max_hours:
                candidate.is_prior_runner = True
                candidate.prior_runner_hours_ago = hours_ago
                candidate.rotation_confidence *= self.thresholds.get("prior_runner_boost", 2.0)
                candidate.rotation_score *= self.thresholds.get("prior_runner_boost", 2.0)
        
        # Check if source had ignition
        if source in self._token_last_ignition:
            ignition_time = self._token_last_ignition[source]
            hours_ago = (now - ignition_time).total_seconds() / 3600
            max_hours = self.thresholds.get("prior_ignition_hours", 6)
            
            if hours_ago <= max_hours:
                candidate.is_prior_ignition = True
                candidate.source_token_state = "recent_ignition"
            elif candidate.source_token_state != "recent_runner":
                candidate.source_token_state = "prior_runner"
        
        # Set why_now
        if candidate.is_prior_runner or candidate.is_prior_ignition:
            candidate.why_now = f"Rotation from prior {candidate.source_token_state or 'runner'}"
        else:
            candidate.why_now = f"Rotation from {candidate.source_token[:10]}..."
    
    def _update_token_history(self, token: str, flow: TradeFlow):
        """Update token history for prior-runner detection."""
        now = flow.timestamp
        
        # Get current state
        metrics = self.get_metrics(token, 15)
        
        # If high activity, mark as potential runner
        if metrics.estimated_novel_capital > 10000:  # $10k+ novel capital
            self._token_last_runner[token] = now
        
        # If ignition state, mark as ignition
        if metrics.signal_state in [SignalState.IGNITION, SignalState.ACCELERATING]:
            self._token_last_ignition[token] = now
    
    def get_rotation_candidates(self, limit: int = 10) -> List[RotationCandidate]:
        """Get active rotation candidates."""
        # Sort by score descending
        sorted_candidates = sorted(
            self._rotation_candidates.values(),
            key=lambda x: x.rotation_score,
            reverse=True
        )
        return sorted_candidates[:limit]
    
    def get_rotation_events(self, limit: int = 20) -> List[Dict]:
        """Get recent rotation events."""
        events = list(self._rotation_events)
        return events[-limit:]
    
    def get_rotations_for_token(self, token: str) -> Optional[RotationCandidate]:
        """Get rotation data for a specific token."""
        return self._rotation_candidates.get(token.lower())


# Global analyzer instance
_analyzer: Optional[FlowAnalyzer] = None


def get_flow_analyzer() -> FlowAnalyzer:
    """Get or create the global flow analyzer."""
    global _analyzer
    if _analyzer is None:
        _analyzer = FlowAnalyzer()
    return _analyzer
