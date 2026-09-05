"""Scanner and ingestion engine for RH Volume Ignition."""

import os
import time
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
from collections import deque
from dataclasses import dataclass, field

from src.models import RawEvent, WatchedToken, WatchTier, WatchReason, EventType, BudgetState
from src.providers import get_provider_manager, ProviderManager
from src.db import get_database, Database


@dataclass
class IngestStats:
    """Ingestion statistics."""
    events_ingested: int = 0
    events_per_second: float = 0.0
    last_block: int = 0
    ingest_lag_ms: int = 0
    last_event_time: Optional[datetime] = None
    
    # Tier polling intervals (in seconds)
    tier_poll_intervals: Dict[int, int] = field(default_factory=lambda: {
        0: 5,   # TIER_0 - fresh launches: every 5s
        1: 5,   # TIER_1 - active: every 5s
        2: 15,  # TIER_2 - important actors: every 15s
        3: 60,  # TIER_3 - recent winners: every 60s
        4: 300, # TIER_4 - background: every 5min
    })


class Scanner:
    """Main scanner engine for volume ignition detection."""
    
    def __init__(self):
        self.providers = get_provider_manager()
        self.db = get_database()
        self.stats = IngestStats()
        
        # Known token contract addresses (DEX pairs, factories)
        self._known_contracts: Set[str] = set()
        
        # Adaptive polling state
        self._last_poll: Dict[str, datetime] = {}
        
        # Recent events buffer for dedup
        self._recent_tx_hashes: deque = deque(maxlen=10000)
        
        # Running state
        self._running = False
        self._ingest_thread: Optional[threading.Thread] = None
        self._poll_thread: Optional[threading.Thread] = None
    
    def start(self):
        """Start the scanner."""
        if self._running:
            return
        
        self._running = True
        
        # Start ingestion thread
        self._ingest_thread = threading.Thread(target=self._ingestion_loop, daemon=True)
        self._ingest_thread.start()
        
        # Start polling thread
        self._poll_thread = threading.Thread(target=self._polling_loop, daemon=True)
        self._poll_thread.start()
        
        print("Scanner started")
    
    def stop(self):
        """Stop the scanner."""
        self._running = False
        if self._ingest_thread:
            self._ingest_thread.join(timeout=5)
        if self._poll_thread:
            self._poll_thread.join(timeout=5)
        print("Scanner stopped")
    
    def _ingestion_loop(self):
        """Main ingestion loop - fetch new blocks and events."""
        while self._running:
            try:
                # Get latest block
                block, provider, latency = self.providers.get_latest_block()
                
                if block is None:
                    print("Failed to get latest block, waiting...")
                    time.sleep(5)
                    continue
                
                self.stats.last_block = block
                self.stats.ingest_lag_ms = int(latency)
                
                # Determine polling frequency based on budget
                poll_interval = self._get_poll_interval()
                
                # Fetch events from last processed block
                last_processed = self._get_last_processed_block()
                from_block = max(last_processed + 1, block - 100)  # Cap at 100 blocks back
                to_block = block
                
                if from_block <= to_block:
                    events = self._fetch_events(from_block, to_block)
                    
                    # Process and persist events
                    for event in events:
                        if self._dedupe_event(event):
                            self.db.insert_event(event)
                            self.stats.events_ingested += 1
                            self.stats.last_event_time = datetime.utcnow()
                            
                            # Update watch universe based on event
                            self._update_watch_universe(event)
                
                # Update stats
                self._update_stats()
                
                time.sleep(poll_interval)
                
            except Exception as e:
                print(f"Ingestion error: {e}")
                time.sleep(5)
    
    def _polling_loop(self):
        """Polling loop for watch universe tokens."""
        while self._running:
            try:
                # Get all tokens from watch universe
                tokens = self.db.get_watch_universe(limit=1000)
                
                for token_dict in tokens:
                    tier = token_dict.get("watch_tier", 0)
                    address = token_dict.get("token_address")
                    
                    if not address:
                        continue
                    
                    # Check if it's time to poll this tier
                    poll_key = f"{address}:{tier}"
                    last_poll = self._last_poll.get(poll_key)
                    interval = self.stats.tier_poll_intervals.get(tier, 60)
                    
                    if last_poll and (datetime.utcnow() - last_poll).total_seconds() < interval:
                        continue
                    
                    # Poll this token
                    self._poll_token(address, tier)
                    self._last_poll[poll_key] = datetime.utcnow()
                
                time.sleep(1)  # Brief sleep between polling cycles
                
            except Exception as e:
                print(f"Polling error: {e}")
                time.sleep(5)
    
    def _fetch_events(self, from_block: int, to_block: int) -> List[RawEvent]:
        """Fetch events from blockchain in a block range."""
        events = []
        
        # Test the range first
        test_result = self.providers.test_range(from_block, to_block)
        
        if not test_result.get("success"):
            print(f"Range test failed: {test_result.get('error')}")
            return events
        
        # Fetch actual logs
        result, provider = self.providers.call(
            "eth_getLogs", 
            [{
                "fromBlock": hex(from_block),
                "toBlock": hex(to_block),
            }]
        )
        
        if not result.success:
            print(f"Failed to fetch logs: {result.error}")
            return events
        
        logs = result.data if isinstance(result.data, list) else result.data.get("logs", [])
        
        for log in logs:
            try:
                event = self._parse_log(log, provider)
                if event:
                    events.append(event)
            except Exception as e:
                print(f"Error parsing log: {e}")
        
        return events
    
    def _parse_log(self, log: Dict, provider: str) -> Optional[RawEvent]:
        """Parse a raw log into a RawEvent."""
        try:
            block_number = int(log.get("blockNumber", "0x0"), 16)
            tx_index = int(log.get("transactionIndex", "0x0"), 16)
            log_index = int(log.get("logIndex", "0x0"), 16)
            tx_hash = log.get("transactionHash", "")
            
            # Skip if we've seen this tx recently
            if tx_hash in self._recent_tx_hashes:
                return None
            
            # Extract contract address
            contract_address = log.get("address", "").lower()
            
            # Extract event type from topics
            topics = log.get("topics", [])
            event_type = "Unknown"
            if topics:
                # First topic is event signature
                event_sig = topics[0]
                event_type = self._identify_event_type(event_sig)
            
            # Parse timestamp (we'd need to fetch block for this in production)
            block_timestamp = datetime.utcnow()
            
            return RawEvent(
                block_number=block_number,
                transaction_index=tx_index,
                log_index=log_index,
                tx_hash=tx_hash,
                block_timestamp=block_timestamp,
                observed_at=datetime.utcnow(),
                source=provider,
                contract_address=contract_address,
                event_type=event_type,
                raw_reference=str(log)
            )
            
        except Exception as e:
            print(f"Error parsing log: {e}")
            return None
    
    def _identify_event_type(self, event_sig: str) -> str:
        """Identify event type from signature."""
        # Common event signatures
        signatures = {
            "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef": "Transfer",
            "0x7fcf532c15f6576d0b1d8c5b9b3c9b5c9c9c9c9c9c9c9c9c9c9c9c9c9c9c9c": "Mint",
            "0x0000000000000000000000000000000000000000000000000000000000000000": "Burn",
            "0x1c411e9a96e071241c2f21f7726b17f89e54799b12d4c9a9f7a5c9e9c9c9c9c": "Swap",
            "0x8c5be1e5ebec7d5bd14f71427d1e84f3dd0314c0f7b2291e5b200ac8c7c3b925": "Approval",
            "0x0d3648bd0f6ba80134a33ba9275ac585d9d315f0ad8355cddefde31afa28d0e9": "PairCreated",
            "0x1c411e9a96e071241c2f21f7726b17f89e54799b12d4c9a9f7a5c9e9c9c9c9c": "Sync",
        }
        
        return signatures.get(event_sig, "Unknown")
    
    def _dedupe_event(self, event: RawEvent) -> bool:
        """Check if event is a duplicate."""
        if event.tx_hash in self._recent_tx_hashes:
            return False
        
        self._recent_tx_hashes.append(event.tx_hash)
        return True
    
    def _update_watch_universe(self, event: RawEvent):
        """Update watch universe based on new event."""
        address = event.contract_address
        
        if not address:
            return
        
        # Check if token exists
        existing = self.db.get_token(address)
        
        if existing:
            # Update last activity
            token = WatchedToken(
                token_address=address,
                protocol=existing.get("protocol", "UNKNOWN"),
                watch_tier=WatchTier(existing.get("watch_tier", 0)),
                watch_reason=WatchReason(existing.get("watch_reason", "ACTIVE_FLOW")),
                activity_score=existing.get("activity_score", 0.0),
            )
            token.last_activity_at = datetime.utcnow()
            
            # Check for tier promotion
            self._check_tier_promotion(token, event)
            
            self.db.upsert_token(token)
        else:
            # New token - add to watch universe at TIER_0
            token = WatchedToken(
                token_address=address,
                watch_tier=WatchTier.TIER_0,
                watch_reason=WatchReason.FRESH_LAUNCH,
            )
            self.db.upsert_token(token)
    
    def _check_tier_promotion(self, token: WatchedToken, event: RawEvent):
        """Check if token should be promoted to a higher tier."""
        current_tier = token.watch_tier.value
        
        # Simple promotion logic
        if current_tier >= 1:
            return  # Already at TIER_1 or higher
        
        # If we have enough activity, promote to TIER_1
        # In production, this would be based on actual activity metrics
        if event.event_type in ["Transfer", "Swap"]:
            old_tier = token.watch_tier
            token.watch_tier = WatchTier.TIER_1
            token.watch_reason = WatchReason.ACTIVE_FLOW
            
            # Log transition
            self.db.log_tier_transition(
                token.token_address,
                old_tier,
                token.watch_tier,
                "ACTIVITY_THRESHOLD",
                event.event_type
            )
    
    def _poll_token(self, address: str, tier: int):
        """Poll a specific token for updates."""
        # In production, this would fetch token-specific events
        # For now, this is a placeholder
        pass
    
    def _get_poll_interval(self) -> int:
        """Get polling interval based on budget state."""
        stats = self.providers.get_stats()
        budget_state = stats.get("budget_state", "GREEN")
        
        intervals = {
            BudgetState.GREEN.value: 5,
            BudgetState.YELLOW.value: 15,
            BudgetState.RED.value: 30,
        }
        
        return intervals.get(budget_state, 5)
    
    def _get_last_processed_block(self) -> int:
        """Get the last processed block from database."""
        events = self.db.get_recent_events(limit=1)
        if events:
            return events[0].get("block_number", 0)
        return 0
    
    def _update_stats(self):
        """Update ingestion statistics."""
        self.stats.events_per_second = self.db.get_events_per_second()
    
    def get_status(self) -> Dict:
        """Get current scanner status."""
        return {
            "running": self._running,
            "last_block": self.stats.last_block,
            "ingest_lag_ms": self.stats.ingest_lag_ms,
            "events_per_second": self.stats.events_per_second,
            "total_events": self.stats.events_ingested,
            "last_event_time": self.stats.last_event_time.isoformat() if self.stats.last_event_time else None,
            "budget": self.providers.get_stats(),
            "tier_counts": self.db.get_tier_counts(),
            "total_tokens": self.db.get_total_tokens(),
        }


# Global scanner instance
_scanner: Optional[Scanner] = None


def get_scanner() -> Scanner:
    """Get or create the global scanner."""
    global _scanner
    if _scanner is None:
        _scanner = Scanner()
    return _scanner
