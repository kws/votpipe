import queue
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO

from votpipe._parser import parse_votable


class VOTableStreamingParser:
    """
    Streaming VOTable parser. Accepts a path (str or Path), including .vot.gz,
    or a file-like object opened in binary mode. Iteration yields row dicts
    keyed by column name.
    """

    def __init__(self, source: str | Path | BinaryIO):
        self.source = source

    def __iter__(self) -> Iterator[tuple[list[dict], list[tuple]]]:
        _sentinel = object()
        q: queue.SimpleQueue = queue.SimpleQueue()

        def putter(fields, rows):
            q.put((fields, rows))

        t = threading.Thread(
            target=lambda: (parse_votable(self.source, putter), q.put(_sentinel)),
            daemon=True,
        )
        t.start()
        for fields, batch in iter(q.get, _sentinel):
            field_names = [f["name"] for f in fields]
            for row in batch:
                yield dict(zip(field_names, row, strict=True))
        t.join()
