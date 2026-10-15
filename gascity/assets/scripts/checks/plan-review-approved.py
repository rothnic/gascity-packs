#!/usr/bin/env python3
"""Native check gate for the default plan-review contract."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from validate_plan_review import main

if __name__ == "__main__":
    raise SystemExit(main(["native-check"]))
