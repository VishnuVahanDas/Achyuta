#!/usr/bin/env bash
# Download the Tailwind standalone CLI (no Node needed) into bin/tailwindcss.
set -euo pipefail

VERSION="${1:?usage: install_tailwind.sh <version>}"

case "$(uname -s)-$(uname -m)" in
  Linux-x86_64) TARGET=linux-x64 ;;
  Linux-aarch64) TARGET=linux-arm64 ;;
  Darwin-x86_64) TARGET=macos-x64 ;;
  Darwin-arm64) TARGET=macos-arm64 ;;
  *) echo "Unsupported platform: $(uname -s)-$(uname -m)" >&2; exit 1 ;;
esac

mkdir -p bin
curl -fsSL -o bin/tailwindcss \
  "https://github.com/tailwindlabs/tailwindcss/releases/download/v${VERSION}/tailwindcss-${TARGET}"
chmod +x bin/tailwindcss
echo "Installed $(bin/tailwindcss --help | head -n 1)"
