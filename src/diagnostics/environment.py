from __future__ import annotations

import importlib.metadata
import platform
import subprocess
from datetime import datetime, timezone
from typing import Any



PACKAGE_NAMES = ("opencv-python", "pydantic", "mss", "pytest", "torch")


def _normalize_architecture(value: str) -> str:
    return value.replace("bit", "-bit") if value.endswith("bit") else value


def _collect_host_gpu() -> dict[str, Any]:
    """Collect host GPU facts independently of the Python Torch build."""
    query = "name,memory.total,memory.used,utilization.gpu,driver_version"
    try:
        completed = subprocess.run(
            ["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"available": False, "error": str(exc)}
    devices = []
    for line in completed.stdout.splitlines():
        fields = [field.strip() for field in line.split(",")]
        if len(fields) != 5:
            continue
        name, total, used, utilization, driver = fields
        devices.append({
            "name": name,
            "vram_total_mib": int(float(total)),
            "vram_used_mib": int(float(used)),
            "utilization_percent": int(float(utilization)),
            "driver": driver,
        })
    return {"available": bool(devices), "devices": devices}


def collect_environment() -> dict[str, Any]:
    """Collect read-only local runtime facts with graceful fallbacks."""
    report: dict[str, Any] = {
        "schema_version": "environment-report.v2",
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "platform": {"os": platform.system(), "release": platform.release(), "version": platform.version(), "architecture": _normalize_architecture(platform.architecture()[0]), "python": platform.python_version()},
        "host_gpu": _collect_host_gpu(),
        "python_gpu_runtime": {},
        "screen_capture": {"available": False, "backend": "mss", "reason": "mss_not_installed"},
        "installed_relevant_packages": {},
        "scope": {"network": False, "game_operation": False, "cloud_api_used": False},
    }
    for name in PACKAGE_NAMES:
        try:
            report["installed_relevant_packages"][name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            report["installed_relevant_packages"][name] = None
    if report["installed_relevant_packages"].get("mss"):
        report["screen_capture"] = {"available": True, "backend": "mss", "reason": ""}

    try:
        import torch
        runtime = {"torch": torch.__version__, "torch_cuda_available": bool(torch.cuda.is_available()), "torch_cuda_version": torch.version.cuda, "configuration_warnings": []}
        if torch.cuda.is_available():
            runtime["cuda_device_count"] = torch.cuda.device_count()
            runtime["gpu_names"] = [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())]
        report["python_gpu_runtime"] = runtime
    except Exception as exc:
        report["python_gpu_runtime"] = {"error": str(exc)}

    try:
        import paddle
        report["python_gpu_runtime"]["paddle"] = paddle.__version__
        report["python_gpu_runtime"]["paddle_cuda_available"] = bool(paddle.device.is_compiled_with_cuda())
        report["python_gpu_runtime"]["paddle_device"] = paddle.get_device()
    except Exception as exc:
        report["python_gpu_runtime"]["paddle_error"] = str(exc)

    if report["host_gpu"].get("available") and report["python_gpu_runtime"].get("torch_cuda_available") is False:
        report["python_gpu_runtime"].setdefault("configuration_warnings", []).append(
            "host GPU is available but the installed PyTorch build has no CUDA support"
        )
    return report
