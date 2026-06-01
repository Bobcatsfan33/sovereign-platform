"""AI pack domain models — inference endpoints and RAG workspaces.

These are the request/parameter shapes the AI pack's renderers consume.
They are deliberately pack-local Pydantic models (not chassis models):
the chassis stays AI-agnostic, and the pack owns its vocabulary
(model ids, accelerator types, context windows, data-residency).

The renderers turn an `InferenceEndpointParams` into a Kubernetes
Deployment+Service manifest applied through the chassis's `k8s-apply`
executor (Step 0.2), so the pack ships no apply logic of its own.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Accelerator = Literal["cpu", "a10", "a100", "h100"]
Classification = Literal["U", "CUI", "SECRET"]


class InferenceEndpointParams(BaseModel):
    """Provisioning parameters for a managed model-serving endpoint."""

    model_id: str = Field(min_length=1)
    # Serving engine — vLLM is the chassis default; packs can add more.
    engine: Literal["vllm", "tgi"] = "vllm"
    accelerator: Accelerator = "a10"
    replicas: int = Field(default=1, ge=1, le=64)
    max_context_tokens: int = Field(default=8192, ge=512, le=1_000_000)
    namespace: str = "sovereign-ai"
    # Compliance-relevant declarations the policy layer reads.
    classification: Classification = "U"
    data_residency: str = "us-gov-west-1"
    pii_redaction: bool = True
    tls: bool = True
    logging_enabled: bool = True


class RagWorkspaceParams(BaseModel):
    """Provisioning parameters for a retrieval-augmented-generation
    workspace: a vector store plus an ingestion pipeline fed by the
    chassis connector subsystem (S3/GitHub/SharePoint)."""

    name: str = Field(min_length=1)
    embedding_model: str = "text-embedding-3-large"
    vector_store: Literal["pgvector", "qdrant", "milvus"] = "pgvector"
    namespace: str = "sovereign-ai"
    connectors: list[str] = Field(default_factory=list)
    classification: Classification = "CUI"
    data_residency: str = "us-gov-west-1"
    encryption_at_rest: bool = True
    pii_redaction: bool = True


# Accelerators that require a GPU node pool / quota (for the pack's
# quota + policy hooks). cpu is the only non-GPU option.
GPU_ACCELERATORS: frozenset[str] = frozenset({"a10", "a100", "h100"})


def is_gpu(accelerator: str) -> bool:
    return accelerator in GPU_ACCELERATORS
