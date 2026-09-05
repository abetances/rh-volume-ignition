"""RH Volume Ignition - Flask API + Dashboard."""
import os
import time
from flask import Flask, render_template, jsonify

# src/api/app.py -> src/api -> src -> project_root
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
app = Flask(__name__, 
            template_folder=os.path.join(PROJECT_ROOT, 'templates'),
            static_folder='static')

# In-memory state (will be replaced with real chain data)
state = {
    "chain_live": False,
    "last_block": 0,
    "ingest_lag_ms": 0,
    "events_per_sec": 0,
    "tokens": [],
    "rpc_connected": False,
    "rpc_provider": None,
    "db_connected": True,
    "db_type": "SQLite",
    "started_at": int(time.time()),
}


@app.route('/')
def index():
    """Dashboard homepage."""
    return render_template('index.html')


@app.route('/api/v1/health')
def health():
    """System health status."""
    return jsonify(state)


@app.route('/api/v1/tokens')
def tokens():
    """List tracked tokens."""
    return jsonify(state["tokens"])


@app.route('/api/v1/system')
def system():
    """System info."""
    uptime = int(time.time()) - state["started_at"]
    return jsonify({
        "uptime_seconds": uptime,
        "started_at": state["started_at"],
        "version": "0.1.0",
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5555))
    print(f"\n" + "="*50)
    print(f"  🔥 RH Volume Ignition Dashboard")
    print(f"  =======================================")
    print(f"  Local URL: http://localhost:{port}")
    print(f"  ==============================" + "\n")
    app.run(host='0.0.0.0', port=port, debug=True)
