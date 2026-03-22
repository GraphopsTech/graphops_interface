# graphops_interface

Backend communication for Graph Ops: init, encryption, API client, and output to `nodes.json`. Grammar packages (e.g. `ruby_grammars`, `python_grammars`) plug in for language-specific scanning.

## Install

```bash
pip install graphops_interface
# and a grammar, e.g.:
pip install ruby_grammars

# CLI entrypoint
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
- Backend URL: `GRAPHOPS_INTERFACE_BACKEND_URL`, or `AGENT_INTERFACE_BACKEND_URL` / `GRAPH_OPS_AGENT_BACKEND_URL` / `RUBY_AGENT_BACKEND_URL` (fallback), default `http://localhost:3000/api/v1`
