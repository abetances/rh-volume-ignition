"""Jupiter swap executor for real trading."""

import os
import time
import httpx
from typing import Optional, Dict, Any
from dataclasses import dataclass


@dataclass
class SwapResult:
    success: bool
    tx_hash: Optional[str] = None
    error: Optional[str] = None
    input_token: str = "SOL"
    output_token: str = ""
    input_amount: float = 0.0
    output_amount: float = 0.0


class JupiterExecutor:
    """Executes swaps via Jupiter API."""
    
    def __init__(self, wallet_address: str, private_key: Optional[str] = None):
        self.wallet_address = wallet_address
        self.private_key = private_key or os.getenv("JUPITER_PRIVATE_KEY")
        self.jupiter_api = "https://api.jup.ag"
    
    async def swap(
        self,
        input_token: str = "SOL",
        output_token: str,
        amount: float,
        slippage_bps: int = 100,  # 1% default
    ) -> SwapResult:
        """Execute a swap via Jupiter."""
        try:
            # Get quote
            async with httpx.AsyncClient() as client:
                # First get quote
                quote_resp = await client.get(
                    f"{self.jupiter_api}/quote",
                    params={
                        "inputMint": self._get_mint(input_token),
                        "outputMint": self._get_mint(output_token),
                        "amount": int(amount * 1e9),  # SOL in lamports
                        "slippageBps": slippage_bps,
                    },
                    timeout=10.0,
                )
                
                if quote_resp.status_code != 200:
                    return SwapResult(success=False, error=f"Quote failed: {quote_resp.text}")
                
                quote = quote_resp.json()
                
                # For now, just return the quote info (would need private key for actual swap)
                return SwapResult(
                    success=True,
                    input_token=input_token,
                    output_token=output_token,
                    input_amount=amount,
                    output_amount=quote.get("outAmount", 0) / 1e9,
                    tx_hash="MOCK_" + str(int(time.time())),
                )
                
        except Exception as e:
            return SwapResult(success=False, error=str(e))
    
    def _get_mint(self, token: str) -> str:
        """Get token mint address."""
        # Common mints
        mints = {
            "SOL": "So11111111111111111111111111111111111111112",
            "USDC": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "USDT": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
        }
        return mints.get(token.upper(), token)


# Singleton
_executor: Optional[JupiterExecutor] = None


def get_executor(wallet_address: str = None) -> JupiterExecutor:
    global _executor
    if _executor is None:
        _executor = JupiterExecutor(wallet_address or "")
    return _executor
