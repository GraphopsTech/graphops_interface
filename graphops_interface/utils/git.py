"""Git utilities for running git status on the project root path."""

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple


@dataclass
class GitStatus:
    """Parsed git status result with categorized file paths."""
    
    modified: List[str] = field(default_factory=list)
    """Files that have been modified."""
    
    deleted: List[str] = field(default_factory=list)
    """Files that have been deleted."""
    
    created: List[str] = field(default_factory=list)
    """Files that are new/untracked."""
    
    staged_modified: List[str] = field(default_factory=list)
    """Files modified and staged for commit."""
    
    staged_deleted: List[str] = field(default_factory=list)
    """Files deleted and staged for commit."""
    
    staged_added: List[str] = field(default_factory=list)
    """Files added (new) and staged for commit."""
    
    renamed: List[Tuple[str, str]] = field(default_factory=list)
    """Files renamed: list of (old_path, new_path) tuples."""
    
    branch: Optional[str] = None
    """Current branch name."""
    
    raw_output: str = ""
    """Raw git status output."""
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "modified": self.modified,
            "deleted": self.deleted,
            "created": self.created,
            "staged_modified": self.staged_modified,
            "staged_deleted": self.staged_deleted,
            "staged_added": self.staged_added,
            "renamed": [{"from": old, "to": new} for old, new in self.renamed],
            "branch": self.branch,
        }


def _run_git_command(args: list, cwd: Optional[Path] = None) -> Tuple[int, str, str]:
    """
    Internal: Run a git command in the specified directory.
    Only used by allowed functions (git_status, is_git_repo, get_current_branch).
    """
    cmd = ["git"] + args
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        return result.returncode, result.stdout, result.stderr
    except FileNotFoundError:
        return 1, "", "git is not installed or not in PATH"
    except Exception as e:
        return 1, "", str(e)


def git_status_raw(cwd: Optional[Path] = None) -> Tuple[int, str, str]:
    """Run git status and return raw output."""
    return _run_git_command(["status"], cwd=cwd)


def git_status(cwd: Optional[Path] = None) -> GitStatus:
    """
    Run git status and return parsed result with categorized file paths.
    
    Returns:
        GitStatus with lists of modified, deleted, and created file paths.
    """
    result = GitStatus()
    result.branch = get_current_branch(cwd)
    
    # Use porcelain format for reliable parsing
    code, stdout, _ = _run_git_command(["status", "--porcelain=v1"], cwd=cwd)
    if code != 0:
        return result
    
    result.raw_output = stdout
    
    for line in stdout.splitlines():
        if len(line) < 3:
            continue
        
        # Porcelain format: XY filename
        # X = staged status, Y = unstaged status
        # ' ' = unmodified, M = modified, A = added, D = deleted, R = renamed
        # ? = untracked, ! = ignored
        index_status = line[0]  # Staged status
        worktree_status = line[1]  # Unstaged status
        filepath = line[3:]  # File path (after "XY ")
        
        # Handle renamed files (format: "R  old -> new" or "R  old\tnew")
        if index_status == "R" or worktree_status == "R":
            if " -> " in filepath:
                old_path, new_path = filepath.split(" -> ", 1)
                result.renamed.append((old_path.strip(), new_path.strip()))
            elif "\t" in filepath:
                # Alternative format with tab separator
                parts = filepath.split("\t")
                if len(parts) == 2:
                    result.renamed.append((parts[0].strip(), parts[1].strip()))
            continue
        
        # Untracked files (created/new)
        if index_status == "?" and worktree_status == "?":
            result.created.append(filepath)
            continue
        
        # Staged changes
        if index_status == "M":
            result.staged_modified.append(filepath)
        elif index_status == "A":
            result.staged_added.append(filepath)
        elif index_status == "D":
            result.staged_deleted.append(filepath)
        
        # Unstaged changes (working tree)
        if worktree_status == "M":
            result.modified.append(filepath)
        elif worktree_status == "D":
            result.deleted.append(filepath)
    
    return result


def is_git_repo(cwd: Optional[Path] = None) -> bool:
    """Check if the directory is a git repository."""
    code, _, _ = _run_git_command(["rev-parse", "--git-dir"], cwd=cwd)
    return code == 0


def get_current_branch(cwd: Optional[Path] = None) -> Optional[str]:
    """Get the current branch name."""
    code, stdout, _ = _run_git_command(["rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd)
    if code == 0:
        return stdout.strip()
    return None
