#!/usr/bin/env python3
"""Run the OverseaArk end-to-end verification suite."""

from __future__ import annotations

import argparse
import os
import sys
import unittest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mock",
        action="store_true",
        help="start the stdlib mock OverseaArk server before running tests",
    )
    parser.add_argument(
        "--base-url",
        help="target service URL; defaults to OVERSEAARK_BASE_URL",
    )
    parser.add_argument(
        "--failfast",
        action="store_true",
        help="stop after the first failing test",
    )
    args = parser.parse_args()

    if args.mock:
        os.environ["OVERSEAARK_E2E_MOCK"] = "1"
    if args.base_url:
        os.environ["OVERSEAARK_BASE_URL"] = args.base_url.rstrip("/")

    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    suite = unittest.defaultTestLoader.discover(start_dir=os.path.dirname(__file__), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2, failfast=args.failfast).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
