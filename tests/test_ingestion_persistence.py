from collections import deque
from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from src.db import Database
from src.models import RawEvent
from src.scanner import Scanner, IngestStats


def scanner(db):
    obj = Scanner.__new__(Scanner)
    obj.db = db
    obj.stats = IngestStats()
    obj._recent_event_keys = deque(maxlen=10000)
    return obj


def event():
    return RawEvent(block_number=100, transaction_index=2, log_index=3,
                    tx_hash='0xABC', block_timestamp=datetime.now(timezone.utc),
                    observed_at=datetime.now(timezone.utc))


def test_multi_log_transaction_survives_and_restart_is_idempotent(tmp_path):
    path = str(tmp_path / 'events.db')
    db = Database(path)
    first = event()
    second = replace(first, event_id='second', log_index=4)
    obj = scanner(db)
    assert obj._persist_event(first)
    assert obj._persist_event(second)
    assert not obj._persist_event(replace(first, tx_hash='0xabc'))
    assert obj.stats.events_ingested == 2
    restarted = scanner(Database(path))
    assert not restarted._persist_event(first)
    assert not restarted._persist_event(second)
    assert restarted.stats.events_ingested == 0
    assert len(db.get_recent_events()) == 2


def test_failed_insert_remains_retryable_and_is_not_counted():
    db = Mock()
    db.insert_event.side_effect = [False, True]
    obj = scanner(db)
    row = event()
    assert not obj._persist_event(row)
    assert obj.stats.events_ingested == 0
    assert obj.stats.last_event_time is None
    assert obj._persist_event(row)
    assert obj.stats.events_ingested == 1
    assert obj.stats.last_event_time.tzinfo == timezone.utc


def test_storage_exception_does_not_poison_retry_cache():
    db = Mock()
    db.insert_event.side_effect = [RuntimeError('storage unavailable'), True]
    obj = scanner(db)
    row = event()
    with pytest.raises(RuntimeError):
        obj._persist_event(row)
    assert obj.stats.events_ingested == 0
    assert obj._persist_event(row)
