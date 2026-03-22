"""Git status handler: run git status on the project root_path from graphops.yml."""

import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

from graphops_interface.utils.git import git_status, is_git_repo, GitStatus


# Language to file extensions mapping
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


def _load_graphops_yml() -> Dict[str, Any]:
    """Load configuration from graphops.yml in current directory."""
    yml_path = Path.cwd() / "graphops.yml"
    config: Dict[str, Any] = {
        "root_path": None,
        "language": None,
        "excluded_paths": [],
    }
    
    if not yml_path.exists():
        return config
    
    try:
        text = yml_path.read_text(encoding="utf-8")
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                continue
            
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            
            if key == "root_path":
                config["root_path"] = value.strip('"').strip("'")
            elif key == "language":
                config["language"] = value.strip('"').strip("'").lower()
            elif key == "excluded_paths":
                # Strip inline comment if present
                if "#" in value:
                    value = value.split("#", 1)[0].strip()
                if value == "[]" or not value:
                    config["excluded_paths"] = []
                else:
                    try:
                        config["excluded_paths"] = json.loads(value)
                    except json.JSONDecodeError:
                        config["excluded_paths"] = []
    except Exception:
        pass
    
    return config


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
    
    # Normalize the filepath
    parts = filepath.replace("\\", "/").split("/")
    
    for excluded in excluded_paths:
        excluded = excluded.strip().strip("/")
        if not excluded:
            continue
        
        # Check if any part of the path matches the excluded directory
        # or if the path starts with the excluded directory
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
        return True  # No filter if no extensions specified
    
    filepath_lower = filepath.lower()
    return any(filepath_lower.endswith(ext) for ext in extensions)


def _filter_files(
    files: List[str],
    extensions: List[str],
    excluded_paths: List[str],
) -> List[str]:
    """Filter files by extension and excluded paths."""
    result = []
    for f in files:
        if _is_excluded_path(f, excluded_paths):
            continue
        if not _has_valid_extension(f, extensions):
            continue
        result.append(f)
    return result


def _filter_renamed(
    renamed: List[Tuple[str, str]],
    extensions: List[str],
    excluded_paths: List[str],
) -> List[Tuple[str, str]]:
    """Filter renamed files by extension and excluded paths."""
    result = []
    for old, new in renamed:
        # Include if the new file passes filters (the file that exists now)
        if _is_excluded_path(new, excluded_paths):
            continue
        if not _has_valid_extension(new, extensions):
            continue
        result.append((old, new))
    return result


def run_git(path: Optional[str] = None, output_json: bool = False) -> Optional[GitStatus]:
    """
    Run git status on the project root_path. Only git status is allowed.
    
    Files are filtered based on graphops.yml:
    - Only files matching the language extension are included
    - Files in excluded_paths directories are ignored
    
    Args:
        path: Override path (defaults to root_path from graphops.yml)
        output_json: If True, output JSON format instead of human-readable
        
    Returns:
        GitStatus object with parsed and filtered results
    """
    # Load config from graphops.yml
    config = _load_graphops_yml()
    language = config.get("language")
    excluded_paths = config.get("excluded_paths", [])
    extensions = _get_extensions_for_language(language)
    
    # Determine working directory
    if path:
        cwd = Path(path).expanduser().resolve()
    else:
        root_path = config.get("root_path")
        if root_path:
            cwd = Path(root_path).expanduser().resolve()
        else:
            cwd = Path.cwd()
            if not output_json:
                print(f"Note: No graphops.yml found. Using current directory: {cwd}")
    
    if not cwd.exists():
        if output_json:
            print(json.dumps({"error": f"Path does not exist: {cwd}"}))
        else:
            print(f"Error: Path does not exist: {cwd}")
        sys.exit(1)
    
    if not cwd.is_dir():
        if output_json:
            print(json.dumps({"error": f"Path is not a directory: {cwd}"}))
        else:
            print(f"Error: Path is not a directory: {cwd}")
        sys.exit(1)
    
    # Check if it's a git repo
    if not is_git_repo(cwd):
        if output_json:
            print(json.dumps({"error": f"Not a git repository: {cwd}"}))
        else:
            print(f"Error: Not a git repository: {cwd}")
        sys.exit(1)
    
    # Run git status and parse results
    status = git_status(cwd=cwd)
    
    # Apply filters based on language and excluded paths
    filtered_modified = _filter_files(status.modified, extensions, excluded_paths)
    filtered_deleted = _filter_files(status.deleted, extensions, excluded_paths)
    filtered_created = _filter_files(status.created, extensions, excluded_paths)
    filtered_staged_modified = _filter_files(status.staged_modified, extensions, excluded_paths)
    filtered_staged_deleted = _filter_files(status.staged_deleted, extensions, excluded_paths)
    filtered_staged_added = _filter_files(status.staged_added, extensions, excluded_paths)
    filtered_renamed = _filter_renamed(status.renamed, extensions, excluded_paths)
    
    if output_json:
        # JSON output for programmatic use
        output = {
            "repository": str(cwd),
            "branch": status.branch,
            "language": language,
            "extensions": extensions,
            "excluded_paths": excluded_paths,
            "modified": filtered_modified,
            "deleted": filtered_deleted,
            "created": filtered_created,
            "staged": {
                "modified": filtered_staged_modified,
                "deleted": filtered_staged_deleted,
                "added": filtered_staged_added,
            },
            "renamed": [{"from": old, "to": new} for old, new in filtered_renamed],
        }
        print(json.dumps(output, indent=2))
    else:
        # Human-readable output
        print(f"Repository: {cwd}")
        if status.branch:
            print(f"Branch: {status.branch}")
        if language:
            print(f"Language: {language} ({', '.join(extensions) if extensions else 'all files'})")
        if excluded_paths:
            print(f"Excluded: {', '.join(excluded_paths)}")
        print("=" * 60)
        
        # Modified files (unstaged)
        if filtered_modified:
            print(f"\n📝 Modified files ({len(filtered_modified)}):")
            for f in filtered_modified:
                print(f"   {f}")
        
        # Deleted files (unstaged)
        if filtered_deleted:
            print(f"\n🗑️  Deleted files ({len(filtered_deleted)}):")
            for f in filtered_deleted:
                print(f"   {f}")
        
        # Created/untracked files
        if filtered_created:
            print(f"\n✨ Created/untracked files ({len(filtered_created)}):")
            for f in filtered_created:
                print(f"   {f}")
        
        # Renamed files
        if filtered_renamed:
            print(f"\n🔄 Renamed files ({len(filtered_renamed)}):")
            for old, new in filtered_renamed:
                print(f"   {old} → {new}")
        
        # Staged changes
        has_staged = filtered_staged_modified or filtered_staged_deleted or filtered_staged_added
        if has_staged:
            print(f"\n📦 Staged for commit:")
            if filtered_staged_added:
                print(f"   Added ({len(filtered_staged_added)}):")
                for f in filtered_staged_added:
                    print(f"      {f}")
            if filtered_staged_modified:
                print(f"   Modified ({len(filtered_staged_modified)}):")
                for f in filtered_staged_modified:
                    print(f"      {f}")
            if filtered_staged_deleted:
                print(f"   Deleted ({len(filtered_staged_deleted)}):")
                for f in filtered_staged_deleted:
                    print(f"      {f}")
        
        # Summary
        total_changes = (
            len(filtered_modified) + len(filtered_deleted) + len(filtered_created) +
            len(filtered_staged_modified) + len(filtered_staged_deleted) + 
            len(filtered_staged_added) + len(filtered_renamed)
        )
        if total_changes == 0:
            print("\n✓ No relevant changes (after filtering)")
        else:
            print(f"\n─────────────────────────────────────────────────────────────")
            print(f"Total: {total_changes} file(s) with changes")
    
    # Return a filtered GitStatus for programmatic use
    filtered_status = GitStatus(
        modified=filtered_modified,
        deleted=filtered_deleted,
        created=filtered_created,
        staged_modified=filtered_staged_modified,
        staged_deleted=filtered_staged_deleted,
        staged_added=filtered_staged_added,
        renamed=filtered_renamed,
        branch=status.branch,
        raw_output=status.raw_output,
    )
    return filtered_status
