# graphops_interface

Backend communication for Graph Ops: init, encryption, API client, and output to `nodes.json`. Grammar packages (e.g. `ruby_grammars`, `python_grammars`) plug in for language-specific scanning.

## Install

**`graphops_interface` is not on the public PyPI index** — it is served from your **Graph Ops** app’s private PEP 503 API (same host as your Rails API, e.g. `https://api.graphops.tech/pypi/simple/`). You must tell pip about that index:

```bash
pip install graphops_interface \
  --extra-index-url "https://YOUR_TOKEN:@api.graphops.tech/pypi/simple/" \
  --trusted-host api.graphops.tech
```

Or set `PIP_EXTRA_INDEX_URL` / `PIP_TRUSTED_HOST`, or configure `[global] extra-index-url` in `pip.conf` (see `ruby_base` README for examples).

Optional grammar packages (if published separately):

```bash
pip install ruby_grammars
```

CLI:

```bash
graphops --help
```

## Multi-project config

Config supports **multiple projects**. Each project has: `root_path`, `external_uuid`, `api_key`, `encryption_key`, and `language`. Init stores `api_token` and a global `encryption_key`.

- Config file: `~/.graphops_interface/config.json`
- One project can be set as **default** for `scan` when `--project` is omitted.

## Commands

| Command | Description |
|---------|-------------|
| `graphops init` | Store API token + encryption key (no activation/root path). |
| `graphops scan [--project P] [--language L] [--path PATH]` | Scan and write `nodes.json` (+ upload). |
| `graphops scan2 [--path P] [--rules-dir R] [--exclude D...] [--output O]` | Ruby scan via ruby_base (Phase 1 + Phase 2). Writes `output/nodes.json`. |
| `graphops projects` | List projects and show which is default. |
| `graphops use PROJECT` | Set the default project. |

### graphops scan2

Uses `ruby_base` to run Phase 1 (type dictionary) and Phase 2 (metadata extraction) in one command.

```bash
# From project root (requires graphops.yml with root_path)
graphops scan2

# Or with explicit path and rules
graphops scan2 --path backend --rules-dir backend/rules

# Exclude dirs, custom output
graphops scan2 --path backend -r backend/rules --exclude tmp --exclude vendor -o output/nodes.json
```

Requires `ruby_base`. For local development:
```bash
pip install -e ./ruby_base
pip install -e ./graphops_interface
# or: pip install -e '.[ruby]'  (if ruby_base is published)
```

## Grammar plugins (entry points)

Register under the `graphops_interface.grammars` entry point:

```ini
[project.entry-points."graphops_interface.grammars"]
ruby = "ruby_grammars:get_analyzer"
```

## Config and env

- Config: `~/.graphops_interface/config.json`
- Backend URL: `GRAPHOPS_INTERFACE_BACKEND_URL`, or `AGENT_INTERFACE_BACKEND_URL` / `GRAPH_OPS_AGENT_BACKEND_URL` / `RUBY_AGENT_BACKEND_URL` (fallback), default `https://api.graphops.tech/api/v1`.
- `graphops init --dev` writes `backend_url: "http://localhost:3000"` to `graphops.yml` (local mode).
- `graphops init` (without `--dev`) writes `backend_url: "https://api.graphops.tech"` (production mode).
- `scan`, `scan2`, and `full_scan` read `backend_url` from `graphops.yml` and route requests there unless explicitly overridden by env/flags.
- Large upload tuning:
  - `GRAPHOPS_UPLOAD_TIMEOUT_SECONDS` (default: `300`)
  - `GRAPHOPS_UPLOAD_BATCH_FILES_PER_REQUEST` (default: `10`)
  These apply to protobuf batch uploads in `scan2` / `full_scan`.
