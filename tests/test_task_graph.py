from __future__ import annotations

import pytest

from core.task_graph import TaskGraph, TaskGraphError, TaskStatus


def test_linear_graph_exposes_only_root_as_ready():
    graph = TaskGraph(plan_revision=3)
    graph.add_task("research", "inspect repository", role="research")
    graph.add_task("review", "review findings", depends_on=["research"], role="review")
    graph.add_task("implement", "apply approved change", depends_on=["review"], role="implement")

    assert [node.task_id for node in graph.ready_tasks()] == ["research"]
    assert graph.get_task("review").status == TaskStatus.PENDING


def test_completion_unlocks_dependents_and_requires_evidence():
    graph = TaskGraph(plan_revision=1)
    graph.add_task("a", "first")
    graph.add_task("b", "second", depends_on=["a"])

    graph.mark_running("a")
    with pytest.raises(TaskGraphError, match="evidence"):
        graph.mark_completed("a", evidence_ids=[])

    graph.mark_completed("a", evidence_ids=["ev-1"])
    assert graph.get_task("a").status == TaskStatus.COMPLETED
    assert [node.task_id for node in graph.ready_tasks()] == ["b"]
    assert graph.get_task("a").events[-1].evidence_ids == ("ev-1",)


def test_failure_blocks_transitive_dependents():
    graph = TaskGraph()
    graph.add_task("a", "first")
    graph.add_task("b", "second", depends_on=["a"])
    graph.add_task("c", "third", depends_on=["b"])

    graph.mark_running("a")
    graph.mark_failed("a", reason="verification failed")

    assert graph.get_task("a").status == TaskStatus.FAILED
    assert graph.get_task("b").status == TaskStatus.BLOCKED
    assert graph.get_task("c").status == TaskStatus.BLOCKED
    assert len(graph.blocked_tasks()) == 2


def test_duplicate_missing_and_cyclic_dependencies_fail_closed():
    graph = TaskGraph()
    graph.add_task("a", "first")
    with pytest.raises(TaskGraphError, match="duplicate"):
        graph.add_task("a", "duplicate")
    with pytest.raises(TaskGraphError, match="unknown"):
        graph.add_task("b", "missing", depends_on=["not-found"])
    with pytest.raises(TaskGraphError, match="duplicate dependency"):
        graph.add_task("b", "duplicate dep", depends_on=["a", "a"])


def test_unknown_roles_and_stale_plan_revisions_are_rejected():
    graph = TaskGraph(plan_revision=2)
    with pytest.raises(TaskGraphError, match="unknown role"):
        graph.add_task("a", "bad role", role="admin")
    with pytest.raises(TaskGraphError, match="does not match"):
        graph.add_task("a", "stale", plan_revision=1)

    graph.add_task("a", "first")
    with pytest.raises(TaskGraphError, match="must increase"):
        graph.set_plan_revision(2)
    graph.set_plan_revision(3)
    assert graph.plan_revision == 3


def test_running_task_prevents_plan_revision_change():
    graph = TaskGraph()
    graph.add_task("a", "first")
    graph.mark_running("a")
    with pytest.raises(TaskGraphError, match="running"):
        graph.set_plan_revision(1)


def test_serialization_contains_auditable_state():
    graph = TaskGraph(plan_revision=4)
    graph.add_task("a", "first", role="review")
    payload = graph.to_dict()

    assert payload["plan_revision"] == 4
    assert payload["tasks"][0]["status"] == "ready"
    assert payload["tasks"][0]["role"] == "review"
    assert payload["tasks"][0]["events"][0]["to_status"] == "ready"


def test_implement_requires_apply_authorization_and_matching_role():
    graph = TaskGraph(plan_revision=1)
    graph.add_task("implement", "apply change", role="implement")

    with pytest.raises(TaskGraphError, match="Plan/Apply authorization"):
        graph.mark_running("implement", role="implement", apply_authorized=False)

    with pytest.raises(TaskGraphError, match="role mismatch"):
        graph.mark_running("implement", role="review", apply_authorized=True)

    node = graph.mark_running("implement", role="implement", apply_authorized=True)
    assert node.status == TaskStatus.RUNNING
