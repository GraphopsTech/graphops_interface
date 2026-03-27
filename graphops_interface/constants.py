"""Default endpoints for the GraphOps API."""

PRODUCTION_GRAPHOPS_BACKEND_ORIGIN = "https://api.graphops.tech"
DEVELOPMENT_GRAPHOPS_BACKEND_ORIGIN = "http://localhost:3000"

# Default fallback remains production unless explicitly overridden via env or init --dev config.
DEFAULT_GRAPHOPS_BACKEND_ORIGIN = PRODUCTION_GRAPHOPS_BACKEND_ORIGIN
DEFAULT_GRAPHOPS_API_BASE_URL = f"{DEFAULT_GRAPHOPS_BACKEND_ORIGIN}/api/v1"
