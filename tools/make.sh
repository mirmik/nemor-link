#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/.." && pwd)"
dist_dir="${repo_root}/dist"

rm -rf -- "${dist_dir}"
mkdir -p -- "${dist_dir}"

cd -- "${repo_root}"
uv build --out-dir "${dist_dir}"
python3 -m twine check "${dist_dir}"/*
