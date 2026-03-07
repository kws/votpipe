# AGENTS.md

## Purpose

This project provides a Python-native streaming parser and processing pipeline for VOTable data.

## Current implementation status

Implemented and documented:

- **Parser** — `parse_votable(source, on_batch, batch_size)` in `_parser.py`; supports TABLEDATA, BINARY, BINARY2; gzipped `.vot.gz` input. Emits batches of `(fields, rows)` with rows as tuples in field order.
- **CLI** — `votpipe convert INPUT [OUTPUT]` with `--select`, `--where`, `--progress`, `--compression`, `--batch-size`. Output is Parquet only. Entry point: `votpipe._cli:cli`.
- **Filters** — `CompiledBatchQuery` in `query.py` compiles `--select` (column list) and `--where` (expression string) against the first batch’s field metadata, then applies a fused filter+projection per batch. Expression language: column names, constants, `and`/`or`/`not`, comparisons, `is None`/`is not None`, chained comparisons. Null-safe.
- **Batch sinks** — `ParquetAdapter` (`parquet.py`), `DelimitedTextAdapter` (`csv.py`); both expose `on_batch(fields, rows)` and are used as context managers.
- **Row iterator** — `VOTableStreamingParser` in `_generator.py` yields row dicts (one per row) via a thread+queue adapter over the parser.

Not yet in CLI: CSV/ECSV output (adapters exist in Python). Expression language does not support arithmetic in this version.

The core goal is to make large VOTable files practical to use in normal Python workflows without loading the entire table into memory. The project should support inline VOTable serializations such as `TABLEDATA`, `BINARY`, and `BINARY2`, and should be suitable for conversion, filtering, transformation, and downstream serialization to formats such as Parquet, CSV, ECSV, or Astropy tables.

This is not intended to be a full in-memory table framework. It is a streaming tool with clear boundaries and composable parts.

## Core design preference

Prefer **generators over callbacks**.

The parser should expose a row-streaming interface that can be consumed naturally in Python:

- parse input into a stream of rows
- optionally transform that stream
- serialize the resulting stream

This is preferred over callback-driven designs because generators are:

- more idiomatic in Python
- easier to compose
- easier to test
- easier to reason about
- a better fit for streaming pipelines

Callbacks may still exist as thin adapters where genuinely useful, but they should not drive the architecture.

## Code layout

- `_parser.py` — SAX-based parser; `parse_votable()`; batch callback only.
- `_generator.py` — `VOTableStreamingParser` (row-dict iterator over parser).
- `_compile.py` — compiles `--select`/`--where` into a batch transform (used by `query.py`).
- `query.py` — `CompiledBatchQuery`; compiles on first batch, forwards transformed batches to a sink.
- `parquet.py` — `ParquetAdapter`; context manager, `on_batch` writes to Parquet.
- `csv.py` — `DelimitedTextAdapter` and ECSV-oriented helpers.
- `_cli.py` — Click group `cli` with `convert` command; wires parser → optional `CompiledBatchQuery` → `ParquetAdapter`.

Public API (`__init__.py`): `parse_votable`, `VOTableStreamingParser`, `compile_row_transform`.

## Architectural principles

Keep the pipeline conceptually simple:

`parse -> transform -> serialize`

Maintain clear separation of concerns:

- **Parsing** should only decode VOTable structure and values into rows
- **Transforms** should only consume rows and emit rows
- **Serialization** should only write output in the target format
- **Batching**, where needed, should live in serializers or helper utilities, not in the core parser contract

Avoid blending these responsibilities together.

## Code quality expectations

Prioritise maintainable, testable code.

### Separation of concerns
Modules and classes should each have one clear job. Avoid large classes that parse, transform, validate, and write output all in one place.

### DRY
Avoid duplicated parsing logic, datatype handling, null handling, and serialization behaviour. Shared behaviour should live in focused reusable helpers.

### Clear naming
Use explicit, unsurprising names. Prefer names that describe role and behaviour directly over clever or overly abstract names.

Good examples:
- `VOTableStreamingParser`
- `parse_fields`
- `decode_binary2_row`
- `ParquetAdapter`, `CompiledBatchQuery`
- `compile_row_transform`
- `iter_tabledata_rows`

Avoid vague names such as:
- `process`
- `handle`
- `do_parse`
- `utils` for unrelated helpers

### Testability
Code should be structured so that important logic can be tested in isolation.

In particular, make it easy to test:

- field parsing
- datatype decoding
- null and mask handling
- row emission
- generator transforms
- serializers
- gzip input handling
- error behaviour for unsupported constructs

Prefer small pure functions where possible.

### Readability
Optimise for code that is easy to inspect and modify. Streaming parsers can become difficult to follow if state is spread widely or hidden in complex control flow.

Keep functions short where practical. Document non-obvious invariants. Prefer straightforward control flow over cleverness.

### Explicit scope
Do not silently support partial or ambiguous behaviour. If a datatype, serialization mode, or VOTable feature is not yet supported, fail early with a clear error.

## Performance guidance

Performance matters, but only after correctness and clarity.

This project exists partly to support large files, so avoid obviously wasteful designs, but do not sacrifice maintainability for premature optimisation. Optimise only where profiling or realistic large-file usage shows the need.

## Testing expectations

Changes should include tests where appropriate.

At minimum, aim for coverage of:

- `TABLEDATA`
- `BINARY`
- `BINARY2`
- gzipped `.vot.gz` input
- representative datatype decoding
- missing-value handling
- row filtering / mutation (generator transforms and `CompiledBatchQuery` / `--where`)
- output writers (Parquet, CSV adapters)
- CLI `convert` with `--select` / `--where`
- failure cases for unsupported features

Round-trip and compatibility tests against Astropy fixtures should be added as support broadens.

## Style

Keep the public API small and coherent.

Prefer simple, composable interfaces over feature-heavy abstractions. This project should feel like a clean streaming utility, not a mini dataframe framework.
