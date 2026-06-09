class CLIError(Exception):
    """Base exception for all Financial Analyst CLI errors."""

    pass


class ConfigError(CLIError):
    """Base exception for configuration-related issues."""

    pass


class ConfigNotFoundError(ConfigError):
    """Raised when the configuration file is not found."""

    pass


class WorkspaceError(CLIError):
    """Base exception for workspace-related issues."""

    pass


class InvalidWorkspaceError(WorkspaceError):
    """Raised when a workspace path is invalid or cannot be initialized."""

    pass
