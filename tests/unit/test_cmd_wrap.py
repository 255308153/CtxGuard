import pytest
import sys
from ctxguard.cli.cmd_wrap import _ensure_proxy_running

def test_ensure_proxy_running_live():
    # Tests that health check against live proxy returns without error
    _ensure_proxy_running(8787)
