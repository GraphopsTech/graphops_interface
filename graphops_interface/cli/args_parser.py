import argparse
import re


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Graph Ops Interface - Backend communication. Grammar plugins plug in for language-specific scanning.")
    sub = parser.add_subparsers(dest="command", help="Commands", required=True)

    p_scan = sub.add_parser("scan", help="Scan project and write nodes.json.")
    p_scan.add_argument("--project", "-p", help="Project to scan.")
    p_scan.add_argument("--language", "-l", help="Override project language (e.g. ruby, python).")
    p_scan.add_argument("--path", help="Override project root path for this run.")

    p_full_scan = sub.add_parser(
        "full_scan",
        help="Full scan of Ruby project via ruby_base (no incremental). Writes output/nodes.json and uploads.",
    )
    p_full_scan.add_argument("--path", "-p", help="Override root path (default from graphops.yml root_path).")
    p_full_scan.add_argument("--rules-dir", "-r", help="Path to rules directory (e.g. backend/rules).")
    p_full_scan.add_argument("--exclude", action="append", metavar="DIR", help="Exclude directory (repeatable).")
    p_full_scan.add_argument("--output", "-o", help="Output base path (default: output/nodes.pb -> output/nodes_batches/*.pb.gz).")
    p_full_scan.add_argument("--backend-url", "-b", help="Backend URL for rules and upload.")
    p_full_scan.add_argument("--validate-ids", action="store_true", help="Validate all IDs during extraction.")
    p_full_scan.add_argument("--no-upload", action="store_true", help="Skip uploading to backend.")

    p_scan2 = sub.add_parser(
        "scan2",
        help="Incremental scan: full scan if no output; else git status + scan changed files only. Writes updates.json and uploads.",
    )
    p_scan2.add_argument("--path", "-p", help="Override root path (default from graphops.yml root_path).")
    p_scan2.add_argument("--rules-dir", "-r", help="Path to rules directory (e.g. backend/rules).")
    p_scan2.add_argument("--exclude", action="append", metavar="DIR", help="Exclude directory (repeatable, e.g. tmp vendor log).")
    p_scan2.add_argument("--output", "-o", help="Output base path (default: output/nodes.pb -> output/nodes_batches/*.pb.gz).")
    p_scan2.add_argument("--backend-url", "-b", help="Backend URL to fetch missing rules.")
    p_scan2.add_argument("--validate-ids", action="store_true", help="Validate all IDs during extraction (fail on mismatch).")
    p_scan2.add_argument("--no-upload", action="store_true", help="Skip uploading to backend (default: upload when api_key and uuid are set).")

    init_parser = sub.add_parser("init", help="Initialize project: set API key and root path (interactive or via arguments).")
    init_parser.add_argument("--api-key", "-k", dest="api_key", help="Agent API key (from the agent show page).")
    init_parser.add_argument("--root-path", "-r", dest="root_path", help="Root path of the project to scan.")
    init_parser.add_argument(
        "extra",
        nargs="*",
        help=argparse.SUPPRESS,
        metavar="",
    )

    args = parser.parse_args()

    # Support "graphops init API_KEY=xxx" or "graphops init API_KEY=xxx ROOT_PATH=/path" style
    if getattr(args, "command", None) == "init" and getattr(args, "extra", None):
        for tok in args.extra:
            m = re.match(r"API_KEY=(.+)", tok, re.IGNORECASE)
            if m and not getattr(args, "api_key", None):
                args.api_key = m.group(1).strip().strip("'\"")
            m = re.match(r"ROOT_PATH=(.+)", tok, re.IGNORECASE)
            if m and not getattr(args, "root_path", None):
                args.root_path = m.group(1).strip().strip("'\"")

    return args
