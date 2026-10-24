#!/usr/bin/env bash
# merge_dryrun.sh <base> <branch>...
#
# Dry run of a merge order. Merges each branch, in the order given, onto the RUNNING
# result (base first) with `git merge-tree --write-tree`, and prints the conflicted
# paths per step. Needs git 2.38 or newer. Run it inside the repo (any cwd in it).
#
# Read only for everything you can see: it never moves a ref, never touches HEAD, the
# index or the working tree, and never merges, checks out, pushes or fetches. It does
# write unreferenced objects (merge trees and one throwaway commit per step) into the
# object database; `git gc` removes them. A conflicted step keeps its conflict markers
# in the running result and the walk goes on, so a later step that touches the same
# file reports again. Read the table top down, the first line for a path is the real one.
#
# Exit codes: 0 when the walk finished (conflicts are a result, not a failure),
# 2 for bad usage or a base that does not resolve.
set -euo pipefail

if [ "$#" -lt 2 ]; then
  echo "usage: merge_dryrun.sh <base> <branch>..." >&2
  exit 2
fi

base="$1"
shift

if ! running="$(git rev-parse --verify --quiet "${base}^{commit}")"; then
  echo "merge_dryrun.sh: base '${base}' does not resolve to a commit" >&2
  exit 2
fi

export GIT_AUTHOR_NAME="merge-dryrun" GIT_AUTHOR_EMAIL="merge-dryrun@localhost"
export GIT_COMMITTER_NAME="merge-dryrun" GIT_COMMITTER_EMAIL="merge-dryrun@localhost"

short() { git rev-parse --short "$1"; }

echo "base: ${base} ($(short "$running"))"

total=0
conflicts=0
missing=0
errors=0
errfile="$(mktemp)"
trap 'rm -f "$errfile"' EXIT

for branch in "$@"; do
  total=$((total + 1))
  if ! tip="$(git rev-parse --verify --quiet "${branch}^{commit}")"; then
    missing=$((missing + 1))
    echo "step ${total} ${branch} (-): NOT FOUND, skipped (fetch it or fix the name)"
    continue
  fi
  label="step ${total} ${branch} ($(short "$tip"))"

  if git merge-base --is-ancestor "$tip" "$running"; then
    echo "${label}: clean, already contained in the running result"
    continue
  fi

  status=0
  out="$(git merge-tree --write-tree --name-only "$running" "$tip" 2>"$errfile")" || status=$?

  if [ "$status" -ne 0 ] && [ "$status" -ne 1 ]; then
    errors=$((errors + 1))
    echo "${label}: ERROR, skipped ($(head -n 1 "$errfile"))"
    continue
  fi

  tree="$(printf '%s\n' "$out" | sed -n '1p')"
  if [ "$status" -eq 1 ]; then
    conflicts=$((conflicts + 1))
    paths="$(printf '%s\n' "$out" | sed -n '2,$p' | sed '/^$/,$d')"
    count="$(printf '%s\n' "$paths" | grep -c . || true)"
    echo "${label}: CONFLICT in ${count} file(s)"
    printf '%s\n' "$paths" | sed 's/^/  /'
  else
    echo "${label}: clean"
  fi

  running="$(git commit-tree "$tree" -p "$running" -p "$tip" -m "merge_dryrun step ${total}: ${branch}")"
done

echo "summary: ${conflicts} of ${total} steps conflict, ${missing} not found, ${errors} errors"
