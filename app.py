from flask import Flask, request, jsonify
from datetime import datetime, timezone
import json
import urllib.request
from urllib.parse import urlparse

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
    received_at = datetime.now(timezone.utc).isoformat()
    raw_body = request.get_data(as_text=True)

    print("----- WEBHOOK RECEIVED -----", flush=True)
    print(f"Received UTC: {received_at}", flush=True)
    print(f"Content-Type: {request.content_type}", flush=True)
    print(
        f"SNS message type: "
        f"{request.headers.get('x-amz-sns-message-type')}",
        flush=True
    )
    print(f"Raw body: {raw_body}", flush=True)

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        print("Body was not valid JSON.", flush=True)

        return jsonify({
            "status": "received",
            "received_at_utc": received_at,
            "body_type": "non-json"
        }), 200

    message_type = payload.get("Type")

    print(
        "Parsed JSON:",
        json.dumps(payload, indent=2),
        flush=True
    )

    if message_type == "SubscriptionConfirmation":
        subscribe_url = payload.get("SubscribeURL")

        if not subscribe_url:
            print(
                "SubscriptionConfirmation had no SubscribeURL.",
                flush=True
            )
            return jsonify({
                "status": "error",
                "message": "SubscribeURL missing"
            }), 400

        parsed_url = urlparse(subscribe_url)

        # Basic safety check before opening an external URL.
        if (
            parsed_url.scheme != "https"
            or not parsed_url.hostname
            or not parsed_url.hostname.endswith(".amazonaws.com")
        ):
            print(
                f"Rejected unexpected SubscribeURL: {subscribe_url}",
                flush=True
            )
            return jsonify({
                "status": "error",
                "message": "Unexpected confirmation URL"
            }), 400

        try:
            with urllib.request.urlopen(
                subscribe_url,
                timeout=15
            ) as response:
                confirmation_status = response.status

            print(
                "SNS subscription confirmed. "
                f"HTTP status: {confirmation_status}",
                flush=True
            )

            return jsonify({
                "status": "subscription confirmed",
                "received_at_utc": received_at
            }), 200

        except Exception as error:
            print(
                f"SNS confirmation failed: {error}",
                flush=True
            )

            return jsonify({
                "status": "confirmation failed"
            }), 500

    if message_type == "Notification":
        message = payload.get("Message")

        print("----- SNS NOTIFICATION -----", flush=True)
        print(f"Message: {message}", flush=True)

        # The Message field might itself contain JSON.
        if isinstance(message, str):
            try:
                observation = json.loads(message)
                print(
                    "Parsed observation:",
                    json.dumps(observation, indent=2),
                    flush=True
                )
            except json.JSONDecodeError:
                observation = message
        else:
            observation = message

        return jsonify({
            "status": "notification received",
            "received_at_utc": received_at
        }), 200

    print(
        f"Unrecognized message type: {message_type}",
        flush=True
    )

    return jsonify({
        "status": "received",
        "received_at_utc": received_at,
        "message_type": message_type
    }), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
