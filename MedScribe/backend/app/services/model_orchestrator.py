"""
GPU model lifecycle manager. Enforces the resource plan's hard rule:
MedASR and MedGemma must never both be resident in VRAM simultaneously
on an 8GB card. This is a singleton with an explicit asyncio lock --
any code wanting a GPU model must go through here, never load a model
directly.

Phase 9 only registers MedASR. MedGemma's loader arrives in Phase 13,
plugged into this same orchestrator rather than a separate mechanism.
"""
import asyncio
import gc
from enum import Enum
from typing import Any, Callable

import torch

from app.core.metrics import GPU_MODEL_SLOT_LOADED, GPU_VRAM_RESERVED_BYTES, GPU_VRAM_USED_BYTES
from app.core.logging_config import get_logger

logger = get_logger(__name__)


class GPUModelSlot(str, Enum):
    MEDASR = "medasr"
    MEDGEMMA = "medgemma"  # loaded via AutoModelForImageTextToText, see medgemma_service.py


class ModelOrchestrator:
    """
    Singleton. Only one GPU model slot may be loaded at a time. Loading
    a different slot automatically unloads whatever was previously
    resident. Callers acquire the lock implicitly via get_model() --
    they never manage VRAM state themselves.
    """

    _instance: "ModelOrchestrator | None" = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._lock = asyncio.Lock()
            cls._instance._current_slot: GPUModelSlot | None = None
            cls._instance._current_model: Any = None
            cls._instance._current_processor: Any = None
        return cls._instance

    async def get_model(
        self,
        slot: GPUModelSlot,
        loader_fn: Callable[[], tuple[Any, Any]],
    ) -> tuple[Any, Any]:
        """
        loader_fn is a synchronous, blocking function that loads and
        returns (model, processor) already moved to the target device.
        It's only called if the requested slot isn't already resident.
        Runs inside the lock, and off the event loop via to_thread,
        since model loading is itself a blocking, potentially slow
        operation (disk I/O + GPU memory allocation).
        """
        async with self._lock:
            if self._current_slot == slot and self._current_model is not None:
                logger.info("model_orchestrator_cache_hit", slot=slot.value)
                return self._current_model, self._current_processor

            if self._current_slot is not None:
                await self._unload_current_locked()

            logger.info("model_orchestrator_loading", slot=slot.value)
            model, processor = await asyncio.to_thread(loader_fn)
            self._current_slot = slot
            self._current_model = model
            self._current_processor = processor
            if torch.cuda.is_available():
                GPU_VRAM_USED_BYTES.set(torch.cuda.memory_allocated())
                GPU_VRAM_RESERVED_BYTES.set(torch.cuda.memory_reserved())
            for s in GPUModelSlot:
                GPU_MODEL_SLOT_LOADED.labels(slot=s.value).set(1 if s == slot else 0)
            logger.info("model_orchestrator_loaded", slot=slot.value)
            return model, processor

    async def release_all(self) -> None:
        """Explicit unload -- called after a batch of work is done, so
        VRAM isn't held longer than necessary even if nothing else has
        requested a different slot yet."""
        async with self._lock:
            await self._unload_current_locked()

    async def _unload_current_locked(self) -> None:
        if self._current_slot is None:
            return
        logger.info("model_orchestrator_unloading", slot=self._current_slot.value)
        self._current_model = None
        self._current_processor = None
        self._current_slot = None
        # Explicit cleanup -- Python's GC alone doesn't reliably and
        # immediately free CUDA VRAM held by torch tensors; empty_cache()
        # tells the CUDA allocator to release cached (but unused) memory
        # back to the driver, which matters a lot on an 8GB card shared
        # between two different large-ish models.
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            GPU_VRAM_USED_BYTES.set(torch.cuda.memory_allocated())
            GPU_VRAM_RESERVED_BYTES.set(torch.cuda.memory_reserved())
            for s in GPUModelSlot:
                GPU_MODEL_SLOT_LOADED.labels(slot=s.value).set(0)
        logger.info("model_orchestrator_unloaded")


# Module-level singleton accessor -- import this, not the class directly,
# so every caller shares the exact same lock/state.
orchestrator = ModelOrchestrator()