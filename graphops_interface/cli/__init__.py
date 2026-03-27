"""CLI module for graphops interface."""

import sys

from graphops_interface.cli.agent_init import run_init
from graphops_interface.cli.agent_scan import run_scan
from graphops_interface.cli.agent_full_scan import run_full_scan
from graphops_interface.cli.agent_scan2 import run_scan2
from graphops_interface.cli.args_parser import parse_args


def main() -> None:
    args = parse_args()
    if args.command == "scan":
        run_scan(project_name=getattr(args, "project", None), language=getattr(args, "language", None), path=getattr(args, "path", None))
    elif args.command == "full_scan":
        run_full_scan(
            path=getattr(args, "path", None),
            rules_dir=getattr(args, "rules_dir", None),
            exclude=getattr(args, "exclude", None),
            output=getattr(args, "output", None),
            backend_url=getattr(args, "backend_url", None),
            validate_ids=getattr(args, "validate_ids", False),
            no_upload=getattr(args, "no_upload", False),
        )
    elif args.command == "scan2":
        run_scan2(
            path=getattr(args, "path", None),
            rules_dir=getattr(args, "rules_dir", None),
            exclude=getattr(args, "exclude", None),
            output=getattr(args, "output", None),
            backend_url=getattr(args, "backend_url", None),
            validate_ids=getattr(args, "validate_ids", False),
            no_upload=getattr(args, "no_upload", False),
        )
    elif args.command == "init":
        run_init(
            api_key=getattr(args, "api_key", None),
            root_path=getattr(args, "root_path", None),
            dev=getattr(args, "dev", False),
        )
    else:
        print("Use: graphops scan | graphops full_scan | graphops scan2 | graphops init")
        print("Run 'graphops --help' for details.")
        sys.exit(1)
