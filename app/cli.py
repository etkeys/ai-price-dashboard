"""Command line interface entry point for the ai-price-dashboard package."""

import argparse
import sys

from app import create_app


def main(argv: list[str] | None = None) -> int:
    """Run a simple CLI command for the application package."""
    parser = argparse.ArgumentParser(
        prog="ai-price-dashboard",
        description="AI Price Dashboard CLI",
    )
    parser.add_argument(
        "command",
        choices=["routes"],
        help="Command to run (routes: list registered URL rules).",
    )
    args = parser.parse_args(argv)

    if args.command == "routes":
        app = create_app("development")
        for rule in app.url_map.iter_rules():
            print(f"{rule.endpoint:30} {rule.methods - {'HEAD', 'OPTIONS'}} {rule.rule}")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
