"""The projection kernel: fold an append-only log into named derived views.

Three pieces, and a client imports the ones it needs:

* :mod:`~aj_crew.projection.definition` -- what a fold IS, declarable without
  importing the driver that runs it.
* :mod:`~aj_crew.projection.registry` -- the driver: per-store cells, the
  watermark that makes folding idempotent, and the change feed.
* :mod:`~aj_crew.projection.checkpoint` -- savepoints, so a resumed fold starts
  at a watermark instead of replaying the log. A client that never persists need
  not import it.

The kernel owns no carrier and no path. An event is an opaque payload whose ``seq``
is read through a client-supplied reader, so the member log's ``Event`` TypedDict
and the crew log's ``Entry`` dataclass drive the same registry while each type
stays in the package that owns it; and a concrete savepoint store is handed its
directory by the client.
"""

from aj_crew.projection.checkpoint import (
    EMPTY_WATERMARK,
    MAX_PAYLOAD_BYTES,
    PAYLOAD_VERSION,
    Admit,
    CheckpointStore,
    DirectoryCheckpointStore,
    Savepoint,
)
from aj_crew.projection.definition import ProjectionDefinition
from aj_crew.projection.registry import (
    OnChange,
    ProjectionRegistry,
    SeqOf,
    attribute_seq,
    mapping_seq,
)

__all__ = [
    "EMPTY_WATERMARK",
    "MAX_PAYLOAD_BYTES",
    "PAYLOAD_VERSION",
    "Admit",
    "CheckpointStore",
    "DirectoryCheckpointStore",
    "OnChange",
    "ProjectionDefinition",
    "ProjectionRegistry",
    "Savepoint",
    "SeqOf",
    "attribute_seq",
    "mapping_seq",
]
