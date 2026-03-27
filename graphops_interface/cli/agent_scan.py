"""Scan: load graphops.yml and GRAPHOPS_API_KEY, run analysis, handle incremental updates via git status."""

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from graphops_interface.api.client import ExternalAPIClient
from graphops_interface.core.config import AgentConfig
from graphops_interface.grammar_registry import get_analyzer
from graphops_interface.utils.encryption import encrypt_payload
from graphops_interface.utils.git import git_status, is_git_repo, GitStatus


# Language to file extensions mapping (same as in agent_git.py)
LANGUAGE_EXTENSIONS: Dict[str, List[str]] = {
    "ruby": [".rb", ".rake", ".gemspec", ".ru"],
    "python": [".py", ".pyw", ".pyi"],
    "javascript": [".js", ".jsx", ".mjs", ".cjs"],
    "typescript": [".ts", ".tsx", ".mts", ".cts"],
    "java": [".java"],
    "go": [".go"],
    "rust": [".rs"],
    "c": [".c", ".h"],
    "cpp": [".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx", ".h"],
    "csharp": [".cs"],
    "php": [".php"],
    "swift": [".swift"],
    "kotlin": [".kt", ".kts"],
    "scala": [".scala"],
    "elixir": [".ex", ".exs"],
    "erlang": [".erl", ".hrl"],
}


def _load_graphops_yml(path: Path) -> Dict[str, Any]:
    """Parse graphops.yml (uuid, root_path, language, excluded_paths, backend_url). Minimal YAML-style parser."""
    if not path.exists():
        raise FileNotFoundError(f"graphops.yml not found: {path}")
    text = path.read_text(encoding="utf-8")
    out: Dict[str, Any] = {"uuid": "", "root_path": "", "language": "", "excluded_paths": [], "backend_url": ""}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if key == "uuid":
            out["uuid"] = value.strip('"').strip("'")
        elif key == "root_path":
            out["root_path"] = value.strip('"').strip("'")
        elif key == "language":
            out["language"] = value.strip('"').strip("'")
        elif key == "excluded_paths":
            value = value.strip()
            if "#" in value:
                value = value.split("#", 1)[0].strip().rstrip(",").strip()
            if value == "[]" or not value:
                out["excluded_paths"] = []
            else:
                try:
                    out["excluded_paths"] = json.loads(value)
                except json.JSONDecodeError:
                    out["excluded_paths"] = []
        elif key == "backend_url":
            out["backend_url"] = value.strip('"').strip("'")
    return out


def _load_api_key(project_root: Path) -> Optional[str]:
    """Load GRAPHOPS_API_KEY: first from .env.graphops in project_root, then from env var."""
    env_path = project_root / ".env.graphops"
    if env_path.exists():
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() == "GRAPHOPS_API_KEY":
                    return v.strip()
        except Exception:
            pass
    return os.environ.get("GRAPHOPS_API_KEY")


def _get_extensions_for_language(language: Optional[str]) -> List[str]:
    """Get file extensions for a language."""
    if not language:
        return []
    lang_key = language.lower().strip()
    return LANGUAGE_EXTENSIONS.get(lang_key, [])


def _is_excluded_path(filepath: str, excluded_paths: List[str]) -> bool:
    """Check if a file path is within any excluded directory."""
    if not excluded_paths:
        return False
    parts = filepath.replace("\\", "/").split("/")
    for excluded in excluded_paths:
        excluded = excluded.strip().strip("/")
        if not excluded:
            continue
        if excluded in parts:
            return True
        if filepath.startswith(excluded + "/") or filepath.startswith(excluded + "\\"):
            return True
        if ("/" + excluded + "/") in ("/" + filepath):
            return True
    return False


def _has_valid_extension(filepath: str, extensions: List[str]) -> bool:
    """Check if a file has one of the valid extensions."""
    if not extensions:
        return True
    filepath_lower = filepath.lower()
    return any(filepath_lower.endswith(ext) for ext in extensions)


def _filter_files(files: List[str], extensions: List[str], excluded_paths: List[str]) -> List[str]:
    """Filter files by extension and excluded paths."""
    result = []
    for f in files:
        if _is_excluded_path(f, excluded_paths):
            continue
        if not _has_valid_extension(f, extensions):
            continue
        result.append(f)
    return result


def _generate_file_hash_id(file_path: str) -> str:
    """Generate a deterministic hash ID for a file path."""
    return hashlib.md5(file_path.encode()).hexdigest()


def _relativize_file_path(path_str: str, root: Path) -> str:
    """
    Make a path relative to root_path, falling back to the original string if it cannot be relativized.
    """
    try:
        p = Path(path_str)
        return str(p.resolve().relative_to(root))
    except Exception:
        try:
          return str(Path(path_str).relative_to(root))
        except Exception:
          return path_str


def _relativize_node_paths(nodes: List[Dict[str, Any]], root: Path) -> None:
    """
    In-place: adjust file_path (and data.filePath) to be relative to root_path.
    """
    for node in nodes:
        fp = node.get("file_path")
        if fp:
            rel = _relativize_file_path(fp, root)
            node["file_path"] = rel
        data = node.get("data")
        if isinstance(data, dict):
            fp2 = data.get("filePath") or data.get("file_path")
            if fp2:
                data["filePath"] = _relativize_file_path(fp2, root)


def create_output_dir() -> Path:
    d = Path.cwd() / "output"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_existing_nodes(output_dir: Path) -> Optional[List[Dict[str, Any]]]:
    """Load existing nodes.json if it exists and has data."""
    nodes_file = output_dir / "nodes.json"
    if not nodes_file.exists():
        return None
    try:
        data = json.loads(nodes_file.read_text(encoding="utf-8"))
        if isinstance(data, list) and len(data) > 0:
            return data
    except (json.JSONDecodeError, IOError):
        pass
    return None


def save_nodes_to_file(nodes: List[Dict[str, Any]], output_dir: Path) -> None:
    (output_dir / "nodes.json").write_text(json.dumps(nodes, indent=2), encoding="utf-8")
    print(f"✓ Wrote {len(nodes)} nodes to nodes.json")


def save_updates_to_file(updates: List[Dict[str, Any]], output_dir: Path) -> None:
    (output_dir / "updates.json").write_text(json.dumps(updates, indent=2), encoding="utf-8")
    print(f"✓ Wrote {len(updates)} updates to updates.json")


def save_classes_to_file(classes_dict: Dict[str, List[str]], output_dir: Path) -> None:
    (output_dir / "classes_dictionary.json").write_text(json.dumps(classes_dict, indent=2, sort_keys=True), encoding="utf-8")
    print(f"✓ Wrote classes_dictionary.json ({len(classes_dict)} files)")


def _fetch_encryption_key(api_key: str) -> Optional[str]:
    """Fetch encryption key from backend (X-API-Key). Key is not stored; use only for this request."""
    try:
        resp = ExternalAPIClient().get("/agents/encryption_key", headers={"X-API-Key": api_key})
        data = resp.get("data", resp) if isinstance(resp, dict) else {}
        if isinstance(data, dict):
            return data.get("encryption_key")
    except Exception:
        pass
    return None


def upload_full_scan(api_key: str, external_uuid: str, nodes: List[Dict], graph_hash_id: str) -> bool:
    """Upload full scan via POST. Returns True on success."""
    if not api_key:
        print("⚠️  Missing GRAPHOPS_API_KEY. Skipping upload.")
        return False
    encryption_key = _fetch_encryption_key(api_key)
    if not encryption_key:
        print("⚠️  Could not fetch encryption key from backend. Skipping upload.")
        return False
    try:
        payload = encrypt_payload({"nodes": nodes, "graph_hash_id": graph_hash_id, "action": "create"}, encryption_key)
        ExternalAPIClient().post(
            f"/agents/{external_uuid}/raw_data/create/",
            data=payload,
            headers={"X-API-Key": api_key},
        )
        print(f"✓ Uploaded {len(nodes)} nodes to backend (full scan)")
        return True
    except Exception as e:
        print(f"⚠️  Upload failed: {e}")
        return False


def upload_incremental_update(api_key: str, external_uuid: str, updates: List[Dict], graph_hash_id: str) -> bool:
    """Upload incremental updates via POST to the create endpoint. Returns True on success."""
    if not api_key:
        print("⚠️  Missing GRAPHOPS_API_KEY. Skipping upload.")
        return False
    encryption_key = _fetch_encryption_key(api_key)
    if not encryption_key:
        print("⚠️  Could not fetch encryption key from backend. Skipping upload.")
        return False
    try:
        payload = encrypt_payload({"nodes": updates, "graph_hash_id": graph_hash_id, "action": "update"}, encryption_key)
        ExternalAPIClient().post(
            f"/agents/{external_uuid}/raw_data/create/",
            data=payload,
            headers={"X-API-Key": api_key},
        )
        print(f"✓ Uploaded {len(updates)} updates to backend (incremental)")
        return True
    except Exception as e:
        print(f"⚠️  Incremental upload failed: {e}")
        return False


def apply_updates_to_nodes(
    existing_nodes: List[Dict[str, Any]],
    updates: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Apply updates to the existing nodes list.
    - 'create': add new node
    - 'update': replace existing node with same file_path
    - 'delete': remove node with matching file_path
    """
    # Index existing nodes by file_path for quick lookup
    nodes_by_path: Dict[str, Dict[str, Any]] = {}
    for node in existing_nodes:
        fp = node.get("file_path")
        if fp:
            nodes_by_path[fp] = node
    
    # Apply updates
    for update in updates:
        action = update.get("action")
        file_path = update.get("file_path")
        
        if not file_path:
            continue
        
        if action == "delete":
            # Remove node with this file_path
            if file_path in nodes_by_path:
                del nodes_by_path[file_path]
        elif action in ("create", "update"):
            # Add or replace node (remove action field for storage)
            node_copy = {k: v for k, v in update.items() if k != "action"}
            nodes_by_path[file_path] = node_copy
    
    return list(nodes_by_path.values())


def run_scan(
    project_name: Optional[str] = None,
    language: Optional[str] = None,
    path: Optional[str | Path] = None,
    analyzer: Optional[Any] = None,
    force_full: bool = False,
) -> None:
    """
    Smart scan with incremental update support.
    
    If output/nodes.json exists and has data:
        - Run git status to detect changed files
        - Scan only modified/created files
        - Mark deleted files for removal
        - Upload via PATCH
        - Update local nodes.json on success
    
    Otherwise:
        - Full scan of root_path
        - Upload via POST
    """
    project_root = Path.cwd().resolve()
    yml_path = project_root / "graphops.yml"
    if not yml_path.exists():
        raise SystemExit(
            "No graphops.yml found in the current directory.\n"
            "Run `graphops scan` from the project root (where `graphops init` created graphops.yml), "
            "or run `graphops init` first."
        )

    # 1) Load config
    api_key = _load_api_key(project_root)
    if not api_key:
        print("⚠️  GRAPHOPS_API_KEY not found in .env.graphops or env. Upload will be skipped.")

    try:
        yml = _load_graphops_yml(yml_path)
    except Exception as e:
        raise SystemExit(f"Failed to load graphops.yml: {e}")

    uuid_val = (yml.get("uuid") or "").strip()
    root_path = (yml.get("root_path") or "").strip()
    lang = (language or yml.get("language") or "").strip()
    excluded_paths = list(yml.get("excluded_paths") or [])
    backend_url = (yml.get("backend_url") or "").strip()

    if not uuid_val:
        raise SystemExit("graphops.yml is missing 'uuid'. Re-run `graphops init`.")
    if not root_path:
        raise SystemExit("graphops.yml is missing 'root_path'. Re-run `graphops init`.")
    if not lang:
        raise SystemExit("graphops.yml is missing 'language'. Re-run `graphops init` or set --language.")

    if backend_url:
        os.environ["GRAPHOPS_INTERFACE_BACKEND_URL"] = f"{backend_url.rstrip('/')}/api/v1"

    scan_path = Path(root_path).expanduser().resolve()
    if not scan_path.exists() or not scan_path.is_dir():
        raise SystemExit(f"root_path in graphops.yml does not exist or is not a directory: {scan_path}")

    # 2) Load analyzer
    if analyzer is None:
        try:
            analyzer = get_analyzer(lang)
        except (ValueError, ModuleNotFoundError):
            dash_lang = lang.replace("_", "-")
            raise SystemExit(
                f"Grammar for language '{lang}' not found. Install the plugin (e.g., pip install {dash_lang}-grammers) "
                f"and re-run graphops scan."
            )

    grammar_hint = f"{lang.replace('_', '-')}-grammers" if lang else "grammar"
    extensions = _get_extensions_for_language(lang)
    out = create_output_dir()
    graph_hash_id = hashlib.md5(root_path.encode()).hexdigest()

    # 3) Check for existing nodes.json and git repo for incremental scan
    existing_nodes = load_existing_nodes(out)
    can_incremental = (
        not force_full
        and existing_nodes is not None
        and is_git_repo(scan_path)
    )

    if can_incremental:
        print(f"📦 Found existing nodes.json with {len(existing_nodes)} nodes")
        print(f"🔍 Checking git status for changes...")
        
        # Get git status
        status: GitStatus = git_status(cwd=scan_path)
        
        # Filter files by language and excluded paths
        modified_files = _filter_files(
            status.modified + status.staged_modified,
            extensions,
            excluded_paths,
        )
        created_files = _filter_files(
            status.created + status.staged_added,
            extensions,
            excluded_paths,
        )
        deleted_files = _filter_files(
            status.deleted + status.staged_deleted,
            extensions,
            excluded_paths,
        )
        
        # Handle renamed files: treat as delete old + create new
        for old_path, new_path in status.renamed:
            if _has_valid_extension(old_path, extensions) and not _is_excluded_path(old_path, excluded_paths):
                deleted_files.append(old_path)
            if _has_valid_extension(new_path, extensions) and not _is_excluded_path(new_path, excluded_paths):
                created_files.append(new_path)
        
        # Deduplicate
        modified_files = list(set(modified_files))
        created_files = list(set(created_files))
        deleted_files = list(set(deleted_files))
        
        total_changes = len(modified_files) + len(created_files) + len(deleted_files)
        
        if total_changes == 0:
            print("✓ No changes detected. Nothing to update.")
            return
        
        print(f"\n📝 Changes detected:")
        if modified_files:
            print(f"   Modified: {len(modified_files)} file(s)")
        if created_files:
            print(f"   Created:  {len(created_files)} file(s)")
        if deleted_files:
            print(f"   Deleted:  {len(deleted_files)} file(s)")
        
        # 4) Build updates list
        updates: List[Dict[str, Any]] = []
        
        # Process deleted files
        for rel_path in deleted_files:
            abs_path = scan_path / rel_path
            rel_str = _relativize_file_path(str(abs_path), scan_path)
            updates.append({
                "id": _generate_file_hash_id(rel_str),
                "file_path": rel_str,
                "action": "delete",
            })
        
        # Process modified and created files
        files_to_scan = []
        for rel_path in modified_files:
            files_to_scan.append((rel_path, "update"))
        for rel_path in created_files:
            files_to_scan.append((rel_path, "create"))
        
        if files_to_scan:
            print(f"\n🔬 Scanning {len(files_to_scan)} file(s)...")
            
            # We need to scan each file individually
            # First, build class registry for the whole project (needed for resolving references)
            try:
                analyzer.build_class_registry(scan_path, excluded_paths=excluded_paths)
            except (TypeError, AttributeError):
                pass  # Analyzer may not have this method
            
            for rel_path, action in files_to_scan:
                abs_path = scan_path / rel_path
                rel_str = _relativize_file_path(str(abs_path), scan_path)
                if not abs_path.exists():
                    # File was created but doesn't exist? Skip
                    continue
                
                try:
                    file_nodes = analyzer.analyze_file(abs_path)
                    formatted = getattr(analyzer, "format_nodes", lambda n: n)(file_nodes)
                    # Apply the same post-processing used in directory scans (namespace synthesis, new->initialize mapping, call filtering)
                    for step in [
                        "_add_synthetic_namespace_nodes",
                        "_map_new_calls_to_initialize",
                        "_filter_calls_by_method_definitions",
                    ]:
                        fn = getattr(analyzer, step, None)
                        if callable(fn):
                            try:
                                fn(formatted)
                            except Exception:
                                # Best-effort; continue if a helper isn't compatible
                                pass

                    for node in formatted:
                        _relativize_node_paths([node], scan_path)
                        node["action"] = action
                        updates.append(node)
                except Exception as e:
                    print(f"   ⚠️  Failed to scan {rel_path}: {e}")
        
        # Save updates.json
        save_updates_to_file(updates, out)
        
        # 5) Upload incremental updates
        if api_key:
            success = upload_incremental_update(api_key, uuid_val, updates, graph_hash_id)
            
            if success:
                # 6) Update local nodes.json
                print("📝 Updating local nodes.json...")
                updated_nodes = apply_updates_to_nodes(existing_nodes, updates)
                save_nodes_to_file(updated_nodes, out)
        else:
            print("⚠️  No GRAPHOPS_API_KEY. Skipping upload.")
            print("   Run again with API key to sync with backend.")
        
        print(f"\n✓ Incremental scan complete. Output: {out}")
    
    else:
        # Full scan
        if force_full:
            print("🔄 Force full scan requested")
        elif existing_nodes is None:
            print("📦 No existing nodes.json found. Running full scan...")
        elif not is_git_repo(scan_path):
            print("📦 Not a git repository. Running full scan...")
        
        print(f"Using language '{lang}' from graphops.yml ({grammar_hint})")
        print(f"Scanning: {scan_path}")
        
        try:
            nodes = analyzer.analyze_directory(scan_path, excluded_paths=excluded_paths)
        except TypeError:
            nodes = analyzer.analyze_directory(scan_path)
        
        formatted = getattr(analyzer, "format_nodes", lambda n: n)(nodes)
        _relativize_node_paths(formatted, scan_path)
        classes = getattr(analyzer, "build_classes_dictionary", lambda: {})()
        
        save_nodes_to_file(formatted, out)
        save_classes_to_file(classes, out)

        if api_key:
            upload_full_scan(api_key, uuid_val, formatted, graph_hash_id)
        else:
            print("⚠️  No GRAPHOPS_API_KEY. Skipping upload.")
        
        print(f"\n✓ Full scan complete. Output: {out}")
