# graphops_interface

`graphops_interface` is the open-source command-line package that connects a local
scan to the Graphops backend. It handles project initialization, backend
configuration, encryption-key retrieval, scan orchestration, and upload of the
generated metadata batches.

This package is open source and released under the MIT License.

## What This Package Does

`graphops_interface` is responsible for:

- creating local project configuration with `graphops init`
- reading `graphops.yml` and `.env.graphops`
- resolving the backend origin used for rule downloads and uploads
- invoking `ruby_base` for Ruby Phase 1 and Phase 2 scanning
- uploading protobuf batch files to the Graphops backend

It does **not** parse Ruby itself. Ruby parsing and rule-driven extraction live in
the companion package `ruby_base`.

## Open Source Packages

Graphops currently publishes two open-source packages:

- [`graphops_interface`](https://github.com/GraphopsTech/graphops_interface)
- [`ruby_base`](https://github.com/GraphopsTech/ruby_base)

## Installation

### Editable install for local development

From the monorepo root:

```bash
pip install -e ./ruby_base
pip install -e ./graphops_interface
```

Or install `graphops_interface` with the Ruby extra when `ruby_base` is available
from your package index:

```bash
pip install "graphops_interface[ruby]"
```

### Install from your private Graphops package index

`graphops_interface` is not published on the public PyPI index. It is served from
the same Graphops host that serves the Rails API.

```bash
pip install graphops_interface \
  --extra-index-url "https://YOUR_TOKEN:@api.graphops.tech/pypi/simple/" \
  --trusted-host api.graphops.tech
```

You can also set these once per environment:

```bash
export PIP_EXTRA_INDEX_URL="https://YOUR_TOKEN:@api.graphops.tech/pypi/simple/"
export PIP_TRUSTED_HOST="api.graphops.tech"
```

### Requirements

- Python 3.10+
- access to your Graphops backend
- `ruby_base` for Ruby scanning

## CLI Overview

Install exposes the `graphops` command:

```bash
graphops --help
```

Public commands:

- `graphops init`
- `graphops scan`

## Quick Start

### 1. Initialize a project

```bash
graphops init --api-key YOUR_API_KEY --root-path backend
```

For local development against a local backend:

```bash
graphops init --api-key YOUR_API_KEY --root-path backend --dev
```

This writes:

- `graphops.yml`
- `.env.graphops`

### 2. Run a scan

```bash
graphops scan
```

Or with explicit options:

```bash
graphops scan --path backend --rules-dir backend/rules
graphops scan --path backend -r backend/rules --exclude tmp --exclude vendor -o output/nodes.pb
```

## Command Reference

### `graphops init`

Initializes a project for scanning.

What it does:

- validates the provided API key with the backend
- receives a project UUID
- writes `graphops.yml`
- writes `.env.graphops`

Important flags:

- `--api-key`, `-k`
- `--root-path`, `-r`
- `--dev`

Generated `graphops.yml` contains:

- `uuid`
- `root_path`
- `language`
- `excluded_paths`
- `backend_url`

### `graphops scan`

Runs the Ruby scan flow using `ruby_base`.

What it does:

1. reads `graphops.yml`
2. resolves the scan root and backend origin
3. runs Phase 1 dictionary generation
4. runs Phase 2 metadata extraction
5. writes protobuf batches locally
6. uploads the batches unless `--no-upload` is set

Supported flags:

- `--path`, `-p`
- `--rules-dir`, `-r`
- `--exclude`
- `--output`, `-o`
- `--backend-url`, `-b`
- `--validate-ids`
- `--no-upload`

## Output

By default, `graphops scan` writes protobuf+gzip batches under an output directory
derived from the provided output path.

Typical output files:

- `output/dictionary.json` from Phase 1
- `output/nodes_batches/*.pb.gz`
- `output/namespaces_batches/*.pb.gz`
- a manifest describing the generated batches

## Package Structure

Main modules in `graphops_interface`:

- `graphops_interface.cli` - CLI entrypoints and command routing
- `graphops_interface.api` - backend HTTP client
- `graphops_interface.core` - config helpers
- `graphops_interface.utils.encryption` - payload encryption helpers
- `graphops_interface.utils.git` - git helpers used by internal tooling
- `graphops_interface.grammar_registry` - grammar/analyzer registration

## Configuration

### Project files

- `graphops.yml` - project-level scan configuration
- `.env.graphops` - stores `GRAPHOPS_API_KEY`

### Environment variables

- `GRAPHOPS_INTERFACE_BACKEND_URL`
- `AGENT_INTERFACE_BACKEND_URL`
- `GRAPH_OPS_AGENT_BACKEND_URL`
- `RUBY_AGENT_BACKEND_URL`

Fallback default:

- `https://api.graphops.tech/api/v1`

### Upload tuning

- `GRAPHOPS_UPLOAD_TIMEOUT_SECONDS` default: `300`
- `GRAPHOPS_UPLOAD_BATCH_FILES_PER_REQUEST` default: `10`

## Relationship to `ruby_base`

`graphops_interface` orchestrates the scan.
`ruby_base` performs the Ruby analysis.

In practice:

- `graphops_interface` handles init, config, backend URL resolution, and upload
- `ruby_base` handles dictionary building, rule loading, AST extraction, and
  protobuf batch generation

See the companion package:

- [`ruby_base`](https://github.com/GraphopsTech/ruby_base)

## Building and Publishing

Build a wheel locally:

```bash
pip install build
python -m build
ls -la dist/
```

Then upload the generated distribution to your private Graphops package index.

## License

This package is licensed under the MIT License.

See [`LICENSE`](./LICENSE) for the full license text.
