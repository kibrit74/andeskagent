from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


WorkflowContext = dict[str, Any]
WorkflowRunner = Callable[[WorkflowContext], dict[str, Any] | None]
WorkflowVerifier = Callable[[WorkflowContext, dict[str, Any] | None], bool]


@dataclass(slots=True)
class WorkflowStep:
    id: str
    title: str
    run: WorkflowRunner
    verify: WorkflowVerifier | None = None
    continue_on_error: bool = False


@dataclass(slots=True)
class WorkflowExecution:
    summary: str
    steps: list[dict[str, Any]] = field(default_factory=list)
    context: WorkflowContext = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return bool(self.steps) and all(step.get("status") in {"success", "skipped"} for step in self.steps)


def execute_workflow(*, summary: str, steps: list[WorkflowStep], initial_context: WorkflowContext | None = None) -> WorkflowExecution:
    context: WorkflowContext = dict(initial_context or {})
    execution_steps: list[dict[str, Any]] = []

    for step in steps:
        try:
            result = step.run(context) or {}
            if step.verify and not step.verify(context, result):
                raise RuntimeError(f"Verification failed for step: {step.id}")

            if isinstance(result, dict):
                context.update(result)

            execution_steps.append(
                {
                    "id": step.id,
                    "title": step.title,
                    "status": "success",
                    "result": result,
                }
            )
        except Exception as exc:
            execution_steps.append(
                {
                    "id": step.id,
                    "title": step.title,
                    "status": "error",
                    "error": str(exc),
                }
            )
            if not step.continue_on_error:
                break

    return WorkflowExecution(summary=summary, steps=execution_steps, context=context)
