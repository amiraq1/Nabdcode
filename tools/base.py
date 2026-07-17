from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Type

# Pydantic — the self-validation backend for all tool args.
# Every tool subclass declares an ``args_schema`` (a BaseModel subclass)
# that the ``__call__`` entry point uses to validate and parse raw JSON
# args automatically.  Tools that omit it get no-op pass-through (backward
# compatible with the legacy ``execute(**kwargs)`` contract).
#
# IMPORTANT: We import pydantic under a private name and run a smoke test
# to verify pydantic-core is actually functional.  pydantic 2.x can import
# successfully even when pydantic-core is a broken stub (e.g. v0.0.1), but
# model instantiation will silently corrupt field values (using the ``...``
# sentinel literally instead of treating it as "required").  If the smoke
# test fails, we set ``BaseModel = None`` and all tools gracefully degrade
# to dict-based fallback rather than producing silently wrong values.
try:
    from pydantic import BaseModel as _PydanticBaseModel
    from pydantic import ValidationError, Field as _PydanticField
    Field = _PydanticField

    # Smoke test: create a minimal model and verify field assignment.
    class _SmokeTest(_PydanticBaseModel):
        x: str = "ok"
    _t = _SmokeTest(x="hello")
    assert _t.x == "hello", f"pydantic-core broken: field became {_t.x!r}"

    # Smoke test passed — use real pydantic.
    BaseModel = _PydanticBaseModel
except Exception:
    # pydantic absent, broken, or pydantic-core cannot load on this platform
    # (e.g. Termux/Android where prebuilt pydantic-core wheels link against
    # glibc/musl libs that are unavailable). Rather than degrading to a bare
    # None (which crashes any ``class X(BaseModel)`` defined at import time),
    # provide a minimal but functional stand-in so every tool still imports
    # and runs. It mirrors the surface the tools rely on:
    #   - subclassing with ``field: T = Field(...)`` annotations
    #   - ``Model(**kwargs)`` construction
    #   - ``.model_dump()`` and ``.model_json_schema()``
    #   - ``.model_rebuild()``
    ValidationError = None  # type: ignore[assignment]

    class _FieldInfo:
        """Lightweight descriptor mirroring pydantic Field metadata."""

        __slots__ = ("default", "required", "metadata")

        def __init__(self, default: Any = ..., metadata: Optional[dict] = None):
            self.default = default
            self.required = default is ... or default is _MISSING
            self.metadata = metadata or {}

    _MISSING = object()

    def Field(*args: Any, **kwargs: Any) -> Any:  # type: ignore[misc]
        """Stand-in for pydantic.Field. Returns a _FieldInfo descriptor."""
        default = args[0] if args else kwargs.get("default", ...)
        meta = {k: v for k, v in kwargs.items() if k != "default"}
        return _FieldInfo(default=default, metadata=meta)

    class BaseModel:  # type: ignore[no-redef]
        """Minimal pydantic-compatible stand-in for environments without a
        working pydantic-core. Stores fields, applies defaults, and exposes
        ``model_dump`` / ``model_json_schema`` / ``model_rebuild``."""

        _fields_: dict = {}

        def __init__(self, **kwargs: Any) -> None:
            for name, finfo in self.__class__._fields_.items():
                if name in kwargs:
                    value = kwargs[name]
                elif not finfo.required:
                    value = finfo.default
                elif finfo.default is _MISSING:
                    value = kwargs.get(name)
                else:
                    value = finfo.default
                if finfo.required and value is None and name not in kwargs:
                    raise ValueError(f"Missing required field: {name}")
                setattr(self, name, value)
            # Absorb any extra kwargs so callers can pass additional data.
            for k, v in kwargs.items():
                if not hasattr(self, k):
                    setattr(self, k, v)

        @classmethod
        def model_rebuild(cls) -> None:
            return None

        def model_dump(self) -> dict:
            out: dict = {}
            for name in self.__class__._fields_:
                if hasattr(self, name):
                    out[name] = getattr(self, name)
            return out

        @classmethod
        def model_json_schema(cls) -> dict:
            props: dict = {}
            required: list = []
            for name, finfo in cls._fields_.items():
                props[name] = {"type": "string"}  # best-effort, untyped
                if finfo.required:
                    required.append(name)
            schema: dict = {"type": "object", "properties": props}
            if required:
                schema["required"] = required
            return schema

    def _collect_fields(cls: type) -> dict:
        """Gather Field descriptors declared as class annotations on ``cls``.

        Skips the framework base class and any private/dunder attributes
        (notably ``_fields_``) so they never leak into model_dump/schema.
        """
        fields: dict = {}
        for klass in reversed(cls.__mro__):
            if klass is BaseModel:
                continue
            for name, val in vars(klass).items():
                if name.startswith("_"):
                    continue
                if isinstance(val, _FieldInfo):
                    fields[name] = val
        # Fall back to annotations without a Field() default.
        for klass in reversed(cls.__mro__):
            if klass is BaseModel:
                continue
            ann = getattr(klass, "__annotations__", {})
            for name, _t in ann.items():
                if name.startswith("_") or name in fields:
                    continue
                fields[name] = _FieldInfo(default=None)
        return fields

    # Make subclasses auto-collect their Field descriptors at definition time.
    def _init_subclass(cls) -> None:
        cls._fields_ = _collect_fields(cls)  # type: ignore[attr-defined]

    BaseModel.__init_subclass__ = classmethod(_init_subclass)  # type: ignore[assignment]


from tools.models import ToolResult


# ── Central re-export for all tools ─────────────────────────────────────
# Every tool should import ``BaseModel`` and ``Field`` from ``tools.base``
# rather than from ``pydantic`` directly.  This keeps the import surface
# unified and makes the pydantic fallback transparent to all tools.
__all__ = ["BaseTool", "BaseModel", "Field"]


class BaseTool(ABC):
    """Standard interface that all tools must implement.

    Guarantees all tools communicate with the engine the same way.
    Supports self-validating entry points via Pydantic ``args_schema``.

    **Entry points (in order of precedence):**

    1. ``__call__(raw_args: dict) -> ToolResult`` — validates via Pydantic,
       emits UI bridge events, then delegates to ``execute()``.

    2. ``execute(**kwargs) -> ToolResult`` — legacy interface. Subclasses
       that have migrated to the self-validating pattern can override
       ``execute_with_args(args: BaseModel)`` instead.

    3. ``forward(*args, **kwargs) -> str`` — smolagents-compatible shim
       that normalises positional / list / dict drift and delegates to
       ``__call__``.  Returns a plain string (smolagents convention).
    """
    name: str = "unnamed_tool"
    description: str = "No description provided."
    # smolagents compatibility: input schema dict (generated from args_schema
    # if not explicitly provided).
    inputs: dict = {}

    # ------------------------------------------------------------------
    # Pydantic argument schema
    # ------------------------------------------------------------------

    @property
    def args_schema(self) -> Optional[Type["BaseModel"]]:
        """Pydantic model that describes this tool's arguments.

        Override in subclasses:

            class MyArgs(BaseModel):
                action: str = Field(..., pattern="^(read|write)$")
                path: str = Field(..., min_length=1)

            @property
            def args_schema(self):
                return MyArgs

        Returning ``None`` (default) leaves validation to the old manual
        checks inside ``execute()`` — backward compatible.
        """
        return None

    # ------------------------------------------------------------------
    # Self-validation
    # ------------------------------------------------------------------

    def validate_and_parse(self, raw_args: Dict[str, Any]) -> Any:
        """Validate *raw_args* against the Pydantic schema.

        Returns a validated Pydantic model instance when ``args_schema``
        is provided, or the raw dict unchanged for backward compatibility.

        Raises ``ValueError`` with an LLM-readable error message when
        validation fails (or when Pydantic is not installed).
        """
        schema = self.args_schema
        if schema is None:
            return raw_args  # no schema = pass-through

        if BaseModel is None:
            raise ValueError(
                f"Pydantic is required for tool '{self.name}' but not installed. "
                "Run: pip install pydantic>=2.0"
            )

        try:
            return schema(**raw_args)
        except ValidationError as e:
            errors = []
            for err in e.errors():
                loc = ".".join(str(x) for x in err["loc"])
                msg = err["msg"]
                errors.append(f"{loc}: {msg}")
            raise ValueError(
                f"Invalid arguments for {self.name}: {'; '.join(errors)}"
            )

    # ------------------------------------------------------------------
    # Execution (must be overridden by subclasses)
    # ------------------------------------------------------------------

    @abstractmethod
    def execute(self, **kwargs: Any) -> ToolResult:
        """
        Primary function for executing the tool.

        Must return a ``tools.models.ToolResult`` with ``success``,
        ``stdout``/``stderr``, and ``returncode`` set. The ``ToolResult``
        dataclass also exposes ``output`` (stdout or stderr), ``status``,
        ``diff``, and ``get()``/``__getitem__`` dict-compat shims so legacy
        dict-style access keeps working.

        .. note::
           Traditionally receives keyword arguments. Subclasses that have
           migrated to the self-validating pattern may override
           ``execute_with_args(args)`` instead, which receives a validated
           Pydantic model instance and is called by ``__call__``.
        """
        ...

    def execute_with_args(self, args: Any) -> ToolResult:
        """Execute the tool with a validated argument object.

        Default implementation:
          - If *args* is a Pydantic model, calls ``execute(**args.model_dump())``.
          - If *args* is a plain dict, calls ``execute(**args)``.

        New tools should override this method to receive strongly-typed,
        validated ``args`` directly — no manual validation needed.
        """
        if isinstance(args, BaseModel):
            return self.execute(**args.model_dump())
        if isinstance(args, dict):
            return self.execute(**args)
        return self.execute(**dict(args) if hasattr(args, "items") else {"args": args})

    # ------------------------------------------------------------------
    # Self-validating entry point
    # ------------------------------------------------------------------

    def __call__(self, *args: Any, **kwargs: Any) -> ToolResult:
        """Self-validating entry point: validate → emit events → execute.

    Normalises arguments (positional dict, keyword pairs, or a mix) into a
    single ``raw_args`` dict, validates against ``args_schema``, emits UI
    bridge events, then delegates to ``execute_with_args()``.

    Call patterns accepted:

    * ``tool({"command": "ls"})`` — single positional dict (new self-validating style)
    * ``tool(command="ls")`` — keyword arguments (dispatcher style)
    * ``tool({"command": "ls"}, timeout=30)`` — mixed (positional dict + extra kwargs)

    This is the **primary entry point** for the ``Dispatcher`` (which
    submits via ``_SHARED_POOL.submit(tool, **kwargs)``) and for
    any caller that wants self-validation for free.  The old
    ``execute(**kwargs)`` path remains for direct use.
        """
        # ── Normalise args into a single dict ─────────────────────────
        raw_args: Dict[str, Any] = {}
        if args:
            if isinstance(args[0], dict):
                raw_args.update(args[0])
            else:
                # Positional non-dict args are tool-specific (e.g. forward("echo hi"))
                raw_args = {"args": args} if not kwargs else {**dict(zip(range(len(args)), args))}
        raw_args.update(kwargs)

        # ── 1. UI bridge: tool start ─────────────────────────────────
        try:
            from core.ui_bridge import get_bridge
            get_bridge().emit_tool_start_sync(self.name, raw_args)
        except Exception:
            pass  # bridge must never break the tool

        try:
            # ── 2. Validate ──────────────────────────────────────────
            validated = self.validate_and_parse(raw_args)

            # ── 3. Execute ───────────────────────────────────────────
            result = self.execute_with_args(validated)

            # ── 4. UI bridge: tool end ───────────────────────────────
            try:
                summary = str(result)[:150]
                from core.ui_bridge import get_bridge
                get_bridge().emit_tool_end_sync(self.name, summary)
            except Exception:
                pass

            return result

        except ValueError as exc:
            result = ToolResult(
                success=False,
                stderr=str(exc),
                returncode=-1,
                status="error",
            )
            try:
                from core.ui_bridge import get_bridge
                get_bridge().emit_tool_end_sync(
                    self.name, f"❌ Error: {str(exc)[:120]}"
                )
            except Exception:
                pass
            return result

        except Exception as exc:
            result = ToolResult(
                success=False,
                stderr=f"{type(exc).__name__}: {exc}",
                returncode=-1,
                status="error",
            )
            try:
                from core.ui_bridge import get_bridge
                get_bridge().emit_tool_end_sync(
                    self.name, f"❌ Error: {str(exc)[:120]}"
                )
            except Exception:
                pass
            return result

    # ------------------------------------------------------------------
    # smolagents compatibility layer
    # ------------------------------------------------------------------

    def forward(self, *args: Any, **kwargs: Any) -> str:
        """smolagents-compatible entry point.

        ``smolagents.CodeAgent`` calls ``tool.forward(**kwargs)``. This
        shim normalises positional, list, dict, and keyword-based calling
        conventions and delegates to ``__call__()`` for validation +
        execution.  Returns a plain string (smolagents ``output_type``).

        Subclasses that already override ``forward()`` (e.g. the Secure*
        wrappers) are **not** affected — their ``forward()`` takes priority
        through normal MRO.
        """
        # Resolve the raw args dict from whatever shape the model sends.
        raw_args: Dict[str, Any] = {}

        if args:
            first = args[0]
            if isinstance(first, dict):
                raw_args = first
            elif isinstance(first, (list, tuple)):
                # Positional list often wraps a single command.
                raw_args = {"command": str(first[0])} if first else {}
            else:
                raw_args = {"command": str(first)}
        elif kwargs:
            raw_args = dict(kwargs)

        result = self.__call__(raw_args)
        return str(result.stdout or result.stderr or "")

    # ------------------------------------------------------------------
    # Schema introspection
    # ------------------------------------------------------------------

    def get_schema(self) -> dict:
        """Return the tool schema for upstream LLM consumption.

        When ``args_schema`` is set, automatically generates a JSON Schema
        from the Pydantic model.  Otherwise returns the basic name/desc dict.
        """
        schema = self.args_schema
        if schema is not None and BaseModel is not None:
            return {
                "name": self.name,
                "description": self.description,
                "input_schema": schema.model_json_schema(),
            }
        return {
            "name": self.name,
            "description": self.description,
        }
