"""Init: collect api_key and root_path from env vars, arguments, or interactive prompts; call backend init, write graphops.yml and .env.graphops."""

import json
import os
import urllib.error
from getpass import getpass
from pathlib import Path
from typing import Optional

from graphops_interface.api.client import ExternalAPIClient


def run_init(api_key: Optional[str] = None, root_path: Optional[str] = None) -> None:
    """
    Run graphops init: first check env vars GRAPHOPS_API_KEY and GRAPHOPS_ROOT_PATH.
    If both are set, use them and proceed. Otherwise use provided arguments, then prompt for any missing value.
    POST to api/v1/agents/init with X-API-Key header and root_path in body.
    On success, write graphops.yml (uuid, root_path, language, excluded_paths) and .env.graphops (api_key).
    """
    print("=" * 60)
    print("GraphOps Init")
    print("=" * 60)
    print()

    # 1) Check env vars first; if both set, no need for args or prompts
    api_key = api_key or os.environ.get("GRAPHOPS_API_KEY")
    root_path = root_path or os.environ.get("GRAPHOPS_ROOT_PATH")

    # 2) If still missing, use args (already merged above) or prompt
    if not api_key:
        api_key = getpass("API key (hidden): ").strip()
    if not api_key:
        print("API key is required. Set GRAPHOPS_API_KEY, pass --api-key, or enter when prompted. Init cancelled.")
        return

    default_root = str(Path.cwd())
    if not root_path:
        root_path = input(f"Root path for your project [{default_root}]: ").strip() or default_root

    try:
        root_path_resolved = Path(root_path).expanduser().resolve()
    except Exception as e:
        print(f"Invalid root path: {e}")
        return
    if not root_path_resolved.exists() or not root_path_resolved.is_dir():
        print(f"Root path does not exist or is not a directory: {root_path_resolved}")
        return
    root_path = str(root_path_resolved)

    print("\nSending init request to backend...")
    try:
        resp = ExternalAPIClient().post(
            "/agents/init",
            data={"root_path": root_path},
            headers={"X-API-Key": api_key},
        )
    except urllib.error.HTTPError as e:
        try:
            body = (e.fp.read().decode("utf-8") if getattr(e, "fp", None) else "") or ""
        except Exception:
            body = str(e)
        try:
            err = json.loads(body) if body else {}
            msg = err.get("message") or err.get("error") or body or str(e)
        except Exception:
            msg = body or str(e)
        print(f"✗ Init failed: {msg}")
        return
    except Exception as e:
        print(f"✗ Init failed: {e}")
        return

    data = resp.get("data", resp) if isinstance(resp, dict) else {}
    if not isinstance(data, dict):
        data = {}
    uuid_val = data.get("uuid")
    language = data.get("language") or "ruby"

    if not uuid_val:
        print("✗ Init failed: backend did not return uuid.")
        return

    _write_graphops_yml(root_path=root_path, uuid=uuid_val, language=language)
    _write_env_file(root_path=root_path, api_key=api_key)

    print("✓ Init complete")
    print("-" * 60)
    print(f"  graphops.yml:  {Path(root_path).expanduser().resolve() / 'graphops.yml'}")
    print(f"  .env.graphops: {Path(root_path).expanduser().resolve() / '.env.graphops'}")
    print("-" * 60)


def _write_graphops_yml(root_path: str, uuid: str, language: str) -> None:
    """Create graphops.yml in root_path with uuid, root_path, language, excluded_paths."""
    path = Path(root_path).expanduser().resolve() / "graphops.yml"
    # Default excluded_paths: db (migrations), vendor, tmp so migrations/framework noise stay out of the graph
    default_excluded = '["db", "vendor", "tmp", "test", "tests", "spec", "specs", "config"]'
    content = f"""uuid: "{uuid}"
root_path: "{root_path}"
language: "{language}"
excluded_paths: {default_excluded}
"""
    try:
        path.write_text(content.strip() + "\n", encoding="utf-8")
        print(f"✓ Wrote {path}")
    except Exception as e:
        print(f"Warning: failed to write graphops.yml at {path}: {e}")


def _write_env_file(root_path: str, api_key: str) -> None:
    """Create .env.graphops in root_path with api_key only."""
    path = Path(root_path).expanduser().resolve() / ".env.graphops"
    content = f"# GraphOps API key (treat as secret)\nGRAPHOPS_API_KEY={api_key}\n"
    try:
        path.write_text(content, encoding="utf-8")
        print(f"✓ Wrote {path}")
    except Exception as e:
        print(f"Warning: failed to write .env.graphops at {path}: {e}")
