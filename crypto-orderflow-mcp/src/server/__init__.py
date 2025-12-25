"""MCP Server module."""

import sys
from pathlib import Path

# Add project root to path
_project_root = str(Path(__file__).parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from src.server.mcp_server import CryptoMCPServer

__all__ = ["CryptoMCPServer"]
