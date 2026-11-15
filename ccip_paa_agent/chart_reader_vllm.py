
import os
import json
import logging
import base64
import tempfile

from pathlib import Path

import mplfinance as mpf
import pandas as pd

from dotenv import load_dotenv
from openai import OpenAI


# ============================================================
# 1. CONFIGURATION
# ============================================================

load_dotenv()

logger = logging.getLogger("cryptoguardian.chart_reader")

MODEL = "nvidia/nemotron-3.5-super-vl-120b-a12b"

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"

CHART_CANDLE_LIMIT = 200
MINIMUM_CANDLES = 20

MAX_OUTPUT_TOKENS = 2048

# Lazy initialization: API key is checked when analysis starts.
client = None


def get_nvidia_client():
    """Initialize the NVIDIA-compatible API client."""

    global client

    if client is None:
        api_key = os.getenv("NVIDIA_API_KEY")

        if not api_key:
            raise ValueError(
                "NVIDIA_API_KEY is missing from environment variables."
            )

        client = OpenAI(
            base_url=NVIDIA_BASE_URL,
            api_key=api_key,
            timeout=90.0,
            max_retries=2
        )

    return client


# ============================================================
# 2. SYSTEM PROMPT
# ============================================================

SYSTEM_PROMPT = """
You are CryptoGuardian, an elite Visual Cryptocurrency Chart Analyst.

Your ONLY responsibility is visual chart pattern identification.
Python performs mathematical calculations and independent validation.

PATTERN CHECKLIST:

REVERSAL:
1. Head & Shoulders
2. Inverse Head & Shoulders
3. Double Top
4. Double Bottom
5. Triple Top
6. Triple Bottom
7. Cup & Handle

CONTINUATION:
8. Bull Flag
9. Bear Flag
10. Bull Pennant
11. Bear Pennant
12. Ascending Triangle
13. Descending Triangle
14. Symmetrical Triangle
15. Rectangle

CANDLESTICK:
16. Bullish Engulfing
17. Bearish Engulfing
18. Hammer
19. Shooting Star

VISUAL ANALYSIS:

- Identify only patterns with visible supporting evidence.
- Identify overall market structure.
- Observe support and resistance.
- Examine visible price and volume behaviour.
- Multiple patterns may be reported.
- Patterns can be DEVELOPING, CONFIRMED or INVALIDATED.
- Do not force patterns onto choppy charts.
- If no reliable pattern exists, return an empty patterns_found list.
- Consider the supplied timeframe.

BREAKOUT RULES:

- CONFIRMED: Visible candle close outside the pattern boundary.
- FAILED: Price moves outside but returns inside.
- NONE: No breakout is visible.
- UNCLEAR: Evidence is insufficient.

A wick alone is not a confirmed breakout.
If candle closure cannot be established visually, use UNCLEAR.

STRICT RULES:

- Never invent patterns, prices or indicators.
- Do not assume an incomplete pattern is confirmed.
- Do not calculate entry, stop-loss, targets or position size.
- Do not execute or recommend trades.
- LONG/SHORT represents visual directional bias, not a trade instruction.
- Confidence measures visual evidence, NOT probability of profit.
- Report conflicting or insufficient evidence honestly.

RETURN ONLY VALID JSON.
No Markdown or text outside JSON.

REQUIRED JSON STRUCTURE:

{
  "patterns_found": [
    {
      "name": "Double Bottom",
      "type": "REVERSAL",
      "status": "DEVELOPING",
      "evidence": "Two visible troughs near a similar support zone."
    }
  ],
  "market_structure": "BULLISH",
  "overall_visual_bias": "LONG",
  "breakout_status": "NONE",
  "volume_confirmation": "UNAVAILABLE",
  "confidence": 75,
  "visual_evidence": "Brief explanation of visible chart evidence.",
  "limitations": []
}

ALLOWED VALUES:

market_structure:
BULLISH, BEARISH, SIDEWAYS, UNCLEAR

overall_visual_bias:
LONG, SHORT, NEUTRAL

breakout_status:
CONFIRMED, FAILED, NONE, UNCLEAR

volume_confirmation:
YES, NO, UNAVAILABLE

Pattern type:
REVERSAL, CONTINUATION, CANDLESTICK

Pattern status:
DEVELOPING, CONFIRMED, INVALIDATED

If no pattern is found:
"patterns_found": []

Confidence must be a number between 0 and 100.
"""


# ============================================================
# 3. ALLOWED PATTERNS AND JSON VALIDATION
# ============================================================

ALLOWED_PATTERNS = {
    "Head & Shoulders",
    "Inverse Head & Shoulders",
    "Double Top",
    "Double Bottom",
    "Triple Top",
    "Triple Bottom",
    "Cup & Handle",
    "Bull Flag",
    "Bear Flag",
    "Bull Pennant",
    "Bear Pennant",
    "Ascending Triangle",
    "Descending Triangle",
    "Symmetrical Triangle",
    "Rectangle",
    "Bullish Engulfing",
    "Bearish Engulfing",
    "Hammer",
    "Shooting Star"
}

ALLOWED_TYPES = {
    "REVERSAL",
    "CONTINUATION",
    "CANDLESTICK"
}

ALLOWED_STATUSES = {
    "DEVELOPING",
    "CONFIRMED",
    "INVALIDATED"
}

ALLOWED_MARKET_STRUCTURES = {
    "BULLISH",
    "BEARISH",
    "SIDEWAYS",
    "UNCLEAR"
}

ALLOWED_BIASES = {
    "LONG",
    "SHORT",
    "NEUTRAL"
}

ALLOWED_BREAKOUTS = {
    "CONFIRMED",
    "FAILED",
    "NONE",
    "UNCLEAR"
}

ALLOWED_VOLUME_CONFIRMATIONS = {
    "YES",
    "NO",
    "UNAVAILABLE"
}


def extract_json(text: str) -> dict | None:
    """
    Extract the first valid JSON object from model output.
    Handles accidental Markdown code fences.
    """

    if not isinstance(text, str) or not text.strip():
        logger.error("Nemotron returned empty content.")
        return None

    decoder = json.JSONDecoder()

    for position, character in enumerate(text):

        if character != "{":
            continue

        try:
            data, _ = decoder.raw_decode(text[position:])

            if isinstance(data, dict):
                return data

        except json.JSONDecodeError:
            continue

    logger.error("No valid JSON object found in model response.")

    return None


def validate_vlm_json(data: dict) -> bool:
    """Validate JSON keys, values and pattern data types."""

    required_keys = {
        "patterns_found",
        "market_structure",
        "overall_visual_bias",
        "breakout_status",
        "volume_confirmation",
        "confidence",
        "visual_evidence",
        "limitations"
    }

    if not isinstance(data, dict):
        return False

    missing_keys = required_keys - set(data.keys())

    if missing_keys:
        logger.warning(f"Missing JSON keys: {missing_keys}")
        return False

    if not isinstance(data["patterns_found"], list):
        return False

    if data["market_structure"] not in ALLOWED_MARKET_STRUCTURES:
        return False

    if data["overall_visual_bias"] not in ALLOWED_BIASES:
        return False

    if data["breakout_status"] not in ALLOWED_BREAKOUTS:
        return False

    if data["volume_confirmation"] not in ALLOWED_VOLUME_CONFIRMATIONS:
        return False

    confidence = data["confidence"]

    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0 <= confidence <= 100
    ):
        return False

    if not isinstance(data["visual_evidence"], str):
        return False

    if not isinstance(data["limitations"], list):
        return False

    if not all(isinstance(item, str) for item in data["limitations"]):
        return False

    # Validate each detected pattern.

    for pattern in data["patterns_found"]:

        if not isinstance(pattern, dict):
            return False

        required_pattern_keys = {
            "name",
            "type",
            "status",
            "evidence"
        }

        if not required_pattern_keys.issubset(pattern.keys()):
            return False

        if pattern["name"] not in ALLOWED_PATTERNS:
            logger.warning(
                f"Unknown pattern returned: {pattern['name']}"
            )
            return False

        if pattern["type"] not in ALLOWED_TYPES:
            return False

        if pattern["status"] not in ALLOWED_STATUSES:
            return False

        if not isinstance(pattern["evidence"], str):
            return False

    return True


def extract_and_validate_json(text: str) -> dict | None:
    """Extract JSON and validate its complete structure."""

    data = extract_json(text)

    if data is None:
        return None

    if not validate_vlm_json(data):
        logger.error("Nemotron returned invalid JSON structure.")
        return None

    return data


# ============================================================
# 4. PREPARE AND VALIDATE MARKET DATA
# ============================================================

def prepare_chart_data(df: pd.DataFrame) -> pd.DataFrame | None:
    """Prepare OHLCV data for mplfinance."""

    if not isinstance(df, pd.DataFrame) or df.empty:
        logger.error("Market DataFrame is empty or invalid.")
        return None

    chart_data = df.copy()

    chart_data.columns = [
        str(column).lower() for column in chart_data.columns
    ]

    if chart_data.columns.duplicated().any():
        logger.error("Duplicate columns found in market data.")
        return None

    required_columns = {
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume"
    }

    missing_columns = required_columns - set(chart_data.columns)

    if missing_columns:
        logger.error(f"Missing OHLCV columns: {missing_columns}")
        return None

    # Convert timestamps.

    if pd.api.types.is_numeric_dtype(chart_data["timestamp"]):
        chart_data["timestamp"] = pd.to_datetime(
            chart_data["timestamp"],
            unit="ms",
            errors="coerce",
            utc=True
        )
    else:
        chart_data["timestamp"] = pd.to_datetime(
            chart_data["timestamp"],
            errors="coerce",
            utc=True
        )

    # Convert numeric columns.

    numeric_columns = [
        "open",
        "high",
        "low",
        "close",
        "volume"
    ]

    for column in numeric_columns:
        chart_data[column] = pd.to_numeric(
            chart_data[column],
            errors="coerce"
        )

    chart_data.dropna(
        subset=["timestamp"] + numeric_columns,
        inplace=True
    )

    chart_data.sort_values("timestamp", inplace=True)

    chart_data.drop_duplicates(
        subset=["timestamp"],
        keep="last",
        inplace=True
    )

    if len(chart_data) < MINIMUM_CANDLES:
        logger.warning(
            f"Insufficient candle history: {len(chart_data)}"
        )
        return None

    if (chart_data[["open", "high", "low", "close"]] <= 0).any().any():
        logger.error("Invalid non-positive OHLC prices.")
        return None

    if (chart_data["volume"] < 0).any():
        logger.error("Negative volume detected.")
        return None

    invalid_ranges = (
        (chart_data["high"] < chart_data["low"])
        | (chart_data["high"] < chart_data["open"])
        | (chart_data["high"] < chart_data["close"])
        | (chart_data["low"] > chart_data["open"])
        | (chart_data["low"] > chart_data["close"])
    )

    if invalid_ranges.any():
        logger.error("Invalid OHLC candle ranges detected.")
        return None

    # Use the latest 200 candles.

    chart_data = chart_data.tail(CHART_CANDLE_LIMIT).copy()

    chart_data.set_index("timestamp", inplace=True)

    chart_data.rename(
        columns={
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume"
        },
        inplace=True
    )

    return chart_data


# ============================================================
# 5. CREATE BASE64 CHART IMAGE
# ============================================================

def create_chart_image(
    chart_data: pd.DataFrame,
    symbol: str,
    exchange: str
) -> str | None:
    """Generate a temporary candlestick chart and encode it."""

    image_path = None

    try:

        with tempfile.NamedTemporaryFile(
            suffix=".png",
            delete=False
        ) as temp_file:

            image_path = temp_file.name

        mpf.plot(
            chart_data,
            type="candle",
            style="yahoo",
            title=f"{symbol} ({exchange.upper()}) - Anomaly",
            volume=True,
            figsize=(14, 8),
            savefig=image_path
        )

        with open(image_path, "rb") as image_file:
            base64_image = base64.b64encode(
                image_file.read()
            ).decode("utf-8")

        return base64_image

    except Exception:

        logger.exception("Chart image generation failed.")
        return None

    finally:

        if image_path and os.path.exists(image_path):
            os.remove(image_path)


# ============================================================
# 6. BUILD ANOMALY CONTEXT
# ============================================================

def build_user_context(
    anomaly_event: dict,
    symbol: str,
    exchange: str,
    chart_data: pd.DataFrame
) -> tuple[str, float]:

    """Build compact market context for Nemotron."""

    current_price = anomaly_event.get("current_price")

    if current_price is None:
        current_price = anomaly_event.get("price")

    if current_price is None:
        current_price = float(chart_data["Close"].iloc[-1])

    timeframe = anomaly_event.get("timeframe", "1m")

    reasons = anomaly_event.get("reasons", [])

    rsi = anomaly_event.get("rsi")

    user_context = f"""
Analyze this cryptocurrency candlestick chart.

Symbol: {symbol}
Exchange: {exchange}
Timeframe: {timeframe}
Current Price: {current_price}
RSI: {rsi if rsi is not None else "Unavailable"}
Python Anomaly Signals: {json.dumps(reasons, default=str)}

Identify visible patterns using the system instructions.

Return valid JSON only.
"""

    return user_context, float(current_price)


# ============================================================
# 7. MAIN CHART READER AGENT
# ============================================================

def analyze_chart_visuals(
    anomaly_event: dict,
    df: pd.DataFrame
) -> dict | None:

    """
    Analyze a cryptocurrency chart using NVIDIA Nemotron.

    Input:
        anomaly_event: Python Anomaly Detector event.
        df: OHLCV DataFrame.

    Output:
        Validated visual analysis dictionary or None.
    """

    if not isinstance(anomaly_event, dict):
        logger.error("Invalid anomaly event.")
        return None

    symbol = anomaly_event.get("symbol")
    exchange = anomaly_event.get("exchange")

    if not symbol or not exchange:
        logger.error("Symbol or exchange missing from anomaly event.")
        return None

    logger.info(
        f"NVIDIA Nemotron analyzing {symbol} on {exchange}..."
    )

    try:

        # STEP 1: Prepare market data.

        chart_data = prepare_chart_data(df)

        if chart_data is None:
            return None

        # STEP 2: Generate chart image.

        base64_image = create_chart_image(
            chart_data,
            symbol,
            exchange
        )

        if not base64_image:
            return None

        # STEP 3: Prepare anomaly context.

        user_context, current_price = build_user_context(
            anomaly_event,
            symbol,
            exchange,
            chart_data
        )

        # STEP 4: Initialize NVIDIA client.

        nvidia_client = get_nvidia_client()

        # STEP 5: Send image and prompt to Nemotron.

        completion = nvidia_client.chat.completions.create(
            model=MODEL,

            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": user_context
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": (
                                    "data:image/png;base64,"
                                    f"{base64_image}"
                                )
                            }
                        }
                    ]
                }
            ],

            temperature=0.1,
            top_p=0.95,
            max_tokens=MAX_OUTPUT_TOKENS,
            stream=False,
            seed=42
        )

        # STEP 6: Extract response.

        result_text = completion.choices[0].message.content

        if not result_text:
            logger.error("Nemotron returned empty response.")
            return None

        # STEP 7: Validate JSON.

        vlm_data = extract_and_validate_json(result_text)

        if vlm_data is None:
            logger.error("Chart analysis JSON validation failed.")
            return None

        # STEP 8: Add trusted Python context.

        vlm_data["symbol"] = symbol
        vlm_data["exchange"] = exchange
        vlm_data["timeframe"] = anomaly_event.get(
            "timeframe",
            "1m"
        )
        vlm_data["current_price"] = current_price
        vlm_data["model"] = MODEL

        logger.info(
            f"Chart analysis completed for {symbol}. "
            f"Detected patterns: {len(vlm_data['patterns_found'])}"
        )

        return vlm_data

    except Exception:

        logger.exception(
            f"NVIDIA VLM analysis failed for {symbol} on {exchange}."
        )

        return None
