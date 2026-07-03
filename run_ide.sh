#!/usr/bin/env bash
# Lanzador del IDE del compilador (Linux / macOS / Git Bash).
cd "$(dirname "$0")" || exit 1
python3 ide.py 2>/dev/null || python ide.py
