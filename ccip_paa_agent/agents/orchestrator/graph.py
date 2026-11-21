
import logging
import subprocess
import sys
from pathlib import Path

from langgraph.graph import StateGraph, START, END
from agents.orchestrator.state import CryptoGuardianState

PROJECT_ROOT = Path(__file__).resolve().parents[2]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger("CryptoGuardian")

# Existing agents — no new agents created.
AGENTS = {
    "market_results": "agents.market_scanner.agent",
    "news_results": "agents.news_agent.agent",
    "pattern_results": "agents.pattern_decision_agent.agent",
}

processes = {}


def launch_agent(state: CryptoGuardianState, result_key: str):
    """Launch an existing agent as a background service."""

    module = AGENTS[result_key]

    try:
        process = processes.get(result_key)

        if process and process.poll() is None:
            return {
                result_key: {
                    "status": "already_running",
                    "pid": process.pid,
                }
            }

        process = subprocess.Popen(
            [sys.executable, "-m", module],
            cwd=str(PROJECT_ROOT),
            start_new_session=True,
        )

        processes[result_key] = process

        logger.info("%s started | PID %s", module, process.pid)

        return {
            result_key: {
                "status": "started",
                "pid": process.pid,
            }
        }

    except Exception as exc:
        logger.exception("Failed to launch %s", module)

        return {
            result_key: {
                "status": "failed",
                "error": str(exc),
            }
        }


def market_scanner_node(state: CryptoGuardianState):
    return launch_agent(state, "market_results")


def news_agent_node(state: CryptoGuardianState):
    return launch_agent(state, "news_results")


def pattern_decision_node(state: CryptoGuardianState):
    return launch_agent(state, "pattern_results")


def coordinator_node(state: CryptoGuardianState):
    report = {
        "market_scanner": state.get("market_results", {}),
        "news_agent": state.get("news_results", {}),
        "pattern_decision": state.get("pattern_results", {}),
    }

    logger.info("All three agent services have been launched.")

    for name, result in report.items():
        logger.info("%s: %s", name, result)

    return {"final_report": report}


# LangGraph workflow
builder = StateGraph(CryptoGuardianState)

builder.add_node("market_scanner", market_scanner_node)
builder.add_node("news_agent", news_agent_node)
builder.add_node("pattern_decision", pattern_decision_node)
builder.add_node("coordinator", coordinator_node)

# Parallel execution
builder.add_edge(START, "market_scanner")
builder.add_edge(START, "news_agent")
builder.add_edge(START, "pattern_decision")

# Join all three agents
builder.add_edge(
    ["market_scanner", "news_agent", "pattern_decision"],
    "coordinator",
)

builder.add_edge("coordinator", END)

crypto_guardian_graph = builder.compile()


def run_cryptoguardian():
    return crypto_guardian_graph.invoke({})


if __name__ == "__main__":
    result = run_cryptoguardian()

    print("\n========== CRYPTOGUARDIAN ==========")
    print(result["final_report"])
