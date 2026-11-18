import unittest
from pathlib import Path


def load_tests(loader, tests, pattern):  # noqa: ARG001 - assinatura exigida pelo unittest
    """Permite `python -m unittest rastreador_empenhos.tests.suite`."""
    return loader.discover(start_dir=str(Path(__file__).parent), pattern="test_*.py")
