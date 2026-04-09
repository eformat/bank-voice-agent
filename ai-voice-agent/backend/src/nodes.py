"""Node functions for supervisor and specialist agents."""

from __future__ import annotations

import json
import os
import threading
from typing import Annotated, Literal

from dotenv import load_dotenv
import httpx
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph.message import add_messages
from langgraph.types import Command, interrupt
from pydantic import BaseModel
from typing_extensions import TypedDict

from src.content_utils import normalize_content_to_text
from src.prompts import (
    CREDIT_CARD_AGENT_PROMPT,
    INVESTMENT_AND_SAVINGS_AGENT_PROMPT,
    LOAN_AGENT_PROMPT,
    SUPERVISOR_PROMPT,
)
from src.tools import (
    check_credit_score,
    get_service_type,
    log_inquiry,
    lookup_account,
)

load_dotenv()

MODEL_NAME = os.getenv("MODEL_NAME", "MODEL_NAME")
BASE_URL = os.getenv("BASE_URL", "BASE_URL")
API_KEY = os.getenv("API_KEY", "API_KEY")
GUARDRAILS_URL = os.getenv("GUARDRAILS_URL", "")
GUARDRAILS_TOKEN = os.getenv("GUARDRAILS_TOKEN", "")
NEMO_GUARDRAILS_URL = os.getenv("NEMO_GUARDRAILS_URL", "")
NEMO_GUARDRAILS_TOKEN = os.getenv("NEMO_GUARDRAILS_TOKEN", "")
CREDIT_CARD_TOOLS_MCP_URL = os.getenv("CREDIT_CARD_TOOLS_MCP_URL", "")

# ============================================================
# Configuration
# ============================================================
TEMPERATURE = 0.2
MAX_RETRIES = 2
TIMEOUT = 30

_LLM_COMMON = dict(
    streaming=True,
    model=MODEL_NAME,
    temperature=TEMPERATURE,
    max_retries=MAX_RETRIES,
    timeout=TIMEOUT,
    api_key=API_KEY,
)
_EXTRA_BODY = {"chat_template_kwargs": {"enable_thinking": False}}

llm = ChatOpenAI(base_url=BASE_URL, extra_body=_EXTRA_BODY, **_LLM_COMMON)

# ============================================================
# Guardrails detector configurations
# ============================================================
GUARDRAILS_DETECTORS = {
    "input": {
        "gibberish-detector": {},
        "ibm-hate-and-profanity-detector": {},
        "prompt-injection-detector": {},
        "built-in-detector": {},
    },
    "output": {
        "gibberish-detector": {},
        "ibm-hate-and-profanity-detector": {},
        "built-in-detector": {},
    },
}

# Input-only screening for the user's latest message before supervisor routing.
GUARDRAILS_DETECTORS_INPUT_ONLY = {
    "input": {
        "gibberish-detector": {},
        "ibm-hate-and-profanity-detector": {},
        "prompt-injection-detector": {},
        "built-in-detector": {},
    },
    "output": {},
}

# Output screening for agent responses — uses input detectors on the
# agent's response text (sent as a single user message). We scan the
# text as "input" because the orchestrator scans the LLM's actual
# response for output detectors, not pre-existing text we provide.
# Gibberish detector excluded: agent responses with account details, lists,
# and summaries frequently trigger false positives.
GUARDRAILS_DETECTORS_OUTPUT_SCREEN = {
    "input": {
        "ibm-hate-and-profanity-detector": {},
        "built-in-detector": {},
    },
    "output": {},
}

# ============================================================
# Guardrails LLM instances (ChatOpenAI pointed at orchestrator)
# ============================================================
# Orchestrator does not support streaming (returns empty response)
# or "tool" role messages (422 error), so guardrails LLMs are
# non-streaming and agent nodes use regular agents with tools.

_guardrails_tls = threading.local()


def _log_guardrails_response(response: httpx.Response) -> None:
    """httpx event hook — log and capture detections/warnings from orchestrator."""
    response.read()
    try:
        data = response.json()
        detections = data.get("detections")
        warnings = data.get("warnings")
        # Store for MLFlow tracing
        _guardrails_tls.last_detections = detections
        _guardrails_tls.last_warnings = warnings
        if detections:
            print(f"[guardrails] Detections: {json.dumps(detections, indent=2)}", flush=True)
        if warnings:
            print(f"[guardrails] Warnings: {json.dumps(warnings, indent=2)}", flush=True)
    except Exception:
        pass


def _trace_guardrails(label: str) -> None:
    """Log last guardrails detections/warnings to MLFlow active span."""
    detections = getattr(_guardrails_tls, "last_detections", None)
    warnings = getattr(_guardrails_tls, "last_warnings", None)
    _guardrails_tls.last_detections = None
    _guardrails_tls.last_warnings = None
    if not detections and not warnings:
        return
    try:
        import mlflow

        span = mlflow.get_current_active_span()
        if span:
            if detections:
                span.set_attribute(f"guardrails.{label}.detections", json.dumps(detections))
            if warnings:
                span.set_attribute(f"guardrails.{label}.warnings", json.dumps(warnings))
    except Exception:
        pass


_guardrails_http_client = httpx.Client(event_hooks={"response": [_log_guardrails_response]})
_GUARDRAILS_LLM_COMMON = {**_LLM_COMMON, "streaming": False, "http_client": _guardrails_http_client}
if GUARDRAILS_TOKEN:
    _GUARDRAILS_LLM_COMMON["api_key"] = GUARDRAILS_TOKEN

if GUARDRAILS_URL:
    guardrails_llm = ChatOpenAI(
        base_url=GUARDRAILS_URL,
        extra_body={**_EXTRA_BODY, "detectors": GUARDRAILS_DETECTORS},
        **_GUARDRAILS_LLM_COMMON,
    )
    guardrails_llm_input_only = ChatOpenAI(
        base_url=GUARDRAILS_URL,
        extra_body={**_EXTRA_BODY, "detectors": GUARDRAILS_DETECTORS_INPUT_ONLY},
        **_GUARDRAILS_LLM_COMMON,
    )
    guardrails_llm_output_screen = ChatOpenAI(
        base_url=GUARDRAILS_URL,
        extra_body={**_EXTRA_BODY, "detectors": GUARDRAILS_DETECTORS_OUTPUT_SCREEN},
        **_GUARDRAILS_LLM_COMMON,
    )

# ============================================================
# MCP credit-card-tools (optional — falls back to local tool)
# ============================================================
if CREDIT_CARD_TOOLS_MCP_URL:
    import asyncio
    from langchain_mcp_adapters.client import MultiServerMCPClient

    async def _load_mcp_tools():
        client = MultiServerMCPClient(
            {
                "credit-card-tools": {
                    "url": CREDIT_CARD_TOOLS_MCP_URL,
                    "transport": "streamable_http",
                }
            }
        )
        return await client.get_tools()

    _mcp_tools = asyncio.get_event_loop().run_until_complete(_load_mcp_tools())
    print(
        f"[mcp] Loaded {len(_mcp_tools)} tools from {CREDIT_CARD_TOOLS_MCP_URL}: "
        f"{[t.name for t in _mcp_tools]}",
        flush=True,
    )
    for t in _mcp_tools:
        schema = t.args_schema
        if hasattr(schema, 'schema'):
            schema = schema.schema()
        print(f"[mcp]   {t.name}: {t.description[:80]}... args={schema}", flush=True)

    # MCP tools are async-only (StructuredTool with only _arun, no _run).
    # LangGraph's create_react_agent invokes tools synchronously by default.
    # Wrap each MCP tool with a sync-compatible version.
    from langchain_core.tools import StructuredTool as _StructuredTool

    def _make_sync_wrapper(async_tool):
        """Create a sync-compatible tool that delegates to the async MCP tool."""
        def _sync_run(**kwargs):
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(async_tool.ainvoke(kwargs))
            finally:
                loop.close()

        async def _async_run(**kwargs):
            return await async_tool.ainvoke(kwargs)

        return _StructuredTool(
            name=async_tool.name,
            description=async_tool.description,
            args_schema=async_tool.args_schema,
            func=_sync_run,
            coroutine=_async_run,
        )

    _credit_score_tool = [_make_sync_wrapper(t) for t in _mcp_tools]
else:
    _credit_score_tool = [check_credit_score]

# ============================================================
# Agent Creation
# ============================================================
supervisor_agent = create_react_agent(model=llm, tools=[])
loan_agent = create_react_agent(model=llm, tools=[log_inquiry] + _credit_score_tool)
credit_card_agent = create_react_agent(model=llm, tools=[get_service_type] + _credit_score_tool)
investment_agent = create_react_agent(model=llm, tools=[lookup_account] + _credit_score_tool)

# Guardrails agents reuse the regular agents (with tools, regular LLM)
# because the orchestrator cannot handle "tool" role messages in the
# react agent loop. User input is already pre-screened before routing.
if GUARDRAILS_URL:
    g_supervisor_agent = create_react_agent(model=guardrails_llm, tools=[])

# ============================================================
# NeMo Guardrails LLM instance
# ============================================================
if NEMO_GUARDRAILS_URL:
    _nemo_kwargs = {**_LLM_COMMON, "streaming": False}
    if NEMO_GUARDRAILS_TOKEN:
        _nemo_kwargs["api_key"] = NEMO_GUARDRAILS_TOKEN
    nemo_llm = ChatOpenAI(
        base_url=NEMO_GUARDRAILS_URL,
        extra_body=_EXTRA_BODY,
        **_nemo_kwargs,
    )
    nemo_supervisor_agent = create_react_agent(model=nemo_llm, tools=[])

_NEMO_BLOCKED_PATTERNS = [
    "I'm sorry, I can't respond to that",
    "I can't help with that type of request",
]


def _is_nemo_blocked(text: str) -> bool:
    """Check if NeMo returned a canned blocked response."""
    return any(p in text for p in _NEMO_BLOCKED_PATTERNS)


def _screen_nemo_input(user_text: str) -> None:
    """Screen user input through NeMo guardrails. Raises if blocked."""
    result = nemo_llm.invoke([HumanMessage(content=user_text)])
    response_text = normalize_content_to_text(result.content)
    if _is_nemo_blocked(response_text):
        raise ValueError(f"[nemo] Input blocked: {response_text}")


def _screen_nemo_output(agent_text: str) -> None:
    """Screen agent output through NeMo guardrails. Raises if blocked."""
    if not agent_text:
        return
    result = nemo_llm.invoke([HumanMessage(content=agent_text)])
    response_text = normalize_content_to_text(result.content)
    if _is_nemo_blocked(response_text):
        raise ValueError(f"[nemo] Output blocked: {response_text}")


# ============================================================
# State and Models
# ============================================================
class SupervisorState(TypedDict, total=False):
    """State shared across all agents in the graph."""

    messages: Annotated[
        list, add_messages
    ]  # Conversation history (uses add_messages reducer)
    service_type: Annotated[str, "The type of banking service the user is inquiring about."]


class SupervisorDecision(BaseModel):
    """Structured output from supervisor for routing decisions."""

    next_agent: Literal["loan_agent", "credit_card_agent", "investment_agent", "none"]
    service_type: Annotated[str, "The type of banking service the user is inquiring about."]
    response: str = ""  # Direct response if no routing needed


# ============================================================
# Helper Functions
# ============================================================
def _invoke_agent(agent, prompt: str, messages: list, agent_name: str):
    """Helper to invoke an agent and return formatted response.

    This consolidates the common pattern of:
    1. Adding system prompt to messages
    2. Invoking the agent subgraph
    3. Extracting and naming the response message
    """
    agent_input = {"messages": [SystemMessage(content=prompt)] + messages}
    agent_result = agent.invoke(agent_input)
    response_message = agent_result["messages"][-1]
    response_message.name = agent_name
    return response_message


def supervisor_command_node(state: SupervisorState) -> Command:
    """Supervisor for Command routing - uses structured output."""
    decision: SupervisorDecision = llm.with_structured_output(
        SupervisorDecision
    ).invoke([SystemMessage(content=SUPERVISOR_PROMPT)] + state["messages"])

    if decision.next_agent == "none":
        response = _invoke_agent(
            supervisor_agent, SUPERVISOR_PROMPT, state["messages"], "supervisor"
        )
        return Command(goto="__end__", update={"messages": [response]})

    update = {
        "messages": [
            AIMessage(content=f"Routing to {decision.next_agent}", name="supervisor")
        ]
    }

    if decision.service_type != "":
        update["service_type"] = decision.service_type
        print(f"Supervisor: Extracted service_type='{decision.service_type}'")

    print(f"Supervisor: Routing to {decision.next_agent}")
    return Command[str](goto=decision.next_agent, update=update)


def credit_card_agent_node(state: SupervisorState) -> Command:
    """Credit card agent - handles credit card queries."""
    print("Credit Card Agent")
    response = _invoke_agent(
        credit_card_agent, CREDIT_CARD_AGENT_PROMPT, state["messages"], "credit_card_agent",
    )
    print("Credit Card Agent: routed to wait_for_user_after_credit_card")
    return Command[str](
        goto="wait_for_user_after_credit_card", update={"messages": [response]}
    )


def loan_agent_node(state: SupervisorState) -> Command:
    """Loan agent - handles loan queries."""
    print("Loan Agent")
    response = _invoke_agent(
        loan_agent, LOAN_AGENT_PROMPT, state["messages"], "loan_agent",
    )
    print("Loan Agent: routed to wait_for_user_after_loan")
    return Command[str](
        goto="wait_for_user_after_loan", update={"messages": [response]}
    )


def investment_agent_node(state: SupervisorState) -> Command:
    """Investment agent - handles investment and savings queries."""
    print("Investment Agent")
    response = _invoke_agent(
        investment_agent, INVESTMENT_AND_SAVINGS_AGENT_PROMPT, state["messages"], "investment_agent",
    )
    print("Investment Agent: routed to wait_for_user_after_investment")
    return Command[str](
        goto="wait_for_user_after_investment", update={"messages": [response]}
    )


def _interrupt_payload(state: SupervisorState, agent: str) -> dict:
    """Create a JSON-serializable interrupt payload for the UI."""
    last = state.get("messages", [])[-1] if state.get("messages") else None
    return {
        "agent": agent,
        "prompt": normalize_content_to_text(getattr(last, "content", ""))
        if last
        else "",
        "service_type": state.get("service_type", ""),
    }


def wait_for_user_after_credit_card(state: SupervisorState) -> Command:
    """Interrupt after credit card agent, waiting for user's next input."""
    user_text = interrupt(_interrupt_payload(state, "credit_card_agent"))
    return Command(
        goto="supervisor", update={"messages": [HumanMessage(content=str(user_text))]}
    )


def wait_for_user_after_loan(state: SupervisorState) -> Command:
    """Interrupt after loan agent, waiting for user's next input."""
    user_text = interrupt(_interrupt_payload(state, "loan_agent"))
    return Command(
        goto="supervisor", update={"messages": [HumanMessage(content=str(user_text))]}
    )


def wait_for_user_after_investment(state: SupervisorState) -> Command:
    """Interrupt after investment agent, waiting for user's next input."""
    user_text = interrupt(_interrupt_payload(state, "investment_agent"))
    return Command(
        goto="supervisor", update={"messages": [HumanMessage(content=str(user_text))]}
    )


GUARDRAILS_BLOCKED_MSG = "Unsuitable content detected, please rephrase your message."


def _guardrails_blocked_command() -> Command:
    """Return a Command that interrupts with the guardrails blocked message."""
    print("[guardrails] Content blocked by guardrails", flush=True)
    return Command(
        goto="wait_for_user_after_guardrails",
        update={"messages": [AIMessage(content=GUARDRAILS_BLOCKED_MSG, name="guardrails")]},
    )


def wait_for_user_after_guardrails(state: SupervisorState) -> Command:
    """Interrupt after guardrails block, waiting for user's next input."""
    user_text = interrupt(_interrupt_payload(state, "guardrails"))
    return Command(
        goto="supervisor", update={"messages": [HumanMessage(content=str(user_text))]}
    )


def _screen_user_input(messages: list) -> None:
    """Screen the user's latest message through guardrails input detectors.

    Sends only the latest user message (not full history) to avoid false
    positives from internal prompts. If blocked, the orchestrator returns
    empty choices and langchain raises an error.
    """
    last_user_msg = None
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            last_user_msg = m.content
            break
    if not last_user_msg:
        return

    guardrails_llm_input_only.invoke([HumanMessage(content=last_user_msg)])
    _trace_guardrails("input_screen")


def _screen_agent_output(response_text: str) -> None:
    """Screen an agent's response through guardrails detectors.

    Sends the agent's response as a single user message and scans it
    through input detectors (HAP, built-in). We use input detectors
    because the orchestrator's output detectors scan the LLM's live
    response, not pre-existing text we provide. Gibberish detector is
    excluded as agent responses with account details and lists trigger
    false positives.
    """
    if not response_text:
        return

    guardrails_llm_output_screen.invoke([HumanMessage(content=response_text)])
    _trace_guardrails("output_screen")


def make_guardrails_nodes() -> dict:
    """Create node functions that route LLM calls through the guardrails orchestrator."""

    def g_supervisor_command_node(state: SupervisorState) -> Command:
        # Pre-screen user input before routing.
        try:
            _screen_user_input(state["messages"])
        except Exception as exc:
            _trace_guardrails("input_screen")
            print(f"[guardrails] User input blocked: {exc}", flush=True)
            return _guardrails_blocked_command()

        # Routing uses regular LLM (structured output, no guardrails).
        decision: SupervisorDecision = llm.with_structured_output(
            SupervisorDecision
        ).invoke([SystemMessage(content=SUPERVISOR_PROMPT)] + state["messages"])

        if decision.next_agent == "none":
            try:
                response = _invoke_agent(
                    g_supervisor_agent, SUPERVISOR_PROMPT, state["messages"], "supervisor"
                )
            except Exception as exc:
                _trace_guardrails("supervisor_response")
                print(f"[guardrails] Supervisor response blocked: {exc}", flush=True)
                return _guardrails_blocked_command()
            _trace_guardrails("supervisor_response")
            return Command(goto="__end__", update={"messages": [response]})

        update = {
            "messages": [
                AIMessage(content=f"Routing to {decision.next_agent}", name="supervisor")
            ]
        }
        if decision.service_type != "":
            update["service_type"] = decision.service_type
            print(f"Supervisor [guardrails]: Extracted service_type='{decision.service_type}'")
        print(f"Supervisor [guardrails]: Routing to {decision.next_agent}")
        return Command[str](goto=decision.next_agent, update=update)

    # Agent nodes use regular agents (with tools, regular LLM) because
    # the orchestrator rejects "tool" role messages (422: Last message
    # role must be user, assistant, or system). User input is already
    # pre-screened before routing.

    def g_credit_card_agent_node(state: SupervisorState) -> Command:
        print("Credit Card Agent [guardrails]")
        response = _invoke_agent(
            credit_card_agent, CREDIT_CARD_AGENT_PROMPT, state["messages"], "credit_card_agent"
        )
        try:
            _screen_agent_output(normalize_content_to_text(response.content))
        except Exception as exc:
            _trace_guardrails("output_screen")
            print(f"[guardrails] Credit card agent output blocked: {exc}", flush=True)
            return _guardrails_blocked_command()
        return Command[str](goto="wait_for_user_after_credit_card", update={"messages": [response]})

    def g_loan_agent_node(state: SupervisorState) -> Command:
        print("Loan Agent [guardrails]")
        response = _invoke_agent(
            loan_agent, LOAN_AGENT_PROMPT, state["messages"], "loan_agent"
        )
        try:
            _screen_agent_output(normalize_content_to_text(response.content))
        except Exception as exc:
            _trace_guardrails("output_screen")
            print(f"[guardrails] Loan agent output blocked: {exc}", flush=True)
            return _guardrails_blocked_command()
        return Command[str](goto="wait_for_user_after_loan", update={"messages": [response]})

    def g_investment_agent_node(state: SupervisorState) -> Command:
        print("Investment Agent [guardrails]")
        response = _invoke_agent(
            investment_agent, INVESTMENT_AND_SAVINGS_AGENT_PROMPT, state["messages"], "investment_agent"
        )
        try:
            _screen_agent_output(normalize_content_to_text(response.content))
        except Exception as exc:
            _trace_guardrails("output_screen")
            print(f"[guardrails] Investment agent output blocked: {exc}", flush=True)
            return _guardrails_blocked_command()
        return Command[str](goto="wait_for_user_after_investment", update={"messages": [response]})

    return {
        "supervisor": g_supervisor_command_node,
        "loan_agent": g_loan_agent_node,
        "credit_card_agent": g_credit_card_agent_node,
        "investment_agent": g_investment_agent_node,
    }


def make_nemo_guardrails_nodes() -> dict:
    """Create node functions that route through NeMo guardrails."""

    def n_supervisor_command_node(state: SupervisorState) -> Command:
        # Pre-screen user input through NeMo.
        last_user_msg = None
        for m in reversed(state["messages"]):
            if isinstance(m, HumanMessage):
                last_user_msg = m.content
                break
        if last_user_msg:
            try:
                _screen_nemo_input(last_user_msg)
            except Exception as exc:
                print(f"[nemo] User input blocked: {exc}", flush=True)
                return _guardrails_blocked_command()

        # Routing uses regular LLM.
        decision: SupervisorDecision = llm.with_structured_output(
            SupervisorDecision
        ).invoke([SystemMessage(content=SUPERVISOR_PROMPT)] + state["messages"])

        if decision.next_agent == "none":
            response = _invoke_agent(
                nemo_supervisor_agent, SUPERVISOR_PROMPT, state["messages"], "supervisor"
            )
            response_text = normalize_content_to_text(response.content)
            if _is_nemo_blocked(response_text):
                print("[nemo] Supervisor response blocked", flush=True)
                return _guardrails_blocked_command()
            return Command(goto="__end__", update={"messages": [response]})

        update = {
            "messages": [
                AIMessage(content=f"Routing to {decision.next_agent}", name="supervisor")
            ]
        }
        if decision.service_type != "":
            update["service_type"] = decision.service_type
            print(f"Supervisor [nemo]: Extracted service_type='{decision.service_type}'")
        print(f"Supervisor [nemo]: Routing to {decision.next_agent}")
        return Command[str](goto=decision.next_agent, update=update)

    def n_credit_card_agent_node(state: SupervisorState) -> Command:
        print("Credit Card Agent [nemo]")
        response = _invoke_agent(credit_card_agent, CREDIT_CARD_AGENT_PROMPT, state["messages"], "credit_card_agent")
        try:
            _screen_nemo_output(normalize_content_to_text(response.content))
        except Exception as exc:
            print(f"[nemo] Credit card agent output blocked: {exc}", flush=True)
            return _guardrails_blocked_command()
        return Command[str](goto="wait_for_user_after_credit_card", update={"messages": [response]})

    def n_loan_agent_node(state: SupervisorState) -> Command:
        print("Loan Agent [nemo]")
        response = _invoke_agent(loan_agent, LOAN_AGENT_PROMPT, state["messages"], "loan_agent")
        try:
            _screen_nemo_output(normalize_content_to_text(response.content))
        except Exception as exc:
            print(f"[nemo] Loan agent output blocked: {exc}", flush=True)
            return _guardrails_blocked_command()
        return Command[str](goto="wait_for_user_after_loan", update={"messages": [response]})

    def n_investment_agent_node(state: SupervisorState) -> Command:
        print("Investment Agent [nemo]")
        response = _invoke_agent(investment_agent, INVESTMENT_AND_SAVINGS_AGENT_PROMPT, state["messages"], "investment_agent")
        try:
            _screen_nemo_output(normalize_content_to_text(response.content))
        except Exception as exc:
            print(f"[nemo] Investment agent output blocked: {exc}", flush=True)
            return _guardrails_blocked_command()
        return Command[str](goto="wait_for_user_after_investment", update={"messages": [response]})

    return {
        "supervisor": n_supervisor_command_node,
        "loan_agent": n_loan_agent_node,
        "credit_card_agent": n_credit_card_agent_node,
        "investment_agent": n_investment_agent_node,
    }


def make_both_guardrails_nodes() -> dict:
    """Create node functions that layer both FMS and NeMo guardrails."""

    def b_supervisor_command_node(state: SupervisorState) -> Command:
        # FMS input screening.
        try:
            _screen_user_input(state["messages"])
        except Exception as exc:
            _trace_guardrails("input_screen")
            print(f"[guardrails/both] FMS input blocked: {exc}", flush=True)
            return _guardrails_blocked_command()

        # NeMo input screening.
        last_user_msg = None
        for m in reversed(state["messages"]):
            if isinstance(m, HumanMessage):
                last_user_msg = m.content
                break
        if last_user_msg:
            try:
                _screen_nemo_input(last_user_msg)
            except Exception as exc:
                print(f"[guardrails/both] NeMo input blocked: {exc}", flush=True)
                return _guardrails_blocked_command()

        # Routing uses regular LLM.
        decision: SupervisorDecision = llm.with_structured_output(
            SupervisorDecision
        ).invoke([SystemMessage(content=SUPERVISOR_PROMPT)] + state["messages"])

        if decision.next_agent == "none":
            # Route through FMS guardrails LLM for direct response.
            try:
                response = _invoke_agent(
                    g_supervisor_agent, SUPERVISOR_PROMPT, state["messages"], "supervisor"
                )
            except Exception as exc:
                _trace_guardrails("supervisor_response")
                print(f"[guardrails/both] FMS supervisor response blocked: {exc}", flush=True)
                return _guardrails_blocked_command()
            _trace_guardrails("supervisor_response")
            return Command(goto="__end__", update={"messages": [response]})

        update = {
            "messages": [
                AIMessage(content=f"Routing to {decision.next_agent}", name="supervisor")
            ]
        }
        if decision.service_type != "":
            update["service_type"] = decision.service_type
            print(f"Supervisor [both]: Extracted service_type='{decision.service_type}'")
        print(f"Supervisor [both]: Routing to {decision.next_agent}")
        return Command[str](goto=decision.next_agent, update=update)

    def b_credit_card_agent_node(state: SupervisorState) -> Command:
        print("Credit Card Agent [both]")
        response = _invoke_agent(credit_card_agent, CREDIT_CARD_AGENT_PROMPT, state["messages"], "credit_card_agent")
        response_text = normalize_content_to_text(response.content)
        try:
            _screen_agent_output(response_text)
        except Exception as exc:
            _trace_guardrails("output_screen")
            print(f"[guardrails/both] FMS credit card output blocked: {exc}", flush=True)
            return _guardrails_blocked_command()
        try:
            _screen_nemo_output(response_text)
        except Exception as exc:
            print(f"[guardrails/both] NeMo credit card output blocked: {exc}", flush=True)
            return _guardrails_blocked_command()
        return Command[str](goto="wait_for_user_after_credit_card", update={"messages": [response]})

    def b_loan_agent_node(state: SupervisorState) -> Command:
        print("Loan Agent [both]")
        response = _invoke_agent(loan_agent, LOAN_AGENT_PROMPT, state["messages"], "loan_agent")
        response_text = normalize_content_to_text(response.content)
        try:
            _screen_agent_output(response_text)
        except Exception as exc:
            _trace_guardrails("output_screen")
            print(f"[guardrails/both] FMS loan output blocked: {exc}", flush=True)
            return _guardrails_blocked_command()
        try:
            _screen_nemo_output(response_text)
        except Exception as exc:
            print(f"[guardrails/both] NeMo loan output blocked: {exc}", flush=True)
            return _guardrails_blocked_command()
        return Command[str](goto="wait_for_user_after_loan", update={"messages": [response]})

    def b_investment_agent_node(state: SupervisorState) -> Command:
        print("Investment Agent [both]")
        response = _invoke_agent(investment_agent, INVESTMENT_AND_SAVINGS_AGENT_PROMPT, state["messages"], "investment_agent")
        response_text = normalize_content_to_text(response.content)
        try:
            _screen_agent_output(response_text)
        except Exception as exc:
            _trace_guardrails("output_screen")
            print(f"[guardrails/both] FMS investment output blocked: {exc}", flush=True)
            return _guardrails_blocked_command()
        try:
            _screen_nemo_output(response_text)
        except Exception as exc:
            print(f"[guardrails/both] NeMo investment output blocked: {exc}", flush=True)
            return _guardrails_blocked_command()
        return Command[str](goto="wait_for_user_after_investment", update={"messages": [response]})

    return {
        "supervisor": b_supervisor_command_node,
        "loan_agent": b_loan_agent_node,
        "credit_card_agent": b_credit_card_agent_node,
        "investment_agent": b_investment_agent_node,
    }
