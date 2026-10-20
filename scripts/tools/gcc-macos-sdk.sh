#!/bin/sh
# Homebrew GCC on macOS cannot find system headers (stdio.h) without the SDK sysroot.
# The data engineer's adapter runs this path as the compiler, so it must accept gcc's arguments.
# Usage: export GCC_PATH="$PWD/scripts/tools/gcc-macos-sdk.sh"
exec /opt/homebrew/bin/gcc-16 -isysroot "$(xcrun --show-sdk-path)" "$@"
