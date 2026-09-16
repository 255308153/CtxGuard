import json
import os
from pathlib import Path
from typing import Dict, Any, List, Optional

class AgentConfigAutoDetector:
    """Auto-detects upstream base URLs and keys from Agent configs and routes them seamlessly."""

    UPSTREAM_RECORD_FILE = Path(".ctxguard_upstreams.json")

    @classmethod
    def get_known_agent_configs(cls) -> List[Dict[str, Any]]:
        home = Path.home()
        return [
            {
                "name": "Claude Code",
                "path": home / ".claude" / "config.json",
                "type": "json",
                "url_keys": ["anthropic_base_url", "base_url", "primary_url"],
                "patch_key": "anthropic_base_url",
            },
            {
                "name": "Cursor",
                "path": home / "Library" / "Application Support" / "Cursor" / "User" / "settings.json",
                "type": "json",
                "url_keys": ["cursor.openAI.baseUrl", "openai.baseUrl"],
                "patch_key": "cursor.openAI.baseUrl",
            },
            {
                "name": "Pi Agent",
                "path": home / ".pi" / "config.json",
                "type": "json",
                "url_keys": ["base_url", "openai_base_url", "anthropic_base_url"],
                "patch_key": "base_url",
            }
        ]

    @classmethod
    def discover_and_save_upstreams(cls) -> Dict[str, str]:
        """Reads original upstream URLs configured by user in agents and remembers them."""
        discovered = {}
        for target in cls.get_known_agent_configs():
            path: Path = target["path"]
            if path.exists():
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    for k in target["url_keys"]:
                        val = data.get(k)
                        if val and "127.0.0.1:8787" not in val and "localhost:8787" not in val:
                            discovered[target["name"]] = val
                            break
                except Exception:
                    pass
        if discovered:
            with open(cls.UPSTREAM_RECORD_FILE, "w", encoding="utf-8") as f:
                json.dump(discovered, f, indent=2)
        return discovered

    @classmethod
    def get_upstream_for_client(cls, client_name: str) -> Optional[str]:
        if cls.UPSTREAM_RECORD_FILE.exists():
            try:
                with open(cls.UPSTREAM_RECORD_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get(client_name)
            except Exception:
                pass
        return None
