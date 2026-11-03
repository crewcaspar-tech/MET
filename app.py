from flask import Flask, request, jsonify
from datetime import datetime, timezone
import json

app = Flask(__name__)


@app.route("/", methods=["GET"])
def home():
    return """
    <h1>MET Hydrology</h1>
    <p>DADDS webhook receiver is running.</p>
    <p>Webhook endpoint: <code>/webhook</code></p>
    """


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "time_utc": datetime.now(timezone.utc).isoformat()
    }), 200


@app.route("/webhook", methods=["POST"])
def webhook():
    content_type = request.headers.get("Content-Type", "")
    received_at = datetime.now(timezone.utc).isoformat()

    if request.is_json:
        payload = request.get_json(silent=True)
    elif request.form:
        payload = request.form.to_dict(flat=False)
    else:
        payload = request.get_data(as_text=True)

    print("----- DADDS WEBHOOK RECEIVED -----", flush=True)
    print(f"Received UTC: {received_at}", flush=True)
    print(f"Content-Type: {content_type}", flush=True)
    print(json.dumps(payload, indent=2, default=str), flush=True)
    print("----------------------------------", flush=True)

    return jsonify({
        "status": "received",
        "received_at_utc": received_at
    }), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
