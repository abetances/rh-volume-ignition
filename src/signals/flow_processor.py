"""Flow processor - protocol-aware trade decoding."""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass
import hashlib
import struct

from src.signals import TradeFlow, FlowSnapshot
from src.db import get_database, Database


# Known event signatures
TRANSFER_SIG = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
UNISWAP_V3_SWAP_SIG = "0x205442d60b70af1203d43cab62352c3b69b94f091be32fe683198057282b5c92"

# Known router/pool addresses (Base chain - common prefixes)
KNOWN_ROUTERS = {
    "0xa0aeba6d88f3d77bd3d2d8e3f3e7e8c8e3e7e8c",
    "0x3fc91a3afd70395cd496c647d5a6cc9d4ceb2e89",
    "0xe592427a0aece92de3edee1f18e0157c05861564",
    "0xcb1355ff08ab38e0950d5d5314ec202c5d1cbe44",
}

# Zero address (mint/burn)
ZERO_ADDR = "0" * 40


@dataclass
class DecodedTrade:
    """Decoded trade with confirmed direction."""
    token_address: str
    trader: str  # The actual trader wallet
    side: str  # "BUY" or "SELL"
    native_amount: float  # Token amount
    usd_value: Optional[float] = None
    tx_hash: str = ""
    block: int = 0
    tx_index: int = 0
    log_index: int = 0
    timestamp: Optional[datetime] = None
    source: str = "unknown"
    protocol: str = "unknown"


class FlowProcessor:
    """Processes raw events into normalized trade flows with protocol-aware decoding."""
    
    def __init__(self):
        self.db = get_database()
        
        # Track processed tx hashes
        self._processed_txs: Set[str] = set()
        
        # Cache for token metadata
        self._token_cache: Dict[str, Dict] = {}
        
        # Stats for validation
        self._stats = {
            "uniswap_v3_swaps": 0,
            "transfers": 0,
            "unknown": 0,
            "buy": 0,
            "sell": 0,
            "decode_errors": 0,
        }
    
    def process_event(self, event: Dict) -> Optional[TradeFlow]:
        """Process a raw event into a trade flow."""
        tx_hash = event.get("tx_hash", "")
        if tx_hash in self._processed_txs:
            return None
        
        self._processed_txs.add(tx_hash)
        
        topics = event.get("topics", [])
        if not topics:
            self._stats["unknown"] += 1
            return None
        
        event_sig = topics[0]
        
        # Try protocol-specific decoding
        if event_sig == UNISWAP_V3_SWAP_SIG:
            decoded = self._parse_uniswap_v3_swap(event, topics)
            if decoded:
                self._stats["uniswap_v3_swaps"] += 1
                self._stats["buy" if decoded.side == "BUY" else "sell"] += 1
                return self._tradeflow_from_decoded(decoded)
        
        elif event_sig == TRANSFER_SIG and len(topics) >= 3:
            decoded = self._parse_transfer(event, topics)
            if decoded:
                self._stats["transfers"] += 1
                self._stats["buy" if decoded.side == "BUY" else "sell"] += 1
                return self._tradeflow_from_decoded(decoded)
        
        self._stats["unknown"] += 1
        return None
    
    def _parse_uniswap_v3_swap(self, event: Dict, topics: List[str]) -> Optional[DecodedTrade]:
        """
        Parse Uniswap V3 Swap event.
        
        Topics[0]: Swap signature
        Topics[1]: sender (the router/pool)
        Topics[2]: recipient (the trader)
        
        Data: amount0, amount1, sqrtPriceX96, liquidity, tick
        If amount0 < 0: SELL (token0 out)
        If amount0 > 0: BUY (token0 in)
        """
        try:
            if len(topics) < 3:
                return None
            
            sender = topics[1][-40:] if len(topics) > 1 else ""
            recipient = topics[2][-40:] if len(topics) > 2 else ""
            
            data = event.get("data", "0x")
            if not data or len(data) < 66:
                return None
            
            # Parse amount0 (first 32 bytes) - signed int256
            amount0_hex = data[2:66]
            amount0 = int(amount0_hex, 16)
            if amount0 >= 2**255:
                amount0 -= 2**256
            
            # Parse amount1 (second 32 bytes)
            amount1 = 0
            if len(data) >= 130:
                amount1_hex = data[66:130]
                amount1 = int(amount1_hex, 16)
                if amount1 >= 2**255:
                    amount1 -= 2**256
            
            # Determine trader and direction
            trader = "0x" + recipient if recipient else "0x" + sender
            
            # Determine side based on amount signs
            # amount0 is token0, amount1 is token1
            # Negative = sold to pool, Positive = bought from pool
            if amount0 < 0:
                side = "SELL"
                native_amount = abs(amount0)
            elif amount0 > 0:
                side = "BUY"
                native_amount = amount0
            elif amount1 < 0:
                side = "SELL"
                native_amount = abs(amount1)
            else:
                side = "BUY"
                native_amount = amount1 if amount1 > 0 else 0
            
            timestamp = self._parse_timestamp(event.get("block_timestamp"))
            
            return DecodedTrade(
                token_address=event.get("contract_address", "").lower(),
                trader=trader,
                side=side,
                native_amount=native_amount,
                tx_hash=event.get("tx_hash", ""),
                block=event.get("block_number", 0),
                tx_index=event.get("transaction_index", 0),
                log_index=event.get("log_index", 0),
                timestamp=timestamp,
                source=event.get("source", "unknown"),
                protocol="uniswap_v3",
            )
            
        except Exception as e:
            self._stats["decode_errors"] += 1
            return None
    
    def _parse_transfer(self, event: Dict, topics: List[str]) -> Optional[DecodedTrade]:
        """
        Parse ERC-20 Transfer event.
        
        Heuristics for direction:
        - Mint (from = zero): BUY
        - Burn (to = zero): SELL
        - To pool: SELL
        - From pool: BUY
        - Default: BUY
        """
        try:
            if len(topics) < 3:
                return None
            
            from_addr = topics[1][-40:]
            to_addr = topics[2][-40:]
            
            value_hex = event.get("data", "0x0")
            try:
                value = int(value_hex, 16) if value_hex else 0
            except:
                value = 0
            
            if value == 0:
                return None
            
            # Heuristics for direction
            if from_addr == ZERO_ADDR:
                # Mint - new tokens created
                side = "BUY"
                trader = "0x" + to_addr
            elif to_addr == ZERO_ADDR:
                # Burn - tokens destroyed
                side = "SELL"
                trader = "0x" + from_addr
            elif self._is_likely_pool(to_addr):
                # Token going to pool -> SELL
                side = "SELL"
                trader = "0x" + from_addr
            elif self._is_likely_pool(from_addr):
                # Token coming from pool -> BUY
                side = "BUY"
                trader = "0x" + to_addr
            else:
                # Default: BUY (most transfers are to holders)
                side = "BUY"
                trader = "0x" + to_addr
            
            timestamp = self._parse_timestamp(event.get("block_timestamp"))
            
            return DecodedTrade(
                token_address=event.get("contract_address", "").lower(),
                trader=trader,
                side=side,
                native_amount=float(value),
                tx_hash=event.get("tx_hash", ""),
                block=event.get("block_number", 0),
                tx_index=event.get("transaction_index", 0),
                log_index=event.get("log_index", 0),
                timestamp=timestamp,
                source=event.get("source", "unknown"),
                protocol="transfer",
            )
            
        except Exception as e:
            self._stats["decode_errors"] += 1
            return None
    
    def _is_likely_pool(self, addr: str) -> bool:
        """Check if address is likely a pool/router."""
        if not addr or len(addr) < 40:
            return False
        
        if addr in KNOWN_ROUTERS:
            return True
        
        # Conservative: only flag obvious pool prefixes
        return addr.startswith(('0x0', '0x1', '0x2', '0x3', '0x4')) and len(addr) == 40
    
    def _parse_timestamp(self, ts_value) -> Optional[datetime]:
        """Parse timestamp from various formats."""
        if ts_value is None:
            return datetime.now(timezone.utc)
        
        try:
            if isinstance(ts_value, str) and ts_value.startswith('0x'):
                ts_int = int(ts_value, 16)
                return datetime.fromtimestamp(ts_int, tz=timezone.utc)
            
            if isinstance(ts_value, int):
                return datetime.fromtimestamp(ts_value, tz=timezone.utc)
            
            if isinstance(ts_value, str):
                if ts_value.startswith('0x'):
                    ts_int = int(ts_value, 16)
                    return datetime.fromtimestamp(ts_int, tz=timezone.utc)
                if 'T' in ts_value:
                    return datetime.fromisoformat(ts_value.replace('Z', '+00:00'))
                try:
                    ts_int = int(ts_value)
                    return datetime.fromtimestamp(ts_int, tz=timezone.utc)
                except:
                    pass
            
            return datetime.now(timezone.utc)
            
        except Exception:
            return datetime.now(timezone.utc)
    
    def _tradeflow_from_decoded(self, decoded: DecodedTrade) -> TradeFlow:
        """Convert DecodedTrade to TradeFlow."""
        # Normalize native_amount (assume 18 decimals for ETH/ERC20)
        normalized_amount = decoded.native_amount / 1e18 if decoded.native_amount else 0
        
        return TradeFlow(
            token_address=decoded.token_address,
            wallet=decoded.trader,
            side=decoded.side,
            native_amount=normalized_amount,
            usd_value=decoded.usd_value,
            tx_hash=decoded.tx_hash,
            timestamp=decoded.timestamp or datetime.now(timezone.utc),
            block=decoded.block,
            tx_index=decoded.tx_index,
            log_index=decoded.log_index,
            source=decoded.source,
        )
    
    def get_stats(self) -> Dict:
        """Get processing stats."""
        return self._stats.copy()
    
    def reset_stats(self):
        """Reset stats counters."""
        self._stats = {
            "uniswap_v3_swaps": 0,
            "transfers": 0,
            "unknown": 0,
            "buy": 0,
            "sell": 0,
            "decode_errors": 0,
        }
    
    def reset_processed(self):
        """Reset processed tx cache."""
        self._processed_txs.clear()


# === SINGLETON ACCESSORS ===
_flow_processor_instance = None

def get_flow_processor() -> FlowProcessor:
    """Get singleton FlowProcessor instance."""
    global _flow_processor_instance
    if _flow_processor_instance is None:
        _flow_processor_instance = FlowProcessor()
    return _flow_processor_instance
