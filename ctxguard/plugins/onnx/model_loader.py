"""ONNX Runtime session lazy loader with graceful degradation."""

from pathlib import Path
from typing import Any, Optional
from ctxguard.utils.console import Console


class ONNXModelLoader:
    """Manages ONNX Runtime CPU inference session."""

    def __init__(self, model_path: Optional[str] = None):
        self.model_path = model_path
        self._session: Optional[Any] = None
        self._checked: bool = False
        self._available: bool = False

    def is_available(self) -> bool:
        """Check if onnxruntime is installed and model is loadable."""
        if not self._checked:
            self._checked = True
            try:
                import onnxruntime as ort
                self._available = True
            except ImportError:
                self._available = False
        return self._available

    def get_session(self) -> Optional[Any]:
        """Lazy load ONNX inference session."""
        if not self.is_available():
            return None

        if self._session is None and self.model_path and Path(self.model_path).exists():
            try:
                import onnxruntime as ort
                opts = ort.SessionOptions()
                opts.intra_op_num_threads = 2
                opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
                self._session = ort.InferenceSession(self.model_path, opts, providers=["CPUExecutionProvider"])
            except Exception as e:
                Console.warning(f"Failed to load ONNX model at {self.model_path}: {e}")
                self._session = None

        return self._session
