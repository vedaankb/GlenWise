#!/usr/bin/env bash
# Generate a lightweight SBOM snapshot for releases (D13). Full CycloneDX signing
# rides with the first tagged release; this script publishes lockfile inventories.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
out="${1:-"$root/dist/sbom"}"
mkdir -p "$out"

echo "Writing Python inventory…"
(cd "$root/services/core" && uv export --frozen --no-dev --no-hashes > "$out/python-requirements.txt")

echo "Writing JavaScript inventory…"
(cd "$root" && pnpm list -r --depth Infinity --json > "$out/pnpm-deps.json" 2>/dev/null || pnpm list -r --depth 1 --json > "$out/pnpm-deps.json")

{
  echo "# GleanWise SBOM snapshot"
  echo
  echo "Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo
  echo "- Python: \`python-requirements.txt\` (from uv.lock)"
  echo "- JavaScript: \`pnpm-deps.json\` (from pnpm-lock.yaml)"
  echo
  echo "Signed CycloneDX artifacts ship with tagged releases."
} > "$out/README.md"

echo "Wrote $out"
