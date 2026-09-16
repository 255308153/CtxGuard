"""Semantic token scoring and classification pruner based on LLMLingua-2 principles."""

from typing import List, Set
from ctxguard.core.compressors.base import BaseCompressor
from ctxguard.core.context import RequestContext, Message
from ctxguard.plugins.onnx.tokenizer import FastTokenizer
from ctxguard.plugins.onnx.model_loader import ONNXModelLoader


# High value code & structural anchors
CODE_KEYWORDS: Set[str] = {
    "def", "class", "async", "await", "return", "import", "from", "for", "while",
    "if", "elif", "else", "try", "except", "finally", "with", "as", "const",
    "let", "var", "function", "interface", "type", "export", "default", "SELECT",
    "INSERT", "UPDATE", "DELETE", "FROM", "WHERE", "JOIN", "TABLE", "CREATE",
}

# Common conversational filler words suitable for low-loss pruning in ultra-long contexts
LOW_VALUE_STOPWORDS: Set[str] = {
    "basically", "essentially", "actually", "literally", "furthermore", "moreover",
    "additionally", "please", "kindly", "note", "certainly", "absolutely", "definitely",
    "perhaps", "maybe", "somewhat", "honestly", "frankly", "obviously", "clearly",
}


class SemanticPruner(BaseCompressor):
    """Semantic Token classifier and pruner implementing LLMLingua-2 style density selection."""

    def __init__(
        self,
        protected_keywords: List[str] = None,
        model_path: str = None,
        target_prune_ratio: float = 0.85,
    ):
        self.protected_keywords = set(protected_keywords or ["CRITICAL", "TODO", "FIXME", "EXCEPTION", "ERROR"])
        self.loader = ONNXModelLoader(model_path)
        self.target_prune_ratio = target_prune_ratio

    @property
    def name(self) -> str:
        return "semantic_pruner"

    def is_applicable(self, context: RequestContext) -> bool:
        # Cache-Aware Invariant: If session already has active cloud KV cache,
        # never run lossy semantic pruning unless in 'deep' extreme compression mode,
        # ensuring 100% prefix byte stability and KV cache hit rate (Cache > Lossy Compression).
        if context.state.get("has_active_cache", False):
            mode = context.state.get("compression_mode", "lossless")
            if mode != "deep":
                return False

        # Activated when active level is 'deep' or explicit target_prune_ratio < 0.95
        mode = context.state.get("compression_mode", "lossless")
        return mode in {"deep", "semantic"} or context.state.get("target_prune_ratio", 1.0) < 0.95

    def process(self, context: RequestContext, target_messages: list[Message]) -> None:
        """Process target messages in place using dynamic target_prune_ratio from context state."""
        ratio = context.state.get("target_prune_ratio", self.target_prune_ratio)
        for msg in target_messages:
            # Never semantically prune system instructions or short prompts
            if msg.role == "system":
                continue
            text = msg.get_text_content()
            if text and len(text) >= 200:
                optimized = self.prune_text(text, keep_ratio=ratio)
                if optimized != text:
                    msg.set_text_content(optimized)
                    if self.name not in context.applied_compressors:
                        context.applied_compressors.append(self.name)

    def _score_token(self, token: str) -> float:
        """Assign importance score (0.0 to 1.0) to a token."""
        stripped = token.strip()
        if not stripped:
            # Whitespace
            return 0.5

        # Protected keywords always retained
        if stripped in self.protected_keywords:
            return 1.0

        # Code keywords get high retention priority
        if stripped in CODE_KEYWORDS:
            return 0.95

        # Numbers and identifiers
        if stripped.isalnum():
            if stripped.lower() in LOW_VALUE_STOPWORDS:
                return 0.1
            return 0.7

        # Punctuation / Brackets
        if stripped in "{}[]():;.,=><+-*/":
            return 0.9

        return 0.5

    def prune_text(self, text: str, keep_ratio: float = 0.85) -> str:
        """Prune text down to target keep_ratio while retaining high information density."""
        if not text or keep_ratio >= 1.0:
            return text

        tokens = FastTokenizer.tokenize(text)
        if len(tokens) < 10:
            return text

        # Score every token
        scores = [self._score_token(t) for t in tokens]

        # Calculate target number of tokens to keep
        target_count = max(1, int(len(tokens) * keep_ratio))
        if target_count >= len(tokens):
            return text

        # Determine threshold score via sorting
        sorted_scores = sorted(scores, reverse=True)
        threshold_score = sorted_scores[target_count - 1]

        # Filter tokens preserving order
        kept_tokens = []
        kept_count = 0
        for token, score in zip(tokens, scores):
            if score >= threshold_score or token.strip() in self.protected_keywords:
                kept_tokens.append(token)
                kept_count += 1
                if kept_count >= target_count and score <= threshold_score:
                    # Satisfied quota
                    pass
            elif token.isspace():
                # Keep whitespace if surrounding tokens were kept to prevent jamming
                if kept_tokens and not kept_tokens[-1].isspace():
                    kept_tokens.append(" ")

        return FastTokenizer.detokenize(kept_tokens)

    def compress_text(self, text: str) -> str:
        return self.prune_text(text, keep_ratio=self.target_prune_ratio)
