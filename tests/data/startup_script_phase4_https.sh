#!/bin/bash
# Written by shadeform_deploy.py. Starts vLLM serving Qwen/Qwen3.8-27B-FP8
# (HTTPS, port 8443). Shadeform runs it once the VM is active.
set -euo pipefail
DIR="${QWEN38_DIR:-/opt/qwen38}"
SUDO=""; [ "$(id -u)" -eq 0 ] || SUDO="sudo -n"
$SUDO mkdir -p "$DIR"; $SUDO chown "$(id -u)" "$DIR"
LOG="$DIR/start.log"
exec > >(tee -a "$LOG") 2>&1
step() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*"; }
trap 'step "FATAL: line $LINENO failed with status $?"' ERR
step 'start: mode=https port=8443 image=vllm/vllm-openai:v0.30.0'

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

step "TLS: self-signed certificate"
mkdir -p "$DIR/tls"
openssl req -x509 -newkey rsa:2048 -nodes -days 30 -subj "/CN=qwen38" \
  -keyout "$DIR/tls/key.pem" -out "$DIR/tls/cert.pem"
chmod 600 "$DIR/tls/key.pem"
openssl x509 -in "$DIR/tls/cert.pem" -noout -fingerprint -sha256

# Docker-published ports bypass UFW, so only 8443 is published; UFW
# closes everything else. SSH stays open on 22 and wherever sshd listens.
# Reset first: provider images can ship their own rules (MassedCompute's
# allowed port 80, seen 2026-10-01).
step "firewall: deny incoming except SSH and 8443"
command -v ufw >/dev/null || { $SUDO apt-get update -qq && $SUDO apt-get install -y -qq ufw; }
$SUDO ufw --force reset
$SUDO ufw default deny incoming
$SUDO ufw default allow outgoing
$SUDO ufw allow 22/tcp
for p in $($SUDO ss -Htlnp 2>/dev/null | awk '/sshd/ {n=split($4,a,":"); print a[n]}' | sort -u); do
  $SUDO ufw allow "$p/tcp"
done
$SUDO ufw allow 8443/tcp
$SUDO ufw --force enable
$SUDO ufw status verbose

$SUDO docker version --format 'docker client {{.Client.Version}}, server {{.Server.Version}}'
step 'pulling vllm/vllm-openai:v0.30.0 (8.7 GB)'
$SUDO docker pull vllm/vllm-openai:v0.30.0
$SUDO docker rm -f qwen38 >/dev/null 2>&1 || true
SERVE_ARGS=(Qwen/Qwen3.8-27B-FP8 --host 0.0.0.0 --port 8443 --max-model-len 250000 --kv-cache-dtype fp8 --gpu-memory-utilization 0.9 --reasoning-parser qwen3 --default-chat-template-kwargs '{"reasoning_effort": "low"}' --enable-auto-tool-choice --tool-call-parser qwen3_xml --speculative-config '{"method": "mtp", "num_speculative_tokens": 3}' --ssl-keyfile /tls/key.pem --ssl-certfile /tls/cert.pem)
step "starting vLLM; the model (~28 GB) downloads on first start"
$SUDO docker run -d --name qwen38 --restart on-failure:3 --gpus all --shm-size 16g \
  -p 8443:8443 -v "$DIR/hf-cache:/root/.cache/huggingface" -v "$DIR/tls:/tls:ro" \
  --env-file "$DIR/vllm.env" -e HF_HUB_DISABLE_XET=1 \
  vllm/vllm-openai:v0.30.0 "${SERVE_ARGS[@]}"
step "container started; follow it with: sudo docker logs -f qwen38"
