
import json
import os

from dotenv import load_dotenv
from google import genai

load_dotenv()

MODEL_NAME = "gemini-decision-1"

def ask_llm_advisor(
    vlm_report: dict,
    market_context: dict,
    has_open_position: bool = False,
) -> dict:
    """
    Gemini Decision 1 evaluates all unique patterns from the
    Pattern Tracker and chooses a market action.

    No separate Python ranking or pattern verification.
    """

    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise ValueError("GEMINI_API_KEY is missing from .env")

    client = genai.Client(
        api_key=api_key,
        http_options={"api_version": "v1beta"},
    )

    current_patterns = vlm_report.get("current_detections", [])
    tracked_patterns = vlm_report.get("tracked_patterns", [])

    actions = {
        "ENTER": (
            "A sufficiently confirmed trading opportunity exists. "
            "The detected pattern, price action, confirmation conditions "
            "and potential risk/reward support a possible entry."
        ),
        "WAIT": (
            "The trading opportunity is not ready. The pattern may be "
            "developing, confirmation may be missing, or market evidence "
            "may be conflicting or uncertain."
        ),
    }

    if has_open_position:
        actions["EXIT"] = (
            "The existing position has evidence of a deteriorating setup "
            "or conditions that support closing the position."
        )

    input_data = {
        "symbol": vlm_report.get("symbol"),
        "timeframe": vlm_report.get("timeframe"),
        "current_detections": current_patterns,
        "tracked_patterns": tracked_patterns,
        "vlm_market_analysis": {
            "market_structure": vlm_report.get("market_structure"),
            "overall_visual_bias": vlm_report.get("overall_visual_bias"),
            "breakout_status": vlm_report.get("breakout_status"),
            "confidence": vlm_report.get("confidence"),
            "visual_evidence": vlm_report.get("visual_evidence"),
            "limitations": vlm_report.get("limitations", []),
        },
        "market_context": market_context,
        "has_open_position": has_open_position,
    }

    instructions = (
    "You are CryptoGuardian's Pattern Decision Agent.\n\n"

    "Your ONLY responsibility is to decide whether the supplied "
    "cryptocurrency market setup is ready for entry, should be "
    "waited on, or requires exiting an existing position.\n\n"

    "Nemotron VLM detects chart patterns. Do not independently "
    "detect new patterns. Evaluate the supplied detections and "
    "tracked pattern history together with market data.\n\n"

    "ENTER:\n"
    "Choose ENTER only when there is sufficient evidence of "
    "confirmation. Check pattern direction, trigger level, "
    "completed candle close, volume, market structure and "
    "potential risk/reward when available. Do not enter merely "
    "because a pattern has been detected.\n\n"

    "WAIT:\n"
    "Choose WAIT when a pattern is developing, breakout or "
    "breakdown is unconfirmed, volume confirmation is missing, "
    "evidence conflicts, or necessary information is unavailable.\n\n"

    "EXIT:\n"
    "Choose EXIT only when has_open_position is true and "
    "the supplied evidence supports closing the existing position. "
    "Consider invalidation levels and deterioration of the setup.\n\n"

    "If there is no open position, never choose EXIT.\n\n"

    "Do not invent prices, candle closes, volume or confirmations. "
    "Visual pattern confidence is not probability of profit. "
    "Never execute trades.\n\n"

    "Make ONE overall decision for the supplied symbol and timeframe. "
    
    "When uncertain, prefer WAIT."
    "Also provide a short reason explaining why you selected "
"ENTER, WAIT, or EXIT. Base it only on the supplied evidence.\n"
"ENTER, WAIT, or EXIT. Base it only on the supplied evidence.\n"
)
    
    
    


    
    result = client.decisions.create(
        model=MODEL_NAME,
        input=json.dumps(input_data, default=str),
        questions={
            "market_decision": {
                "type": "choice",
                "instructions": instructions,
                "criteria": actions,
            }
        },
    )

    answer = result.answers["market_decision"]
    decision = answer.choice

    if decision not in actions:
        raise ValueError(
            f"Unexpected decision returned: {decision}"
        )
    return {
 
        "symbol": vlm_report.get("symbol"),
        "timeframe": vlm_report.get("timeframe"),
        "decision": decision,
        "reason": "Decision returned by Gemini. Explanation not yet available.",

        "decision_confidence": getattr(answer, "confidence", None),
        "model": MODEL_NAME,
        "current_patterns_considered": current_patterns,
        "tracked_patterns_considered": tracked_patterns,
    }
