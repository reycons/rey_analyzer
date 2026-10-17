"""rey_analyzer's approved implementation catalog, as the canonical Workflow binds to it.

The canonical Workflow (backlog 963) binds each step to the implementation its
application approves, read from the registration's ``approved_implementations``.
A published operation with no approved implementation stops any workflow that
names it from hydrating (backlog console.workflow_map).
"""

from __future__ import annotations

import inspect

from types import SimpleNamespace
from typing import Any

import pytest

from rey_analyzer import workflow
from rey_analyzer.registration import get_registration


def test_every_published_operation_has_an_approved_implementation() -> None:
    registration = get_registration()
    published = [operation["name"] for operation in registration["workflow_operations"]]
    approved = registration["approved_implementations"]

    assert sorted(approved) == sorted(published)


def test_each_implementation_takes_the_canonical_step() -> None:
    # Run.execute calls implementation(ctx, run_log, settings, run, step); the
    # legacy coordinator that called it without the step is retired (#1011).
    for name, implementation in get_registration()["approved_implementations"].items():
        parameters = list(inspect.signature(implementation).parameters.values())
        assert len(parameters) == 5, name
        assert parameters[-1].name == "step", name
        assert parameters[-1].default is inspect.Parameter.empty, name


def test_analysis_hands_its_handler_every_argument_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The wrapper called _process_analysis(ctx, config, run): one argument short.
    seen: list[Any] = []
    monkeypatch.setattr(workflow, "_process_analysis",
                        lambda *args: seen.append(args) or "result")
    ctx, run_log, config, run, step = (object(), object(), {"source": "s"},
                                       SimpleNamespace(), object())

    answer = get_registration()["approved_implementations"]["analysis"](
        ctx, run_log, config, run, step)

    assert answer == "result"
    assert seen == [(ctx, run_log, config, run, step)]


def test_analysis_takes_its_data_source_from_the_steps_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The data source is the process's configuration (#1043): asked of it, not of ctx."""
    asked: list[str] = []
    source = SimpleNamespace(name="proposals", analysis_config="infer")
    process = SimpleNamespace(data_source=lambda name: asked.append(name) or source)
    step = SimpleNamespace(process=process)
    received: list[Any] = []
    monkeypatch.setattr(workflow, "_resolve_analysis", lambda _ctx, name: f"analysis:{name}")
    monkeypatch.setattr(workflow, "run_source", lambda _ctx, _log, source_cfg, analysis_cfg,
                        **_kw: received.append((source_cfg, analysis_cfg)) or (1, 0, 0))
    ctx = SimpleNamespace()  # no data_sources: nothing is read from the context

    result = get_registration()["approved_implementations"]["analysis"](
        ctx, object(), {"source": "proposals"}, SimpleNamespace(metadata={}), step)

    assert asked == ["proposals"]
    assert received == [(source, "analysis:infer")]
    assert result.status == "ok"
