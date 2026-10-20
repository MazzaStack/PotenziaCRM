"""
Loading Overlay Plugin - Real-time log streaming via SSE
"""
import time
import threading
from collections import deque
from flask import Blueprint, Response, jsonify, request
from flask_login import login_required

loading_overlay_bp = Blueprint('loading_overlay', __name__, url_prefix='/loading')

# Thread-safe in-memory log buffer (max 200 entries)
_log_buffer = deque(maxlen=200)
_log_lock = threading.Lock()
_log_session_id = None
_log_session_start = 0


def push_log(message: str):
    """Push a log message to the SSE buffer. Call this from any long-running task."""
    ts = time.time()
    with _log_lock:
        _log_buffer.append({'ts': ts, 'msg': message.strip()})


def start_log_session(session_id: str = None):
    """Start a new logging session (clears old buffer)."""
    global _log_session_id, _log_session_start
    import uuid
    _log_session_id = session_id or str(uuid.uuid4())[:8]
    _log_session_start = time.time()
    with _log_lock:
        _log_buffer.clear()
    push_log(f"[Sistema] Sesión de trabajo iniciada — {_log_session_id}")


class LogCapture:
    """Context manager that intercepts print() calls and pushes them to the log buffer."""
    def __init__(self):
        import sys
        self._original_stdout = sys.stdout
        self._original_stderr = sys.stderr

    def write(self, text):
        if text and text.strip():
            push_log(text.strip())
        self._original_stdout.write(text)

    def flush(self):
        self._original_stdout.flush()

    def __enter__(self):
        import sys
        sys.stdout = self
        return self

    def __exit__(self, *args):
        import sys
        sys.stdout = self._original_stdout


@loading_overlay_bp.route('/log-push', methods=['POST'])
@login_required
def push_log_endpoint():
    """Endpoint to push a log message from a background task."""
    data = request.json or {}
    msg = data.get('msg', '')
    if msg:
        push_log(msg)
    return jsonify({'ok': True})


@loading_overlay_bp.route('/log-stream')
@login_required
def log_stream():
    """SSE endpoint that streams log messages to the browser."""
    def generate():
        sent_count = 0
        # Get snapshot of current buffer on connect
        with _log_lock:
            initial = list(_log_buffer)

        # Send all buffered messages first
        for entry in initial:
            yield f"data: {entry['msg']}\n\n"
        sent_count = len(initial)

        # Then stream new messages as they arrive
        while True:
            time.sleep(0.3)
            with _log_lock:
                current = list(_log_buffer)

            if len(current) > sent_count:
                new_entries = current[sent_count:]
                for entry in new_entries:
                    yield f"data: {entry['msg']}\n\n"
                sent_count = len(current)
            else:
                # Send heartbeat to keep connection alive
                yield f": heartbeat\n\n"

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive'
        }
    )


@loading_overlay_bp.route('/log-clear', methods=['POST'])
@login_required
def log_clear():
    """Clear the log buffer (called when overlay is dismissed)."""
    with _log_lock:
        _log_buffer.clear()
    return jsonify({'ok': True})


@loading_overlay_bp.route('/log-snapshot')
@login_required
def log_snapshot():
    """Return current log buffer as JSON (for polling fallback)."""
    with _log_lock:
        entries = [e['msg'] for e in list(_log_buffer)]
    return jsonify({'logs': entries})
