from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any


def _run(cmd: list[str], timeout: float = 2.0) -> str:
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout)
        if p.returncode != 0:
            return (p.stdout or "").strip()
        return (p.stdout or "").strip()
    except Exception:
        return ""


def _has_nvidia_gpu() -> tuple[bool, list[str], str]:
    names: list[str] = []
    method = ""
    out = _run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], timeout=2.5)
    if out:
        for line in out.splitlines():
            line = line.strip()
            if line:
                names.append(line)
        if names:
            return True, names, "nvidia-smi"
    # lspci fallback
    out = _run(["lspci"], timeout=2.0)
    if out:
        for line in out.splitlines():
            l = line.lower()
            if ("vga" in l or "3d controller" in l or "display" in l) and ("nvidia" in l):
                names.append(line.strip())
        if names:
            return True, names, "lspci"
    # /proc driver
    if Path("/proc/driver/nvidia/gpus").exists():
        try:
            gpus = sorted([p.name for p in Path("/proc/driver/nvidia/gpus").iterdir() if p.is_dir()])
            if gpus:
                return True, gpus, "/proc/driver/nvidia/gpus"
        except Exception:
            pass
    return False, [], ""


def _has_amd_gpu() -> tuple[bool, list[str], str]:
    names: list[str] = []
    # rocminfo / rocm-smi hints
    out = _run(["rocminfo"], timeout=2.5)
    if out and ("agent" in out.lower() or "gfx" in out.lower() or "amdgpu" in out.lower()):
        # try to extract marketing names
        for line in out.splitlines():
            s = line.strip()
            if "Marketing Name" in s or "Name:" in s:
                names.append(s)
        if not names:
            names.append("AMD GPU detected via rocminfo")
        return True, names[:5], "rocminfo"
    out = _run(["rocm-smi", "--showproductname"], timeout=2.5)
    if out and "gpu" in out.lower():
        for line in out.splitlines():
            line = line.strip()
            if line and "================" not in line:
                names.append(line)
        if names:
            return True, names[:5], "rocm-smi"
    # lspci fallback
    out = _run(["lspci"], timeout=2.0)
    if out:
        for line in out.splitlines():
            l = line.lower()
            if ("vga" in l or "3d controller" in l or "display" in l) and ("amd" in l or "advanced micro devices" in l or "ati" in l or "radeon" in l):
                names.append(line.strip())
        if names:
            return True, names, "lspci"
    # drm sysfs fallback
    drm = Path("/sys/class/drm")
    if drm.exists():
        try:
            for card in drm.glob("card*/device/vendor"):
                vendor = card.read_text(encoding="utf-8", errors="ignore").strip().lower()
                if vendor in ("0x1002", "1002"):
                    names.append(f"AMD GPU (vendor {vendor}) via sysfs")
                    return True, names, "/sys/class/drm"
        except Exception:
            pass
    return False, [], ""


def detect_hardware() -> dict[str, Any]:
    nvidia_present, nvidia_names, nvidia_method = _has_nvidia_gpu()
    amd_present, amd_names, amd_method = _has_amd_gpu()

    torch_info: dict[str, Any] = {"installed": False}
    try:
        import torch  # type: ignore

        cuda_available = bool(getattr(torch, "cuda", None) and torch.cuda.is_available())
        hip_version = getattr(getattr(torch, "version", None), "hip", None)
        torch_info = {
            "installed": True,
            "version": getattr(torch, "__version__", None),
            "cuda_available": cuda_available,
            "cuda_version": getattr(getattr(torch, "version", None), "cuda", None),
            "hip_version": hip_version,
            "cuda_device_count": int(torch.cuda.device_count()) if cuda_available else 0,
        }
        if cuda_available:
            try:
                torch_info["cuda_devices"] = [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())]
            except Exception:
                pass
    except Exception as e:
        torch_info = {"installed": False, "error": str(e)}

    gpu_accel_available = bool(torch_info.get("installed") and torch_info.get("cuda_available"))
    accel_backend = None
    if gpu_accel_available:
        if torch_info.get("hip_version"):
            accel_backend = "rocm"
        elif torch_info.get("cuda_version"):
            accel_backend = "cuda"
        else:
            accel_backend = "cuda-compatible"

    supported_engines: list[str] = []
    notes: list[str] = []
    if nvidia_present:
        notes.append("NVIDIA GPU detected.")
    if amd_present:
        notes.append("AMD GPU detected.")
    if not nvidia_present and not amd_present:
        notes.append("No NVIDIA/AMD GPU detected by system probes; CPU mode will be used.")

    if torch_info.get("installed"):
        if gpu_accel_available:
            supported_engines.extend(["coqui-xtts", "mms-tts"])
            notes.append(f"PyTorch GPU acceleration is available ({accel_backend or 'gpu'}). Coqui XTTS and MMS-TTS can use the GPU when loaded.")
        else:
            notes.append("PyTorch is installed but GPU acceleration is not available in this environment (CPU mode).")
            if nvidia_present:
                notes.append("For NVIDIA acceleration, install a CUDA-enabled PyTorch build and compatible NVIDIA drivers/CUDA runtime.")
            if amd_present:
                notes.append("For AMD acceleration, install a ROCm-enabled PyTorch build supported by your GPU/OS.")
    else:
        notes.append("PyTorch is not installed. Heavy engines (Coqui XTTS, MMS-TTS) require torch; GPU acceleration requires a CUDA/ROCm-enabled torch build.")

    notes.append("Model files are downloaded/cached by the selected engine; GPU usage depends on the installed runtime (drivers + CUDA/ROCm PyTorch). BookCoder cannot install system GPU drivers automatically.")

    return {
        "platform": platform.platform(),
        "gpus": {
            "nvidia": {"present": nvidia_present, "names": nvidia_names, "detected_via": nvidia_method},
            "amd": {"present": amd_present, "names": amd_names, "detected_via": amd_method},
        },
        "torch": torch_info,
        "acceleration": {
            "gpu_available_for_tts": gpu_accel_available,
            "backend": accel_backend,
            "supported_heavy_engines": supported_engines,
        },
        "notes": notes,
    }
