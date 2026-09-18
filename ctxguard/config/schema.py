"""Configuration data structures for CtxGuard."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8787
    timeout_seconds: int = 180
    log_level: str = "INFO"
    cors_origins: List[str] = field(default_factory=lambda: ["http://localhost:*", "http://127.0.0.1:*"])


@dataclass
class ProviderConfig:
    base_url: str = ""
    api_key: Optional[str] = None
    api_key_env: Optional[str] = None


@dataclass
class UpstreamConfig:
    default_provider: str = "anthropic"
    providers: Dict[str, ProviderConfig] = field(default_factory=lambda: {
        "anthropic": ProviderConfig(
            base_url="https://api.anthropic.com",
            api_key_env="ANTHROPIC_API_KEY",
        ),
        "openai": ProviderConfig(
            base_url="https://api.openai.com",
            api_key_env="OPENAI_API_KEY",
        ),
        "deepseek": ProviderConfig(
            base_url="https://api.deepseek.com",
            api_key_env="DEEPSEEK_API_KEY",
        ),
        "google": ProviderConfig(
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            api_key_env="GEMINI_API_KEY",
        ),
        "gemini": ProviderConfig(
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            api_key_env="GEMINI_API_KEY",
        ),
        "custom": ProviderConfig(
            base_url="http://127.0.0.1:11434",
            api_key="ollama",
        ),
    })


@dataclass
class ToolInjectionConfig:
    enabled: bool = True
    tool_name: str = "ctx_expand"
    description: str = "Expand compressed context reference by ref_id if you need full details."


@dataclass
class DedupConfig:
    enabled: bool = True
    min_chars: int = 120
    exclude_patterns: List[str] = field(default_factory=lambda: ["*.env*", "*secret*", "*credential*"])
    tool_injection: ToolInjectionConfig = field(default_factory=ToolInjectionConfig)


@dataclass
class LogCleanerConfig:
    enabled: bool = True
    strip_ansi: bool = True
    merge_progress_bars: bool = True
    fold_repeated_stacktraces: bool = True
    stacktrace_threshold: int = 3
    max_log_lines: int = 120
    head_lines: int = 25
    tail_lines: int = 75
    custom_patterns: List[Dict[str, str]] = field(default_factory=list)


@dataclass
class SecretRedactorConfig:
    enabled: bool = True
    mask_token: str = "<REDACTED_SECRET>"
    custom_patterns: List[str] = field(default_factory=list)


@dataclass
class ThinkingManagerConfig:
    enabled: bool = False
    strip_deepseek_reasoning: bool = False
    strip_gemini_thought: bool = False
    anthropic_max_thinking_tokens: int = 16384


@dataclass
class JSONCompressorConfig:
    enabled: bool = True
    min_array_length: int = 3
    ignore_keys: List[str] = field(default_factory=lambda: ["error"])


@dataclass
class ASTCodeCompressorConfig:
    enabled: bool = True
    min_lines: int = 35
    preserve_docstrings: bool = True
    supported_languages: List[str] = field(default_factory=lambda: [
        "python", "py", "javascript", "js", "typescript", "ts", "go", "rust", "rs", "java", "c", "cpp"
    ])


@dataclass
class GitDiffCompressorConfig:
    enabled: bool = True
    min_lines: int = 15
    max_context_lines: int = 1


@dataclass
class ToolDeltaConfig:
    enabled: bool = True
    min_items: int = 15
    max_delta_ratio: float = 0.35
    max_delta_items: int = 20


@dataclass
class StructuralCompressionConfig:
    log_cleaner: LogCleanerConfig = field(default_factory=LogCleanerConfig)
    json_compressor: JSONCompressorConfig = field(default_factory=JSONCompressorConfig)
    ast_compressor: ASTCodeCompressorConfig = field(default_factory=ASTCodeCompressorConfig)
    git_diff: GitDiffCompressorConfig = field(default_factory=GitDiffCompressorConfig)
    secret_redactor: SecretRedactorConfig = field(default_factory=SecretRedactorConfig)
    tool_delta: ToolDeltaConfig = field(default_factory=ToolDeltaConfig)


@dataclass
class LevelConfig:
    name: str = "level_1"
    max_tokens: int = 16384
    compression_mode: str = "lossless"
    prune_ratio: float = 1.0
    use_onnx: bool = False


@dataclass
class AdaptivePipelineConfig:
    enabled: bool = True
    levels: List[LevelConfig] = field(default_factory=lambda: [
        LevelConfig(name="level_1", max_tokens=131072, compression_mode="lossless", prune_ratio=1.0),       # < 128k: 纯无损结构压缩
        LevelConfig(name="level_2", max_tokens=524288, compression_mode="lightweight", prune_ratio=0.90),   # 128k ~ 512k: AST骨架与堆栈剪枝
        LevelConfig(name="level_3", max_tokens=2097152, compression_mode="deep", prune_ratio=0.60, use_onnx=False), # 512k ~ 2M+: 深度修剪与激进语义去重
    ])
    protected_keywords: List[str] = field(default_factory=lambda: [
        "CRITICAL", "FATAL", "TODO", "FIXME", "EXCEPTION"
    ])


@dataclass
class CacheGuardConfig:
    enabled: bool = True
    freeze_system_prompt: bool = True
    freeze_prefix_rounds: int = 2
    auto_anthropic_cache_control: bool = True
    min_cacheable_tokens: int = 1024
    cache_ttl_seconds: int = 3600
    cold_recompact_enabled: bool = True
    provider_read_discounts: Dict[str, float] = field(default_factory=lambda: {
        "anthropic": 0.9,
        "deepseek": 0.9,
        "openai": 0.5,
        "gemini": 0.9,
        "google": 0.9,
        "bedrock": 0.9,
        "default": 0.5,
    })
    provider_write_penalties: Dict[str, float] = field(default_factory=lambda: {
        "anthropic": 0.25,
        "deepseek": 0.0,
        "openai": 0.0,
        "gemini": 0.0,
        "google": 0.0,
        "default": 0.0,
    })


@dataclass
class TargetFileConfig:
    path: str
    marker: str = "CTXGUARD_AUTO_RULES"


@dataclass
class LearnConfig:
    enabled: bool = True
    storage_db: str = ".ctxguard.db"
    detect_loop_threshold: int = 3
    target_files: List[TargetFileConfig] = field(default_factory=lambda: [
        TargetFileConfig(path="CLAUDE.local.md", marker="CTXGUARD_AUTO_RULES"),
        TargetFileConfig(path=".cursorrules", marker="CTXGUARD_AUTO_RULES"),
        TargetFileConfig(path=".windsurfrules", marker="CTXGUARD_AUTO_RULES"),
    ])


@dataclass
class SemanticCacheConfig:
    enabled: bool = True
    similarity_threshold: float = 0.95
    max_entries: int = 1000
    ttl_seconds: int = 300
    use_exact_matching: bool = True


@dataclass
class PiggybackExtractionConfig:
    enabled: bool = True


@dataclass
class OutputShapingConfig:
    enabled: bool = False
    level: int = 2


@dataclass
class ProactiveExpansionConfig:
    enabled: bool = True
    relevance_threshold: float = 0.35
    max_expansions: int = 2
    max_content_chars: int = 1200
    max_context_age_seconds: float = 300.0  # Strict 5-minute TTL to prevent stale CLI dumps
    max_contexts: int = 100                 # LRU eviction capacity
    skip_in_cache_mode: bool = False        # Prioritize upstream KV Cache stability over proactive backfill
    blocked_keywords: List[str] = field(default_factory=lambda: [
        "pytest", "git status", "git diff", "incremental paging queries",
        "CTXGUARD_AUTO_RULES", "Do not repeatedly execute", "Headroom Learned Patterns"
    ])


@dataclass
class AppConfig:
    server: ServerConfig = field(default_factory=ServerConfig)
    upstream: UpstreamConfig = field(default_factory=UpstreamConfig)
    dedup: DedupConfig = field(default_factory=DedupConfig)
    structural_compression: StructuralCompressionConfig = field(default_factory=StructuralCompressionConfig)
    adaptive_pipeline: AdaptivePipelineConfig = field(default_factory=AdaptivePipelineConfig)
    cache_guard: CacheGuardConfig = field(default_factory=CacheGuardConfig)
    thinking_manager: ThinkingManagerConfig = field(default_factory=ThinkingManagerConfig)
    learn: LearnConfig = field(default_factory=LearnConfig)
    semantic_cache: SemanticCacheConfig = field(default_factory=SemanticCacheConfig)
    piggyback_extraction: PiggybackExtractionConfig = field(default_factory=PiggybackExtractionConfig)
    output_shaper: OutputShapingConfig = field(default_factory=OutputShapingConfig)
    proactive_expansion: ProactiveExpansionConfig = field(default_factory=ProactiveExpansionConfig)

