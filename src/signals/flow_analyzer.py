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
    SignalState, AccelerationState, WINDOWS, DEFAULT_THRESHOLDS, WalletCluster
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
        
        # Determine signal state
        metrics.signal_state = self._determine_state(metrics)
        
        # Determine acceleration
        metrics.acceleration = self._determine_acceleration(token, window_seconds)
        
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
            is_recycled = buy.estimated_new_capital == False
            
            if is_recycled:
                recycled += amount
            else:
                # Assume novel unless proven otherwise
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
            self._ignition_candidates[token] = IgnitionCandidate(
                token_address=token,
                signal_state=current_state,
                novel_capital_15s=metrics.estimated_novel_capital,
                novel_capital_acceleration_15s=metrics.vs_baseline_novel_capital,
                independent_buyers_15s=metrics.estimated_independent_buyers,
                buyer_acceleration_15s=metrics.vs_baseline_buyers,
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


# Global analyzer instance
_analyzer: Optional[FlowAnalyzer] = None


def get_flow_analyzer() -> FlowAnalyzer:
    """Get or create the global flow analyzer."""
    global _analyzer
    if _analyzer is None:
        _analyzer = FlowAnalyzer()
    return _analyzer
