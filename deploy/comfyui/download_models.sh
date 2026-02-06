#!/usr/bin/env bash
#
# download_models.sh -- Download models for ComfyUI into Docker named volumes.
#
# Downloads:
#   - SDXL Base 1.0              -> checkpoints/
#   - ControlNet depth (SDXL)    -> controlnet/
#   - ControlNet normal (SDXL)   -> controlnet/
#   - SDXL inpainting model      -> checkpoints/
#
# Usage:
#   ./download_models.sh              # auto-detect volume mount path
#   MODELS_DIR=/path ./download_models.sh   # override base path
#
set -euo pipefail

# ---------------------------------------------------------------------------
# Resolve the models directory.
# Default: the Docker named-volume mount used by the compose stack.
# Override with MODELS_DIR env var for manual / host-side downloads.
# ---------------------------------------------------------------------------
MODELS_DIR="${MODELS_DIR:-/opt/ComfyUI/models}"

CHECKPOINTS_DIR="${MODELS_DIR}/checkpoints"
CONTROLNET_DIR="${MODELS_DIR}/controlnet"

mkdir -p "${CHECKPOINTS_DIR}" "${CONTROLNET_DIR}"

# ---------------------------------------------------------------------------
# Model definitions:  <local_filename>  <target_dir>  <url>
# ---------------------------------------------------------------------------
declare -a MODELS=(
  "sd_xl_base_1.0.safetensors|${CHECKPOINTS_DIR}|https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors"
  "sd_xl_base_1.0_inpainting_0.1.safetensors|${CHECKPOINTS_DIR}|https://huggingface.co/diffusers/stable-diffusion-xl-1.0-inpainting-0.1/resolve/main/sd_xl_base_1.0_inpainting_0.1.safetensors"
  "control-lora-depth-rank256.safetensors|${CONTROLNET_DIR}|https://huggingface.co/stabilityai/control-lora/resolve/main/control-LoRAs-rank256/control-lora-depth-rank256.safetensors"
  "control-lora-normal-rank256.safetensors|${CONTROLNET_DIR}|https://huggingface.co/stabilityai/control-lora/resolve/main/control-LoRAs-rank256/control-lora-normal-rank256.safetensors"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
RESET='\033[0m'

info()  { echo -e "${BOLD}[INFO]${RESET}  $*"; }
ok()    { echo -e "${GREEN}[OK]${RESET}    $*"; }
warn()  { echo -e "${YELLOW}[SKIP]${RESET}  $*"; }
fail()  { echo -e "${RED}[FAIL]${RESET}  $*"; }

download() {
    local filename="$1"
    local dest_dir="$2"
    local url="$3"
    local dest_path="${dest_dir}/${filename}"

    if [[ -f "${dest_path}" ]]; then
        warn "${filename} already exists -- skipping."
        return 0
    fi

    info "Downloading ${filename} ..."
    info "  URL:  ${url}"
    info "  Dest: ${dest_path}"

    local tmp_path="${dest_path}.part"

    if command -v wget &>/dev/null; then
        wget --continue --progress=bar:force:noscroll -O "${tmp_path}" "${url}"
    elif command -v curl &>/dev/null; then
        curl --location --continue-at - --progress-bar -o "${tmp_path}" "${url}"
    else
        fail "Neither wget nor curl found. Cannot download ${filename}."
        return 1
    fi

    mv "${tmp_path}" "${dest_path}"
    ok "${filename} downloaded successfully."
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
info "Models directory: ${MODELS_DIR}"
echo ""

ERRORS=0

for entry in "${MODELS[@]}"; do
    IFS='|' read -r filename dest_dir url <<< "${entry}"
    if ! download "${filename}" "${dest_dir}" "${url}"; then
        fail "Failed to download ${filename}"
        ((ERRORS++))
    fi
    echo ""
done

if [[ "${ERRORS}" -gt 0 ]]; then
    fail "${ERRORS} download(s) failed."
    exit 1
fi

ok "All models downloaded successfully."
