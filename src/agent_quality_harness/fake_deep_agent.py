from collections.abc import Sequence
from typing import Any
from uuid import uuid4

from deepagents import create_deep_agent
from fastapi import FastAPI
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import BaseModel, Field


class DeepAgentRequest(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)


class _DeterministicBindableModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "aqh-deterministic-deepagents-fixture"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "_DeterministicBindableModel":
        del tools, kwargs
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager, kwargs
        prompt = next(
            (
                str(message.content)
                for message in reversed(messages)
                if isinstance(message, HumanMessage)
            ),
            "ok",
        )
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=prompt))])


deep_agent = create_deep_agent(
    model=_DeterministicBindableModel(),
    name="agent-quality-harness-deepagents-fixture",
    system_prompt="Return the user request without adding unsupported claims.",
)


def create_deep_agent_target_app() -> FastAPI:
    app = FastAPI(title="Agent Quality Harness DeepAgents Target")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/invoke")
    async def invoke(payload: DeepAgentRequest) -> dict[str, Any]:
        run_id = str(uuid4())
        prompt = str(payload.input.get("prompt") or payload.input.get("text") or "ok")
        target_version = str(payload.context.get("target_version", "deepagents"))
        if target_version == "control":
            text = prompt
            harness = "plain-control"
            state_keys: list[str] = []
        else:
            state = await deep_agent.ainvoke(
                {"messages": [{"role": "user", "content": prompt}]}
            )
            text = str(state["messages"][-1].content)
            harness = "deepagents-0.7.6"
            state_keys = sorted(state)
        return {
            "run_id": run_id,
            "final_action": "answer",
            "output": {
                "text": text,
                "harness": harness,
                "state_keys": state_keys,
            },
            "events": [
                {"event_type": "run_started", "data": {"run_id": run_id}},
                {
                    "event_type": "run_completed",
                    "data": {"run_id": run_id, "harness": harness},
                },
            ],
        }

    @app.post("/invoke/{run_id}/cancel", status_code=202)
    async def cancel(run_id: str) -> dict[str, str]:
        return {"run_id": run_id, "status": "cancel_requested"}

    return app


app = create_deep_agent_target_app()
