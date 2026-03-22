"""Scan2: Incremental scan. Full scan if no output; else git status + scan changed files only."""

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

try:
    from graphops_interface.api.client import ExternalAPIClient
    from graphops_interface.utils.git import git_status, is_git_repo, GitStatus
    from ruby_base.proto import ProtobufNodeBatchWriter, list_batch_files, read_all_batches
except ImportError:
    ExternalAPIClient = None  # type: ignore
    git_status = None  # type: ignore
    is_git_repo = None  # type: ignore
    GitStatus = None  # type: ignore
    ProtobufNodeBatchWriter = None  # type: ignore
    list_batch_files = None  # type: ignore
    read_all_batches = None  # type: ignore


def _load_api_key(project_root: Path) -> Optional[str]:
    """Load GRAPHOPS_API_KEY from .env.graphops or env."""
    env_path = project_root / ".env.graphops"
    if env_path.exists():
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() == "GRAPHOPS_API_KEY":
                    return v.strip()
        except Exception:
            pass
    return os.environ.get("GRAPHOPS_API_KEY")


def _fetch_encryption_key(api_key: str) -> Optional[str]:
    """Fetch encryption key from backend."""
    if not ExternalAPIClient:
        return None
    try:
        resp = ExternalAPIClient().get("/agents/encryption_key", headers={"X-API-Key": api_key})
        data = resp.get("data", resp) if isinstance(resp, dict) else {}
        return data.get("encryption_key") if isinstance(data, dict) else None
    except Exception:
        return None


def _load_graphops_yml(path: Path) -> Dict[str, Any]:
    """Minimal parser for graphops.yml."""
    if not path.exists():
        return {"uuid": "", "root_path": "", "excluded_paths": [], "backend_url": ""}
    text = path.read_text(encoding="utf-8")
    out: Dict[str, Any] = {"uuid": "", "root_path": "", "excluded_paths": [], "backend_url": ""}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key == "uuid":
            out["uuid"] = value
        elif key == "root_path":
            out["root_path"] = value
        elif key == "excluded_paths":
            if value and value != "[]":
                try:
                    out["excluded_paths"] = json.loads(value)
                except Exception:
                    out["excluded_paths"] = []
        elif key == "backend_url":
            out["backend_url"] = value or ""
    return out


def _resolve_backend_url(
    explicit: Optional[str],
    yml: Dict[str, Any],
) -> Optional[str]:
    """
    Resolve backend URL for rule fetching. RuleLoader expects base URL (no /api/v1).
    Priority: explicit arg > graphops.yml backend_url > env GRAPHOPS_INTERFACE_BACKEND_URL.
    """
    if explicit and str(explicit).strip():
        url = str(explicit).rstrip("/")
    else:
        yml_url = (yml.get("backend_url") or "").strip()
        if yml_url:
            url = yml_url.rstrip("/")
        else:
            url = (os.environ.get("GRAPHOPS_INTERFACE_BACKEND_URL") or "").strip().rstrip("/")
    if not url:
        return None
    # RuleLoader appends /api/v1/rules/... so strip /api/v1 if present
    if url.endswith("/api/v1"):
        url = url[: -len("/api/v1")].rstrip("/")
    return url if url else None


def _load_existing_nodes(out_path: Path) -> Optional[List[Dict[str, Any]]]:
    """Load nodes from json (legacy) or protobuf batches."""
    try:
        if out_path.exists() and out_path.is_file():
            data = json.loads(out_path.read_text(encoding="utf-8"))
            nodes = data if isinstance(data, list) else data.get("nodes", [])
            if isinstance(nodes, list) and len(nodes) > 0:
                return nodes
        batches_dir = _batches_output_dir(out_path)
        if (
            read_all_batches is not None
            and batches_dir.exists()
            and batches_dir.is_dir()
        ):
            nodes = read_all_batches(batches_dir, "nodes")
            return nodes if nodes else None
    except Exception:
        pass
    return None


def _batches_output_dir(nodes_out_path: Path) -> Path:
    if nodes_out_path.suffix:
        return nodes_out_path.parent / f"{nodes_out_path.stem}_batches"
    return nodes_out_path


def _load_existing_namespaces(nodes_out_path: Path) -> Optional[List[Dict[str, Any]]]:
    """Load namespaces from json (legacy) or protobuf batches."""
    try:
        namespaces_path = nodes_out_path.with_name("namespaces.json")
        if namespaces_path.exists() and namespaces_path.is_file():
            data = json.loads(namespaces_path.read_text(encoding="utf-8"))
            namespaces = data if isinstance(data, list) else data.get("namespaces", [])
            if isinstance(namespaces, list) and len(namespaces) > 0:
                return namespaces
        batches_dir = _batches_output_dir(nodes_out_path)
        if (
            read_all_batches is not None
            and batches_dir.exists()
            and batches_dir.is_dir()
        ):
            namespaces = read_all_batches(batches_dir, "namespaces")
            return namespaces if namespaces else None
    except Exception:
        pass
    return None


def _load_existing_graph_items(nodes_out_path: Path) -> Optional[List[Dict[str, Any]]]:
    """Load and combine nodes + namespaces for upload/update flows."""
    nodes = _load_existing_nodes(nodes_out_path) or []
    namespaces = _load_existing_namespaces(nodes_out_path) or []
    combined = nodes + namespaces
    return combined or None


def _write_split_outputs(items: List[Dict[str, Any]], nodes_out_path: Path) -> None:
    """Write protobuf+gzip batch files split by node_type."""
    if ProtobufNodeBatchWriter is None:
        raise RuntimeError("ruby_base protobuf utilities are unavailable")

    nodes_only: List[Dict[str, Any]] = []
    namespaces_only: List[Dict[str, Any]] = []
    for item in items:
        if item.get("node_type") == "namespace":
            namespaces_only.append(item)
        else:
            nodes_only.append(item)

    output_dir = _batches_output_dir(nodes_out_path)
    writer = ProtobufNodeBatchWriter(output_dir=output_dir)
    writer.reset_output_dir()
    node_files = writer.write_kind(
        kind="nodes",
        root_path=nodes_out_path.parent,
        records=nodes_only,
        batch_size=1000,
    )
    namespace_files = writer.write_kind(
        kind="namespaces",
        root_path=nodes_out_path.parent,
        records=namespaces_only,
        batch_size=1000,
    )
    writer.write_manifest(
        {
            "format": "protobuf-gzip",
            "output_dir": str(output_dir),
            "nodes_batch_files": [str(p) for p in node_files],
            "namespaces_batch_files": [str(p) for p in namespace_files],
            "nodes_count": len(nodes_only),
            "namespaces_count": len(namespaces_only),
        }
    )


def _is_excluded_path(filepath: str, excluded_paths: List[str]) -> bool:
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
    return False


def _filter_ruby_files(files: List[str], excluded_paths: List[str]) -> List[str]:
    """Filter to .rb files, excluding specified dirs."""
    result = []
    for f in files:
        if not f.lower().endswith(".rb"):
            continue
        if _is_excluded_path(f, excluded_paths):
            continue
        result.append(f)
    return list(set(result))


def _upload_scan2(
    api_key: str,
    external_uuid: str,
    nodes: List[Dict[str, Any]],
    graph_hash_id: str,
    action: str = "create",
) -> bool:
    """Legacy encrypted JSON upload (kept for backward compatibility)."""
    from graphops_interface.utils.encryption import encrypt_payload

    """Encrypt and upload to backend."""
    if not ExternalAPIClient or not encrypt_payload:
        print("⚠️  graphops_interface API client or encryption not available.")
        return False
    encryption_key = _fetch_encryption_key(api_key)
    if not encryption_key:
        print("⚠️  Could not fetch encryption key from backend.")
        return False
    try:
        payload = encrypt_payload(
            {"nodes": nodes, "graph_hash_id": graph_hash_id, "action": action},
            encryption_key,
        )
        ExternalAPIClient().post(
            f"/agents/{external_uuid}/raw_data/create/",
            data=payload,
            headers={"X-API-Key": api_key},
        )
        label = "updates" if action == "update" else "nodes"
        print(f"✓ Uploaded {len(nodes)} {label} to backend (encrypted)")
        return True
    except Exception as e:
        print(f"⚠️  Upload failed: {e}")
        return False


def _upload_batch_files(
    api_key: str,
    external_uuid: str,
    batches_dir: Path,
    graph_hash_id: str,
    action: str = "create",
) -> bool:
    """Upload all protobuf batches as multipart files."""
    if list_batch_files is None or ExternalAPIClient is None:
        print("⚠️  Protobuf uploader is not available.")
        return False
    namespace_files = list_batch_files(batches_dir, "namespaces")
    node_files = list_batch_files(batches_dir, "nodes")
    all_files = namespace_files + node_files
    if not all_files:
        print("⚠️  No protobuf batches found to upload.")
        return False

    multipart_files = [
        ("batch_files[]", batch_file, "application/gzip")
        for batch_file in all_files
    ]
    client = ExternalAPIClient()
    # Rails may treat `format` specially depending on parser/route resolution.
    # Send it in both query string and multipart fields for compatibility.
    fields = {
        "format": "protobuf-gzip",
        "graph_hash_id": graph_hash_id,
        "action": action,
    }
    try:
        client.post_multipart(
            f"/agents/{external_uuid}/raw_data/create.protobuf-gzip",
            fields=fields,
            files=multipart_files,
            headers={"X-API-Key": api_key},
        )
        print(f"✓ Uploaded {len(all_files)} protobuf batch files")
        return True
    except Exception as e:
        print(f"⚠️  Upload failed: {e}")
        return False


def _upload_updates_as_batches(
    api_key: str,
    external_uuid: str,
    updates: List[Dict[str, Any]],
    graph_hash_id: str,
) -> bool:
    if ProtobufNodeBatchWriter is None:
        print("⚠️  Protobuf writer is not available.")
        return False
    temp_dir = Path(tempfile.mkdtemp(prefix="graphops_updates_batches_"))
    try:
        writer = ProtobufNodeBatchWriter(output_dir=temp_dir)
        writer.reset_output_dir()
        nodes_only = [u for u in updates if u.get("node_type") != "namespace"]
        namespaces_only = [u for u in updates if u.get("node_type") == "namespace"]
        writer.write_kind(
            kind="namespaces",
            root_path=Path.cwd(),
            records=namespaces_only,
            batch_size=1000,
        )
        writer.write_kind(
            kind="nodes",
            root_path=Path.cwd(),
            records=nodes_only,
            batch_size=1000,
        )
        return _upload_batch_files(
            api_key=api_key,
            external_uuid=external_uuid,
            batches_dir=temp_dir,
            graph_hash_id=graph_hash_id,
            action="update",
        )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def apply_updates_to_nodes(
    existing_nodes: List[Dict[str, Any]],
    updates: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Apply updates to existing nodes. Updates have action: create|update|delete.
    - delete by file_path: remove all nodes from that file
    - delete by id: remove that node
    - create/update: add or replace by id
    """
    nodes_by_id: Dict[str, Dict[str, Any]] = {n["id"]: n for n in existing_nodes if n.get("id")}
    delete_file_paths: Set[str] = set()
    delete_ids: Set[str] = set()

    for u in updates:
        action = (u.get("action") or "create").lower()
        if action == "delete":
            if u.get("file_path"):
                delete_file_paths.add(u["file_path"])
            if u.get("id"):
                delete_ids.add(u["id"])
        elif action in ("create", "update"):
            node_copy = {k: v for k, v in u.items() if k != "action"}
            if node_copy.get("id"):
                nodes_by_id[node_copy["id"]] = node_copy

    for nid in list(nodes_by_id.keys()):
        node = nodes_by_id[nid]
        fp = node.get("file_path")
        if fp and fp in delete_file_paths:
            del nodes_by_id[nid]
        elif nid in delete_ids:
            del nodes_by_id[nid]

    return list(nodes_by_id.values())


def run_scan2(
    path: Optional[str | Path] = None,
    rules_dir: Optional[str | Path] = None,
    exclude: Optional[List[str]] = None,
    output: Optional[str | Path] = None,
    backend_url: Optional[str] = None,
    validate_ids: bool = False,
    no_upload: bool = False,
) -> None:
    """
    Incremental scan:
    - If protobuf batch output does not exist or is empty → full scan
    - If exists and has data → git status, scan only changed files, build updates.json,
      upload encrypted updates, apply to local protobuf batches
    """
    from graphops_interface.cli.agent_full_scan import run_full_scan, _run_full_scan

    project_root = Path.cwd().resolve()
    yml_path = project_root / "graphops.yml"
    yml = _load_graphops_yml(yml_path)

    root_path = path or yml.get("root_path") or ""
    if not root_path:
        for candidate in ["backend", "."]:
            candidate_path = (project_root / candidate).expanduser().resolve()
            if candidate_path.exists() and candidate_path.is_dir():
                root_path = candidate
                break
    if not root_path:
        root_path = "."
    scan_path = (project_root / root_path).expanduser().resolve()
    if not scan_path.exists() or not scan_path.is_dir():
        raise SystemExit(f"Root path does not exist or is not a directory: {scan_path}")

    excluded_paths: List[str] = exclude if exclude is not None else list(yml.get("excluded_paths") or [])
    if not excluded_paths:
        excluded_paths = ["tmp", "log", "vendor", "node_modules"]

    rules_path: Optional[Path] = None
    if rules_dir:
        rules_path = Path(rules_dir).resolve()
        if not (rules_path / "ruby").exists() or not (rules_path / "ruby" / "base.json").exists():
            rules_path = None
    if rules_path is None:
        for c in [scan_path / "rules", project_root / "backend" / "rules", project_root / "rules"]:
            if (c / "ruby").exists() and (c / "ruby" / "base.json").exists():
                rules_path = c
                break

    if output:
        out_path = Path(output).resolve()
    else:
        out_dir = project_root / "output"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "nodes.pb"
    updates_path = out_path.parent / "updates.json"

    resolved_backend = _resolve_backend_url(backend_url, yml)
    effective_backend = resolved_backend or backend_url
    if effective_backend:
        os.environ["GRAPHOPS_INTERFACE_BACKEND_URL"] = f"{str(effective_backend).rstrip('/')}/api/v1"
        if not backend_url:
            print(f"   Backend: {effective_backend} (from config/env)")

    existing_nodes = _load_existing_graph_items(out_path)
    can_incremental = (
        existing_nodes is not None
        and is_git_repo is not None
        and is_git_repo(scan_path)
    )

    if not can_incremental:
        print("📦 No existing graph batches or not a git repo → running full scan")
        run_full_scan(
            path=path,
            rules_dir=rules_dir,
            exclude=exclude,
            output=out_path,
            backend_url=resolved_backend or backend_url,
            validate_ids=validate_ids,
            no_upload=no_upload,
        )
        return

    print(f"📦 graphops scan2 (incremental)")
    print(f"   Root:    {scan_path}")
    print(f"   Exclude: {excluded_paths}")
    print(f"   Output:  {out_path}")
    print(f"   Found existing graph data with {len(existing_nodes)} records")
    print(f"   Checking git status...")

    status: GitStatus = git_status(cwd=scan_path)
    modified = _filter_ruby_files(
        status.modified + status.staged_modified,
        excluded_paths,
    )
    created = _filter_ruby_files(
        status.created + status.staged_added,
        excluded_paths,
    )
    deleted = _filter_ruby_files(
        status.deleted + status.staged_deleted,
        excluded_paths,
    )
    for old_p, new_p in status.renamed:
        if old_p.endswith(".rb") and not _is_excluded_path(old_p, excluded_paths):
            deleted.append(old_p)
        if new_p.endswith(".rb") and not _is_excluded_path(new_p, excluded_paths):
            created.append(new_p)

    total = len(modified) + len(created) + len(deleted)
    if total == 0:
        print("✓ No changes detected. Nothing to update.")
        return

    print(f"\n📝 Changes detected: modified {len(modified)}, created {len(created)}, deleted {len(deleted)}")

    updates: List[Dict[str, Any]] = []

    for rel_path in deleted:
        updates.append({"action": "delete", "file_path": rel_path})

    files_to_scan = set(modified + created)
    if files_to_scan:
        from graphops_interface.cli.agent_full_scan import _run_full_scan

        incremental_temp_path = updates_path.parent / ".incremental_scan_temp.pb"
        all_nodes = _run_full_scan(
            scan_path=scan_path,
            project_root=project_root,
            rules_path=rules_path,
            excluded_paths=excluded_paths,
            out_path=incremental_temp_path,
            backend_url=resolved_backend or backend_url,
            validate_ids=validate_ids,
            return_nodes=False,
        )
        if not all_nodes:
            all_nodes = (
                (_load_existing_nodes(incremental_temp_path) or [])
                + (_load_existing_namespaces(incremental_temp_path) or [])
            )
        existing_ids = {n["id"] for n in existing_nodes if n.get("id")}
        for node in all_nodes:
            fp = node.get("file_path")
            if fp not in files_to_scan:
                continue
            node_id = node.get("id")
            if not node_id:
                continue
            action = "update" if node_id in existing_ids else "create"
            node_copy = dict(node)
            node_copy["action"] = action
            updates.append(node_copy)

    updates_path.write_text(json.dumps(updates, indent=2), encoding="utf-8")
    print(f"✓ Wrote {len(updates)} updates to {updates_path}")

    if not no_upload:
        api_key = _load_api_key(project_root)
        uuid_val = (yml.get("uuid") or "").strip()
        if api_key and uuid_val:
            graph_hash_id = hashlib.md5(str(scan_path).encode()).hexdigest()
            if _upload_updates_as_batches(api_key, uuid_val, updates, graph_hash_id):
                merged = apply_updates_to_nodes(existing_nodes, updates)
                _write_split_outputs(merged, out_path)
                print(f"✓ Updated protobuf batches in {_batches_output_dir(out_path)} with {len(merged)} records")
        elif api_key or uuid_val:
            print("⚠️  uuid missing in graphops.yml. Add uuid to upload.")
    else:
        merged = apply_updates_to_nodes(existing_nodes, updates)
        _write_split_outputs(merged, out_path)
        print(f"✓ Updated protobuf batches in {_batches_output_dir(out_path)} with {len(merged)} records (no upload)")
