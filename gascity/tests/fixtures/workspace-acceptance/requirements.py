#!/usr/bin/env python3
"""Frozen order-calculator requirements, run outside the project under test."""
import argparse
import importlib
import json
from pathlib import Path
import sys


def check(project, stage):
    requirements = json.loads(Path(__file__).with_name("requirements.json").read_text())
    sys.path.insert(0, str(project))
    pricing, shipping, quote, receipt = (
        importlib.import_module(name) for name in ("pricing", "shipping", "quote", "receipt")
    )
    checks = []

    def assertion(name, expected, observe):
        try:
            actual = observe()
            checks.append({"name": name, "status": "pass" if actual == expected else "fail",
                           "expected": expected, "actual": actual})
        except Exception as exc:
            checks.append({"name": name, "status": "fail", "error": f"{type(exc).__name__}: {exc}"})

    if stage in ("A", "AB", "C", "D"):
        assertion("A.quantity-subtotal", requirements["subtotal_cents"],
                  lambda: pricing.subtotal(requirements["items"]))
        assertion("A.empty-subtotal", 0, lambda: pricing.subtotal([]))
    if stage in ("B", "AB", "C", "D"):
        for zone, cost in requirements["shipping_cents"].items():
            assertion(f"B.{zone}-shipping", cost, lambda zone=zone: shipping.shipping_cost(zone))
    if stage in ("C", "D"):
        for zone in ("domestic", "international"):
            assertion(f"C.{zone}-quote", requirements[f"{zone}_quote"],
                      lambda zone=zone: quote.quote(requirements["items"], zone))
        assertion("C.empty-quote", requirements["empty_quote"], lambda: quote.quote([], "domestic"))
    if stage == "D":
        for zone in ("domestic", "international"):
            assertion(f"D.{zone}-receipt", requirements[f"{zone}_receipt"],
                      lambda zone=zone: receipt.render_receipt(quote.quote(requirements["items"], zone)))
    return {"stage": stage, "status": "pass" if all(c["status"] == "pass" for c in checks) else "fail",
            "checks": checks}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--stage", required=True, choices=("A", "B", "AB", "C", "D"))
    args = parser.parse_args()
    result = check(args.project.resolve(), args.stage)
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0 if result["status"] == "pass" else 1)
