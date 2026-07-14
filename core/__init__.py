# Core package initialization
from core.parser import (
    ToolCall,
    extract_command,
    ValidationResult,
    validate_tool_call,
    TOOL_SCHEMAS,
    extract_json_from_response,
)
from core.config import AgentConfig, ConfigManager
from core.security import validate, is_safe_command
from core.utils import safe_execute_command, truncate
from core.logger import Logger
from core.metrics import MetricsEngine
from core.session import SessionManager
from core.memory import (
    LRUTTLMemory,
    MemoryManager,
    PurePythonEmbedder,
    SemanticMemoryPipeline,
)
from core.retry import retry
from core.llm import (
    OpenRouterClient,
    OpenRouterConfig,
    OpenRouterError,
    AuthenticationError,
    RateLimitError,
    ServerError,
    LocalClient,
    NvidiaClient,
)
from core.model_registry import (
    ModelEntry,
    MODEL_REGISTRY,
    is_free_model,
    format_model_selector_label,
    get_model_short_name,
    get_visible_models,
)
from core.constants import TODO_DISCIPLINE, SECURITY_COMPLIANCE_RULE, LANGUAGE_POLICY
from core.diff_matrix import generate_diff, DiffMatrixResult
from core.bootloader import NabdBootloader
from core.sanitize import (
    sanitize,
    format_tool_result_output,
    has_goal_complete_signal,
    strip_goal_complete_marker,
    fix_arabic_reversal,
)
from core.errors import (
    NabdError,
    AuthenticationError,
    PermissionDeniedError,
    SandboxExecutionError,
    MCPConnectionError,
    MCPToolCallError,
    StreamTruncationError,
    TastePipelineError,
    ConfigurationError,
    RateLimitExceededError,
    TelemetryExportError,
)

from core.skills import (
    SkillRouter,
    SkillVerbMetadata,
    SkillExecutionMode,
    ExternalSkillStub,
    SkillManifest,
    SkillLoader,
    ReviewInspector,
    DeslopInspector,
    ColorInspector,
    Skill,
    discover_skills,
    find_skill,
    format_skill_context,
    execute_skill,
)

from core.gateway import (
    InputGateway,
    ProviderGateway,
    ModelCategory,
    PlanTier,
    ResolvedRoute,
)

__all__ = [
    "InputGateway",
    "ProviderGateway",
    "ModelCategory",
    "PlanTier",
    "ResolvedRoute",
    "SkillRouter",
    "SkillManifest",
    "SkillLoader",
    "ReviewInspector",
    "DeslopInspector",
    "ColorInspector",
    "SkillVerbMetadata",
    "SkillExecutionMode",
    "ExternalSkillStub",
    "NabdBootloader",
    "NabdError",
    "AuthenticationError",
    "PermissionDeniedError",
    "SandboxExecutionError",
    "MCPConnectionError",
    "MCPToolCallError",
    "StreamTruncationError",
    "TastePipelineError",
    "ConfigurationError",
    "RateLimitExceededError",
    "TelemetryExportError",
    "generate_diff",
    "DiffMatrixResult",
    "ToolCall",
    "extract_command",
    "ValidationResult",
    "validate_tool_call",
    "TOOL_SCHEMAS",
    "extract_json_from_response",
    "AgentConfig",
    "ConfigManager",
    "validate",
    "is_safe_command",
    "safe_execute_command",
    "truncate",
    "Logger",
    "MetricsEngine",
    "SessionManager",
    "LRUTTLMemory",
    "MemoryManager",
    "PurePythonEmbedder",
    "SemanticMemoryPipeline",
    "retry",
    "OpenRouterClient",
    "OpenRouterConfig",
    "OpenRouterError",
    "AuthenticationError",
    "RateLimitError",
    "ServerError",
    "LocalClient",
    "NvidiaClient",
    "ModelEntry",
    "MODEL_REGISTRY",
    "is_free_model",
    "format_model_selector_label",
    "get_model_short_name",
    "get_visible_models",
    "sanitize",
    "format_tool_result_output",
    "has_goal_complete_signal",
    "strip_goal_complete_marker",
    "fix_arabic_reversal",
    "TODO_DISCIPLINE",
    "SECURITY_COMPLIANCE_RULE",
    "LANGUAGE_POLICY",
]

