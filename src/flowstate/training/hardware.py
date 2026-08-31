from __future__ import annotations

import platform
from typing import Any

import psutil
import torch

try:
    import pynvml
except Exception:
    pynvml = None


def hardware_capabilities() -> dict[str, Any]:
    """Return measured hardware facts used for model and device decisions."""
    driver_version: str | None = None
    nvml_error: str | None = None
    if pynvml is not None:
        try:
            pynvml.nvmlInit()
            driver_version = str(pynvml.nvmlSystemGetDriverVersion())
        except Exception as error:
            nvml_error = f"{type(error).__name__}: {error}"
        finally:
            try:
                pynvml.nvmlShutdown()
            except Exception:
                pass

    devices: list[dict[str, Any]] = []
    if torch.cuda.is_available():
        for index in range(torch.cuda.device_count()):
            properties = torch.cuda.get_device_properties(index)
            devices.append(
                {
                    "index": index,
                    "name": torch.cuda.get_device_name(index),
                    "compute_capability": list(torch.cuda.get_device_capability(index)),
                    "memory_mb": round(properties.total_memory / 1024 / 1024),
                }
            )

    cuda_usable = bool(torch.cuda.is_available() and devices and torch.version.cuda)
    return {
        "platform": platform.platform(),
        "cpu_logical_cores": psutil.cpu_count(logical=True),
        "system_memory_mb": round(psutil.virtual_memory().total / 1024 / 1024),
        "torch_version": torch.__version__,
        "torch_cuda_runtime": torch.version.cuda,
        "nvidia_driver": driver_version,
        "cuda_available": torch.cuda.is_available(),
        "cuda_usable": cuda_usable,
        "devices": devices,
        "compatibility_decision": (
            "CUDA training is available for PyTorch models. Select cuda unless the model or operation "
            "requires an unsupported kernel, exceeds device memory, or is faster on CPU."
            if cuda_usable
            else "CUDA training is unavailable in this runtime; select cpu."
        ),
        "telemetry_warning": nvml_error,
    }
