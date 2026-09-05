"""Configuration module for rh-volume-ignition."""
from dataclasses import dataclass
import os


@dataclass
class Config:
    """Project configuration."""
    
    # Provider URLs
    rh_public_rpc_url: str = ""
    rh_sequencer_ws_url: str = ""
    fallback_rpc_url: str = ""
    
    # ClickHouse
    clickhouse_host: str = ""
    clickhouse_port: int = 8123
    clickhouse_database: str = "rh_volume_ignition"
    clickhouse_user: str = ""
    clickhouse_password: str = ""
    
    # SQLite fallback
    use_sqlite_fallback: bool = True
    
    def validate(self) -> list[str]:
        """Validate config and return list of errors."""
        errors = []
        if not self.rh_public_rpc_url and not self.fallback_rpc_url:
            errors.append("At least one RPC URL required (RH_PUBLIC_RPC_URL or FALLBACK_RPC_URL)")
        return errors


def load_config() -> Config:
    """Load configuration from environment."""
    return Config(
        rh_public_rpc_url=os.getenv("RH_PUBLIC_RPC_URL", ""),
        rh_sequencer_ws_url=os.getenv("RH_SEQUENCER_WS_URL", ""),
        fallback_rpc_url=os.getenv("FALLBACK_RPC_URL", ""),
        clickhouse_host=os.getenv("CLICKHOUSE_HOST", ""),
        clickhouse_port=int(os.getenv("CLICKHOUSE_PORT", "8123")),
        clickhouse_database=os.getenv("CLICKHOUSE_DATABASE", "rh_volume_ignition"),
        clickhouse_user=os.getenv("CLICKHOUSE_USER", ""),
        clickhouse_password=os.getenv("CLICKHOUSE_PASSWORD", ""),
        use_sqlite_fallback=os.getenv("USE_SQLITE_FALLBACK", "1") == "1",
    )
