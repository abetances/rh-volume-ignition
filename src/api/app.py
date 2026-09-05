"""RH Volume Ignition - Flask API + Dashboard."""
import os
import sys
import time
from flask import Flask, render_template, jsonify, request
from dataclasses import asdict

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, PROJECT_ROOT)

from src.scanner import get_scanner, Scanner
from src.db import get_database, Database
from src.providers import get_provider_manager, ProviderManager
from src.signals.flow_analyzer import FlowAnalyzer, get_flow_analyzer
from src.signals.flow_processor import FlowProcessor, get_flow_processor

app = Flask(__name__, 
            template_folder=os.path.join(PROJECT_ROOT, 'templates'),
            static_folder='static')

# Global instances
_scanner: Scanner = None
_db: Database = None
_providers: ProviderManager = None
_flow_analyzer: FlowAnalyzer = None
_flow_processor: FlowProcessor = None

started_at = int(time.time())


def get_app_state():
    """Get current application state."""
    global _scanner, _db, _providers
    
    # Try to get scanner status
    chain_live = False
    last_block = 0
    ingest_lag_ms = 0
    events_per_sec = 0
    rpc_connected = False
    rpc_provider = None
    tier_counts = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}
    total_tokens = 0
    
    if _scanner:
        try:
            status = _scanner.get_status()
            chain_live = status.get("last_block", 0) > 0
            last_block = status.get("last_block", 0)
            ingest_lag_ms = status.get("ingest_lag_ms", 0)
            events_per_sec = status.get("events_per_second", 0)
            tier_counts = status.get("tier_counts", tier_counts)
            total_tokens = status.get("total_tokens", 0)
        except Exception as e:
            print(f"Error getting scanner status: {e}")
    
    if _providers:
        try:
            stats = _providers.get_stats()
            rpc_connected = len(stats.get("providers", [])) > 0
            # Get the first connected provider
            if stats.get("providers"):
                rpc_provider = stats["providers"][0]
        except Exception as e:
            print(f"Error getting provider status: {e}")
    
    db_connected = False
    db_type = "SQLite"
    if _db:
        try:
            # Test connection
            _db.get_total_tokens()
            db_connected = True
        except:
            pass
    
    return {
        "chain_live": chain_live,
        "last_block": last_block,
        "ingest_lag_ms": ingest_lag_ms,
        "events_per_sec": round(events_per_sec, 2),
        "rpc_connected": rpc_connected,
        "rpc_provider": rpc_provider,
        "db_connected": db_connected,
        "db_type": db_type,
        "started_at": started_at,
        "tier_counts": tier_counts,
        "total_tokens": total_tokens,
    }


@app.route('/')
def index():
    """Dashboard homepage."""
    return render_template('index.html')


@app.route('/api/v1/health')
def health():
    """System health status."""
    return jsonify(get_app_state())


@app.route('/api/v1/tokens')
def tokens():
    """List tracked tokens with filters."""
    global _db
    
    if not _db:
        return jsonify({"error": "Database not initialized"})
    
    # Get filter params
    tier = request.args.get('tier', type=int)
    reason = request.args.get('reason')
    active_since = request.args.get('active_since_hours', type=int)
    limit = request.args.get('limit', 100, type=int)
    
    try:
        watch_tokens = _db.get_watch_universe(
            tier=tier,
            reason=reason,
            active_since_hours=active_since,
            limit=limit
        )
        return jsonify(watch_tokens)
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route('/api/v1/watch-universe')
def watch_universe():
    """Get watch universe summary."""
    global _db
    
    if not _db:
        return jsonify({"error": "Database not initialized"})
    
    try:
        tier_counts = _db.get_tier_counts()
        total = _db.get_total_tokens()
        
        return jsonify({
            "total": total,
            "tier_counts": tier_counts,
            "tiers": {
                "tier_0": tier_counts.get(0, 0),
                "tier_1": tier_counts.get(1, 0),
                "tier_2": tier_counts.get(2, 0),
                "tier_3": tier_counts.get(3, 0),
                "tier_4": tier_counts.get(4, 0),
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route('/api/v1/events')
def events():
    """Get recent events."""
    global _db
    
    if not _db:
        return jsonify({"error": "Database not initialized"})
    
    limit = request.args.get('limit', 100, type=int)
    contract = request.args.get('contract')
    
    try:
        recent_events = _db.get_recent_events(limit=limit, contract=contract)
        return jsonify(recent_events)
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route('/api/v1/transitions')
def transitions():
    """Get recent tier transitions."""
    global _db
    
    if not _db:
        return jsonify({"error": "Database not initialized"})
    
    limit = request.args.get('limit', 50, type=int)
    
    try:
        recent_transitions = _db.get_recent_transitions(limit=limit)
        return jsonify(recent_transitions)
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route('/api/v1/providers')
def providers():
    """Get provider status."""
    global _providers
    
    if not _providers:
        return jsonify({"error": "Providers not initialized"})
    
    try:
        return jsonify(_providers.get_stats())
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route('/api/v1/scanner')
def scanner():
    """Get scanner status."""
    global _scanner
    
    if not _scanner:
        return jsonify({"error": "Scanner not initialized"})
    
    try:
        return jsonify(_scanner.get_status())
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route('/api/v1/test-range', methods=['POST'])
def test_range():
    """Test a block range on public RPC."""
    global _providers
    
    if not _providers:
        return jsonify({"error": "Providers not initialized"})
    
    data = request.get_json() or {}
    from_block = data.get('from_block')
    to_block = data.get('to_block')
    
    if from_block is None or to_block is None:
        return jsonify({"error": "from_block and to_block required"})
    
    try:
        result = _providers.test_range(from_block, to_block)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route('/api/v1/system')
def system():
    """System info."""
    uptime = int(time.time()) - started_at
    return jsonify({
        "uptime_seconds": uptime,
        "started_at": started_at,
        "version": "0.1.0",
    })


@app.route('/api/v1/signals/ignition')
def signals_ignition():
    """Get current ignition candidates."""
    global _flow_analyzer
    
    if not _flow_analyzer:
        return jsonify({"error": "Flow analyzer not initialized"})
    
    try:
        candidates = _flow_analyzer.get_ignition_candidates(limit=10)
        return jsonify({
            "candidates": [asdict(c) for c in candidates],
            "count": len(candidates)
        })
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route('/api/v1/signals/transitions')
def signals_transitions():
    """Get recent signal state transitions."""
    global _flow_analyzer
    
    if not _flow_analyzer:
        return jsonify({"error": "Flow analyzer not initialized"})
    
    try:
        transitions = _flow_analyzer.get_state_transitions(limit=20)
        return jsonify({
            "transitions": transitions,
            "count": len(transitions)
        })
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route('/api/v1/tokens/<address>/flow')
def token_flow(address):
    """Get detailed flow for a specific token."""
    global _flow_analyzer
    
    if not _flow_analyzer:
        return jsonify({"error": "Flow analyzer not initialized"})
    
    try:
        flow = _flow_analyzer.get_token_flow(address.lower())
        return jsonify(flow)
    except Exception as e:
        return jsonify({"error": str(e)})


def init_app():
    """Initialize the application."""
    global _scanner, _db, _providers, _flow_analyzer, _flow_processor
    
    print("Initializing RH Volume Ignition...")
    
    # Initialize database
    db_path = os.getenv("DATABASE_PATH", "data/rh_volume_ignition.db")
    _db = Database(db_path)
    print(f"  Database: {db_path}")
    
    # Initialize providers
    _providers = get_provider_manager()
    print(f"  Providers: {list(_providers.providers.keys())}")
    
    # Initialize flow processor and analyzer
    _flow_processor = get_flow_processor()
    _flow_analyzer = get_flow_analyzer()
    print(f"  Flow analyzer initialized")
    
    # Initialize scanner
    _scanner = get_scanner()
    print(f"  Scanner initialized")
    
    # Start scanner in background
    _scanner.start()
    print("  Scanner started")


if __name__ == '__main__':
    # Initialize app
    init_app()
    
    port = int(os.environ.get('PORT', 5555))
    print(f"\n" + "="*50)
    print(f"  🔥 RH Volume Ignition Dashboard")
    print(f"  =======================================")
    print(f"  Local URL: http://localhost:{port}")
    print(f"  ==============================" + "\n")
    
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
