"""Repository implementations for the durable metadata tables."""

from trendsmapp.persistence.repositories.artifacts import ArtifactRepository
from trendsmapp.persistence.repositories.datasets import DatasetRepository
from trendsmapp.persistence.repositories.jobs import JobRepository
from trendsmapp.persistence.repositories.provenance import ProvenanceRepository
from trendsmapp.persistence.repositories.registries import RegistryRepository
from trendsmapp.persistence.repositories.runs import RunRepository
from trendsmapp.persistence.repositories.uploads import UploadRepository

__all__ = [
    "ArtifactRepository",
    "DatasetRepository",
    "JobRepository",
    "ProvenanceRepository",
    "RegistryRepository",
    "RunRepository",
    "UploadRepository",
]
