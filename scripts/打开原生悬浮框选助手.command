#!/bin/zsh
set -e
cd "$(dirname "$0")/.."
PYTHONPATH=src python3 floating_region_assistant.py
