#!/bin/bash
set -e

# 下载 python-build-standalone 的独立 Python 构建
# https://github.com/indygreg/python-build-standalone
#
# 用法：
#   ./download-python.sh          # 自动检测当前平台
#   ./download-python.sh mac      # 仅下载 macOS (arm64 + x64)
#   ./download-python.sh linux    # 仅下载 Linux x64
#   ./download-python.sh win      # 仅下载 Windows x64

PYTHON_VERSION="3.11"
PBS_VERSION="20241016"
PATCH_VERSION="10"
DOWNLOAD_DIR="$(dirname "$0")/../python-runtime"

mkdir -p "$DOWNLOAD_DIR"

# ── 平台检测 ──────────────────────────────────────────────────────────────────
ARG="${1:-}"
if [ -z "$ARG" ]; then
  case "$(uname -s)" in
    Darwin*)  ARG="mac" ;;
    Linux*)   ARG="linux" ;;
    *)        ARG="win" ;;   # MINGW / MSYS / Cygwin
  esac
fi

echo "Downloading Python standalone builds for: $ARG"

# ── macOS ─────────────────────────────────────────────────────────────────────
download_mac() {
  if [ ! -d "$DOWNLOAD_DIR/darwin-arm64" ]; then
    echo "Downloading Python for macOS arm64..."
    curl -fL "https://github.com/indygreg/python-build-standalone/releases/download/${PBS_VERSION}/cpython-${PYTHON_VERSION}.${PATCH_VERSION}+${PBS_VERSION}-aarch64-apple-darwin-install_only.tar.gz" \
      -o "/tmp/python-darwin-arm64.tar.gz"
    mkdir -p "$DOWNLOAD_DIR/darwin-arm64"
    tar -xzf "/tmp/python-darwin-arm64.tar.gz" -C "$DOWNLOAD_DIR/darwin-arm64" --strip-components=1
    rm "/tmp/python-darwin-arm64.tar.gz"
    echo "✓ macOS arm64 Python downloaded"
  fi

  if [ ! -d "$DOWNLOAD_DIR/darwin-x64" ]; then
    echo "Downloading Python for macOS x64..."
    curl -fL "https://github.com/indygreg/python-build-standalone/releases/download/${PBS_VERSION}/cpython-${PYTHON_VERSION}.${PATCH_VERSION}+${PBS_VERSION}-x86_64-apple-darwin-install_only.tar.gz" \
      -o "/tmp/python-darwin-x64.tar.gz"
    mkdir -p "$DOWNLOAD_DIR/darwin-x64"
    tar -xzf "/tmp/python-darwin-x64.tar.gz" -C "$DOWNLOAD_DIR/darwin-x64" --strip-components=1
    rm "/tmp/python-darwin-x64.tar.gz"
    echo "✓ macOS x64 Python downloaded"
  fi
}

# ── Linux ─────────────────────────────────────────────────────────────────────
download_linux() {
  if [ ! -d "$DOWNLOAD_DIR/linux-x64" ]; then
    echo "Downloading Python for Linux x64..."
    curl -fL "https://github.com/indygreg/python-build-standalone/releases/download/${PBS_VERSION}/cpython-${PYTHON_VERSION}.${PATCH_VERSION}+${PBS_VERSION}-x86_64-unknown-linux-gnu-install_only.tar.gz" \
      -o "/tmp/python-linux-x64.tar.gz"
    mkdir -p "$DOWNLOAD_DIR/linux-x64"
    tar -xzf "/tmp/python-linux-x64.tar.gz" -C "$DOWNLOAD_DIR/linux-x64" --strip-components=1
    rm "/tmp/python-linux-x64.tar.gz"
    echo "✓ Linux x64 Python downloaded"
  fi
}

# ── Windows ───────────────────────────────────────────────────────────────────
download_win() {
  if [ ! -d "$DOWNLOAD_DIR/win32-x64" ]; then
    echo "Downloading Python for Windows x64..."
    curl -fL "https://github.com/indygreg/python-build-standalone/releases/download/${PBS_VERSION}/cpython-${PYTHON_VERSION}.${PATCH_VERSION}+${PBS_VERSION}-x86_64-pc-windows-msvc-install_only.tar.gz" \
      -o "/tmp/python-win32-x64.tar.gz"
    mkdir -p "$DOWNLOAD_DIR/win32-x64"
    # Windows tar 不支持 symlink，用 --no-same-owner 跳过权限问题；
    # symlink 失败只是警告，Python 主程序仍可正常解压
    tar -xzf "/tmp/python-win32-x64.tar.gz" -C "$DOWNLOAD_DIR/win32-x64" --strip-components=1 2>/dev/null || true
    rm "/tmp/python-win32-x64.tar.gz"
    echo "✓ Windows x64 Python downloaded"
  fi
}

# ── 执行 ──────────────────────────────────────────────────────────────────────
case "$ARG" in
  mac)   download_mac ;;
  linux) download_linux ;;
  win)   download_win ;;
  all)   download_mac; download_linux; download_win ;;
  *)     echo "Unknown platform: $ARG (use mac/linux/win/all)"; exit 1 ;;
esac

echo ""
echo "Python runtime ready:"
ls -lh "$DOWNLOAD_DIR"
