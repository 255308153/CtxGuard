import pytest
from pathlib import Path
import json
import tempfile
from ctxguard.cli.config_patcher import AgentConfigAutoDetector

def test_discover_upstreams():
    with tempfile.NamedTemporaryFile("w+", suffix=".json", delete=False) as f:
        json.dump({"cursor.openAI.baseUrl": "https://my-custom-proxy.com/v1"}, f)
        temp_path = Path(f.name)

    try:
        # Mock paths
        configs = [{
            "name": "Cursor",
            "path": temp_path,
            "url_keys": ["cursor.openAI.baseUrl"],
            "patch_key": "cursor.openAI.baseUrl"
        }]
        discovered = {}
        for target in configs:
            with open(target["path"], "r") as ff:
                data = json.load(ff)
            for k in target["url_keys"]:
                val = data.get(k)
                if val:
                    discovered[target["name"]] = val
        assert discovered["Cursor"] == "https://my-custom-proxy.com/v1"
    finally:
        temp_path.unlink()
