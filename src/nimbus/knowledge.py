"""Readable Markdown sources, policy loading, and replaceable retrieval."""

import re
from pathlib import Path

import numpy as np
import yaml
from pydantic import ValidationError

from .errors import NimbusError
from .models import MODELS, resolve_model
from .schemas import Policy
from .util import fingerprint


def read_source(path: Path) -> tuple[dict, str]:
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---\n"):
        return {}, raw
    parts = raw.split("---", 2)
    try:
        metadata = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError as error:
        raise NimbusError(
            "invalid_knowledge_metadata", f"Invalid front matter in {path.name}."
        ) from error
    if not isinstance(metadata, dict):
        raise NimbusError("invalid_knowledge_metadata", f"Invalid front matter in {path.name}.")
    return metadata, parts[2].strip()


class Knowledge:
    def __init__(self, directory: Path):
        self.directory = Path(directory)

    def sources(self):
        known_ids = set()
        for path in sorted(self.directory.rglob("*.md")):
            metadata, body = read_source(path)
            if "source_id" in metadata:
                if not isinstance(metadata["source_id"], str) or not metadata["source_id"].strip():
                    raise NimbusError(
                        "invalid_knowledge_metadata", "Knowledge source_id must be nonempty text."
                    )
                if metadata["source_id"] in known_ids:
                    raise NimbusError(
                        "duplicate_knowledge_id", "Each knowledge source needs a unique source_id."
                    )
                known_ids.add(metadata["source_id"])
                yield path, metadata, body

    def policy(self, policy_id: str):
        # Validate the complete source catalog before selecting an authority.
        for _path, metadata, body in list(self.sources()):
            if (
                metadata.get("source_id") == policy_id
                and metadata.get("document_type") == "verification_policy"
            ):
                try:
                    policy = Policy.model_validate(metadata)
                except ValidationError as error:
                    raise NimbusError(
                        "invalid_policy", "Verification policy metadata failed validation."
                    ) from error
                return policy, fingerprint({"metadata": metadata, "body": body})
        raise NimbusError("policy_not_found", "Select an existing verification policy.", 404)

    def chunks(self):
        chunks = []
        for path, metadata, body in self.sources():
            if metadata.get("approval_status") not in {"approved", "approved_demo"}:
                continue
            for number, section in enumerate(re.split(r"(?m)^## ", body)):
                section = section.strip()
                if not section:
                    continue
                # Bound sections before any model sees them. Token packing is
                # additionally checked by the model's actual tokenizer/runtime.
                for offset in range(0, len(section), 1800):
                    text = section[offset : offset + 2000]
                    chunk_id = fingerprint(
                        {
                            "source": metadata["source_id"],
                            "section": number,
                            "offset": offset,
                            "text": text,
                        }
                    )[:24]
                    chunks.append(
                        {
                            "_id": chunk_id,
                            "source_id": metadata["source_id"],
                            "text": text,
                            "source_path": str(path.relative_to(self.directory)),
                            "source_hash": fingerprint({"metadata": metadata, "body": body}),
                            "machine_types": metadata.get("machine_types", ["general"]),
                            "approval_status": metadata["approval_status"],
                        }
                    )
        return chunks

    def search(self, query: str, machine_type: str = "general", limit: int = 5, encoder=None):
        chunks = [
            chunk
            for chunk in self.chunks()
            if machine_type in chunk["machine_types"] or "general" in chunk["machine_types"]
        ]
        if not chunks:
            return []
        if encoder is None:
            query_terms = set(re.findall(r"\w+", query.casefold()))
            for chunk in chunks:
                terms = set(re.findall(r"\w+", chunk["text"].casefold()))
                chunk["score"] = len(query_terms & terms) / max(1, len(query_terms))
        else:
            vectors = encoder.documents([chunk["text"] for chunk in chunks])
            query_vector = encoder.query(query)
            for chunk, score in zip(chunks, cosine_scores(vectors, query_vector), strict=True):
                chunk["score"] = float(score)
        matches = [chunk for chunk in chunks if chunk["score"] > 0]
        return sorted(matches, key=lambda chunk: chunk["score"], reverse=True)[:limit]


def cosine_scores(documents, query):
    matrix = np.asarray(documents, dtype=np.float32)
    vector = np.asarray(query, dtype=np.float32)
    if matrix.ndim != 2 or vector.ndim != 1 or matrix.shape[1] != len(vector):
        raise NimbusError(
            "embedding_dimensions_mismatch",
            "All query/document vectors must use the same dimension.",
        )
    norms = np.linalg.norm(matrix, axis=1) * np.linalg.norm(vector)
    return np.divide(
        matrix @ vector, norms, out=np.zeros(len(matrix), dtype=np.float32), where=norms > 0
    )


class OpenEncoder:
    """Optional adapter: importing knowledge does not import torch or download weights."""

    def __init__(self, model_id=None, revision=None, device="cpu"):
        from sentence_transformers import SentenceTransformer

        from .inference.base import pinned_revision

        model_id = model_id or MODELS["embedding"].model_id
        resolve_model(model_id, "embedding")
        self.model_id = model_id
        self.model_revision = pinned_revision(model_id, "embedding", revision)
        self.model = SentenceTransformer(model_id, revision=self.model_revision, device=device)

    def documents(self, texts):
        return self.model.encode(texts, normalize_embeddings=True)

    def query(self, text):
        return self.model.encode(
            [text],
            prompt="Instruct: Retrieve relevant factory handover procedures.\nQuery: ",
            normalize_embeddings=True,
        )[0]
