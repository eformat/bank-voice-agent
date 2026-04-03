"""Graph construction shared between CLI and web server."""

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import START, StateGraph

from src.nodes import (
    SupervisorState,
    credit_card_agent_node,
    investment_agent_node,
    loan_agent_node,
    make_both_guardrails_nodes,
    make_guardrails_nodes,
    make_nemo_guardrails_nodes,
    supervisor_command_node,
    wait_for_user_after_credit_card,
    wait_for_user_after_guardrails,
    wait_for_user_after_investment,
    wait_for_user_after_loan,
)


def build_graph(mode: str = "none"):
    """Compile and return the LangGraph instance (with checkpointer for interrupts)."""
    graph = StateGraph(SupervisorState)

    if mode == "fms":
        nodes = make_guardrails_nodes()
    elif mode == "nemo":
        nodes = make_nemo_guardrails_nodes()
    elif mode == "both":
        nodes = make_both_guardrails_nodes()
    else:
        nodes = None

    if nodes:
        graph.add_node("supervisor", nodes["supervisor"])
        graph.add_node("loan_agent", nodes["loan_agent"])
        graph.add_node("credit_card_agent", nodes["credit_card_agent"])
        graph.add_node("investment_agent", nodes["investment_agent"])
    else:
        graph.add_node("supervisor", supervisor_command_node)
        graph.add_node("loan_agent", loan_agent_node)
        graph.add_node("credit_card_agent", credit_card_agent_node)
        graph.add_node("investment_agent", investment_agent_node)

    # Interrupt nodes (these don't use the LLM, so no guardrails variant needed)
    graph.add_node("wait_for_user_after_credit_card", wait_for_user_after_credit_card)
    graph.add_node("wait_for_user_after_loan", wait_for_user_after_loan)
    graph.add_node("wait_for_user_after_investment", wait_for_user_after_investment)
    graph.add_node("wait_for_user_after_guardrails", wait_for_user_after_guardrails)

    graph.add_edge(START, "supervisor")
    return graph.compile(checkpointer=MemorySaver())
