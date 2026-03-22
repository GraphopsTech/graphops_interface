"""Full scan: Run ruby_base on entire project. No incremental logic - always scans everything."""

import resource
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from graphops_interface.cli.agent_scan2 import (
    _batches_output_dir,
    _load_api_key,
    _load_existing_graph_items,
    _load_graphops_yml,
    _resolve_backend_url,
    _upload_batch_files,
)

try:
    from ruby_base import MetadataExtractionBuilder, TypeDictionaryBuilder
except ImportError:
    MetadataExtractionBuilder = None  # type: ignore
    TypeDictionaryBuilder = None  # type: ignore


def _format_rss_mb(raw_rss: int) -> float:
    """Convert ru_maxrss to MB on both Linux and macOS."""
    if sys.platform == "darwin":
        return raw_rss / (1024 * 1024)
    return (raw_rss * 1024) / (1024 * 1024)


def _log_phase_stats(phase_name: str, start_time: float, start_usage: resource.struct_rusage) -> None:
    """Print elapsed and resource usage deltas for a phase."""
    end_time = time.perf_counter()
    end_usage = resource.getrusage(resource.RUSAGE_SELF)

    user_cpu = end_usage.ru_utime - start_usage.ru_utime
    sys_cpu = end_usage.ru_stime - start_usage.ru_stime
    total_cpu = user_cpu + sys_cpu
    wall = end_time - start_time
    cpu_util = (total_cpu / wall * 100.0) if wall > 0 else 0.0
    in_blocks = end_usage.ru_inblock - start_usage.ru_inblock
    out_blocks = end_usage.ru_oublock - start_usage.ru_oublock
    max_rss_mb = _format_rss_mb(end_usage.ru_maxrss)

    print(
        f"[{phase_name}] wall={wall:.3f}s user={user_cpu:.3f}s sys={sys_cpu:.3f}s "
        f"cpu_total={total_cpu:.3f}s cpu_util~={cpu_util:.1f}%"
    )
    print(
        f"[{phase_name}] max_rss={max_rss_mb:.2f}MB io_blocks_in={in_blocks} io_blocks_out={out_blocks}"
    )


def _run_full_scan(
    scan_path: Path,
    project_root: Path,
    rules_path: Optional[Path],
    excluded_paths: List[str],
    out_path: Path,
    backend_url: Optional[str],
    validate_ids: bool,
    return_nodes: bool = True,
) -> List[Dict[str, Any]]:
    """Run full scan and optionally load combined records from batch output."""
    import os

    if MetadataExtractionBuilder is None or TypeDictionaryBuilder is None:
        raise SystemExit(
            "ruby_base is required. Install with: pip install -e ./ruby_base"
        )

    if validate_ids:
        os.environ["RUBY_BASE_VALIDATE_IDS"] = "1"
    if backend_url:
        url = str(backend_url).rstrip("/")
        if not url.endswith("/api/v1"):
            url = f"{url}/api/v1"
        os.environ["GRAPHOPS_INTERFACE_BACKEND_URL"] = url

    dictionary_path = project_root / "output" / "dictionary.json"
    dictionary_path.parent.mkdir(parents=True, exist_ok=True)

    phase1_start_time = time.perf_counter()
    phase1_start_usage = resource.getrusage(resource.RUSAGE_SELF)
    TypeDictionaryBuilder().build(
        root_path=scan_path,
        excluded_paths=excluded_paths or None,
        output_path=dictionary_path,
        return_result=False,
    )
    _log_phase_stats("phase1", phase1_start_time, phase1_start_usage)

    builder = MetadataExtractionBuilder(
        dictionary_path=dictionary_path,
        rules_dir=rules_path,
        backend_url=backend_url,
    )
    phase2_start_time = time.perf_counter()
    phase2_start_usage = resource.getrusage(resource.RUSAGE_SELF)
    builder.build(
        root_path=scan_path,
        excluded_paths=excluded_paths or None,
        output_path=out_path,
        # Always stream-write protobuf batches for lower memory usage.
        return_nodes=False,
    )
    _log_phase_stats("phase2", phase2_start_time, phase2_start_usage)
    if not return_nodes:
        return []
    nodes = _load_existing_graph_items(out_path)
    return nodes or []


def run_full_scan(
    path: Optional[str | Path] = None,
    rules_dir: Optional[str | Path] = None,
    exclude: Optional[List[str]] = None,
    output: Optional[str | Path] = None,
    backend_url: Optional[str] = None,
    validate_ids: bool = False,
    no_upload: bool = False,
) -> None:
    """
    Full scan of Ruby project via ruby_base.
    Always scans the entire project. No incremental/git logic.
    """
    import hashlib
    import os

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
        candidates = [
            scan_path / "rules",
            project_root / "backend" / "rules",
            project_root / "rules",
        ]
        for c in candidates:
            if (c / "ruby").exists() and (c / "ruby" / "base.json").exists():
                rules_path = c
                break

    if output:
        out_path = Path(output).resolve()
    else:
        out_dir = project_root / "output"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "nodes.pb"

    resolved_backend = _resolve_backend_url(backend_url, yml)
    effective_backend = resolved_backend or backend_url
    if effective_backend:
        os.environ["GRAPHOPS_INTERFACE_BACKEND_URL"] = f"{str(effective_backend).rstrip('/')}/api/v1"
        if not backend_url:
            print(f"   Backend: {effective_backend} (from config/env)")

    print(f"📦 graphops full_scan (ruby_base)")
    print(f"   Root:    {scan_path}")
    print(f"   Rules:  {rules_path or '(bundled)'}")
    print(f"   Exclude: {excluded_paths}")
    print(f"   Output: {out_path}")

    _run_full_scan(
        scan_path=scan_path,
        project_root=project_root,
        rules_path=rules_path,
        excluded_paths=excluded_paths,
        out_path=out_path,
        backend_url=effective_backend or backend_url,
        validate_ids=validate_ids,
        return_nodes=False,
    )
    batches_dir = _batches_output_dir(out_path)
    print(f"\n✓ Wrote protobuf batches to {batches_dir}")

    if not no_upload:
        api_key = _load_api_key(project_root)
        uuid_val = (yml.get("uuid") or "").strip()
        if api_key and uuid_val:
            graph_hash_id = hashlib.md5(str(scan_path).encode()).hexdigest()
            _upload_batch_files(
                api_key=api_key,
                external_uuid=uuid_val,
                batches_dir=batches_dir,
                graph_hash_id=graph_hash_id,
                action="create",
            )
        elif api_key or uuid_val:
            print("⚠️  GRAPHOPS_API_KEY or uuid missing. Add uuid to graphops.yml and run graphops init.")
