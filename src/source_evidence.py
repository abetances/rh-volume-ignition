"""Strict ingestion parsing; missing source evidence is never replaced by clock time."""
import ast
import json
from datetime import datetime, timezone


def parse_raw_reference(value):
    if isinstance(value, str):
        if len(value) > 1_000_000:
            raise ValueError('raw reference exceeds limit')
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            # Historical rows were persisted with str(dict), not JSON.
            value = ast.literal_eval(value)
    if not isinstance(value, dict):
        raise ValueError('raw reference must be an object')
    topics = value.get('topics', [])
    data = value.get('data', '0x')
    if not isinstance(topics, list) or not all(isinstance(t, str) for t in topics):
        raise ValueError('invalid topics')
    if not isinstance(data, str):
        raise ValueError('invalid data')
    return value


def parse_source_timestamp(value):
    """UTC-aware source time or None. Naive ISO times have unknown timezone."""
    try:
        if isinstance(value, bool) or value is None:
            return None
        if isinstance(value, int):
            result = datetime.fromtimestamp(value, timezone.utc)
        elif isinstance(value, str):
            if value.startswith('0x') or value.isdigit():
                result = datetime.fromtimestamp(int(value, 16 if value.startswith('0x') else 10), timezone.utc)
            else:
                result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        elif isinstance(value, datetime):
            result = value
        else:
            return None
        if result.tzinfo is None or result.utcoffset() is None:
            return None
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError, OSError):
        return None
