"""RPC Provider layer for RH Volume Ignition."""

import os
import time
import requests
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque

# Load .env file
from dotenv import load_dotenv
load_dotenv()

from src.models import RPCBudget, BudgetState, RawEvent, EventType


@dataclass
class RPCResponse:
    """Standardized RPC response."""
    success: bool
    data: Any = None
    error: str = ""
    latency_ms: float = 0
    logs_count: int = 0
    is_rate_limited: bool = False


class RPCProvider:
    """Base RPC provider interface."""
    
    def __init__(self, name: str, url: str, is_public: bool = True):
        self.name = name
        self.url = url
        self.is_public = is_public
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "User-Agent": "RH-Volume-Ignition/1.0"
        })
    
    def _call(self, method: str, params: List = None) -> RPCResponse:
        """Make an RPC call."""
        if not self.url:
            return RPCResponse(success=False, error="No URL configured")
        
        start = time.time()
        try:
            resp = self.session.post(
                self.url,
                json={"jsonrpc": "2.0", "method": method, "params": params or [], "id": 1},
                timeout=30
            )
            latency = (time.time() - start) * 1000
            
            if resp.status_code == 429:
                return RPCResponse(
                    success=False,
                    error="Rate limited",
                    latency_ms=latency,
                    is_rate_limited=True
                )
            
            if resp.status_code != 200:
                return RPCResponse(
                    success=False,
                    error=f"HTTP {resp.status_code}",
                    latency_ms=latency
                )
            
            data = resp.json()
            if "error" in data:
                return RPCResponse(
                    success=False,
                    error=data["error"].get("message", str(data["error"])),
                    latency_ms=latency
                )
            
            return RPCResponse(success=True, data=data.get("result"), latency_ms=latency)
            
        except requests.exceptions.Timeout:
            return RPCResponse(success=False, error="Timeout", latency_ms=(time.time() - start) * 1000)
        except Exception as e:
            return RPCResponse(success=False, error=str(e), latency_ms=(time.time() - start) * 1000)
    
    def get_block_number(self) -> RPCResponse:
        """Get latest block number."""
        return self._call("eth_blockNumber", [])
    
    def get_block_by_number(self, block: int, full: bool = False) -> RPCResponse:
        """Get block by number."""
        hex_block = hex(block)
        return self._call("eth_getBlockByNumber", [hex_block, full])
    
    def get_logs(self, from_block: int, to_block: int, address: str = None, 
                 topics: List = None) -> RPCResponse:
        """Get logs in a range."""
        params = {
            "fromBlock": hex(from_block),
            "toBlock": hex(to_block)
        }
        if address:
            params["address"] = address
        if topics:
            params["topics"] = topics
        
        result = self._call("eth_getLogs", [params])
        if result.success:
            logs = result.data if isinstance(result.data, list) else result.data.get("logs", [])
            result.logs_count = len(logs)
        return result
    
    def get_transaction_receipt(self, tx_hash: str) -> RPCResponse:
        """Get transaction receipt."""
        return self._call("eth_getTransactionReceipt", [tx_hash])


class ProviderManager:
    """Manages multiple RPC providers with budget tracking."""
    
    def __init__(self):
        self.providers: Dict[str, RPCProvider] = {}
        self.budget = RPCBudget()
        self.request_timestamps: deque = deque(maxlen=10000)
        self._load_config()
    
    def _load_config(self):
        """Load provider URLs from environment."""
        # Public RPC - broad scanning
        public_url = os.getenv("RH_PUBLIC_RPC_URL", "").strip()
        if public_url:
            self.providers["RH_PUBLIC_RPC"] = RPCProvider("RH_PUBLIC_RPC", public_url, is_public=True)
        
        # Sequencer WS - low latency (placeholder for now)
        sequencer_url = os.getenv("RH_SEQUENCER_WS_URL", "").strip()
        if sequencer_url:
            self.providers["RH_SEQUENCER_FEED"] = RPCProvider("RH_SEQUENCER_FEED", sequencer_url, is_public=True)
        
        # Fallback RPC
        fallback_url = os.getenv("FALLBACK_RPC_URL", "").strip()
        if fallback_url:
            self.providers["FALLBACK_RPC"] = RPCProvider("FALLBACK_RPC", fallback_url, is_public=True)
        
        # Alchemy RPC (free tier: 10-block max for eth_getLogs)
        alchemy_url = os.getenv("ALCHEMY_RH_URL", "").strip()
        if alchemy_url:
            self.providers["ALCHEMY_RH"] = RPCProvider("ALCHEMY_RH", alchemy_url, is_public=True)
    
    def _record_request(self, provider_name: str, latency_ms: float, success: bool, 
                       is_rate_limited: bool = False):
        """Record a request for budget tracking."""
        now = datetime.utcnow()
        self.request_timestamps.append(now)
        
        self.budget.request_timestamps.append(now)
        self.budget.latency_samples.append(latency_ms)
        
        # Track by provider type
        if provider_name == "FALLBACK_RPC":
            self.budget.fallback_usage += 1
        elif not self.providers.get(provider_name, RPCProvider("", "")).is_public:
            self.budget.paid_provider_usage += 1
        
        if not success:
            self.budget.errors += 1
        if is_rate_limited:
            self.budget.rate_limited += 1
        
        self._update_budget_state()
    
    def _update_budget_state(self):
        """Update budget state based on usage."""
        now = datetime.utcnow()
        one_minute_ago = now - timedelta(minutes=1)
        
        # Count requests in last minute
        recent_requests = sum(1 for ts in self.request_timestamps if ts > one_minute_ago)
        self.budget.requests_last_minute = recent_requests
        
        # Simple state logic (can be tuned)
        if self.budget.rate_limited > 10 or recent_requests > 300:
            self.budget.state = BudgetState.RED
        elif self.budget.rate_limited > 5 or recent_requests > 200:
            self.budget.state = BudgetState.YELLOW
        else:
            self.budget.state = BudgetState.GREEN
    
    def call(self, method: str, params: List = None, preferred_provider: str = None) -> Tuple[RPCResponse, str]:
        """Make an RPC call with budget tracking and fallback."""
        # Try preferred provider first
        if preferred_provider and preferred_provider in self.providers:
            provider = self.providers[preferred_provider]
            result = provider._call(method, params)
            self._record_request(preferred_provider, result.latency_ms, result.success, result.is_rate_limited)
            
            if result.success or self.budget.state == BudgetState.RED:
                return result, preferred_provider
        
        # Try public RPCs in order
        for name, provider in self.providers.items():
            if provider.is_public:
                result = provider._call(method, params)
                self._record_request(name, result.latency_ms, result.success, result.is_rate_limited)
                
                if result.success:
                    return result, name
                
                # Don't spam on rate limits
                if result.is_rate_limited:
                    time.sleep(1)
        
        # Try fallback
        if "FALLBACK_RPC" in self.providers:
            provider = self.providers["FALLBACK_RPC"]
            result = provider._call(method, params)
            self._record_request("FALLBACK_RPC", result.latency_ms, result.success, result.is_rate_limited)
            return result, "FALLBACK_RPC"
        
        return RPCResponse(success=False, error="No providers available"), ""
    
    def get_latest_block(self) -> Tuple[Optional[int], str, float]:
        """Get latest block number. Returns (block, provider, latency)."""
        result, provider = self.call("eth_blockNumber", [])
        
        if result.success:
            try:
                block = int(result.data, 16)
                return block, provider, result.latency_ms
            except:
                pass
        
        return None, "", 0
    
    def test_range(self, from_block: int, to_block: int) -> Dict[str, Any]:
        """Test a block range on public RPC."""
        provider = self.providers.get("RH_PUBLIC_RPC")
        if not provider:
            return {"success": False, "error": "No public RPC"}
        
        result = provider.get_logs(from_block, to_block)
        
        return {
            "success": result.success,
            "latency_ms": result.latency_ms,
            "logs_returned": result.logs_count,
            "error": result.error,
            "is_rate_limited": result.is_rate_limited
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """Get provider stats."""
        return {
            "providers": list(self.providers.keys()),
            "budget_state": self.budget.state.value,
            "requests_last_minute": self.budget.requests_last_minute,
            "errors": self.budget.errors,
            "rate_limited": self.budget.rate_limited,
            "fallback_usage": self.budget.fallback_usage,
            "paid_provider_usage": self.budget.paid_provider_usage,
            "latency_p50": sorted(self.budget.latency_samples)[len(self.budget.latency_samples)//2] 
                if self.budget.latency_samples else 0,
            "latency_p95": sorted(self.budget.latency_samples)[int(len(self.budget.latency_samples)*0.95)] 
                if len(self.budget.latency_samples) > 20 else 0,
        }


# Global provider manager
_provider_manager: Optional[ProviderManager] = None


def get_provider_manager() -> ProviderManager:
    """Get or create the global provider manager."""
    global _provider_manager
    if _provider_manager is None:
        _provider_manager = ProviderManager()
    return _provider_manager
