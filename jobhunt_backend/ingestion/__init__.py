"""Pack D source-neutral ingestion primitives."""

from .archive import RawArchive, StoredBlob
from .manual import ManualImportAdapter
from .nav import NavCollectionCoordinator, NavDiscoveryMatcher
from .jobbnorge import (
    JobbnorgeCollectionCoordinator,
    JobbnorgeDiscoveryMatcher,
    jobbnorge_extraction_batch,
)
from .pracuj import PracujMailCoordinator

__all__ = [
    "ManualImportAdapter",
    "NavCollectionCoordinator",
    "NavDiscoveryMatcher",
    "JobbnorgeCollectionCoordinator",
    "JobbnorgeDiscoveryMatcher",
    "jobbnorge_extraction_batch",
    "PracujMailCoordinator",
    "RawArchive",
    "StoredBlob",
]
