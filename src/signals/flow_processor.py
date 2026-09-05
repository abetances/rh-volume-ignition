"""Flow processor - converts raw events to trade flows."""

from datetime import datetime
from typing import Dict, List, Optional, Set
from collections import defaultdict
import hashlib

from src.signals import TradeFlow, FlowSnapshot
from src.db import get_database, Database


class FlowProcessor:
    """Processes raw events into normalized trade flows."""
    
    def __init__(self):
        self.db = get_database()
        
        # Track processed tx hashes to avoid duplicates
        self._processed_txs: Set[str] = set()
        
        # Cache for token metadata
        self._token_cache: Dict[str, Dict] = {}
        
        # Common token transfer signatures
        self._transfer_sig = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
        self._swap_sig = "0x1c411e9a96e071241c2f21f7726b17f89e54799b12d4c9a9f7a5c9e9c9c9c9c"
    
    def process_event(self, event: Dict) -> Optional[TradeFlow]:
        """Process a raw event into a trade flow."""
        # Skip if already processed
        tx_hash = event.get("tx_hash", "")
        if tx_hash in self._processed_txs:
            return None
        
        self._processed_txs.add(tx_hash)
        
        # Extract basic info
        contract = event.get("contract_address", "")
        block = event.get("block_number", 0)
        tx_index = event.get("transaction_index", 0)
        log_index = event.get("log_index", 0)
        
        # Parse topics for transfer events
        topics = event.get("topics", [])
        if not topics or len(topics) < 3:
            return None
        
        event_sig = topics[0]
        
        # Handle Transfer events (most common for trading)
        if event_sig == self._transfer_sig and len(topics) >= 4:
            return self._parse_transfer(event, topics)
        
        return None
    
    def _parse_transfer(self, event: Dict, topics: List[str]) -> Optional[TradeFlow]:
        """Parse a Transfer event into a trade flow."""
        try:
            # Topics: [sig, from, to, value]
            from_addr = topics[1][-40:] if len(topics) > 1 else ""  # Last 20 bytes (40 hex)
            to_addr = topics[2][-40:] if len(topics) > 2 else ""    # Last 20 bytes (40 hex)
            
            # Value is in topics[3] or data
            value_hex = topics[3] if len(topics) > 3 else event.get("data", "0x0")
            value = int(value_hex, 16) if value_hex else 0
            
            if value == 0:
                return None
            
            # Determine if this is a buy (流入 to a pool/contract)
            # or sell (流出 from a pool/contract)
            # This is simplified - real implementation needs token reserves
            
            contract = event.get("contract_address", "").lower()
            
            # Simple heuristic: if "to" looks like a pool, it's a buy
            # This is a placeholder - real implementation would check against known DEXs
            is_buy = self._is_pool_address(to_addr)
            
            return TradeFlow(
                token_address=contract,
                wallet=("0x" + to_addr) if is_buy else ("0x" + from_addr),
                side="BUY" if is_buy else "SELL",
                native_amount=float(value),
                block=event.get("block_number", 0),
                tx_index=event.get("transaction_index", 0),
                log_index=event.get("log_index", 0),
                tx_hash=event.get("tx_hash", ""),
                timestamp=datetime.fromisoformat(event.get("block_timestamp", datetime.utcnow().isoformat())),
                source=event.get("source", "unknown"),
            )
            
        except Exception as e:
            return None
    
    def _is_pool_address(self, addr: str) -> bool:
        """Check if an address is likely a pool/DEX."""
        # Simplified - in production would check against known DEX factories/pairs
        # For now, assume addresses with certain patterns are pools
        if not addr or len(addr) < 40:
            return False
        
        # Common pool prefix patterns (simplified)
        # Real implementation would query DEX factories
        return True  # Placeholder - treat all as potential pools
    
    def process_events(self, events: List[Dict]) -> List[TradeFlow]:
        """Process multiple events into trade flows."""
        flows = []
        for event in events:
            flow = self.process_event(event)
            if flow:
                flows.append(flow)
        return flows
    
    def get_recent_flows(self, token: str = None, limit: int = 100) -> List[Dict]:
        """Get recent trade flows from database."""
        events = self.db.get_recent_events(limit=limit, contract=token)
        
        flows = []
        for event in events:
            flow = self.process_event(event)
            if flow:
                flows.append({
                    "token_address": flow.token_address,
                    "wallet": flow.wallet,
                    "side": flow.side,
                    "native_amount": flow.native_amount,
                    "block": flow.block,
                    "timestamp": flow.timestamp.isoformat(),
                })
        
        return flows


# Global processor
_processor: Optional[FlowProcessor] = None


def get_flow_processor() -> FlowProcessor:
    """Get or create the global flow processor."""
    global _processor
    if _processor is None:
        _processor = FlowProcessor()
    return _processor
