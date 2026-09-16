"""Configuration loader supporting CLI args, ENV variables, YAML files, and defaults."""

import os
from pathlib import Path
from typing import Any, Dict, Optional
import yaml

from ctxguard.config.schema import (
    AppConfig,
    ServerConfig,
    UpstreamConfig,
    ProviderConfig,
    DedupConfig,
    ToolInjectionConfig,
    StructuralCompressionConfig,
    LogCleanerConfig,
    JSONCompressorConfig,
    AdaptivePipelineConfig,
    LevelConfig,
    CacheGuardConfig,
    LearnConfig,
    TargetFileConfig,
    SemanticCacheConfig,
    PiggybackExtractionConfig,
)
from ctxguard.config.validator import validate_config


class ConfigLoader:
    """Multi-tiered configuration loader."""

    DEFAULT_FILENAMES = ["ctxguard.yaml", "ctxguard.yml", ".ctxguard.yaml", ".ctxguard.yml"]

    @classmethod
    def find_config_file(cls, explicit_path: Optional[str] = None) -> Optional[Path]:
        """Find configuration file from explicit path, current working directory, or home directory."""
        if explicit_path:
            p = Path(explicit_path)
            if p.is_file():
                return p
            raise FileNotFoundError(f"Config file not found at: {explicit_path}")

        # Search current working directory
        cwd = Path.cwd()
        for fname in cls.DEFAULT_FILENAMES:
            candidate = cwd / fname
            if candidate.is_file():
                return candidate

        # Search user home directory (~/.ctxguard/ctxguard.yaml)
        home_config = Path.home() / ".ctxguard" / "ctxguard.yaml"
        if home_config.is_file():
            return home_config

        return None

    @classmethod
    def load_yaml(cls, path: Path) -> Dict[str, Any]:
        """Load YAML file safely."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                return data if isinstance(data, dict) else {}
        except Exception as e:
            raise RuntimeError(f"Failed to parse config file {path}: {e}") from e

    @classmethod
    def _parse_dict_to_config(cls, data: Dict[str, Any]) -> AppConfig:
        """Parse raw dictionary into AppConfig dataclass."""
        config = AppConfig()

        # Server
        srv_data = data.get("server", {})
        if srv_data:
            config.server = ServerConfig(
                host=srv_data.get("host", config.server.host),
                port=int(srv_data.get("port", config.server.port)),
                timeout_seconds=int(srv_data.get("timeout_seconds", config.server.timeout_seconds)),
                log_level=str(srv_data.get("log_level", config.server.log_level)),
                cors_origins=srv_data.get("cors_origins", config.server.cors_origins),
            )

        # Upstream
        up_data = data.get("upstream", {})
        if up_data:
            providers: Dict[str, ProviderConfig] = {}
            raw_providers = up_data.get("providers", {})
            for name, p_data in raw_providers.items():
                providers[name] = ProviderConfig(
                    base_url=p_data.get("base_url", ""),
                    api_key=p_data.get("api_key"),
                    api_key_env=p_data.get("api_key_env"),
                )
            if not providers:
                providers = config.upstream.providers

            config.upstream = UpstreamConfig(
                default_provider=up_data.get("default_provider", config.upstream.default_provider),
                providers=providers,
            )

        # Dedup
        dedup_data = data.get("dedup", {})
        if dedup_data:
            tool_data = dedup_data.get("tool_injection", {})
            config.dedup = DedupConfig(
                enabled=dedup_data.get("enabled", config.dedup.enabled),
                min_chars=int(dedup_data.get("min_chars", config.dedup.min_chars)),
                exclude_patterns=dedup_data.get("exclude_patterns", config.dedup.exclude_patterns),
                tool_injection=ToolInjectionConfig(
                    enabled=tool_data.get("enabled", config.dedup.tool_injection.enabled),
                    tool_name=tool_data.get("tool_name", config.dedup.tool_injection.tool_name),
                    description=tool_data.get("description", config.dedup.tool_injection.description),
                ),
            )

        # Structural compression
        sc_data = data.get("structural_compression", {})
        if sc_data:
            lc_data = sc_data.get("log_cleaner", {})
            jc_data = sc_data.get("json_compressor", {})
            config.structural_compression = StructuralCompressionConfig(
                log_cleaner=LogCleanerConfig(
                    enabled=lc_data.get("enabled", config.structural_compression.log_cleaner.enabled),
                    strip_ansi=lc_data.get("strip_ansi", config.structural_compression.log_cleaner.strip_ansi),
                    merge_progress_bars=lc_data.get("merge_progress_bars", config.structural_compression.log_cleaner.merge_progress_bars),
                    fold_repeated_stacktraces=lc_data.get("fold_repeated_stacktraces", config.structural_compression.log_cleaner.fold_repeated_stacktraces),
                    stacktrace_threshold=int(lc_data.get("stacktrace_threshold", config.structural_compression.log_cleaner.stacktrace_threshold)),
                    custom_patterns=lc_data.get("custom_patterns", config.structural_compression.log_cleaner.custom_patterns),
                ),
                json_compressor=JSONCompressorConfig(
                    enabled=jc_data.get("enabled", config.structural_compression.json_compressor.enabled),
                    min_array_length=int(jc_data.get("min_array_length", config.structural_compression.json_compressor.min_array_length)),
                    ignore_keys=jc_data.get("ignore_keys", config.structural_compression.json_compressor.ignore_keys),
                ),
            )

        # Adaptive pipeline
        ap_data = data.get("adaptive_pipeline", {})
        if ap_data:
            raw_levels = ap_data.get("levels", [])
            levels = []
            for lvl in raw_levels:
                levels.append(LevelConfig(
                    name=lvl.get("name", "custom"),
                    max_tokens=int(lvl.get("max_tokens", 16384)),
                    compression_mode=lvl.get("compression_mode", "lossless"),
                    prune_ratio=float(lvl.get("prune_ratio", 1.0)),
                    use_onnx=bool(lvl.get("use_onnx", False)),
                ))
            config.adaptive_pipeline = AdaptivePipelineConfig(
                enabled=ap_data.get("enabled", config.adaptive_pipeline.enabled),
                levels=levels if levels else config.adaptive_pipeline.levels,
                protected_keywords=ap_data.get("protected_keywords", config.adaptive_pipeline.protected_keywords),
            )

        # Cache guard
        cg_data = data.get("cache_guard", {})
        if cg_data:
            config.cache_guard = CacheGuardConfig(
                freeze_system_prompt=cg_data.get("freeze_system_prompt", config.cache_guard.freeze_system_prompt),
                freeze_prefix_rounds=int(cg_data.get("freeze_prefix_rounds", config.cache_guard.freeze_prefix_rounds)),
                auto_anthropic_cache_control=cg_data.get("auto_anthropic_cache_control", config.cache_guard.auto_anthropic_cache_control),
            )

        # Learn
        learn_data = data.get("learn", {})
        if learn_data:
            raw_targets = learn_data.get("target_files", [])
            targets = []
            for t in raw_targets:
                targets.append(TargetFileConfig(
                    path=t.get("path", ""),
                    marker=t.get("marker", "CTXGUARD_AUTO_RULES"),
                ))
            config.learn = LearnConfig(
                storage_db=learn_data.get("storage_db", config.learn.storage_db),
                detect_loop_threshold=int(learn_data.get("detect_loop_threshold", config.learn.detect_loop_threshold)),
                target_files=targets if targets else config.learn.target_files,
            )

        # Semantic cache
        sc_data = data.get("semantic_cache", {})
        if sc_data:
            config.semantic_cache = SemanticCacheConfig(
                enabled=bool(sc_data.get("enabled", config.semantic_cache.enabled)),
                similarity_threshold=float(sc_data.get("similarity_threshold", config.semantic_cache.similarity_threshold)),
                max_entries=int(sc_data.get("max_entries", config.semantic_cache.max_entries)),
                ttl_seconds=int(sc_data.get("ttl_seconds", config.semantic_cache.ttl_seconds)),
                use_exact_matching=bool(sc_data.get("use_exact_matching", config.semantic_cache.use_exact_matching)),
            )

        # Piggyback extraction
        pb_data = data.get("piggyback_extraction", {})
        if pb_data:
            config.piggyback_extraction = PiggybackExtractionConfig(
                enabled=bool(pb_data.get("enabled", config.piggyback_extraction.enabled)),
            )

        return config

    @classmethod
    def _apply_env_overrides(cls, config: AppConfig) -> AppConfig:
        """Override configuration with environment variables prefixed by CTXGUARD_."""
        # CTXGUARD_SERVER_HOST / CTXGUARD_SERVER_PORT
        if "CTXGUARD_SERVER_HOST" in os.environ:
            config.server.host = os.environ["CTXGUARD_SERVER_HOST"]
        if "CTXGUARD_SERVER_PORT" in os.environ:
            config.server.port = int(os.environ["CTXGUARD_SERVER_PORT"])
        if "CTXGUARD_LOG_LEVEL" in os.environ:
            config.server.log_level = os.environ["CTXGUARD_LOG_LEVEL"]
        if "CTXGUARD_DEFAULT_PROVIDER" in os.environ:
            config.upstream.default_provider = os.environ["CTXGUARD_DEFAULT_PROVIDER"]
        if "CTXGUARD_DEDUP_ENABLED" in os.environ:
            config.dedup.enabled = os.environ["CTXGUARD_DEDUP_ENABLED"].lower() in {"1", "true", "yes"}

        return config

    @classmethod
    def load_config(
        cls,
        config_path: Optional[str] = None,
        cli_overrides: Optional[Dict[str, Any]] = None,
    ) -> AppConfig:
        """Main entry point to load, merge, and validate configuration."""
        file_path = cls.find_config_file(config_path)
        if file_path:
            raw_data = cls.load_yaml(file_path)
            config = cls._parse_dict_to_config(raw_data)
        else:
            config = AppConfig()

        # Apply Environment Variables
        config = cls._apply_env_overrides(config)

        # Apply CLI overrides if provided
        if cli_overrides:
            if "host" in cli_overrides and cli_overrides["host"] is not None:
                config.server.host = str(cli_overrides["host"])
            if "port" in cli_overrides and cli_overrides["port"] is not None:
                config.server.port = int(cli_overrides["port"])
            if "log_level" in cli_overrides and cli_overrides["log_level"] is not None:
                config.server.log_level = str(cli_overrides["log_level"])
            if "default_provider" in cli_overrides and cli_overrides["default_provider"] is not None:
                config.upstream.default_provider = str(cli_overrides["default_provider"])

        # Validate
        validate_config(config)

        return config
