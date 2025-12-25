#!/usr/bin/env python3
"""
Launcher script for Crypto Orderflow MCP Server.
Run from the project root directory.
"""

import os
import sys

# Ensure we're running from the project root and add it to path
project_root = os.path.dirname(os.path.abspath(__file__))
os.chdir(project_root)

# Add project root to Python path BEFORE any imports
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Now import and run
if __name__ == "__main__":
    from src.main import main
    main()
