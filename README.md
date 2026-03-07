# votpipe

[![Tests](https://github.com/kws/votpipe/actions/workflows/tests.yml/badge.svg)](https://github.com/kws/votpipe/actions/workflows/tests.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Streaming VOTable processing for Python**

`votpipe` is a lightweight streaming parser for large VOTable files.
It allows you to process rows incrementally, apply transformations or filters, and write the results to formats such as Parquet, CSV, or Astropy tables.

The focus is simplicity and pipeline integration:

* **stream rows without loading the entire table into memory**
* **transform rows as they pass through the pipeline**
* **write to modern formats such as Parquet**
* **install and run easily with `pip` or `pipx`**

Unlike tools that require a Java runtime or complex setup, `votpipe` is a small Python-native utility designed to integrate naturally into data pipelines.

---

# Features

* Streaming VOTable parsing (TABLEDATA, BINARY, BINARY2)
* Batch callback API and row-iterator API
* CLI: `votpipe convert` with column selection (`--select`) and row filtering (`--where`)
* Compiled filter expressions (e.g. `parallax > 10 and phot_g_mean_mag < 15`)
* Works with arbitrarily large tables
* Parquet, CSV, and ECSV output (CLI and Python); compression via `.gz` or `.xz` extension

Supported VOTable serializations:

* `TABLEDATA`
* `BINARY`
* `BINARY2`

External serializations such as `FITS` and `PARQUET` references are intentionally out of scope for the core parser.

---

## Comparison with STILTS

[`STILTS`](http://www.star.bris.ac.uk/~mbt/stilts/) is a powerful and mature toolkit for working with VOTable and other astronomy table formats. If you simply need to convert tables between formats or perform standard VO table operations, STILTS is often the best and most feature-complete solution.

`votpipe` is designed for a different niche: **Python-native streaming pipelines**. It can be installed and run with a single `pip install votpipe[cli,parquet]` or `pipx install votpipe[cli,parquet]`, without requiring a Java runtime or managing multiple JAR dependencies. It is particularly useful when you want to integrate VOTable processing directly into a Python workflow, apply custom filtering or transformations in Python, or stream large VOTables directly into modern analytics formats such as Parquet. 

In short:

* **Use STILTS** if you need the most complete astronomy table toolkit and are comfortable working with the Java-based ecosystem.
* **Use votpipe** if you want a lightweight Python tool that streams VOTables into Python pipelines, supports simple CLI filtering (`--select`, `--where`), and writes directly to Parquet, CSV, or ECSV with minimal setup.

---

# Installation

Install for CLI use (includes convert command and progress bar):

```bash
pip install votpipe[cli,parquet]
```

Or with pipx:

```bash
pipx install votpipe[cli,parquet]
```

Minimal install (Python API only, no CLI deps):

```bash
pip install votpipe
```

---

# Command Line Usage

The CLI provides a single command, `convert`, which streams a VOTable to Parquet, CSV, or ECSV with optional column selection and row filtering. Install CLI dependencies with `pip install votpipe[cli]` or `pip install votpipe[parquet,cli]`.

Output format is detected from the output file extension (e.g. `.parquet`, `.csv`, `.ecsv`, `.csv.gz`, `.ecsv.xz`), or set explicitly with `--format auto|csv|ecsv|parquet`. Default output path replaces `.vot`/`.vot.gz` with the appropriate extension for the chosen format.

Basic conversion:

```bash
votpipe convert input.vot.gz
votpipe convert input.vot.gz output.parquet
votpipe convert input.vot.gz output.csv
votpipe convert input.vot.gz output.ecsv.gz
votpipe convert input.vot.gz --format ecsv
```

Select specific columns:

```bash
votpipe convert input.vot.gz output.parquet \
  --select source_id,ra,dec,parallax
```

Filter rows with a `--where` expression:

```bash
votpipe convert input.vot.gz output.parquet \
  --where "parallax > 10 and phot_g_mean_mag < 15"
```

Combined select and filter:

```bash
votpipe convert input.vot.gz output.parquet \
  --select source_id,ra,dec,parallax \
  --where "parallax > 10 and phot_g_mean_mag < 15"
```

Other options:

- `--progress` / `--no-progress` — show a progress bar (default: on)
- `--format` — output format: `auto` (default, from extension), `csv`, `ecsv`, or `parquet`
- `--compression` — Parquet only: `zstd` (default), `snappy`, or `none`. CSV/ECSV use `.gz` or `.xz` in the filename.
- `--batch-size` — max rows per batch (default: 8192)

**Filter expression (`--where`)** supports column names, numeric/string/bool/`None` constants, and:

- Boolean: `and`, `or`, `not`
- Comparisons: `==`, `!=`, `<`, `<=`, `>`, `>=`, `is None`, `is not None`
- Chained comparisons: e.g. `0 < parallax <= 10`

Nullable columns are treated as false in comparisons when the value is `None` (e.g. `parallax > 10` drops nulls).

---

# Python Usage

You can consume parsed data in two ways; the **shape of the data** differs:

| API | What you get | Row shape |
|-----|----------------|-----------|
| **Batch callback** | `on_batch(fields, rows)` called repeatedly | `rows` is a list of **tuples**; each tuple has values in the same order as `fields` (no column names). |
| **Row iterator** | Iterate over the stream | Each item is one **dict** keyed by column name (e.g. `row["ra"]`). |

Use the batch API when you want maximum throughput and are feeding a batch-oriented sink (Parquet, CSV adapter, or `CompiledBatchQuery`). Use the iterator when you want to loop over rows by name or compose with Python generators.

## Batch callback interface

`parse_votable(source, on_batch, batch_size=8192)` parses the VOTable and calls `on_batch(fields, rows)` for each batch. Here `fields` is a list of field metadata dicts (name, datatype, etc.) and `rows` is a list of **tuples**: each tuple is one row, with values in the same order as `fields`. There are no column names in the row data—you use the field list to interpret indices. No threading; lowest overhead. Use it when pushing directly into a sink such as `ParquetAdapter` or `CompiledBatchQuery`.

```python
from votpipe import parse_votable
from votpipe.parquet import ParquetAdapter

with ParquetAdapter("output.parquet") as parquet:
    parse_votable("table.vot.gz", parquet.on_batch)
```

With column selection and filtering (same logic as the CLI):

```python
from votpipe import parse_votable
from votpipe.parquet import ParquetAdapter
from votpipe.query import CompiledBatchQuery

with ParquetAdapter("output.parquet") as parquet:
    query = CompiledBatchQuery(
        parquet.on_batch,
        select="source_id,ra,dec,parallax",
        where="parallax > 10 and phot_g_mean_mag < 15",
    )
    with query:
        parse_votable("table.vot.gz", query.on_batch)
```

## Iterator interface

`VOTableStreamingParser(source)` is iterable and yields **one row per item**, each row as a **dict** with column names as keys (e.g. `row["ra"]`). Unlike the batch API, you get named access per row. The implementation uses a background thread and a queue to bridge SAX’s push model to Python’s pull model. Use it when you want to filter, transform, or chain row streams and prefer dict-style access.

```python
from votpipe import VOTableStreamingParser

for row in VOTableStreamingParser("table.vot.gz"):
    print(row["source_id"], row["ra"], row["dec"])  # each row is a dict
```

## Which interface should I use?

* **Batch callback** — Tuples in field order; zero threading overhead; best for one-shot conversion (e.g. VOTable → Parquet with optional `--select`/`--where`). Use `parse_votable` with `ParquetAdapter` and optionally `CompiledBatchQuery`.
* **Iterator** — Dicts keyed by column name; composable with generator transforms and `for` loops. Slightly higher cost due to the thread and queue. Use `VOTableStreamingParser` when you need row-by-row logic in Python or named column access.

---

# Streaming Pipelines

For batch-oriented conversion with filtering, use the CLI or the Python batch API with `CompiledBatchQuery` (see **Batch callback interface** above); the sink receives batches of tuples. For row-by-row logic with dict access, use `VOTableStreamingParser` and compose with generator transforms.

Example: filter rows in Python and pass batches to Parquet.

```python
from votpipe import parse_votable
from votpipe.parquet import ParquetAdapter
from votpipe.query import CompiledBatchQuery

with ParquetAdapter("output.parquet") as parquet:
    query = CompiledBatchQuery(parquet.on_batch, where="parallax > 10")
    with query:
        parse_votable("input.vot.gz", query.on_batch)
```

Or iterate and transform row dicts with `VOTableStreamingParser`, then feed a custom sink (e.g. build a list or write CSV) in your own loop.

---

# Row Transformations

When using the **iterator** (`VOTableStreamingParser`), you get a stream of row **dicts**. Transforms on that stream can:

* drop rows
* mutate rows
* emit multiple rows

Example (each `row` is a dict, so you can use `row["column_name"]`):

```python
from votpipe import VOTableStreamingParser

def add_distance(rows):
    for row in rows:
        if row["parallax"] is None:
            continue
        row["distance_pc"] = 1000.0 / row["parallax"]
        yield row

# Iterator yields dicts; batch API would give you (fields, list of tuples).
for row in add_distance(VOTableStreamingParser("input.vot.gz")):
    process(row)
```

---

# Astropy Integration

You can consume the row stream from `VOTableStreamingParser` and build an `astropy.table.Table` (e.g. by collecting rows into a list and calling `Table(rows)`). Because that builds the full table in memory, there is little advantage over using Astropy’s own VOTable reader unless you want to **filter or aggregate** in a streaming way before materializing the table. For large files, the batch callback + Parquet path is usually preferable; read the Parquet output with Astropy or pandas as needed.

---

# Output Formats

* **Parquet** — CLI (`votpipe convert` with `.parquet` or `--format parquet`) and `votpipe.parquet.ParquetAdapter`. Install with `pip install votpipe[parquet]`.
* **CSV** — CLI (e.g. `output.csv`, `output.csv.gz`, `output.csv.xz` or `--format csv`) and `votpipe.csv.CsvAdapter`.
* **ECSV** — CLI (e.g. `output.ecsv`, `output.ecsv.gz`, `output.ecsv.xz` or `--format ecsv`) and `votpipe.csv.EcsvAdapter`. Compression for CSV/ECSV is inferred from the output filename (`.gz` or `.xz`; stdlib `gzip` and `lzma`).

---

# Design Philosophy

`votpipe` follows a simple streaming model:

```
VOTable → parser → row stream → transform → serializer
```

The parser produces rows lazily.
Transforms operate on row streams.
Serializers consume the stream and write output.

This design allows large datasets to be processed with predictable memory usage.

---

# Scope

`votpipe` focuses on **streaming VOTable payloads embedded directly in XML**.

Supported:

* `TABLEDATA`
* `BINARY`
* `BINARY2`

Not supported:

* `FITS` external serialization
* `PARQUET` external serialization

These serializations reference external files and are better handled by specialised readers.

---

# Development Status

`votpipe` is an early-stage project. Implemented:

* Streaming parser for TABLEDATA, BINARY, BINARY2 (including `.vot.gz`)
* CLI: `votpipe convert` with `--select`, `--where`, `--format`, `--compression`, `--batch-size`, optional progress bar; Parquet, CSV, and ECSV output (format/compression from extension or `--format`)
* Compiled filter/select: `CompiledBatchQuery` with a small expression language for `--where`
* Batch callback API: `parse_votable` + `ParquetAdapter` (and optionally `CompiledBatchQuery`)
* Row iterator: `VOTableStreamingParser` yielding row dicts
* Parquet and CSV/ECSV adapters for programmatic use

Planned improvements include:

* full datatype coverage
* round-trip tests against Astropy
* improved metadata preservation

---

# License

MIT License.

