from collections import deque
from datetime import datetime, timezone
from unittest.mock import Mock
import json
import pytest

from src.scanner import Scanner, IngestStats
from src.models import RawEvent
from src.source_evidence import parse_raw_reference, parse_source_timestamp
from src.signals.flow_processor import FlowProcessor


def scanner():
    obj = Scanner.__new__(Scanner)
    obj.stats = IngestStats()
    obj._recent_event_keys = deque()
    obj._flow_processor = Mock()
    obj._flow_processor.process_event.return_value = None
    return obj


@pytest.mark.parametrize('raw', ['[]', 'null', "{'topics': 42}", '{bad'])
def test_invalid_reference_rejected(raw):
    with pytest.raises((ValueError, SyntaxError)):
        parse_raw_reference(raw)


def test_provider_code_never_executes(tmp_path):
    marker = tmp_path / 'executed'
    payload = f"__import__('pathlib').Path({str(marker)!r}).touch()"
    obj = scanner()
    obj._process_event_for_signals(RawEvent(raw_reference=payload))
    assert not marker.exists()
    obj._flow_processor.process_event.assert_not_called()


@pytest.mark.parametrize('encode', [str, json.dumps])
def test_legacy_and_json_reference(encode):
    raw = {'topics': ['0xabc'], 'data': '0x', 'removed': False}
    assert parse_raw_reference(encode(raw)) == raw


@pytest.mark.parametrize('value', [None, '', 'bad', '2026-09-06T03:27:37', True, {}, 10**100])
def test_missing_or_ambiguous_source_time(value):
    assert parse_source_timestamp(value) is None


@pytest.mark.parametrize('value', ['2026-09-06T03:27:37Z', '2026-09-06T05:27:37+02:00', 1788665257, '0x6a9b9d29'])
def test_timestamp_formats(value):
    result = parse_source_timestamp(value)
    assert result is not None
    assert result.tzinfo == timezone.utc


def test_log_uses_source_not_ingest_clock():
    obj = scanner()
    event = obj._parse_log({'blockTimestamp': '2026-09-06T03:27:37Z'}, 'provider-a')
    assert event.block_timestamp == datetime(2026, 9, 6, 3, 27, 37, tzinfo=timezone.utc)
    assert event.observed_at > event.block_timestamp
    provenance = json.loads(event.raw_reference)['_ingestion']
    assert provenance['chain_identity'] == 'UNVERIFIED'
    assert provenance['timestamp_source'] == 'provider_log.blockTimestamp'


def test_unknown_timestamp_is_explicit_gap():
    obj = scanner()
    assert obj._parse_log({}, 'provider-a') is None
    assert obj.stats.unknown_source_timestamp_events == 1
    assert RawEvent().block_timestamp is None
    obj._process_event_for_signals(RawEvent(raw_reference="{'topics':['0xabc']}"))
    obj._flow_processor.process_event.assert_not_called()


@pytest.mark.parametrize('value', [None, 'bad', '2026-09-06T03:27:37'])
def test_decoder_timestamp_cannot_fall_back_to_now(value):
    processor = FlowProcessor.__new__(FlowProcessor)
    assert processor._parse_timestamp(value) is None
    with pytest.raises(ValueError, match='source timestamp'):
        processor._tradeflow_from_decoded(Mock(timestamp=value))


def test_source_time_survives_signal_conversion():
    obj = scanner()
    event = obj._parse_log({
        'blockTimestamp': '2026-09-06T03:27:37Z',
        'topics': ['0xabc'], 'data': '0x',
    }, 'provider-a')
    obj._process_event_for_signals(event)
    payload = obj._flow_processor.process_event.call_args.args[0]
    assert payload['block_timestamp'] == '2026-09-06T03:27:37+00:00'
