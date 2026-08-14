from __future__ import annotations

import argparse
import json

from ten_minute_stanford.audit import audit_publication


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Recompute publication claims and verify source provenance."
    )
    parser.add_argument(
        "--require-raw",
        action="store_true",
        help="Verify every active cached source response and regenerate its manifest.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write publication_audit.json and, with --require-raw, source_manifest.json.",
    )
    args = parser.parse_args()
    report = audit_publication(check_raw=args.require_raw, write=args.write)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
