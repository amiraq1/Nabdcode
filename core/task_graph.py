"""Deterministic, fail-closed task graph for multi-step Nabdcode goals.

This module is deliberately independent from the legacy execution DAG.  It is a
state and dependency model; it does not execute tools or grant permissions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from threading import RLock
from typing import Any, Iterable


VALID_ROLES = frozenset({"research", "review", "implement"})


class TaskGraphError(ValueError):
    """Raised when a graph mutation would violate an invariant."""


class TaskStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"


_TERMINAL = frozenset({TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.BLOCKED})


@dataclass(frozen=True)
class TaskEvent:
    task_id: str
    from_status: str
    to_status: str
    reason: str
    plan_revision: int
    evidence_ids: tuple[str, ...] = ()


@dataclass
class TaskNode:
    task_id: str
    description: str
    depends_on: tuple[str, ...] = ()
    role: str = "research"
    plan_revision: int = 0
    status: TaskStatus = TaskStatus.PENDING
    evidence_ids: tuple[str, ...] = ()
    events: list[TaskEvent] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "description": self.description,
            "depends_on": list(self.depends_on),
            "role": self.role,
            "plan_revision": self.plan_revision,
            "status": self.status.value,
            "evidence_ids": list(self.evidence_ids),
            "events": [
                {
                    "task_id": event.task_id,
                    "from_status": event.from_status,
                    "to_status": event.to_status,
                    "reason": event.reason,
                    "plan_revision": event.plan_revision,
                    "evidence_ids": list(event.evidence_ids),
                }
                for event in self.events
            ],
        }


class TaskGraph:
    """Thread-safe task dependency graph with explicit state transitions."""

    def __init__(self, *, plan_revision: int = 0) -> None:
        if int(plan_revision) < 0:
            raise TaskGraphError("plan_revision must be non-negative")
        self.plan_revision = int(plan_revision)
        self._tasks: dict[str, TaskNode] = {}
        self._lock = RLock()

    def add_task(
        self,
        task_id: str,
        description: str,
        *,
        depends_on: Iterable[str] = (),
        role: str = "research",
        plan_revision: int | None = None,
    ) -> TaskNode:
        with self._lock:
            task_id = self._normalize_id(task_id)
            description = str(description or "").strip()
            if not description:
                raise TaskGraphError("description must be non-empty")
            if task_id in self._tasks:
                raise TaskGraphError(f"duplicate task_id: {task_id}")
            role = str(role or "").strip().lower()
            if role not in VALID_ROLES:
                raise TaskGraphError(f"unknown role: {role!r}")
            revision = self.plan_revision if plan_revision is None else int(plan_revision)
            if revision != self.plan_revision:
                raise TaskGraphError(
                    f"task plan_revision {revision} does not match graph revision {self.plan_revision}"
                )
            dependencies = tuple(self._normalize_id(dep) for dep in depends_on)
            if len(set(dependencies)) != len(dependencies):
                raise TaskGraphError(f"duplicate dependency in task: {task_id}")
            if task_id in dependencies:
                raise TaskGraphError(f"task cannot depend on itself: {task_id}")
            missing = sorted(set(dependencies) - self._tasks.keys())
            if missing:
                raise TaskGraphError(
                    f"task {task_id} depends on unknown task(s): {', '.join(missing)}"
                )
            self._tasks[task_id] = TaskNode(
                task_id=task_id,
                description=description,
                depends_on=dependencies,
                role=role,
                plan_revision=revision,
            )
            if self._has_cycle():
                del self._tasks[task_id]
                raise TaskGraphError("adding task would create a dependency cycle")
            self._refresh_ready_locked()
            return self._tasks[task_id]

    def get_task(self, task_id: str) -> TaskNode:
        with self._lock:
            task_id = self._normalize_id(task_id)
            try:
                return self._tasks[task_id]
            except KeyError as exc:
                raise TaskGraphError(f"unknown task_id: {task_id}") from exc

    def tasks(self) -> tuple[TaskNode, ...]:
        with self._lock:
            return tuple(self._tasks.values())

    def ready_tasks(self, *, plan_revision: int | None = None) -> tuple[TaskNode, ...]:
        with self._lock:
            revision = self.plan_revision if plan_revision is None else int(plan_revision)
            if revision != self.plan_revision:
                return ()
            self._refresh_ready_locked()
            return tuple(node for node in self._tasks.values() if node.status == TaskStatus.READY)

    def blocked_tasks(self) -> tuple[TaskNode, ...]:
        with self._lock:
            return tuple(node for node in self._tasks.values() if node.status == TaskStatus.BLOCKED)

    def mark_running(
        self,
        task_id: str,
        *,
        plan_revision: int | None = None,
        role: str | None = None,
        apply_authorized: bool = False,
    ) -> TaskNode:
        with self._lock:
            node = self.get_task(task_id)
            revision = self.plan_revision if plan_revision is None else int(plan_revision)
            if revision != self.plan_revision or node.plan_revision != revision:
                raise TaskGraphError("task is bound to a stale plan revision")
            if role is not None and str(role).strip().lower() != node.role:
                raise TaskGraphError(
                    f"role mismatch for {node.task_id}: expected {node.role}, got {role}"
                )
            if node.role == "implement" and not apply_authorized:
                raise TaskGraphError(
                    "implement tasks require current Plan/Apply authorization"
                )
            self._refresh_ready_locked()
            if node.status != TaskStatus.READY:
                raise TaskGraphError(
                    f"task {node.task_id} is not ready; current status is {node.status.value}"
                )
            self._transition_locked(node, TaskStatus.RUNNING, "execution started")
            return node

    def mark_completed(
        self,
        task_id: str,
        *,
        evidence_ids: Iterable[str],
        reason: str = "execution completed",
    ) -> TaskNode:
        with self._lock:
            node = self.get_task(task_id)
            evidence = tuple(str(item).strip() for item in evidence_ids if str(item).strip())
            if node.status != TaskStatus.RUNNING:
                raise TaskGraphError("only running tasks can be completed")
            if not evidence:
                raise TaskGraphError("completion requires at least one evidence id")
            node.evidence_ids = evidence
            self._transition_locked(node, TaskStatus.COMPLETED, reason, evidence)
            self._refresh_ready_locked()
            return node

    def mark_failed(self, task_id: str, *, reason: str) -> TaskNode:
        with self._lock:
            node = self.get_task(task_id)
            if node.status != TaskStatus.RUNNING:
                raise TaskGraphError("only running tasks can fail")
            reason = str(reason or "").strip()
            if not reason:
                raise TaskGraphError("failure reason must be non-empty")
            self._transition_locked(node, TaskStatus.FAILED, reason)
            self._block_dependents_locked(node.task_id)
            return node

    def set_plan_revision(self, plan_revision: int) -> None:
        with self._lock:
            revision = int(plan_revision)
            if revision <= self.plan_revision:
                raise TaskGraphError("plan_revision must increase monotonically")
            if any(node.status == TaskStatus.RUNNING for node in self._tasks.values()):
                raise TaskGraphError("cannot change plan revision while a task is running")
            self.plan_revision = revision
            for node in self._tasks.values():
                if node.status not in _TERMINAL:
                    node.plan_revision = revision
                    node.status = TaskStatus.PENDING
            self._refresh_ready_locked()

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "plan_revision": self.plan_revision,
                "tasks": [node.to_dict() for node in self._tasks.values()],
            }

    @staticmethod
    def _normalize_id(task_id: object) -> str:
        normalized = str(task_id or "").strip()
        if not normalized or len(normalized) > 128:
            raise TaskGraphError("task_id must be 1-128 non-whitespace characters")
        return normalized

    def _transition_locked(
        self,
        node: TaskNode,
        to_status: TaskStatus,
        reason: str,
        evidence_ids: tuple[str, ...] = (),
    ) -> None:
        previous = node.status
        node.status = to_status
        node.events.append(
            TaskEvent(
                task_id=node.task_id,
                from_status=previous.value,
                to_status=to_status.value,
                reason=str(reason),
                plan_revision=self.plan_revision,
                evidence_ids=evidence_ids,
            )
        )

    def _refresh_ready_locked(self) -> None:
        for node in self._tasks.values():
            if node.status != TaskStatus.PENDING:
                continue
            dependencies = [self._tasks[dep] for dep in node.depends_on]
            if any(dep.status in {TaskStatus.FAILED, TaskStatus.BLOCKED} for dep in dependencies):
                self._transition_locked(node, TaskStatus.BLOCKED, "dependency failed or blocked")
            elif all(dep.status == TaskStatus.COMPLETED for dep in dependencies):
                self._transition_locked(node, TaskStatus.READY, "dependencies satisfied")

    def _block_dependents_locked(self, failed_id: str) -> None:
        for node in self._tasks.values():
            if node.status == TaskStatus.PENDING and failed_id in node.depends_on:
                self._transition_locked(node, TaskStatus.BLOCKED, "dependency failed")
                self._block_dependents_locked(node.task_id)

    def _has_cycle(self) -> bool:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(task_id: str) -> bool:
            if task_id in visiting:
                return True
            if task_id in visited:
                return False
            visiting.add(task_id)
            for dependency in self._tasks[task_id].depends_on:
                if visit(dependency):
                    return True
            visiting.remove(task_id)
            visited.add(task_id)
            return False

        return any(visit(task_id) for task_id in self._tasks)
