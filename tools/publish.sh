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
if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
    echo "Refusing to publish from a dirty worktree." >&2
    exit 1
fi

"${script_dir}/make.sh"
uvx twine upload --repository "${repository}" "$@" "${repo_root}/dist"/*
