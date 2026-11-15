import os
import json
import logging
import math
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

logger = logging.getLogger("cryptoguardian.vlm_analysis")

NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY")
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
MODEL_NAME = "nvidia/nemotron-3.5-super-vl-120b-a12b"

client = (
    OpenAI(base_url=NVIDIA_BASE_URL, api_key=NVIDIA_API_KEY, timeout=90.0, max_retries=2)
    if NVIDIA_API_KEY else None
)

SYSTEM_PROMPT = """
ROLE:
You are an expert cryptocurrency chart pattern prediction model.
Your primary objective is to identify and predict chart patterns
WHILE THEY ARE STILL FORMING, before they become complete.

TIMEFRAME:
Analyze the supplied 15-minute cryptocurrency chart.
The latest candle may still be forming. Do not assume it is closed.

PATTERN CHECKLIST — ANALYZE ALL 27 PATTERNS:

1. REVERSAL PATTERNS (6)
- Head and Shoulders
- Inverse Head and Shoulders
- Double Top
- Double Bottom
- Triple Top
- Triple Bottom

2. CONTINUATION PATTERNS (9)
- Bullish Flag
- Bearish Flag
- Bullish Pennant
- Bearish Pennant
- Ascending Triangle
- Descending Triangle
- Symmetrical Triangle
- Rising Wedge
- Falling Wedge

3. CANDLESTICK PATTERNS (7)
- Bullish Engulfing
- Bearish Engulfing
- Hammer
- Shooting Star
- Morning Star
- Evening Star
- Doji

4. SMART MONEY CONCEPTS (5)
- Break of Structure (BOS)
- Change of Character (CHoCH)
- Liquidity Sweep
- Order Block
- Fair Value Gap (FVG)

EARLY PATTERN PREDICTION RULES:

- Prioritize patterns that are beginning to form.
- Identify incomplete structures using visible price action.
- Do not wait for breakout confirmation before reporting a
  credible developing pattern.
- Distinguish between an early possibility and a completed pattern.
- Do not report a pattern based on one isolated candle alone
  unless it is a valid candlestick pattern.
- Explain which structural elements are already visible and
  which elements are still missing.
- Never claim that a future breakout is guaranteed.
- If evidence is insufficient, return an empty patterns_found list.
- Return a maximum of 3 patterns, ranked by confidence.
- Do not report duplicate patterns.

FORMATION STATES:

DETECTED:
Early visual evidence suggests a possible pattern.

DEVELOPING:
Multiple structural elements are visible, but the pattern
is not yet complete.

CONFIRMING:
The pattern is approaching its defining confirmation condition.

CONFIRMED:
The required structural confirmation is visible.

INVALIDATED:
Price action has invalidated the expected structure.

DIRECTION:
Use LONG, SHORT, or NEUTRAL.

PATTERN TYPES:
REVERSAL, CONTINUATION, CANDLESTICK, SMC.

CONFIDENCE:
90-100: Very clear visual structure.
70-89: Strong developing structure.
50-69: Possible pattern, but incomplete or ambiguous.
0-49: Insufficient evidence. Do not report.

Confidence represents visual pattern recognition confidence,
NOT probability of profit.

KEY LEVELS:
Estimate levels only when visually supportable.
Do not invent prices.
If required levels cannot reasonably be estimated,
do not report that pattern.

RETURN ONLY VALID JSON:

{
  "patterns_found": [
    {
      "name": "",
      "type": "REVERSAL",
      "direction": "LONG",
      "status": "DEVELOPING",
      "formation_state": "DEVELOPING",
      "confidence": 0,
      "key_levels": {
        "level_high": 0.0,
        "level_low": 0.0,
        "trigger_level": 0.0,
        "invalidation_level": 0.0
      },
      "evidence": "",
      "missing_conditions": ""
    }
  ],
  "market_structure": "BULLISH/BEARISH/SIDEWAYS/UNCLEAR",
  "overall_visual_bias": "LONG/SHORT/NEUTRAL",
  "breakout_status": "BREAKOUT_UP/BREAKDOWN/FALSE_BREAK/NONE/UNCLEAR",
  "confidence": 0,
  "visual_evidence": "",
  "limitations": []
}

IMPORTANT:
- Analyze potential formations, not only completed patterns.
- Never confuse a predicted pattern with a confirmed pattern.
- Return only JSON. No Markdown or additional explanations.
"""


def extract_json(text: str) -> dict[str, Any] | None:
    try:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            return None
        data = json.loads(text[start:end+1])
        return data if isinstance(data, dict) else None
    except Exception:
        return None

def safe_float(value: Any) -> float:
    """Converts value to float, but returns 0.0 if it's NaN, Infinity, bool, or invalid."""
    if isinstance(value, bool): # Block booleans (True -> 1)
        return 0.0
    try:
        val = float(value)
        return val if math.isfinite(val) else 0.0
    except (TypeError, ValueError):
        return 0.0

def normalize_vlm_response(data: dict[str, Any]) -> dict[str, Any]:
    """Fix nulls and coerce types safely without inventing data."""
    patterns = data.get("patterns_found")
    if not isinstance(patterns, list):
        patterns = []

    normalized = []
    for p in patterns[:3]:
        if not isinstance(p, dict):
            continue
        p = p.copy()
        
        # FIX 1: Safe key_levels handling (prevents null crash)
        kl = p.get("key_levels")
        if not isinstance(kl, dict):
            kl = {}
        p["key_levels"] = kl
        
        for key in ("level_high", "level_low", "trigger_level", "invalidation_level"):
            if key in kl:
                kl[key] = safe_float(kl[key])
                
        normalized.append(p)

    data["patterns_found"] = normalized
    return data

def validate_vlm_response(
    data: dict[str, Any],
    current_price: float | None = None
) -> bool:

    required_fields = {
        "patterns_found",
        "market_structure",
        "overall_visual_bias",
        "breakout_status",
        "confidence",
        "visual_evidence",
        "limitations"
    }

    if not isinstance(data, dict):
        return False

    if not required_fields.issubset(data.keys()):
        return False

    if isinstance(data["confidence"], bool):
        return False

    if not isinstance(data["confidence"], (int, float)):
        return False

    if not math.isfinite(data["confidence"]) or not 0 <= data["confidence"] <= 100:
        return False

    if data["market_structure"] not in {
        "BULLISH", "BEARISH", "SIDEWAYS", "UNCLEAR"
    }:
        return False

    if data["overall_visual_bias"] not in {
        "LONG", "SHORT", "NEUTRAL"
    }:
        return False

    if data["breakout_status"] not in {
        "BREAKOUT_UP", "BREAKDOWN", "FALSE_BREAK", "NONE", "UNCLEAR"
    }:
        return False

    if not isinstance(data["visual_evidence"], str):
        return False

    if not isinstance(data["limitations"], list):
        return False

    if not all(isinstance(x, str) for x in data["limitations"]):
        return False

    if not isinstance(data["patterns_found"], list):
        return False

    if len(data["patterns_found"]) > 3:
        return False

    valid_types = {
        "REVERSAL", "CONTINUATION", "CANDLESTICK", "SMC"
    }

    valid_statuses = {
    "DETECTED",
    "DEVELOPING",
    "CONFIRMING",
    "CONFIRMED",
    "COMPLETE",
    "INVALIDATED"
    }

    valid_formation_states = {
        "DETECTED",
        "DEVELOPING",
        "CONFIRMING",
        "CONFIRMED",
        "INVALIDATED"
    }

    for pattern in data["patterns_found"]:

        if not isinstance(pattern, dict):
            return False

        required_pattern_fields = {
            "name",
            "type",
            "direction",
            "status",
            "formation_state",
            "confidence",
            "key_levels",
            "evidence",
            "missing_conditions"
        }

        if not required_pattern_fields.issubset(pattern.keys()):
            return False

        if not isinstance(pattern["name"], str) or not pattern["name"].strip():
            return False

        if not isinstance(pattern["evidence"], str):
            return False

        if not isinstance(pattern["missing_conditions"], str):
            return False

        if pattern["type"] not in valid_types:
            return False

        if pattern["status"] not in valid_statuses:
            return False

        if pattern["formation_state"] not in valid_formation_states:
            return False

        if pattern["direction"] not in {"LONG", "SHORT", "NEUTRAL"}:
            return False

        pc = pattern["confidence"]

        if isinstance(pc, bool):
            return False

        if not isinstance(pc, (int, float)):
            return False

        if not math.isfinite(pc) or not 0 <= pc <= 100:
            return False

        kl = pattern["key_levels"]

        if not isinstance(kl, dict):
            return False

        required_levels = {
            "level_high",
            "level_low",
            "trigger_level",
            "invalidation_level"
        }

        if not required_levels.issubset(kl.keys()):
            return False

        for key in required_levels:
            value = kl[key]

            if isinstance(value, bool):
                return False

            if not isinstance(value, (int, float)):
                return False

            if not math.isfinite(value) or value <= 0:
                return False

        if kl["level_low"] >= kl["level_high"]:
            return False

        if current_price is not None and current_price > 0:
            for key in required_levels:
                level = kl[key]

                if abs(level - current_price) / current_price > 0.25:
                    logger.warning(
                        "%s: %s is more than 25%% away from current price",
                        pattern["name"],
                        key
                    )

    return True


    

def analyze_pre_generated_chart(
    symbol: str,
    base64_image: str,
    timeframe: str = "15m",
    current_price: float | None = None,
) -> dict[str, Any] | None:
    
    if client is None or not symbol or not base64_image:
        return None

    text_context = (
        f"Analyze this cryptocurrency chart for {symbol}. "
        f"Timeframe: {timeframe}. "
        f"Current price: approximately {current_price if current_price else 'unknown'}. "
        "Return only the required JSON object."
    )

    try:
        completion = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": [
                    {"type": "text", "text": text_context},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}}
                ]}
            ],
            temperature=0.1,
            top_p=0.95,
            max_tokens=8192,
            stream=False,
            seed=42
        )

        if not completion.choices: return None
        choice = completion.choices[0]
        
        if choice.finish_reason == "length":
            logger.error("JSON truncated by max_tokens for %s. Rejecting.", symbol)
            return None

        result_text = choice.message.content
        if not result_text: return None

        vlm_data = extract_json(result_text)
        if vlm_data is None: return None


        logger.warning(
         "NEMOTRON RAW JSON FOR %s:\n%s",
         symbol,
         json.dumps(vlm_data, indent=2, ensure_ascii=False)
        )

        vlm_data = normalize_vlm_response(vlm_data)
        
        if not validate_vlm_response(vlm_data, current_price):
            logger.warning("Invalid VLM response structure for %s.", symbol)
            return None

        vlm_data["symbol"] = symbol
        return vlm_data

    except Exception:
        logger.exception("NVIDIA Nemotron analysis failed for %s", symbol)
        return None