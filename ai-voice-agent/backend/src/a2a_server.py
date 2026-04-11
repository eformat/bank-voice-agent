"""A2A protocol adapter for the Fed Aura Capital agent.

Exposes the existing LangGraph banking agent as an A2A-compatible HTTP
endpoint so kagenti can discover and interact with it via the agent catalog.

Feature-flagged via KAGENTI_ENABLED env var — only started when enabled.
"""

import asyncio
import logging
import os
from typing import Any

import uvicorn
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.apps import A2AStarletteApplication
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
    Part,
    TaskState,
    TextPart,
    UnsupportedOperationError,
)
from a2a.utils import new_agent_text_message, new_task
from a2a.utils.errors import ServerError

from src.content_utils import normalize_content_to_text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Agent Card
# ---------------------------------------------------------------------------

def _build_agent_card(host: str = "0.0.0.0", port: int = 8080) -> AgentCard:
    return AgentCard(
        name="Fed Aura Capital Assistant",
        description=(
            "AI banking assistant for Fed Aura Capital. Handles credit card inquiries, "
            "loan applications, investment and savings advice, and credit score checks."
        ),
        url=os.getenv("AGENT_ENDPOINT", f"http://{host}:{port}").rstrip("/") + "/",
        version="1.0.0",
        default_input_modes=["text", "text/plain"],
        default_output_modes=["text", "text/plain"],
        capabilities=AgentCapabilities(streaming=True),
        skills=[
            AgentSkill(
                id="general_banking",
                name="General Banking",
                description="Route and answer general banking questions about Fed Aura Capital services",
                tags=["banking", "finance", "acme bank"],
                examples=["What services does Fed Aura Capital offer?"],
            ),
            AgentSkill(
                id="credit_cards",
                name="Credit Card Services",
                description="Help with credit card applications, comparisons, and inquiries",
                tags=["credit card", "rewards", "application"],
                examples=["I'd like to apply for a credit card"],
            ),
            AgentSkill(
                id="loans",
                name="Loan Services",
                description="Assist with loan applications, rates, and pre-qualification",
                tags=["loan", "mortgage", "personal loan", "auto loan"],
                examples=["What are your current mortgage rates?"],
            ),
            AgentSkill(
                id="investments",
                name="Investment & Savings",
                description="Provide investment and savings account guidance",
                tags=["investment", "savings", "retirement", "IRA", "401k"],
                examples=["I want to open a savings account"],
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Executor — bridges A2A requests to the LangGraph graph
# ---------------------------------------------------------------------------

class BankAgentExecutor(AgentExecutor):
    """Wraps the existing LangGraph banking agent for A2A protocol."""

    def __init__(self, graph):
        self._graph = graph

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        query = context.get_user_input()
        if not query:
            raise ServerError(error=UnsupportedOperationError())

        # Create or reuse task
        task = context.current_task
        if not task:
            task = new_task(context.message)
            event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)

        # Use context_id as LangGraph thread_id for multi-turn continuity
        config = {"configurable": {"thread_id": task.context_id}}

        # Check if we need to resume from a previous interrupt
        try:
            state = self._graph.get_state(config)
            has_interrupt = bool(state.values.get("__interrupt__"))
        except Exception:
            has_interrupt = False

        if has_interrupt:
            inputs: Any = Command(resume=query)
        else:
            inputs = {"messages": [HumanMessage(content=query)]}

        try:
            await updater.update_status(
                TaskState.working,
                new_agent_text_message(
                    "Processing your request...",
                    task.context_id,
                    task.id,
                ),
            )

            # Stream graph execution in a thread to avoid blocking
            def _invoke_with_spire():
                result = self._graph.invoke(inputs, config)
                try:
                    from ws_server import _mlflow_enabled, _spire_identity
                    if _mlflow_enabled:
                        import os
                        import mlflow
                        client = mlflow.MlflowClient()
                        experiment = client.get_experiment_by_name(
                            os.environ.get("MLFLOW_EXPERIMENT_NAME", "ai-voice-agent")
                        )
                        if experiment:
                            traces = client.search_traces(
                                experiment_ids=[experiment.experiment_id],
                                max_results=1,
                            )
                            if traces:
                                request_id = traces[0].info.request_id
                                if _spire_identity:
                                    for key, value in _spire_identity.items():
                                        client.set_trace_tag(request_id, key, value)
                                    logger.info(f"[spire] Tagged trace {request_id}")
                                # Link only the prompts that were actually used
                                try:
                                    from src.prompts import _PROMPT_REGISTRY, _mlflow_prompts_enabled
                                    if _mlflow_prompts_enabled:
                                        msg_names = {getattr(m, "name", None) for m in result.get("messages", [])}
                                        used_keys = ["supervisor"]
                                        if "credit_card_agent" in msg_names:
                                            used_keys.append("credit_card")
                                        if "loan_agent" in msg_names:
                                            used_keys.append("loan")
                                        if "investment_agent" in msg_names:
                                            used_keys.append("investment")
                                        prompt_versions = []
                                        for key in used_keys:
                                            pname = _PROMPT_REGISTRY[key][0]
                                            pv = mlflow.genai.load_prompt(
                                                f"prompts:/{pname}@production",
                                                allow_missing=True,
                                                cache_ttl_seconds=60,
                                            )
                                            if pv:
                                                prompt_versions.append(pv)
                                        if prompt_versions:
                                            client.link_prompt_versions_to_trace(
                                                prompt_versions=prompt_versions,
                                                trace_id=request_id,
                                            )
                                            logger.info(f"[prompts] Linked {len(prompt_versions)} prompts to trace {request_id}")
                                except Exception as exc:
                                    logger.error(f"[prompts] Failed to link prompts: {exc}")
                except Exception as exc:
                    logger.error(f"[spire] Failed to set trace tags: {exc}")
                return result

            result = await asyncio.to_thread(_invoke_with_spire)

            # Check for interrupts (agent asking for more info)
            interrupt_values = []
            for item in result.get("__interrupt__", []) or []:
                interrupt_values.append(getattr(item, "value", item))

            if interrupt_values:
                # Agent needs more input from user
                interrupt_data = interrupt_values[0]
                if isinstance(interrupt_data, dict):
                    prompt = normalize_content_to_text(
                        interrupt_data.get("prompt") or ""
                    )
                else:
                    prompt = str(interrupt_data)

                await updater.update_status(
                    TaskState.input_required,
                    new_agent_text_message(
                        prompt or "Could you provide more information?",
                        task.context_id,
                        task.id,
                    ),
                    final=True,
                )
                return

            # Extract final response text from messages
            response_text = self._extract_response(result)

            await updater.add_artifact(
                [Part(root=TextPart(text=response_text))],
                name="banking_response",
            )
            await updater.complete()

        except Exception as e:
            logger.error(f"Graph execution error: {e}")
            await updater.update_status(
                TaskState.failed,
                new_agent_text_message(
                    "An error occurred processing your request. Please try again.",
                    task.context_id,
                    task.id,
                ),
                final=True,
            )

    async def cancel(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        raise ServerError(error=UnsupportedOperationError())

    @staticmethod
    def _extract_response(result: dict) -> str:
        """Extract the last meaningful agent response from graph result."""
        for m in reversed(result.get("messages", []) or []):
            if isinstance(m, (ToolMessage,)):
                continue
            role = getattr(m, "name", None) or getattr(m, "type", "")
            if role == "human":
                continue
            content = normalize_content_to_text(getattr(m, "content", "") or "")
            if not content or content.startswith("Routing to"):
                continue
            return content
        return "I wasn't able to generate a response. Please try again."


# ---------------------------------------------------------------------------
# Server startup
# ---------------------------------------------------------------------------

async def run_a2a_server(graph, host: str = "0.0.0.0", port: int = 8080):
    """Start the A2A HTTP server as an async coroutine (non-blocking)."""
    agent_card = _build_agent_card(host, port)
    executor = BankAgentExecutor(graph)

    request_handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=InMemoryTaskStore(),
    )

    server = A2AStarletteApplication(
        agent_card=agent_card, http_handler=request_handler
    )
    app = server.build()

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
    )
    srv = uvicorn.Server(config)
    logger.info(f"A2A server listening on http://{host}:{port}")
    await srv.serve()
