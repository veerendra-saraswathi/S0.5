#!/usr/bin/env bash
# Run the two-generation archive test against a disposable localhost MinIO server.
set -euo pipefail
cd "$(dirname "$0")/.."
python_bin=${PYTHON:-python3}
image=${MINIO_TEST_IMAGE:-docker.io/jcometki/minio@sha256:a1ea29fa28355559ef137d71fc570e508a214ec84ff8083e39bc5428980b015e}
"$python_bin" -c 'import pytest, polars, pyarrow'
docker image inspect "$image" >/dev/null

deps=$(mktemp -d)
cid=''
cleanup() {
  if [[ -n "$cid" ]]; then docker rm -fv "$cid" >/dev/null || true; fi
  rm -rf "$deps"
}
trap cleanup EXIT
export MINIO_ROOT_USER=s05readback
MINIO_ROOT_PASSWORD=$("$python_bin" -c 'import secrets; print(secrets.token_hex(24))')
export MINIO_ROOT_PASSWORD
cid=$(docker run -d --pull=never -p 127.0.0.1::9000 \
  -e MINIO_ROOT_USER -e MINIO_ROOT_PASSWORD "$image" server /data)
endpoint=$(docker port "$cid" 9000/tcp)
ready=no
for ((i=0; i<30; i++)); do
  if curl --noproxy '*' -fsS --max-time 1 "http://$endpoint/minio/health/ready" >/dev/null 2>&1; then
    ready=yes
    break
  fi
  [[ "$(docker inspect -f '{{.State.Running}}' "$cid")" == true ]] || break
  sleep 1
done
if [[ "$ready" != yes ]]; then
  docker inspect -f 'MinIO startup: status={{.State.Status}} exit={{.State.ExitCode}} oom={{.State.OOMKilled}}' "$cid" >&2
  exit 1
fi

if ! "$python_bin" -c 'import minio' 2>/dev/null; then
  "$python_bin" -m pip install --quiet --target "$deps" minio
  export PYTHONPATH="$deps${PYTHONPATH:+:$PYTHONPATH}"
fi
export STORAGE_BACKEND=duckdb CNC_DUCKDB_PATH="$deps/readback.duckdb"
export MINIO_ENDPOINT="$endpoint" MINIO_ACCESS_KEY="$MINIO_ROOT_USER"
export MINIO_SECRET_KEY="$MINIO_ROOT_PASSWORD" MINIO_SECURE=false S05_TEST_MINIO=1
"$python_bin" -m pytest -q -rs src/data/test_minio_readback.py::test_read_published_generation
