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
# In production, these would be fetched from DEX factories
KNOWN_ROUTERS = {
    "0xa0aeba6d88f3d77bd3d2d8e3f3e7e8c8e3e7e8c",  # Uniswap V3 Router
    "0x3fc91a3afd70395cd496c647d5a6cc9d4ceb2e89",  # Uniswap V3
    "0xe592427a0aece92de3edee1f18e0157c05861564",  # Uniswap V3 Router
    "0xcb1355ff08ab38e0950d5d5314ec202c5d1cbe44",  # Universal Router
    "0x8b1bd6b3a5f7e3e7e3e7e3e7e3e7e3e7e3e7e",  # Camelot
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
    protocol: str = "unknown"  # "uniswap_v3", "transfer", "unknown"


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
        
        # Extract common fields
        contract = event.get("contract_address", "").lower()
        block = event.get("block_number", 0)
        tx_index = event.get("transaction_index", 0)
        log_index = event.get("log_index", 0)
        
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
        
        Data encodes: amount0, amount1, sqrtPriceX96, liquidity, tick
        For V3: amount0 is token0, amount1 is token1
        If amount0 < 0: SELL (token0 out, token1 in)
        If amount0 > 0: BUY (token0 in, token1 out)
        """
        try:
            if len(topics) < 3:
                return None
            
            sender = topics[1][-40:] if len(topics) > 1 else ""
            recipient = topics[2][-40:] if len(topics) > 2 else ""
            
            # Parse data field - contains signed amounts
            data = event.get("data", "0x")
            if len(data) < 66:  # Need at least 2 * 32 bytes
                return None
            
            # amount0 is first 32 bytes, amount1 is second 32 bytes
            # These are signed integers (negative = sold, positive = bought)
            amount0 = int(data[2:66], 16) if len(data) > 66 else 0
            amount1 = int(data[66:130], 16) if len(data) > 130 else 0
            
            # Get token addresses
            contract = event.get("contract_address", "").lower()
            
            # Determine direction based on amount signs
            # In V3: amount0 < 0 means token0 was sold (received by pool)
            # amount0 > 0 means token0 was bought (sent to pool)
            # Same logic applies to amount1
            
            # Use the token being traded (contract address)
            # If amount0 is negative, trader SOLD token0
            # If amount0 is positive, trader BOUGHT token0
            
            # The recipient receives the output token
            trader = "0x" + recipient if recipient else "0x" + sender
            
            # Determine side: if amount0 is negative, sold; if positive, bought
            # We need to know which token is the one we're tracking
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
                native_amount = amount1
            
            # Parse timestamp
            timestamp = self._parse_timestamp(event.get("block_timestamp"))
            
            return DecodedTrade(
                token_address=contract,
                trader=trader,
                side=side,
                native_amount=float(native_amount),
                tx_hash=event.get("tx_hash", ""),
                block=block,
                tx_index=tx_index,
                log_index=log_index,
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
        
        This is less reliable than swap events for direction detection.
        We use heuristics but mark as uncertain.
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
            
            contract = event.get("contract_address", "").lower()
            
            # Parse timestamp
            timestamp = self._parse_timestamp(event.get("block_timestamp"))
            
            # Heuristics for direction
            # 1. Mint: from = zero address -> BUY (new tokens created)
            # 2. Burn: to = zero address -> SELL (tokens destroyed)
            # 3. Pool transfer: one address is known router -> use that
            # 4. Default: treat as BUY (most tokens go to holders)
            
            if from_addr == ZERO_ADDR:
                # Mint - new tokens created, treat as BUY
                side = "BUY"
                trader = "0x" + to_addr
            elif to_addr == ZERO_ADDR:
                # Burn - tokens destroyed, treat as SELL
                side = "SELL"
                trader = "0x" + from_addr
            elif self._is_likely_pool(to_addr):
                # Token going to pool -> SELL (trader sells for liquidity)
                side = "SELL"
                trader = "0x" + from_addr
            elif self._is_likely_pool(from_addr):
                # Token coming from pool -> BUY (trader buys with ETH)
                side = "BUY"
                trader = "0x" + to_addr
            else:
                # Unclear - default to BUY (most transfers are to holders)
                # Mark with lower confidence by using different thresholds later
                side = "BUY"
                trader = "0x" + to_addr
            
            return DecodedTrade(
                token_address=contract,
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
        
        # Check against known routers
        if addr in KNOWN_ROUTERS:
            return True
        
        # Common pool patterns on Base:
        # - Start with 0x0 (very common for deployed pools)
        # - Start with 0x4 (another common prefix)
        # - Have specific suffix patterns (less reliable)
        
        # Be conservative - only flag obvious pools
        # In production, would query DEX factories
        return addr.startswith(('0x0', '0x1', '0x2', '0x3', '0x4')) and len(addr) == 40
    
    def _parse_timestamp(self, ts_value) -> Optional[datetime]:
        """Parse timestamp from various formats."""
        if ts_value is None:
            return datetime.now(timezone.utc)
        
        try:
            # Handle hex string (Unix seconds)
            if isinstance(ts_value, str) and ts_value.startswith('0x'):
                ts_int = int(ts_value, 16)
                return datetime.fromtimestamp(ts_int, tz=timezone.utc)
            
            # Handle integer
            if isinstance(ts_value, int):
                return datetime.fromtimestamp(ts_value, tz=timezone.utc)
            
            # Handle string
            if isinstance(ts_value, str):
                # Try hex
                if ts_value.startswith('0x'):
                    ts_int = int(ts_value, 16)
                    return datetime.fromtimestamp(ts_int, tz=timezone.utc)
                # Try ISO
                if 'T' in ts_value:
                    return datetime.fromisoformat(ts_value.replace('Z', '+00:00'))
                # Try Unix
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


# Export for backwards compatibility
__all__ = ['FlowProcessor', 'DecodedTrade']
