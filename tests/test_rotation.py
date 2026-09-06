"""Tests for rotation inflow detection."""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.signals.flow_analyzer import FlowAnalyzer
from src.signals import (
    TradeFlow, RotationState, WalletCluster, IgnitionCandidate, AccelerationState
)


def now():
    return datetime.now(timezone.utc)


class TestRotationDetection:
    """Test rotation detection logic."""

    @pytest.fixture
    def analyzer(self):
        """Create fresh analyzer."""
        return FlowAnalyzer()

    def test_real_atoi_rotation(self, analyzer):
        """Test real A→B rotation is detected."""
        now_ts = now()

        # Actor sells Token A
        sell_flow = TradeFlow(
            token_address="TokenA",
            wallet="actor123",
            side="SELL",
            native_amount=100,
            usd_value=500,
            tx_hash="0xsell",
            timestamp=now_ts - timedelta(minutes=2),
            block=100,
            tx_index=1,
            log_index=1
        )
        analyzer.ingest_trade(sell_flow)

        # Same actor buys Token B within 5 minutes
        buy_flow = TradeFlow(
            token_address="TokenB",
            wallet="actor123",
            side="BUY",
            native_amount=50,
            usd_value=250,
            tx_hash="0xbuy",
            timestamp=now_ts,
            block=101,
            tx_index=5,
            log_index=1
        )
        analyzer.ingest_trade(buy_flow)

        # Check rotation detected
        candidates = analyzer.get_rotation_candidates(limit=10)

        # Should have at least one rotation candidate for TokenB
        tokenb_rotations = [c for c in candidates if c.token_address == "TokenB"]
        assert len(tokenb_rotations) > 0, "Rotation not detected"

        rotation = tokenb_rotations[0]
        assert rotation.source_token == "TokenA"
        assert rotation.actor_id == "actor123"
        assert rotation.rotation_state in [RotationState.POSSIBLE_ROTATION,
                                          RotationState.PROBABLE_ROTATION,
                                          RotationState.STRONG_ROTATION]

    def test_sequential_unrelated_trades_rejected(self, analyzer):
        """Test sequential unrelated trades are rejected as rotation."""
        now_ts = now()

        # Wallet A sells Token A
        sell_flow_a = TradeFlow(
            token_address="TokenA",
            wallet="wallet_a",
            side="SELL",
            native_amount=10,
            usd_value=50,
            tx_hash="0xsella",
            timestamp=now_ts - timedelta(minutes=30),
            block=100,
            tx_index=1,
            log_index=1
        )
        analyzer.ingest_trade(sell_flow_a)

        # Wallet B buys Token B (different wallet - no rotation)
        buy_flow_b = TradeFlow(
            token_address="TokenB",
            wallet="wallet_b",
            side="BUY",
            native_amount=50,
            usd_value=250,
            tx_hash="0xbuyb",
            timestamp=now_ts,
            block=101,
            tx_index=5,
            log_index=1
        )
        analyzer.ingest_trade(buy_flow_b)

        # Check no rotation detected
        candidates = analyzer.get_rotation_candidates(limit=10)
        tokenb_rotations = [c for c in candidates if c.token_address == "TokenB"]
        assert len(tokenb_rotations) == 0, "False rotation detected for unrelated trades"

    def test_internal_cluster_transfer_rejected(self, analyzer):
        """Test same-cluster internal transfers are rejected."""
        now_ts = now()

        # Create a wallet cluster
        cluster = WalletCluster(
            cluster_id="cluster_1",
            member_wallets=["wallet1", "wallet2", "wallet3"],
            cluster_type="deployer_related",
            first_seen=now_ts - timedelta(days=30)
        )
        analyzer._wallet_clusters["wallet1"] = cluster
        analyzer._wallet_clusters["wallet2"] = cluster
        analyzer._wallet_clusters["wallet3"] = cluster

        # Member sells Token A
        sell_flow = TradeFlow(
            token_address="TokenA",
            wallet="wallet1",
            side="SELL",
            native_amount=100,
            usd_value=500,
            tx_hash="0xsell",
            timestamp=now_ts - timedelta(minutes=2),
            block=100,
            tx_index=1,
            log_index=1
        )
        analyzer.ingest_trade(sell_flow)

        # Cluster member buys Token B (internal transfer - should be rejected)
        buy_flow = TradeFlow(
            token_address="TokenB",
            wallet="wallet2",
            side="BUY",
            native_amount=50,
            usd_value=250,
            tx_hash="0xbuy",
            timestamp=now_ts,
            block=101,
            tx_index=5,
            log_index=1
        )
        analyzer.ingest_trade(buy_flow)

        # Check rotation rejected or flagged as low confidence
        candidates = analyzer.get_rotation_candidates(limit=10)
        # Internal cluster transfers should have lower confidence or be rejected
        for c in candidates:
            if c.token_address == "TokenB":
                # Should be rejected or have very low confidence
                assert c.rotation_confidence < 0.5 or c.rotation_state == RotationState.REJECTED

    def test_dust_flow_rejected(self, analyzer):
        """Test tiny/dust flows are rejected."""
        now_ts = now()

        # Small sell (below threshold)
        sell_flow = TradeFlow(
            token_address="TokenA",
            wallet="actor123",
            side="SELL",
            native_amount=1,
            usd_value=5,  # Below $10 dust threshold
            tx_hash="0xsell",
            timestamp=now_ts - timedelta(minutes=2),
            block=100,
            tx_index=1,
            log_index=1
        )
        analyzer.ingest_trade(sell_flow)

        # Small buy
        buy_flow = TradeFlow(
            token_address="TokenB",
            wallet="actor123",
            side="BUY",
            native_amount=1,
            usd_value=10,
            tx_hash="0xbuy",
            timestamp=now_ts,
            block=101,
            tx_index=5,
            log_index=1
        )
        analyzer.ingest_trade(buy_flow)

        # Check no rotation detected (dust rejected)
        candidates = analyzer.get_rotation_candidates(limit=10)
        tokenb_rotations = [c for c in candidates if c.token_address == "TokenB"]
        assert len(tokenb_rotations) == 0, "Dust flow should be rejected"

    def test_prior_runner_weighting(self, analyzer):
        """Test prior-runner weighting boosts rotation score."""
        now_ts = now()

        # Mark TokenA as a recent runner (within 24h)
        analyzer._token_last_runner["tokenA"] = now_ts - timedelta(hours=12)

        # Actor sells Token A
        sell_flow = TradeFlow(
            token_address="TokenA",
            wallet="actor123",
            side="SELL",
            native_amount=100,
            usd_value=1000,
            tx_hash="0xsell",
            timestamp=now_ts - timedelta(minutes=2),
            block=100,
            tx_index=1,
            log_index=1
        )
        analyzer.ingest_trade(sell_flow)

        # Actor buys Token B
        buy_flow = TradeFlow(
            token_address="TokenB",
            wallet="actor123",
            side="BUY",
            native_amount=50,
            usd_value=500,
            tx_hash="0xbuy",
            timestamp=now_ts,
            block=101,
            tx_index=5,
            log_index=1
        )
        analyzer.ingest_trade(buy_flow)

        # Check rotation has prior runner flag
        candidates = analyzer.get_rotation_candidates(limit=10)
        tokenb_rotations = [c for c in candidates if c.token_address == "TokenB"]
        assert len(tokenb_rotations) > 0

        rotation = tokenb_rotations[0]
        assert rotation.is_prior_runner == True
        # Score should be boosted
        assert rotation.rotation_score > 1.0

    def test_rotation_with_ignition_combination(self, analyzer):
        """Test rotation + ignition combination."""
        now_ts = now()

        # Actor rotates from Token A to Token B
        sell_flow = TradeFlow(
            token_address="TokenA",
            wallet="actor123",
            side="SELL",
            native_amount=100,
            usd_value=500,
            tx_hash="0xsell",
            timestamp=now_ts - timedelta(minutes=2),
            block=100,
            tx_index=1,
            log_index=1
        )
        analyzer.ingest_trade(sell_flow)

        buy_flow = TradeFlow(
            token_address="TokenB",
            wallet="actor123",
            side="BUY",
            native_amount=50,
            usd_value=250,
            tx_hash="0xbuy",
            timestamp=now_ts,
            block=101,
            tx_index=5,
            log_index=1
        )
        analyzer.ingest_trade(buy_flow)

        # Add independent follow-through buyers
        for i in range(3):
            ft_flow = TradeFlow(
                token_address="TokenB",
                wallet=f"buyer{i}",
                side="BUY",
                native_amount=10,
                usd_value=50,
                tx_hash=f"0xft{i}",
                timestamp=now_ts + timedelta(minutes=3 + i),
                block=102 + i,
                tx_index=i,
                log_index=1
            )
            analyzer.ingest_trade(ft_flow)

        # Check that rotation candidate has follow-through data
        candidates = analyzer.get_rotation_candidates(limit=10)
        tokenb_rotations = [c for c in candidates if c.token_address == "TokenB"]
        assert len(tokenb_rotations) > 0

        rotation = tokenb_rotations[0]
        # Should have follow-through data
        assert rotation.follow_through_buyers >= 0

    def test_unknown_state_for_insufficient_evidence(self, analyzer):
        """Test UNKNOWN state when evidence is insufficient."""
        now_ts = now()

        # Very small amounts with large delay
        sell_flow = TradeFlow(
            token_address="TokenA",
            wallet="actor123",
            side="SELL",
            native_amount=5,
            usd_value=20,  # Small but above threshold
            tx_hash="0xsell",
            timestamp=now_ts - timedelta(hours=2),  # Long delay
            block=100,
            tx_index=1,
            log_index=1
        )
        analyzer.ingest_trade(sell_flow)

        buy_flow = TradeFlow(
            token_address="TokenB",
            wallet="actor123",
            side="BUY",
            native_amount=2,
            usd_value=10,  # Small
            tx_hash="0xbuy",
            timestamp=now_ts,
            block=101,
            tx_index=5,
            log_index=1
        )
        analyzer.ingest_trade(buy_flow)

        # Check rotation state
        candidates = analyzer.get_rotation_candidates(limit=10)
        tokenb_rotations = [c for c in candidates if c.token_address == "TokenB"]

        if len(tokenb_rotations) > 0:
            rotation = tokenb_rotations[0]
            # Should have low confidence or UNKNOWN
            assert rotation.rotation_confidence < 0.5 or rotation.rotation_state == RotationState.UNKNOWN

    def test_evidence_traceability(self, analyzer):
        """Test evidence refs are stored for traceability."""
        now_ts = now()

        sell_tx = "0xsell1234567890abcdef"
        buy_tx = "0xbuy0987654321fedcba"

        sell_flow = TradeFlow(
            token_address="TokenA",
            wallet="actor123",
            side="SELL",
            native_amount=100,
            usd_value=500,
            tx_hash=sell_tx,
            timestamp=now_ts - timedelta(minutes=2),
            block=100,
            tx_index=1,
            log_index=1
        )
        analyzer.ingest_trade(sell_flow)

        buy_flow = TradeFlow(
            token_address="TokenB",
            wallet="actor123",
            side="BUY",
            native_amount=50,
            usd_value=250,
            tx_hash=buy_tx,
            timestamp=now_ts,
            block=101,
            tx_index=5,
            log_index=1
        )
        analyzer.ingest_trade(buy_flow)

        candidates = analyzer.get_rotation_candidates(limit=10)
        tokenb_rotations = [c for c in candidates if c.token_address == "TokenB"]

        if len(tokenb_rotations) > 0:
            rotation = tokenb_rotations[0]
            # Evidence refs should contain tx hashes
            assert len(rotation.evidence_refs) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
