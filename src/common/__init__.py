"""Common utilities for rh-volume-ignition."""
from dataclasses import dataclass
from typing import Optional
import time


@dataclass
class EnrichedField:
    """Structured field with metadata for truthfulness."""
    value: any
    source: str
    observed_at: Optional[int] = None
    status: str = "OK"  # OK, MISSING, UNKNOWN
    
    def __post_init__(self):
        if self.observed_at is None and self.value != "UNKNOWN":
            self.observed_at = int(time.time())


def enrich_field(value, source: str, status: str = "OK") -> dict:
    """Create enriched field dict."""
    if value is None:
        return {
            "value": "UNKNOWN",
            "source": source,
            "observed_at": None,
            "status": "MISSING"
        }
    return {
        "value": value,
        "source": source,
        "observed_at": int(time.time()),
        "status": status
    }
