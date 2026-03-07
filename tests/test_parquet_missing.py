import importlib
import sys

import pytest


def test_import_parquet_without_pyarrow(monkeypatch):
    # Ensure we exercise the import path again, not a cached module.
    sys.modules.pop("votpipe.parquet", None)

    # Simulate missing optional dependency.
    monkeypatch.setitem(sys.modules, "pyarrow", None)
    monkeypatch.setitem(sys.modules, "pyarrow.parquet", None)

    with pytest.raises(ImportError) as excinfo:
        importlib.import_module("votpipe.parquet")

    msg = str(excinfo.value)
    assert "pyarrow" in msg
    assert "votpipe[parquet]" in msg
