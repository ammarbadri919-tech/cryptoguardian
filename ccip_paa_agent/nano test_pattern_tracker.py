from tools.pattern_tracker import PatternTracker
from pathlib import Path
import tempfile

with tempfile.TemporaryDirectory() as temp:
    tracker = PatternTracker(Path(temp) / "patterns.json")

    pattern = {
        "name": "Bullish Flag",
        "type": "CONTINUATION",
        "direction": "LONG",
        "formation_state": "DEVELOPING",
        "confidence": 89,
        "key_levels": {
            "level_high": 100,
            "level_low": 95,
            "trigger_level": 100,
            "invalidation_level": 94
        }
    }

    first = tracker.update("BTC/USDT", "15m", [pattern])
    second = tracker.update("BTC/USDT", "15m", [pattern])

    print("First scan:", len(first), "unique pattern")
    print("Second scan:", len(second), "unique pattern")
    print("Detection count:", second[0]["detections"])
