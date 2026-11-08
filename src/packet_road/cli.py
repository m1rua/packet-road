import argparse
import json
import logging

from packet_road.core import PolicyError, diagnose


def main():
    parser = argparse.ArgumentParser(description="Diagnostics from this process network namespace")
    parser.add_argument("target")
    parser.add_argument("--port", type=int, default=443)
    parser.add_argument("--max-hops", type=int, default=16)
    parser.add_argument("--allow-private", action="store_true", help="Explicit local CLI opt-in")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    try:
        result = diagnose(args.target, args.port, args.max_hops, args.allow_private)
    except PolicyError as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if all(s["status"] == "ok" for s in result["stages"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
