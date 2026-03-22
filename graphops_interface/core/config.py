"""Configuration management for Graph Ops agents. Supports multiple projects."""

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class AgentConfig:
    """Configuration for one project."""

    root_path: str
    external_uuid: str
    api_key: Optional[str] = None
    encryption_key: Optional[str] = None
    language: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AgentConfig":
        encryption_key = data.get("encryption_key") or data.get("public_key")
        return cls(
            root_path=data.get("root_path", ""),
            external_uuid=data.get("external_uuid", ""),
            api_key=data.get("api_key"),
            encryption_key=encryption_key,
            language=data.get("language"),
        )



class ConfigManager:
    """Manages multi-project configuration in ~/.graphops_interface/config.json."""

    def __init__(self, config_file: Optional[Path] = None):
        if config_file is None:
            config_dir = Path.home() / ".graphops_interface"
            config_dir.mkdir(exist_ok=True)
            config_file = config_dir / "config.json"
        self.config_file = Path(config_file)
        self._data: Optional[Dict[str, Any]] = None

    def _ensure_loaded(self) -> None:
        if self._data is not None:
            return
        # 1) Prefer .env.graphops in current working directory
        env_path = Path.cwd() / ".env.graphops"
        if env_path.exists():
            env_data = self._load_env_file(env_path)
            if env_data:
                self._data = env_data
                return

        # 2) Fallback to legacy config file
        default_payload = {"projects": {}}
        if not self.config_file.exists():
            self._data = default_payload
            return
        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                self._data = json.load(f)
        except (json.JSONDecodeError, TypeError):
            self._data = default_payload
            return
        if not isinstance(self._data.get("projects"), dict):
            self._data["projects"] = {}

    def _save(self) -> None:
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        payload = self._data or {"projects": {}}
        # prune legacy top-level keys if present
        for k in ("api_token", "encryption_key", "external_uuid", "default_project"):
            payload.pop(k, None)
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    def list_projects(self) -> List[Tuple[str, AgentConfig]]:
        self._ensure_loaded()
        projs = (self._data or {}).get("projects") or {}
        return [(n, AgentConfig.from_dict(p)) for n, p in sorted(projs.items()) if isinstance(p, dict)]

    def get_project(self, name: str) -> Optional[AgentConfig]:
        self._ensure_loaded()
        p = (self._data or {}).get("projects") or {}
        raw = p.get(name) if isinstance(p, dict) else None
        return AgentConfig.from_dict(raw) if isinstance(raw, dict) else None

    def add_project(
        self,
        name: str,
        root_path: str,
        external_uuid: str,
        api_key: Optional[str] = None,
        encryption_key: Optional[str] = None,
        language: Optional[str] = None,
    ) -> AgentConfig:
        self._ensure_loaded()
        projs = self._data.setdefault("projects", {})
        projs[name] = {
            "root_path": root_path,
            "external_uuid": external_uuid,
            "api_key": api_key,
            "encryption_key": encryption_key,
            "language": language,
        }
        self._save()
        return AgentConfig.from_dict(projs[name])

    def find_project_by_cwd(self) -> Optional[str]:
        cwd = Path.cwd().resolve()
        candidates = []
        for name, cfg in self.list_projects():
            try:
                root = Path(cfg.root_path).resolve()
            except Exception:
                continue
            if cwd == root or str(cwd).startswith(str(root) + "/"):
                candidates.append((name, root))
        if not candidates:
            return None
        candidates.sort(key=lambda x: -len(str(x[1])))
        return candidates[0][0]

    def exists(self) -> bool:
        return self.config_file.exists()

    def get_config(self) -> Optional[AgentConfig]:
        self._ensure_loaded()
        for _, c in self.list_projects():
            return c
        return None

    # Default project helper retained for callers (returns first project if any)
    def get_default_project_name(self) -> Optional[str]:
        self._ensure_loaded()
        names = [name for name, _ in self.list_projects()]
        return names[0] if names else None

    # ----- Init-level helpers (api token + encryption key) -----
    def set_init(self, api_token: str, encryption_key: str, external_uuid: str, language: Optional[str] = None) -> None:
        self._ensure_loaded()
        projs = self._data.setdefault("projects", {})
        # update or create default project entry
        proj = projs.get("default", {}) if isinstance(projs.get("default"), dict) else {}
        proj.setdefault("root_path", "")
        proj["external_uuid"] = external_uuid
        proj["api_key"] = api_token
        proj["encryption_key"] = encryption_key
        proj["language"] = language
        projs["default"] = proj
        # remove legacy top-level keys if present
        for k in ("api_token", "encryption_key", "external_uuid", "default_project"):
            self._data.pop(k, None)
        self._save()

    def get_api_token(self) -> Optional[str]:
        self._ensure_loaded()
        # prefer project-stored api_key
        cfg = self.get_config()
        if cfg and cfg.api_key:
            return cfg.api_key
        return None

    def get_encryption_key(self) -> Optional[str]:
        self._ensure_loaded()
        cfg = self.get_config()
        if cfg and cfg.encryption_key:
            return cfg.encryption_key
        return None

    def get_external_uuid(self) -> Optional[str]:
        self._ensure_loaded()
        cfg = self.get_config()
        if cfg and cfg.external_uuid:
            return cfg.external_uuid
        return None

    # ----- Env loader -----
    def _load_env_file(self, path: Path) -> Optional[Dict[str, Any]]:
        """
        Load .env.graphops with keys:
        GRAPHOPS_<PREFIX>_API_KEY, UUID, ENCRYPTION_KEY, ROOT_PATH, LANGUAGE
        """
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception:
            return None
        kv: Dict[str, str] = {}
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            kv[k.strip()] = v.strip()
        # find prefixes
        prefixes = []
        for k in kv.keys():
            m = re.match(r"GRAPHOPS_([A-Z0-9_]+)_API_KEY", k)
            if m:
                prefixes.append(m.group(1))
        if not prefixes:
            return None
        projects = {}
        for prefix in prefixes:
            api_key = kv.get(f"GRAPHOPS_{prefix}_API_KEY")
            uuid = kv.get(f"GRAPHOPS_{prefix}_UUID")
            enc = kv.get(f"GRAPHOPS_{prefix}_ENCRYPTION_KEY")
            root = kv.get(f"GRAPHOPS_{prefix}_ROOT_PATH")
            lang = kv.get(f"GRAPHOPS_{prefix}_LANGUAGE")
            if not (api_key and uuid and enc and root):
                continue
            projects[prefix.lower()] = {
                "root_path": root,
                "external_uuid": uuid,
                "api_key": api_key,
                "encryption_key": enc,
                "language": lang,
            }
        if not projects:
            return None
        return {"projects": projects}
