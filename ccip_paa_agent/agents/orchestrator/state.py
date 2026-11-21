
from typing import TypedDict, Any


class CryptoGuardianState(TypedDict, total=False):
    # Input
    csv_path: str
    coins: list[dict[str, str]]

    # Agent outputs
    market_results: dict[str, Any]
    news_results: dict[str, Any]
    pattern_results: dict[str, Any]

    # Execution tracking
    errors: list[str]
    final_report: dict[str, Any]
