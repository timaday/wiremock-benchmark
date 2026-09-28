#!/usr/bin/env python3
"""Read the retained full capture for one client ID without modifying the archive."""
import argparse
import json
import sqlite3
import zlib
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--request-id", required=True)
    args = parser.parse_args()
    run_id = args.request_id.split("-", 1)[0]
    with sqlite3.connect(f"file:{args.archive.resolve()}?mode=ro", uri=True) as db:
        rows = db.execute(
            "SELECT payload_zlib FROM events WHERE run_id=? AND request_id=? ORDER BY phase",
            (run_id, args.request_id),
        )
        count = 0
        for (payload,) in rows:
            print(json.dumps(json.loads(zlib.decompress(payload))))
            count += 1
    if count == 0:
        parser.exit(1, "No capture found for the supplied client ID\n")


if __name__ == "__main__":
    main()
