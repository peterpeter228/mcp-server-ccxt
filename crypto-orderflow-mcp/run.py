#!/usr/bin/env python3
"""
Launcher script for Crypto Orderflow MCP Server.
Run from the project root directory.
"""

import os
import sys

# Ensure we're running from the project root
project_root = os.path.dirname(os.path.abspath(__file__))
os.chdir(project_root)
sys.path.insert(0, project_root)

from src.main import main

if __name__ == "__main__":
    main()
