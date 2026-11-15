
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

    patterns = vlm_report.get("patterns_found", [])

    actions = {
        "ENTER": (
            "The combined pattern evidence and market context support "
            "a potential trade entry. There is a clear setup, a meaningful "
            "trigger, and sufficient supporting evidence."
        ),
        "WAIT": (
            "A possible setup exists, but confirmation is incomplete, "
            "signals conflict, or more market information is needed."
        ),
        "AVOID": (
            "The available evidence indicates a weak, invalid, or "
            "contradictory setup that should not be entered."
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
        "unique_patterns": patterns,
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

    result = client.decisions.create(
        model=MODEL_NAME,
        input=json.dumps(input_data, default=str),
        questions={
            "market_decision": {
                "type": "choice",
                "instructions": (
                    "You are the decision-making component of a "
                    "cryptocurrency market analysis system.\n\n"

                    "Evaluate ALL unique detected patterns together "
                    "with the current market context.\n\n"

                    "Compare bullish and bearish evidence. Consider "
                    "pattern direction, formation quality, repeated "
                    "detections, market structure, breakout status, "
                    "volume, and available price levels.\n\n"

                    "Do not simply count bullish and bearish patterns. "
                    "Evaluate their relevance, strength, and whether "
                    "the evidence supports the same market direction.\n\n"

                    "Do not treat visual confidence alone as proof "
                    "of a profitable trade. Do not invent missing "
                    "price levels or market information.\n\n"

                    "Choose ENTER only when the combined evidence "
                    "supports a sufficiently clear potential entry.\n"

                    "Choose WAIT when confirmation is incomplete "
                    "or the evidence is uncertain.\n"

                    "Choose AVOID when the setup is weak, invalid, "
                    "or contradictory.\n"

                    "Choose EXIT only if an existing position is "
                    "provided and the evidence supports closing it.\n\n"

                    "Make one overall decision for the supplied "
                    "symbol and timeframe."
                ),
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

    explanations = {
        "ENTER": "The combined evidence supports a potential entry.",
        "WAIT": "Wait for stronger confirmation or clearer market conditions.",
        "AVOID": "The current setup does not provide sufficient support for entry.",
        "EXIT": "The available evidence supports closing the existing position.",
    }

    return {
        "symbol": vlm_report.get("symbol"),
        "timeframe": vlm_report.get("timeframe"),
        "decision": decision,
        "decision_confidence": getattr(answer, "confidence", None),
        "model": MODEL_NAME,
        "explanation": explanations[decision],
        "patterns_considered": patterns,
    }
