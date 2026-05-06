"""Domain-specific errors for the lab package."""


class LabError(Exception):
    """Base error for the lab package."""


class StudentTodoError(LabError):
    """Backward-compatible error type retained for starter tests."""


class AgentExecutionError(LabError):
    """Raised when an agent fails after retries/fallbacks."""


class ValidationError(LabError):
    """Raised when state or output validation fails."""
