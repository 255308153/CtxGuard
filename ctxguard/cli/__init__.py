"""CLI subsystem for CtxGuard."""

__all__ = ["main"]


def main():
    from ctxguard.cli.main import main as _main
    return _main()
