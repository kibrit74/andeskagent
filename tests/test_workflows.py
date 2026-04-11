from __future__ import annotations

from core.workflows import WorkflowStep, execute_workflow


def test_execute_workflow_runs_steps_in_order() -> None:
    execution = execute_workflow(
        summary="demo",
        initial_context={"count": 1},
        steps=[
            WorkflowStep(
                id="step1",
                title="ilk adim",
                run=lambda context: {"count": int(context["count"]) + 1},
                verify=lambda context, result: result is not None and result["count"] == 2,
            ),
            WorkflowStep(
                id="step2",
                title="ikinci adim",
                run=lambda context: {"final": int(context["count"]) * 2},
                verify=lambda context, result: result is not None and result["final"] == 4,
            ),
        ],
    )

    assert execution.success is True
    assert len(execution.steps) == 2
    assert execution.context["count"] == 2
    assert execution.context["final"] == 4


def test_execute_workflow_stops_on_error() -> None:
    execution = execute_workflow(
        summary="demo",
        steps=[
            WorkflowStep(
                id="step1",
                title="broken",
                run=lambda context: (_ for _ in ()).throw(RuntimeError("boom")),
            ),
            WorkflowStep(
                id="step2",
                title="skipped",
                run=lambda context: {"ok": True},
            ),
        ],
    )

    assert execution.success is False
    assert len(execution.steps) == 1
    assert execution.steps[0]["status"] == "error"
    assert execution.steps[0]["error"] == "boom"
