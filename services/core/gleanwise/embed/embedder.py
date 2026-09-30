# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

"""Embedding backends. Instances are created once per process (see ``Services``)."""

from __future__ import annotations

import asyncio
import hashlib
import re
import threading
from typing import Any, Literal, Protocol

import numpy as np

from gleanwise.config import Settings
from gleanwise.errors import GleanWiseError

Kind = Literal["query", "passage"]
_TOKEN = re.compile(r"\w+", re.UNICODE)


class EmbeddingUnavailable(GleanWiseError):
    code = "embeddings_unavailable"
    status = 503
    action = "open_diagnostics"


class Embedder(Protocol):
    name: str

    async def embed(self, texts: list[str], kind: Kind = "passage") -> np.ndarray: ...
    async def warm(self) -> None: ...
    @property
    def loaded(self) -> bool: ...


def _unit(mat: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1
    return (mat / norms).astype(np.float32)


class HashEmbedder:
    """Deterministic hashed bag-of-n-grams. Not semantic — for tests and offline smoke runs."""

    name = "hash-256"

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    @property
    def loaded(self) -> bool:
        return True

    async def warm(self) -> None:
        return None

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        toks = [t.lower() for t in _TOKEN.findall(text)]
        grams = toks + [f"{a} {b}" for a, b in zip(toks, toks[1:], strict=False)]
        for g in grams:
            h = int.from_bytes(hashlib.blake2b(g.encode(), digest_size=8).digest(), "big")
            v[h % self.dim] += (
                1.0 if (h >> 63) & 1 else -1.0
            )  # signed hashing reduces collisions bias
        return v

    async def embed(self, texts: list[str], kind: Kind = "passage") -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return _unit(np.vstack([self._vec(t) for t in texts]))


_LOCAL_MODELS: dict[str, Any] = {}
_LOCAL_LOCK = threading.Lock()


class LocalEmbedder:
    """fastembed (ONNX, CPU). One model instance per process, loaded lazily on a worker thread."""

    def __init__(self, settings: Settings) -> None:
        self.model_name = settings.effective_embed_model()
        self.name = self.model_name
        self._cache = str(settings.resolved_data_dir() / "models")
        self._offline = settings.offline

    @property
    def loaded(self) -> bool:
        return self.model_name in _LOCAL_MODELS

    def _model(self) -> Any:
        with _LOCAL_LOCK:
            model = _LOCAL_MODELS.get(self.model_name)
            if model is None:
                from fastembed import TextEmbedding

                try:
                    model = TextEmbedding(
                        model_name=self.model_name,
                        cache_dir=self._cache,
                        local_files_only=self._offline,
                    )
                except Exception as exc:
                    raise EmbeddingUnavailable(
                        f"The embedding model '{self.model_name}' could not be loaded.",
                        hint=(
                            "It has not been downloaded and offline mode is on."
                            if self._offline
                            else "Check your internet connection for the one-time model download."
                        ),
                        detail=str(exc)[:200],
                    ) from exc
                _LOCAL_MODELS[self.model_name] = model
            return model

    async def warm(self) -> None:
        await asyncio.to_thread(self._model)

    def _prefix(self, kind: Kind) -> str:
        if "e5" in self.model_name.lower():
            return "query: " if kind == "query" else "passage: "
        return ""

    def _embed(self, texts: list[str], kind: Kind) -> np.ndarray:
        model = self._model()
        pre = self._prefix(kind)
        vecs = list(model.embed([pre + t for t in texts], batch_size=32))
        return _unit(np.vstack(vecs))

    async def embed(self, texts: list[str], kind: Kind = "passage") -> np.ndarray:
        if not texts:
            return np.zeros((0, 1), dtype=np.float32)
        return await asyncio.to_thread(self._embed, texts, kind)


class LiteLLMEmbedder:
    def __init__(self, settings: Settings) -> None:
        self.model_name = settings.embed_model
        self.name = f"litellm:{self.model_name}"
        self._key = settings.llm_api_key or None
        self._base = settings.llm_api_base or None
        self._loaded = False

    @property
    def loaded(self) -> bool:
        return self._loaded

    async def warm(self) -> None:
        await self.embed(["warm-up"])

    async def embed(self, texts: list[str], kind: Kind = "passage") -> np.ndarray:
        import litellm

        if not texts:
            return np.zeros((0, 1), dtype=np.float32)
        out: list[list[float]] = []
        for i in range(0, len(texts), 64):
            try:
                resp = await litellm.aembedding(
                    model=self.model_name,
                    input=texts[i : i + 64],
                    api_key=self._key,
                    api_base=self._base,
                    timeout=30,
                )
            except Exception as exc:
                raise EmbeddingUnavailable(
                    "The embedding provider returned an error.",
                    hint="Check the embedding model and key in Settings, or switch to the built-in local embedder.",
                    detail=str(exc)[:200],
                ) from exc
            out.extend(d["embedding"] for d in resp.data)
        self._loaded = True
        return _unit(np.asarray(out, dtype=np.float32))


def build_embedder(settings: Settings) -> Embedder:
    from gleanwise.egress.policy import assert_strict_local_embedder

    if settings.strict_local:
        assert_strict_local_embedder(settings.embedder, settings.llm_api_base, settings.local_hosts)
    if settings.embedder == "hash":
        return HashEmbedder()
    if settings.embedder == "litellm":
        return LiteLLMEmbedder(settings)
    return LocalEmbedder(settings)
