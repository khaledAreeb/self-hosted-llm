#!/bin/bash
# Written by shadeform_deploy.py. Starts vLLM serving Qwen/Qwen3.8-27B-FP8
# (plain HTTP, port 8000). Shadeform runs it once the VM is active.
set -euo pipefail
DIR="${QWEN38_DIR:-/opt/qwen38}"
SUDO=""; [ "$(id -u)" -eq 0 ] || SUDO="sudo -n"
$SUDO mkdir -p "$DIR"; $SUDO chown "$(id -u)" "$DIR"
LOG="$DIR/start.log"
exec > >(tee -a "$LOG") 2>&1
step() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*"; }
trap 'step "FATAL: line $LINENO failed with status $?"' ERR
step 'start: mode=http port=8000 image=vllm/vllm-openai:v0.30.0'

# The image is CUDA 13.0: the host driver must be 580 or newer.
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
DRIVER="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -n1)"
if [ "${DRIVER%%.*}" -lt 580 ]; then
  step "FATAL: driver $DRIVER is too old for the CUDA 13 image (needs 580+)"; exit 1
fi
df -h / "$DIR" || true

# The key vLLM requires, readable only by this user; docker reads it with --env-file.
umask 077
printf '%s\n' VLLM_API_KEY=vllm-dummy-key-4b2d8f6e1a9c > "$DIR/vllm.env"
umask 022
mkdir -p "$DIR/hf-cache"

$SUDO docker version --format 'docker client {{.Client.Version}}, server {{.Server.Version}}'
step 'pulling vllm/vllm-openai:v0.30.0 (8.7 GB)'
$SUDO docker pull vllm/vllm-openai:v0.30.0
$SUDO docker rm -f qwen38 >/dev/null 2>&1 || true
SERVE_ARGS=(Qwen/Qwen3.8-27B-FP8 --host 0.0.0.0 --port 8000 --max-model-len 250000 --kv-cache-dtype fp8 --gpu-memory-utilization 0.9 --reasoning-parser qwen3 --default-chat-template-kwargs '{"reasoning_effort": "low"}' --enable-auto-tool-choice --tool-call-parser qwen3_xml --speculative-config '{"method": "mtp", "num_speculative_tokens": 3}')
step "starting vLLM; the model (~28 GB) downloads on first start"
$SUDO docker run -d --name qwen38 --restart on-failure:3 --gpus all --shm-size 16g \
  -p 8000:8000 -v "$DIR/hf-cache:/root/.cache/huggingface" \
  --env-file "$DIR/vllm.env" -e HF_HUB_DISABLE_XET=1 \
  vllm/vllm-openai:v0.30.0 "${SERVE_ARGS[@]}"
step "container started; follow it with: sudo docker logs -f qwen38"
