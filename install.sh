#!/usr/bin/env bash
set -euo pipefail

# BookCoder installer
# - Asks for install location
# - Detects GPU (NVIDIA/AMD) or asks user if not found
# - Creates a Python virtual environment
# - Installs BookCoder dependencies and heavy engine packages (Coqui XTTS, MMS-TTS)
# - Installs a PyTorch build appropriate for the selected GPU/CPU target
# - Falls back to CPU PyTorch if a selected GPU wheel/tag is unavailable for this Python/platform
# - Ensures MMS-TTS Python dependencies (transformers/numpy/scipy) are installed
#
# Notes:
# - System GPU drivers/toolkits (NVIDIA driver/CUDA runtime, AMD ROCm stack) are host prerequisites.
#   This script does not install system drivers automatically.
# - For best results on Debian, install system packages first:
#     sudo apt update && sudo apt install -y python3 python3-venv python3-pip ffmpeg ca-certificates
# - ROCm/CUDA PyTorch wheel availability depends on your platform, Python version, and selected wheel tag.
# - Coqui TTS (TTS>=0.22.0) may be unavailable on newer Python versions (e.g. 3.13); the installer will warn and continue.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="BookCoder"
DEFAULT_INSTALL_DIR="${HOME}/bookcoder"
PYTHON_BIN="${PYTHON_BIN:-python3}"

BOLD=""
DIM=""
RED=""
GREEN=""
YELLOW=""
BLUE=""
RESET=""
if [[ -t 1 ]]; then
  BOLD=$'\033[1m'
  DIM=$'\033[2m'
  RED=$'\033[31m'
  GREEN=$'\033[32m'
  YELLOW=$'\033[33m'
  BLUE=$'\033[34m'
  RESET=$'\033[0m'
fi

info()  { printf "%s[INFO]%s %s\n" "$BLUE" "$RESET" "$*"; }
ok()    { printf "%s[OK]%s %s\n" "$GREEN" "$RESET" "$*"; }
warn()  { printf "%s[WARN]%s %s\n" "$YELLOW" "$RESET" "$*"; }
error() { printf "%s[ERROR]%s %s\n" "$RED" "$RESET" "$*" >&2; }

prompt() {
  local msg="$1"
  local default="${2-}"
  local var
  if [[ -n "$default" ]]; then
    read -r -p "$msg [$default]: " var || true
    printf '%s' "${var:-$default}"
  else
    read -r -p "$msg: " var || true
    printf '%s' "$var"
  fi
}

confirm() {
  local msg="$1"
  local default="${2:-Y}" # Y or N
  local ans
  local suffix="Y/n"
  [[ "$default" == "N" || "$default" == "n" ]] && suffix="y/N"
  while true; do
    read -r -p "$msg [$suffix]: " ans || true
    ans="${ans:-$default}"
    case "$ans" in
      y|Y|yes|YES) return 0 ;;
      n|N|no|NO) return 1 ;;
      *) echo "Please answer y or n." ;;
    esac
  done
}

have_cmd() { command -v "$1" >/dev/null 2>&1; }

detect_nvidia() {
  if have_cmd nvidia-smi; then
    if nvidia-smi >/dev/null 2>&1; then
      return 0
    fi
  fi
  if have_cmd lspci; then
    if lspci 2>/dev/null | grep -Eqi '(vga|3d|display).*(nvidia)'; then
      return 0
    fi
  fi
  [[ -d /proc/driver/nvidia/gpus ]] && return 0
  return 1
}

detect_amd() {
  if have_cmd rocminfo; then
    if rocminfo >/dev/null 2>&1; then
      return 0
    fi
  fi
  if have_cmd rocm-smi; then
    if rocm-smi >/dev/null 2>&1; then
      return 0
    fi
  fi
  if have_cmd lspci; then
    if lspci 2>/dev/null | grep -Eqi '(vga|3d|display).*(amd|advanced micro devices|ati|radeon)'; then
      return 0
    fi
  fi
  if [[ -d /sys/class/drm ]]; then
    local vendor
    for vendor in /sys/class/drm/card*/device/vendor; do
      [[ -f "$vendor" ]] || continue
      if grep -qi '0x1002' "$vendor" 2>/dev/null; then
        return 0
      fi
    done
  fi
  return 1
}

detect_cuda_tag_hint() {
  # Best-effort hint from nvidia-smi CUDA version (driver-supported CUDA).
  # PyTorch wheel tag choice also depends on available wheels; user can override.
  local cuda_ver major minor
  cuda_ver="$(nvidia-smi 2>/dev/null | sed -n 's/.*CUDA Version: \([0-9][0-9]*\.[0-9][0-9]*\).*/\1/p' | head -n1 || true)"
  if [[ -z "$cuda_ver" ]]; then
    echo "cu121"
    return
  fi
  major="${cuda_ver%%.*}"
  minor="${cuda_ver#*.}"
  minor="${minor%%.*}"
  if [[ "$major" -ge 12 && "$minor" -ge 4 ]]; then
    echo "cu124"
  elif [[ "$major" -ge 12 && "$minor" -ge 1 ]]; then
    echo "cu121"
  elif [[ "$major" -eq 11 && "$minor" -ge 8 ]]; then
    echo "cu118"
  else
    echo "cu121"
  fi
}

copy_app_files() {
  local src="$1"
  local dst="$2"

  mkdir -p "$dst"

  # If destination is different from source, copy project contents.
  if [[ "$(cd "$src" && pwd)" == "$(cd "$dst" && pwd)" ]]; then
    info "Install location is the source directory; skipping file copy."
    return
  fi

  info "Copying BookCoder files to: $dst"
  if have_cmd rsync; then
    rsync -a \
      --exclude '.venv/' \
      --exclude '__pycache__/' \
      --exclude '*.pyc' \
      --exclude '*.pyo' \
      --exclude '.pytest_cache/' \
      --exclude '.mypy_cache/' \
      --exclude '.ruff_cache/' \
      --exclude '*.egg-info/' \
      --exclude 'build/' \
      --exclude 'dist/' \
      --exclude '*.swp' \
      --exclude '*~' \
      --exclude '.DS_Store' \
      --exclude 'bookcoder.tar.bz2' \
      "$src/" "$dst/"
  else
    # Fallback copy (best effort). Existing .venv/caches in source are not desired but may copy if present.
    warn "rsync not found; using cp fallback (may copy extra files)."
    cp -a "$src/." "$dst/"
    rm -rf "$dst/.venv" "$dst"/**/__pycache__ 2>/dev/null || true
  fi
}

detect_python_bin() {
  # Allow override: PYTHON_BIN=python3.12 ./install.sh
  if [[ -n "${PYTHON_BIN:-}" ]] && have_cmd "$PYTHON_BIN"; then
    return 0
  fi
  PYTHON_BIN="python3"
  # Prefer versions with better heavy-engine wheel compatibility if available
  local candidate
  for candidate in python3.12 python3.11 python3.10 python3; do
    if have_cmd "$candidate"; then
      PYTHON_BIN="$candidate"
      # Keep default as python3 if user didn't override, but we can suggest; actual selection happens in prompt
      break
    fi
  done
  PYTHON_BIN="python3"
}

choose_python_bin() {
  local detected=""
  local c
  for c in python3.12 python3.11 python3.10 python3.13 python3; do
    if have_cmd "$c"; then
      local ver
      ver="$("$c" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))' 2>/dev/null || true)"
      detected+="  - $c (${ver:-unknown})\n"
    fi
  done
  if [[ -n "$detected" ]]; then
    printf "%sAvailable Python interpreters:%s\n%b" "$BOLD" "$RESET" "$detected" >&2
    warn "Heavy engines (Coqui TTS/Torch wheels) are often more compatible with Python 3.10-3.12 than 3.13." >&2
  fi
  PYTHON_BIN="$(prompt "Python interpreter to use for the virtual environment" "${PYTHON_BIN:-python3}")"
  if ! have_cmd "$PYTHON_BIN"; then
    error "Python interpreter not found: $PYTHON_BIN"
    exit 1
  fi
}

check_prereqs() {
  local missing=0
  if ! have_cmd "$PYTHON_BIN"; then
    error "$PYTHON_BIN is required but not found."
    missing=1
  fi
  if ! "$PYTHON_BIN" -m venv --help >/dev/null 2>&1; then
    error "$PYTHON_BIN venv module is unavailable. On Debian: sudo apt install -y ${PYTHON_BIN}-venv python3-venv"
    missing=1
  fi
  if ! "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; then
    warn "$PYTHON_BIN -m pip is not available in the base interpreter. venv creation may still work if ensurepip is available."
  fi
  if ! have_cmd ffmpeg; then
    warn "ffmpeg not found. Recommended for MP3/AAC encoding and audio combining. On Debian: sudo apt install -y ffmpeg"
  fi
  if [[ $missing -ne 0 ]]; then
    error "Missing required prerequisites. Install them and run this script again."
    exit 1
  fi
}

choose_gpu_target() {
  local nvidia_found=0
  local amd_found=0
  local choice=""

  if detect_nvidia; then nvidia_found=1; fi
  if detect_amd; then amd_found=1; fi

  if [[ $nvidia_found -eq 1 && $amd_found -eq 0 ]]; then
    info "Detected GPU: NVIDIA" >&2
    if confirm "Use NVIDIA GPU acceleration (PyTorch CUDA wheels)?" "Y"; then
      echo "nvidia"
      return
    fi
  elif [[ $amd_found -eq 1 && $nvidia_found -eq 0 ]]; then
    info "Detected GPU: AMD" >&2
    if confirm "Use AMD GPU acceleration (PyTorch ROCm wheels)?" "Y"; then
      echo "amd"
      return
    fi
  elif [[ $nvidia_found -eq 1 && $amd_found -eq 1 ]]; then
    warn "Detected both NVIDIA and AMD GPU indicators." >&2
  else
    warn "No NVIDIA/AMD GPU detected automatically." >&2
  fi

  echo >&2
  echo "Select acceleration target:" >&2
  echo "  1) NVIDIA (CUDA PyTorch)" >&2
  echo "  2) AMD (ROCm PyTorch)" >&2
  echo "  3) CPU only" >&2
  while true; do
    read -r -p "Enter choice [1-3]: " choice || true
    case "${choice}" in
      1) echo "nvidia"; return ;;
      2) echo "amd"; return ;;
      3) echo "cpu"; return ;;
      *) echo "Invalid choice. Please enter 1, 2, or 3." >&2 ;;
    esac
  done
}

torch_usable_in_venv() {
  local venv_python="$1"
  "$venv_python" -c "import torch" >/dev/null 2>&1
}

install_torch_cpu() {
  local venv_python="$1"
  info "Installing CPU PyTorch wheels (torch, torchaudio)..."
  if "$venv_python" -m pip install --upgrade --no-cache-dir --index-url "https://download.pytorch.org/whl/cpu" torch torchaudio; then
    return 0
  fi
  warn "CPU PyTorch install from the PyTorch CPU index failed; retrying with default package indexes..."
  "$venv_python" -m pip install --upgrade --no-cache-dir torch torchaudio
}

install_gpu_torch_with_fallback() {
  local target="$1"
  local venv_python="$2"
  local tag idx

  if [[ "$target" == "nvidia" ]]; then
    tag="$(detect_cuda_tag_hint)"
    echo
    info "NVIDIA selected. A CUDA-enabled PyTorch build is required for GPU acceleration."
    info "Host NVIDIA driver/CUDA compatibility must be satisfied (check: nvidia-smi)."
    while true; do
      tag="$(prompt "Enter PyTorch CUDA wheel tag (e.g. cu118, cu121, cu124). Leave empty to use CPU fallback" "$tag")"
      tag="$(printf '%s' "$tag" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
      if [[ -z "$tag" ]]; then
        if confirm "Install CPU PyTorch fallback now (heavy engines will run without GPU acceleration)?" "Y"; then
          install_torch_cpu "$venv_python" || warn "CPU PyTorch installation failed."
        else
          warn "Skipping PyTorch installation. Install a compatible PyTorch build manually to enable heavy engines."
        fi
        return 0
      fi
      idx="https://download.pytorch.org/whl/${tag}"
      info "Installing PyTorch (CUDA: $tag) from $idx"
      if "$venv_python" -m pip install --upgrade --no-cache-dir --index-url "$idx" torch torchaudio && torch_usable_in_venv "$venv_python"; then
        ok "PyTorch CUDA build installed and importable (tag: $tag)."
        return 0
      fi
      warn "PyTorch CUDA wheel install failed or is not usable for $("$venv_python" -c 'import sys; print(sys.version.split()[0])' 2>/dev/null || echo this Python) (tag: $tag)."
      warn "This can happen when no compatible wheel exists for your Python/platform/tag combination."
      if confirm "Try a different CUDA wheel tag?" "Y"; then
        continue
      fi
      if confirm "Install CPU PyTorch fallback now (heavy engines will run without GPU acceleration)?" "Y"; then
        install_torch_cpu "$venv_python" || warn "CPU PyTorch installation failed."
      else
        warn "Skipping CPU fallback. Install a compatible PyTorch build manually to enable heavy engines."
      fi
      return 0
    done
  else
    tag="rocm6.1"
    echo
    info "AMD selected. A ROCm-enabled PyTorch build is required for GPU acceleration."
    warn "ROCm support depends on your GPU, drivers/ROCm version, and OS support."
    while true; do
      tag="$(prompt "Enter PyTorch ROCm wheel tag (e.g. rocm6.0, rocm6.1, rocm6.2). Leave empty to use CPU fallback" "$tag")"
      tag="$(printf '%s' "$tag" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
      if [[ -z "$tag" ]]; then
        if confirm "Install CPU PyTorch fallback now (heavy engines will run without GPU acceleration)?" "Y"; then
          install_torch_cpu "$venv_python" || warn "CPU PyTorch installation failed."
        else
          warn "Skipping PyTorch installation. Install a compatible PyTorch build manually to enable heavy engines."
        fi
        return 0
      fi
      idx="https://download.pytorch.org/whl/${tag}"
      info "Installing PyTorch (ROCm: $tag) from $idx"
      if "$venv_python" -m pip install --upgrade --no-cache-dir --index-url "$idx" torch torchaudio && torch_usable_in_venv "$venv_python"; then
        ok "PyTorch ROCm build installed and importable (tag: $tag)."
        return 0
      fi
      warn "PyTorch ROCm wheel install failed or is not usable for $("$venv_python" -c 'import sys; print(sys.version.split()[0])' 2>/dev/null || echo this Python) (tag: $tag)."
      warn "This can happen when no compatible wheel exists for your Python/platform/tag combination (e.g. some ROCm tags on Python 3.13)."
      if confirm "Try a different ROCm wheel tag?" "Y"; then
        continue
      fi
      if confirm "Install CPU PyTorch fallback now (heavy engines will run without GPU acceleration)?" "Y"; then
        install_torch_cpu "$venv_python" || warn "CPU PyTorch installation failed."
      else
        warn "Skipping CPU fallback. Install a compatible PyTorch build manually to enable heavy engines."
      fi
      return 0
    done
  fi
}

install_torch_for_target() {
  local target="$1"
  local venv_python="$2"

  case "$target" in
    nvidia|amd)
      install_gpu_torch_with_fallback "$target" "$venv_python"
      ;;
    cpu)
      echo
      info "CPU selected. Installing CPU PyTorch wheels (for heavy engines without GPU acceleration)."
      install_torch_cpu "$venv_python" || warn "CPU PyTorch installation failed. Heavy engines may be unavailable."
      ;;
    *)
      error "Unknown target: $target"
      exit 1
      ;;
  esac

  if torch_usable_in_venv "$venv_python"; then
    ok "PyTorch is installed in the virtual environment."
  else
    warn "PyTorch is not installed/usable in the virtual environment. Coqui XTTS and MMS-TTS will remain unavailable until torch is installed."
  fi
}

main() {
  printf "%s%s installer%s\n" "$BOLD" "$APP_NAME" "$RESET"
  echo "This script installs BookCoder into a chosen directory with a virtual environment and Python dependencies."
  echo

  detect_python_bin
  choose_python_bin
  info "Using Python interpreter: $PYTHON_BIN ($("$PYTHON_BIN" -c 'import sys; print(sys.version.split()[0])' 2>/dev/null || echo unknown))"
  check_prereqs

  local install_dir
  install_dir="$(prompt "Enter install location" "$DEFAULT_INSTALL_DIR")"
  if [[ -z "$install_dir" ]]; then
    error "Install location cannot be empty."
    exit 1
  fi
  # Expand ~
  if [[ "$install_dir" == ~* ]]; then
    install_dir="${install_dir/#\~/$HOME}"
  fi
  # If relative path, make it relative to current working directory (not script dir)
  if [[ "$install_dir" != /* ]]; then
    install_dir="$(pwd)/$install_dir"
  fi
  mkdir -p "$install_dir"

  info "Install location: $install_dir"

  copy_app_files "$SCRIPT_DIR" "$install_dir"

  local target
  target="$(choose_gpu_target)"
  info "Selected target: $target"

  echo
  if [[ "$target" == "nvidia" ]]; then
    warn "Make sure NVIDIA drivers are installed and working on the host (nvidia-smi). This script installs PyTorch CUDA wheels only."
  elif [[ "$target" == "amd" ]]; then
    warn "Make sure AMDGPU/ROCm drivers/runtime are installed and supported for your GPU/OS. This script installs PyTorch ROCm wheels only."
  fi

  local venv_dir="$install_dir/.venv"
  if [[ -d "$venv_dir" ]]; then
    if confirm "Virtual environment already exists at $venv_dir. Recreate it?" "N"; then
      info "Removing existing virtual environment..."
      rm -rf "$venv_dir"
    fi
  fi

  if [[ ! -d "$venv_dir" ]]; then
    info "Creating virtual environment..."
    "$PYTHON_BIN" -m venv "$venv_dir"
  else
    info "Using existing virtual environment: $venv_dir"
  fi

  local vpy="$venv_dir/bin/python"
  local vpip=("$vpy" -m pip)

  info "Upgrading pip/setuptools/wheel..."
  "${vpip[@]}" install --upgrade pip setuptools wheel

  if [[ -f "$install_dir/requirements.txt" ]]; then
    info "Installing base Python requirements..."
    "${vpip[@]}" install --no-cache-dir -r "$install_dir/requirements.txt"
  else
    warn "requirements.txt not found in install location; skipping base requirements file install."
  fi

  # Install target-specific PyTorch first (used by heavy engines), then heavy engine deps.
  install_torch_for_target "$target" "$vpy"

  info "Installing heavy engine Python packages (MMS-TTS dependencies: transformers/numpy/scipy)..."
  # Install heavy deps explicitly to avoid replacing the selected torch build.
  if ! "${vpip[@]}" install --no-cache-dir "transformers>=4.41" "numpy" "scipy"; then
    warn "Batch install of transformers/numpy/scipy failed; retrying individually..."
    "${vpip[@]}" install --no-cache-dir "numpy" || warn "Failed to install numpy."
    "${vpip[@]}" install --no-cache-dir "scipy" || warn "Failed to install scipy."
    "${vpip[@]}" install --no-cache-dir "transformers>=4.41" || warn "Failed to install transformers. MMS-TTS may be unavailable."
  fi
  if "$vpy" -c "import transformers" >/dev/null 2>&1; then
    ok "transformers is installed."
  else
    warn "transformers is not importable in the virtual environment. MMS-TTS will remain unavailable until transformers is installed."
  fi

  info "Installing Coqui TTS package (optional, for Coqui XTTS v2)..."
  if ! "${vpip[@]}" install --no-cache-dir "TTS>=0.22.0"; then
    warn "Could not install Coqui TTS package ('TTS>=0.22.0') for this Python/platform environment."
    warn "Coqui XTTS v2 may be unavailable. This is common on newer Python versions (e.g. 3.13) if compatible Coqui TTS releases/wheels are not published."
    warn "You can still use Edge TTS, Piper, and possibly MMS-TTS. For Coqui XTTS, try Python 3.10-3.12 and re-run the installer."
  fi

  # Install project package in editable mode if pyproject.toml exists (without pulling torch extras)
  if [[ -f "$install_dir/pyproject.toml" ]]; then
    info "Installing BookCoder package (editable)..."
    "${vpip[@]}" install --no-cache-dir -e "$install_dir" --no-deps || {
      warn "Editable install with --no-deps failed; retrying without --no-deps."
      "${vpip[@]}" install --no-cache-dir -e "$install_dir"
    }
  fi

  echo
  ok "Installation completed."
  echo
  printf "%sDependency/runtime summary (venv):%s\n" "$BOLD" "$RESET"
  echo "  Base/runtime: flask, edge-tts, piper-tts, ebook/text parsing deps, ffmpeg (system, recommended)"
  echo "  Heavy engines: torch, torchaudio, transformers, numpy, scipy, TTS (Coqui, optional)"
  "$vpy" - <<'PY'
import importlib
mods = [
    ("torch", "torch"),
    ("torchaudio", "torchaudio"),
    ("transformers", "transformers"),
    ("numpy", "numpy"),
    ("scipy", "scipy"),
    ("TTS (Coqui)", "TTS"),
]
for label, mod in mods:
    try:
        m = importlib.import_module(mod)
        ver = getattr(m, "__version__", "installed")
        print(f"  - {label}: OK ({ver})")
    except Exception:
        print(f"  - {label}: not installed/unavailable")
PY
  echo
  printf "%sNext steps:%s\n" "$BOLD" "$RESET"
  echo "  1. Activate the virtual environment:"
  echo "       source \"$venv_dir/bin/activate\""
  echo "  2. Start BookCoder:"
  echo "       python -m bookcoder"
  echo "  3. Open the UI (default): http://127.0.0.1:8765"
  echo
  printf "%sGPU/runtime verification:%s\n" "$BOLD" "$RESET"
  echo "  \"$vpy\" -c \"import torch; print('torch=', torch.__version__); print('cuda_available=', torch.cuda.is_available()); print('hip=', getattr(torch.version,'hip',None))\""
  echo
  if [[ "$target" == "nvidia" ]]; then
    echo "  - If cuda_available is False, verify NVIDIA driver/CUDA compatibility and that a matching CUDA PyTorch wheel was installed."
  elif [[ "$target" == "amd" ]]; then
    echo "  - If cuda_available is False on ROCm, verify ROCm installation/GPU support and that a compatible ROCm PyTorch wheel was installed."
  else
    echo "  - CPU target selected. Heavy engines will run on CPU (slower)."
  fi
  echo
  echo "Heavy model downloads (Coqui XTTS / MMS-TTS) happen in-app or on first use and may be large."
  echo "FFmpeg is recommended for audio encoding/combining: sudo apt install -y ffmpeg"
}

main "$@"