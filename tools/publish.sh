#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/.." && pwd)"
repository="${1:-pypi}"

case "${repository}" in
    pypi|testpypi)
        ;;
    *)
        echo "Usage: $0 [pypi|testpypi] [twine upload options...]" >&2
        exit 2
        ;;
esac

if [[ $# -gt 0 ]]; then
    shift
fi

cd -- "${repo_root}"
"${script_dir}/make.sh"
python3 -m twine upload --repository "${repository}" "$@" "${repo_root}/dist"/*
