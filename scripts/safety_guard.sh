#!/bin/bash
# Safety guard for rh-volume-ignition project isolation

BOUNDARY_FILE=".rhvolume-boundary"

get_project_root() {
    if [ -f "$BOUNDARY_FILE" ]; then
        grep "^absolute_project_root=" "$BOUNDARY_FILE" | cut -d= -f2
    else
        echo ""
    fi
}

assert_root() {
    ROOT=$(get_project_root)
    if [ -z "$ROOT" ]; then
        echo "ERROR: Boundary file not found or invalid"
        exit 1
    fi
    
    CURRENT_DIR=$(pwd)
    if [[ "$CURRENT_DIR" != "$ROOT"* ]]; then
        echo "ERROR: Current directory ($CURRENT_DIR) is outside project root ($ROOT)"
        exit 1
    fi
    
    echo "OK: Project root verified: $ROOT"
    exit 0
}

assert_path() {
    if [ -z "$1" ]; then
        echo "ERROR: Target path required"
        exit 1
    fi
    
    ROOT=$(get_project_root)
    if [ -z "$ROOT" ]; then
        echo "ERROR: Boundary file not found or invalid"
        exit 1
    fi
    
    # Resolve absolute path
    TARGET=$(readlink -f "$1" 2>/dev/null || echo "$1")
    
    if [[ "$TARGET" != "$ROOT"/* ]] && [ "$TARGET" != "$ROOT" ]; then
        echo "ERROR: Target path ($TARGET) is outside project root ($ROOT)"
        echo "EXTERNAL PATH DETECTED - STOPPING"
        exit 1
    fi
    
    echo "OK: Target path is inside project: $TARGET"
    exit 0
}

case "$1" in
    --assert-root)
        assert_root
        ;;
    --assert-path)
        assert_path "$2"
        ;;
    *)
        echo "Usage: $0 --assert-root | --assert-path <target>"
        exit 1
        ;;
esac
