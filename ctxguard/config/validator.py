"""Validation rules for CtxGuard configuration."""

from typing import List
from ctxguard.config.schema import AppConfig


class ConfigValidationError(Exception):
    """Raised when configuration validation fails."""
    pass


def validate_config(config: AppConfig) -> List[str]:
    """Validate AppConfig fields and return a list of warning messages (or raise ConfigValidationError)."""
    errors: List[str] = []
    warnings: List[str] = []

    # Server validation
    if not (1 <= config.server.port <= 65535):
        errors.append(f"Invalid server port: {config.server.port}. Must be between 1 and 65535.")
    if config.server.timeout_seconds <= 0:
        errors.append(f"Invalid timeout_seconds: {config.server.timeout_seconds}. Must be > 0.")
    if config.server.log_level.upper() not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        errors.append(f"Invalid log_level: {config.server.log_level}.")

    # Upstream validation
    default_p = config.upstream.default_provider
    if default_p not in config.upstream.providers:
        errors.append(f"Default provider '{default_p}' is not defined in upstream.providers.")

    # Dedup validation
    if config.dedup.min_chars < 0:
        errors.append(f"dedup.min_chars must be non-negative, got {config.dedup.min_chars}.")

    # Structural compression
    if config.structural_compression.log_cleaner.stacktrace_threshold < 1:
        errors.append("log_cleaner.stacktrace_threshold must be >= 1.")
    if config.structural_compression.json_compressor.min_array_length < 1:
        errors.append("json_compressor.min_array_length must be >= 1.")

    # Adaptive pipeline
    for idx, lvl in enumerate(config.adaptive_pipeline.levels):
        if lvl.max_tokens <= 0:
            errors.append(f"Level [{idx}] '{lvl.name}' max_tokens must be > 0.")
        if not (0.0 < lvl.prune_ratio <= 1.0):
            errors.append(f"Level [{idx}] '{lvl.name}' prune_ratio must be between 0.0 and 1.0.")

    if errors:
        raise ConfigValidationError("\n".join(errors))

    return warnings
