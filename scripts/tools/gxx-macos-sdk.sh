#!/bin/sh
# Same as gcc-macos-sdk.sh for g++ (C++ standard headers).
# Usage: export GXX_PATH="$PWD/scripts/tools/gxx-macos-sdk.sh"
exec /opt/homebrew/bin/g++-16 -isysroot "$(xcrun --show-sdk-path)" "$@"
