from pydantic import BaseModel


class PastIncident(BaseModel):
    id: str
    title: str
    root_cause: str
    fix: str
    similarity: float


def search_incidents(query: str, k: int = 5) -> list[PastIncident]:
    """Top-k similar past incidents from the knowledge base (pgvector)."""
    # TODO(phase 6): embed query, cosine search over knowledge_items
    return []
