"""Load the official cached showcase-ecommerce MCP payloads into local DataHub.

This avoids the DataHub 1.6 CLI file-source issue observed with Python 3.12 while
still using DataHub's own REST emitter and the unmodified official payload files.
"""

from __future__ import annotations

import hashlib
import json
import os
from itertools import islice
from pathlib import Path
from typing import Iterator, Sequence, TypeVar

import requests
from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.emitter.rest_emitter import DatahubRestEmitter
from datahub.configuration.common import OperationalError

SHOWCASE_INDEX_URL = (
    "https://raw.githubusercontent.com/datahub-project/static-assets/main/"
    "datapacks/showcase-ecommerce/index.json"
)
BATCH_SIZE = 100
Item = TypeVar("Item")


def cache_path_for_url(cache_directory: Path, url: str) -> Path:
    """Match the official DataHub datapack cache naming convention."""

    return cache_directory / f"{hashlib.sha256(url.encode()).hexdigest()}.json"


def download_to_cache(cache_directory: Path, url: str) -> Path:
    """Download an official payload only when it is not already cached."""

    path = cache_path_for_url(cache_directory, url)
    if not path.exists():
        response = requests.get(url, timeout=90)
        response.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
    return path


def batched(items: Sequence[MetadataChangeProposalWrapper]) -> Iterator[Sequence[MetadataChangeProposalWrapper]]:
    """Yield bounded OpenAPI ingestion batches."""

    iterator = iter(items)
    while batch := list(islice(iterator, BATCH_SIZE)):
        yield batch


def load_payloads(cache_directory: Path) -> list[MetadataChangeProposalWrapper]:
    """Read the three official payload files referenced by the cached index."""

    index_path = download_to_cache(cache_directory, SHOWCASE_INDEX_URL)

    index = json.loads(index_path.read_text(encoding="utf-8"))
    base_url = SHOWCASE_INDEX_URL.rsplit("/", 1)[0]
    payloads: list[MetadataChangeProposalWrapper] = []

    for entry in index["files"]:
        filename = entry["path"] if isinstance(entry, dict) else entry
        file_path = download_to_cache(cache_directory, f"{base_url}/{filename}")
        records = json.loads(file_path.read_text(encoding="utf-8"))
        payloads.extend(MetadataChangeProposalWrapper.from_obj(record) for record in records)

    return payloads


def main() -> None:
    cache_directory = Path.home() / ".datahub" / "datapack-cache"
    server = os.getenv("DATAHUB_GMS_URL", "http://localhost:8080")
    token = os.getenv("DATAHUB_GMS_TOKEN") or None
    payloads = load_payloads(cache_directory)
    emitter = DatahubRestEmitter(
        gms_server=server,
        token=token,
        openapi_ingestion=True,
    )

    emitted = 0
    skipped = 0
    for batch_number, batch in enumerate(batched(payloads), start=1):
        try:
            emitter.emit_mcps(batch)
            emitted += len(batch)
            print(f"Emitted batch {batch_number}: {len(batch)} metadata change proposals")
        except OperationalError:
            # Static demo data can include aspects added after the local GMS release.
            # Fall back to individual emission so only unsupported aspects are skipped.
            for proposal in batch:
                try:
                    emitter.emit_mcp(proposal)
                    emitted += 1
                except OperationalError:
                    skipped += 1
                    print(
                        "Skipped unsupported proposal: "
                        f"{proposal.entityType}.{proposal.aspectName}"
                    )

    print(
        f"Loaded {emitted} compatible showcase-ecommerce proposals into {server}; "
        f"skipped {skipped} unsupported proposals."
    )


if __name__ == "__main__":
    main()
