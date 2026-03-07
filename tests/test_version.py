"""Package version consistency with metadata."""

import importlib.metadata

import votpipe


def test_version_consistency():
    """votpipe.__version__ matches importlib.metadata.version('votpipe')."""
    assert votpipe.__version__ == importlib.metadata.version("votpipe")
