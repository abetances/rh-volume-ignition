"""Database layer for RH Volume Ignition."""

import os
import sqlite3
import json
from datetime import datetime
from typing import List, Optional, Dict, Any
from contextlib import contextmanager
from dataclasses import asdict

from src.models import RawEvent, WatchedToken, WatchTier, WatchReason, TierTransition


class Database:
    """SQLite-based storage for events and watch universe."""
    
    def __init__(self, db_path: str = "data/rh_volume_ignition.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_schema()
    
    @contextmanager
    def _conn(self):
        """Get database connection."""
        conn = sqlite3.connect(self.db_path, timeout=30.0, isolation_level='DEFERRED')
        conn.row_factory = sqlite3.Row
        # Enable WAL mode for better concurrency
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA busy_timeout=30000')
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
    
    def _init_schema(self):
        """Initialize database schema."""
        with self._conn() as conn:
            cursor = conn.cursor()
            
            # Raw events table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS raw_events (
                    event_id TEXT PRIMARY KEY,
                    block_number INTEGER NOT NULL,
                    transaction_index INTEGER NOT NULL,
                    log_index INTEGER NOT NULL,
                    tx_hash TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    block_timestamp TEXT NOT NULL,
                    source TEXT NOT NULL,
                    contract_address TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    raw_reference TEXT,
                    UNIQUE(block_number, transaction_index, log_index)
                )
            """)
            
            # Watch universe table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS watch_universe (
                    token_address TEXT PRIMARY KEY,
                    protocol TEXT DEFAULT 'UNKNOWN',
                    first_seen_at TEXT NOT NULL,
                    last_activity_at TEXT NOT NULL,
                    watch_tier INTEGER DEFAULT 0,
                    watch_reason TEXT DEFAULT 'FRESH_LAUNCH',
                    activity_score REAL DEFAULT 0.0,
                    last_market_state_at TEXT,
                    previous_tier INTEGER
                )
            """)
            
            # Tier transitions log
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tier_transitions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token_address TEXT NOT NULL,
                    old_tier INTEGER NOT NULL,
                    new_tier INTEGER NOT NULL,
                    trigger_type TEXT NOT NULL,
                    trigger_value TEXT,
                    observed_at TEXT NOT NULL
                )
            """)
            
            # Indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_block ON raw_events(block_number)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_contract ON raw_events(contract_address)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_watch_tier ON watch_universe(watch_tier)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_transitions_token ON tier_transitions(token_address)")
    
    # ========== EVENTS ==========
    
    def insert_event(self, event: RawEvent) -> bool:
        """Insert a raw event (deduped by block_number + tx_index + log_index)."""
        try:
            with self._conn() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR IGNORE INTO raw_events 
                    (event_id, block_number, transaction_index, log_index, tx_hash,
                     observed_at, block_timestamp, source, contract_address, event_type, raw_reference)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    event.event_id,
                    event.block_number,
                    event.transaction_index,
                    event.log_index,
                    event.tx_hash,
                    event.observed_at.isoformat(),
                    event.block_timestamp.isoformat(),
                    event.source,
                    event.contract_address,
                    event.event_type,
                    event.raw_reference
                ))
                return cursor.rowcount > 0
        except Exception as e:
            print(f"Error inserting event: {e}")
            return False
    
    def get_recent_events(self, limit: int = 100, contract: str = None) -> List[Dict]:
        """Get recent events."""
        with self._conn() as conn:
            cursor = conn.cursor()
            if contract:
                cursor.execute("""
                    SELECT * FROM raw_events 
                    WHERE contract_address = ?
                    ORDER BY block_number DESC, log_index DESC
                    LIMIT ?
                """, (contract, limit))
            else:
                cursor.execute("""
                    SELECT * FROM raw_events 
                    ORDER BY block_number DESC, log_index DESC
                    LIMIT ?
                """, (limit,))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_events_per_second(self, window_seconds: int = 60) -> float:
        """Calculate events per second over window."""
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM raw_events 
                WHERE observed_at > datetime('now', '-' || ? || ' seconds')
            """, (window_seconds,))
            count = cursor.fetchone()[0]
            return count / window_seconds
    
    # ========== WATCH UNIVERSE ==========
    
    def upsert_token(self, token: WatchedToken) -> bool:
        """Insert or update a watched token."""
        try:
            with self._conn() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO watch_universe 
                    (token_address, protocol, first_seen_at, last_activity_at, 
                     watch_tier, watch_reason, activity_score, last_market_state_at, previous_tier)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(token_address) DO UPDATE SET
                        last_activity_at = excluded.last_activity_at,
                        watch_tier = excluded.watch_tier,
                        watch_reason = excluded.watch_reason,
                        activity_score = excluded.activity_score,
                        previous_tier = CASE 
                            WHEN excluded.watch_tier != watch_universe.watch_tier 
                            THEN watch_universe.watch_tier 
                            ELSE watch_universe.previous_tier 
                        END
                """, (
                    token.token_address,
                    token.protocol,
                    token.first_seen_at.isoformat(),
                    token.last_activity_at.isoformat(),
                    token.watch_tier.value,
                    token.watch_reason.value,
                    token.activity_score,
                    token.last_market_state_at.isoformat() if token.last_market_state_at else None,
                    token.previous_tier.value if token.previous_tier else None
                ))
                return True
        except Exception as e:
            print(f"Error upserting token: {e}")
            return False
    
    def get_token(self, address: str) -> Optional[Dict]:
        """Get a watched token."""
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM watch_universe WHERE token_address = ?", (address,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_watch_universe(self, tier: int = None, reason: str = None, 
                          active_since_hours: int = None, limit: int = 100) -> List[Dict]:
        """Get watch universe with filters."""
        with self._conn() as conn:
            cursor = conn.cursor()
            
            query = "SELECT * FROM watch_universe WHERE 1=1"
            params = []
            
            if tier is not None:
                query += " AND watch_tier = ?"
                params.append(tier)
            
            if reason:
                query += " AND watch_reason = ?"
                params.append(reason)
            
            if active_since_hours:
                query += " AND last_activity_at > datetime('now', '-' || ? || ' hours')"
                params.append(active_since_hours)
            
            query += " ORDER BY last_activity_at DESC LIMIT ?"
            params.append(limit)
            
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
    
    def get_tier_counts(self) -> Dict[int, int]:
        """Get count of tokens per tier."""
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT watch_tier, COUNT(*) as count 
                FROM watch_universe 
                GROUP BY watch_tier
            """)
            return {row[0]: row[1] for row in cursor.fetchall()}
    
    def get_total_tokens(self) -> int:
        """Get total tokens in watch universe."""
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM watch_universe")
            return cursor.fetchone()[0]
    
    # ========== TIER TRANSITIONS ==========
    
    def log_tier_transition(self, token_address: str, old_tier: WatchTier, 
                           new_tier: WatchTier, trigger_type: str, trigger_value: str = ""):
        """Log a tier transition."""
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO tier_transitions 
                (token_address, old_tier, new_tier, trigger_type, trigger_value, observed_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                token_address,
                old_tier.value,
                new_tier.value,
                trigger_type,
                trigger_value,
                datetime.utcnow().isoformat()
            ))
    
    def get_recent_transitions(self, limit: int = 50) -> List[Dict]:
        """Get recent tier transitions."""
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM tier_transitions 
                ORDER BY observed_at DESC 
                LIMIT ?
            """, (limit,))
            return [dict(row) for row in cursor.fetchall()]
    
    # ========== STATS ==========
    
    def get_stats(self) -> Dict[str, Any]:
        """Get overall database stats."""
        with self._conn() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM raw_events")
            total_events = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM watch_universe")
            total_tokens = cursor.fetchone()[0]
            
            return {
                "total_events": total_events,
                "total_tokens": total_tokens,
                "tier_counts": self.get_tier_counts()
            }


# Global database instance
_db: Optional[Database] = None


def get_database() -> Database:
    """Get or create the global database."""
    global _db
    if _db is None:
        db_path = os.getenv("DATABASE_PATH", "data/rh_volume_ignition.db")
        _db = Database(db_path)
    return _db
