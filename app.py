from flask import Flask, request, jsonify
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
import json
import urllib.request


app = Flask(__name__)


# -------------------------------------------------------------------
# DADDS data layout
#
# Each row represents one parameter.
# Each column represents one 20-minute observation.
#
# Column order:
#   Column 1, left:   newest, top of hour
#   Column 2, center: 20 minutes earlier
#   Column 3, right:  40 minutes earlier
# -------------------------------------------------------------------

PARAMETERS = [
    {
        "field": "air_temperature_c",
        "name": "Air Temperature",
        "units": "deg C",
        "type": float,
    },
    {
        "field": "relative_humidity_pct",
        "name": "Relative Humidity",
        "units": "%",
        "type": float,
    },
    {
        "field": "wind_speed_mps",
        "name": "Wind Speed",
        "units": "m/s",
        "type": float,
    },
    {
        "field": "wind_direction_deg",
        "name": "Wind Direction",
        "units": "degrees",
        "type": float,
    },
    {
        "field": "solar_average",
        "name": "Solar Average",
        "units": None,
        "type": float,
    },
    {
        "field": "season_rain_in",
        "name": "Season Rain Total",
        "units": "in",
        "type": float,
    },
    {
        "field": "visibility_m",
        "name": "Visibility",
        "units": "m",
        "type": float,
    },
    {
        "field": "stage_ft",
        "name": "Stage",
        "units": "ft",
        "type": float,
    },
    {
        "field": "turbidity_ftu",
        "name": "Turbidity",
        "units": "FTU",
        "type": float,
    },
    {
        "field": "next_bottle",
        "name": "Next Bottle",
        "units": "count",
        "type": int,
    },
]


# -------------------------------------------------------------------
# General routes
# -------------------------------------------------------------------

@app.route("/", methods=["GET"])
def home():
    return """
    <h1>MET Hydrology</h1>
    <p>DADDS webhook receiver is running.</p>
    <p>Webhook endpoint: <code>/webhook</code></p>
    <p>Health endpoint: <code>/health</code></p>
    """


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "time_utc": datetime.now(timezone.utc).isoformat()
    }), 200


# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------

def parse_platform_time(time_text):
    """
    Parse the DADDS platform timestamp and explicitly treat it as UTC.

    Example input:
        2026-11-04T00:06:16.168

    Example output:
        2026-11-04 00:06:16.168000+00:00
    """

    if not time_text:
        raise ValueError("The DADDS message does not contain a Time value.")

    normalized = time_text.strip()

    # Python uses +00:00 rather than Z for fromisoformat in some versions.
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"

    parsed_time = datetime.fromisoformat(normalized)

    # DADDS platform timestamps in this feed appear without a timezone,
    # but correspond to UTC reception time.
    if parsed_time.tzinfo is None:
        parsed_time = parsed_time.replace(tzinfo=timezone.utc)
    else:
        parsed_time = parsed_time.astimezone(timezone.utc)

    return parsed_time


def calculate_observation_times(platform_time):
    """
    Floor the DADDS platform time to the top of the hour.

    Assign timestamps to the three transmitted columns:

        Column 1: top of hour
        Column 2: 20 minutes earlier
        Column 3: 40 minutes earlier
    """

    top_of_hour = platform_time.replace(
        minute=0,
        second=0,
        microsecond=0
    )

    return [
        top_of_hour,
        top_of_hour - timedelta(minutes=20),
        top_of_hour - timedelta(minutes=40),
    ]


def parse_data_matrix(data_text):
    """
    Convert the raw DADDS Data string into a 10-row by 3-column matrix.

    Example row:
        "12.9,13.1,13.0,"

    Parsed result:
        ["12.9", "13.1", "13.0"]
    """

    if not isinstance(data_text, str):
        raise ValueError("The DADDS Data field is missing or is not text.")

    rows = []

    for raw_line in data_text.splitlines():
        line = raw_line.strip()

        if not line:
            continue

        values = [
            value.strip()
            for value in line.split(",")
            if value.strip()
        ]

        if values:
            rows.append(values)

    expected_rows = len(PARAMETERS)

    if len(rows) != expected_rows:
        raise ValueError(
            f"Expected {expected_rows} data rows, but received {len(rows)}."
        )

    for row_number, values in enumerate(rows, start=1):
        if len(values) != 3:
            raise ValueError(
                f"Row {row_number} should contain 3 values, "
                f"but contains {len(values)}."
            )

    return rows


def convert_value(raw_value, parameter):
    """
    Convert a raw data value to the configured Python type.

    Empty values and common missing-data values become None.
    """

    if raw_value is None:
        return None

    cleaned = str(raw_value).strip()

    if cleaned.lower() in {
        "",
        "null",
        "none",
        "nan",
        "na",
        "n/a",
        "missing",
    }:
        return None

    try:
        conversion_type = parameter["type"]

        # Some count fields might arrive formatted as "1.0".
        if conversion_type is int:
            return int(float(cleaned))

        return conversion_type(cleaned)

    except (TypeError, ValueError) as error:
        raise ValueError(
            f"Could not convert {parameter['name']} value "
            f"'{raw_value}' to {parameter['type'].__name__}."
        ) from error


def decode_dadds_observation(observation, sns_envelope, received_at):
    """
    Decode one nested DADDS message into three records.

    One record is created for each 20-minute observation.
    """

    platform_time = parse_platform_time(observation.get("Time"))
    observation_times = calculate_observation_times(platform_time)
    matrix = parse_data_matrix(observation.get("Data", ""))

    message_id = sns_envelope.get("MessageId")
    dadds_id = observation.get("Id")
    address = observation.get("Address")
    group_code = observation.get("GroupCd")
    quality = observation.get("Quality") or observation.get("InfoCd")

    records = []

    for column_index, observation_time in enumerate(observation_times):
        record = {
            "observation_time_utc": (
                observation_time.isoformat().replace("+00:00", "Z")
            ),
            "platform_time_utc": (
                platform_time.isoformat().replace("+00:00", "Z")
            ),
            "received_time_utc": (
                received_at.isoformat().replace("+00:00", "Z")
            ),
            "platform_address": address,
            "group_code": group_code,
            "quality": quality,
            "sns_message_id": message_id,
            "dadds_message_id": dadds_id,
            "column_number": column_index + 1,
            "signal_strength": observation.get("SigStrength"),
            "snr": observation.get("Snr"),
            "satellite_id": observation.get("SatId"),
            "channel_id": observation.get("ChannelId"),
        }

        for row_index, parameter in enumerate(PARAMETERS):
            raw_value = matrix[row_index][column_index]

            record[parameter["field"]] = convert_value(
                raw_value,
                parameter
            )

        records.append(record)

    return records


def confirm_sns_subscription(subscribe_url):
    """
    Confirm an Amazon SNS subscription after validating that the URL
    uses HTTPS and belongs to an amazonaws.com host.
    """

    if not subscribe_url:
        raise ValueError("Subscription confirmation has no SubscribeURL.")

    parsed_url = urlparse(subscribe_url)
    hostname = (parsed_url.hostname or "").lower()

    valid_amazon_host = (
        hostname == "amazonaws.com"
        or hostname.endswith(".amazonaws.com")
    )

    if parsed_url.scheme != "https" or not valid_amazon_host:
        raise ValueError(
            "The SNS SubscribeURL is not an approved HTTPS "
            "amazonaws.com address."
        )

    with urllib.request.urlopen(
        subscribe_url,
        timeout=15
    ) as response:
        return response.status


def log_records(records):
    """
    Print parsed observations in a compact, readable format.
    """

    print("===== DECODED DADDS OBSERVATIONS =====", flush=True)

    for record in records:
        print(
            json.dumps(record, indent=2, default=str),
            flush=True
        )

    print("======================================", flush=True)


# -------------------------------------------------------------------
# Webhook route
# -------------------------------------------------------------------

@app.route("/webhook", methods=["POST"])
def webhook():
    received_at = datetime.now(timezone.utc)
    raw_body = request.get_data(as_text=True)

    print("----- WEBHOOK RECEIVED -----", flush=True)
    print(
        f"Received UTC: {received_at.isoformat()}",
        flush=True
    )
    print(
        f"Content-Type: {request.content_type}",
        flush=True
    )
    print(
        "SNS header message type: "
        f"{request.headers.get('x-amz-sns-message-type')}",
        flush=True
    )

    try:
        envelope = json.loads(raw_body)

    except json.JSONDecodeError:
        print("Webhook body was not valid JSON.", flush=True)
        print(f"Raw body: {raw_body}", flush=True)

        return jsonify({
            "status": "error",
            "message": "Request body was not valid JSON."
        }), 400

    message_type = envelope.get("Type")

    print(
        f"SNS message type: {message_type}",
        flush=True
    )


    # ---------------------------------------------------------------
    # SNS subscription confirmation
    # ---------------------------------------------------------------

    if message_type == "SubscriptionConfirmation":
        try:
            confirmation_status = confirm_sns_subscription(
                envelope.get("SubscribeURL")
            )

            print(
                "SNS subscription confirmed. "
                f"HTTP status: {confirmation_status}",
                flush=True
            )

            return jsonify({
                "status": "subscription confirmed",
                "received_at_utc": (
                    received_at.isoformat().replace("+00:00", "Z")
                )
            }), 200

        except Exception as error:
            print(
                f"SNS subscription confirmation failed: {error}",
                flush=True
            )

            return jsonify({
                "status": "error",
                "message": "SNS subscription confirmation failed."
            }), 500


    # ---------------------------------------------------------------
    # SNS unsubscribe confirmation
    # ---------------------------------------------------------------

    if message_type == "UnsubscribeConfirmation":
        print(
            "SNS sent an unsubscribe confirmation message.",
            flush=True
        )

        return jsonify({
            "status": "unsubscribe confirmation received"
        }), 200


    # ---------------------------------------------------------------
    # DADDS observation notification
    # ---------------------------------------------------------------

    if message_type == "Notification":
        nested_message = envelope.get("Message")

        if not isinstance(nested_message, str):
            print(
                "SNS Notification did not contain a text Message.",
                flush=True
            )

            return jsonify({
                "status": "error",
                "message": "SNS Message field is missing."
            }), 400

        try:
            observation = json.loads(nested_message)

        except json.JSONDecodeError:
            print(
                "SNS Message field was not valid nested JSON.",
                flush=True
            )
            print(
                f"Nested Message: {nested_message}",
                flush=True
            )

            return jsonify({
                "status": "error",
                "message": "DADDS Message was not valid JSON."
            }), 400

        try:
            records = decode_dadds_observation(
                observation=observation,
                sns_envelope=envelope,
                received_at=received_at
            )

        except ValueError as error:
            print(
                f"DADDS parsing error: {error}",
                flush=True
            )

            return jsonify({
                "status": "error",
                "message": str(error)
            }), 422

        except Exception as error:
            print(
                f"Unexpected DADDS parsing error: {error}",
                flush=True
            )

            return jsonify({
                "status": "error",
                "message": "Unexpected parsing error."
            }), 500

        log_records(records)

        # Database storage will be added here later.
        #
        # Example:
        # save_records(records)

        return jsonify({
            "status": "notification decoded",
            "platform_address": observation.get("Address"),
            "records_decoded": len(records),
            "newest_observation_time_utc": (
                records[0]["observation_time_utc"]
            ),
            "received_at_utc": (
                received_at.isoformat().replace("+00:00", "Z")
            )
        }), 200


    # ---------------------------------------------------------------
    # Unknown SNS message
    # ---------------------------------------------------------------

    print(
        f"Unsupported SNS message type: {message_type}",
        flush=True
    )

    return jsonify({
        "status": "ignored",
        "message_type": message_type
    }), 200


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=10000
    )
