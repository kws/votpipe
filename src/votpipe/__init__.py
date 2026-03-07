"""Streaming VOTable parser for Python.

Parse large VOTable files without loading them into memory. Supports TABLEDATA,
BINARY, and BINARY2 serializations. Convert to Parquet, CSV, or ECSV with
optional column selection and row filtering.

Public API:
  - parse_votable: Batch callback parser
  - VOTableStreamingParser: Row-dict iterator
  - compile_row_transform: Compile --select/--where for batch transforms
"""

from importlib.metadata import version

from votpipe._compile import compile_row_transform
from votpipe._generator import VOTableStreamingParser
from votpipe._parser import parse_votable

__version__ = version("votpipe")

__all__ = [
    "compile_row_transform",
    "parse_votable",
    "VOTableStreamingParser",
    "__version__",
]
