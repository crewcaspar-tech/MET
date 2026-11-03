from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route("/")
def home():
    return "DADDS webhook is running"

@app.route("/webhook", methods=["POST"])
def webhook():

    payload = request.json

    print(payload)

    return jsonify({
        "status": "received"
    }), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
