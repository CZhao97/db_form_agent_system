#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
build_dir="${BUILD_DIR:-$PWD}"
mkdir -p "$build_dir"
build_dir="$(cd "$build_dir" && pwd)"
for name in DB_Curator_main DB_Curator_SI; do
  xelatex -interaction=nonstopmode -halt-on-error -output-directory="$build_dir" "$name.tex" > "$build_dir/$name.build.log"
  xelatex -interaction=nonstopmode -halt-on-error -output-directory="$build_dir" "$name.tex" >> "$build_dir/$name.build.log"
  if [[ "$build_dir" != "$PWD" ]]; then
    cp "$build_dir/$name.pdf" "$name.pdf"
    cp "$build_dir/$name.build.log" "$name.build.log"
  fi
done
