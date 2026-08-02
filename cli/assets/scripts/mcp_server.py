#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UI/UX Pro Max - MCP Server

Exposes the UI/UX Pro Max search engine as a Model Context Protocol (MCP)
server over stdio. Zero external dependencies (stdlib only), matching the
rest of this skill.

Tools:
  - search_design           Search a single domain (style, color, chart, ...)
  - search_stack            Search stack-specific guidelines (react, vue, ...)
  - generate_design_system  Aggregate a full design-system recommendation

Run directly:
    python3 mcp_server.py

Register in Claude Code (project-level .mcp.json):
    {
      "mcpServers": {
        "ui-ux-pro-max": {
          "command": "python3",
          "args": ["src/ui-ux-pro-max/scripts/mcp_server.py"]
        }
      }
    }
"""

import json
import sys
import os

# Ensure sibling modules (core, design_system) are importable regardless of cwd.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import CSV_CONFIG, AVAILABLE_STACKS, MAX_RESULTS, search, search_stack
from design_system import generate_design_system
from search import format_output

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "ui-ux-pro-max", "version": "2.5.0"}

DOMAINS = list(CSV_CONFIG.keys())


# ============ TOOL DEFINITIONS ============
TOOLS = [
    {
        "name": "search_design",
        "description": (
            "Search UI/UX design intelligence in a single domain: UI styles, "
            "color palettes, font pairings, chart types, landing patterns, "
            "product recommendations, UX guidelines, icons, and more. "
            "Omit 'domain' to auto-detect it from the query."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural-language search query."},
                "domain": {
                    "type": "string",
                    "enum": DOMAINS,
                    "description": "Domain to search. Omit to auto-detect.",
                },
                "max_results": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "description": f"Max results (default {MAX_RESULTS}).",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_stack",
        "description": (
            "Search stack-specific UI/UX implementation guidelines for a given "
            "tech stack (React, Next.js, Vue, Svelte, SwiftUI, Flutter, "
            "Tailwind, shadcn/ui, Jetpack Compose, and more)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural-language search query."},
                "stack": {
                    "type": "string",
                    "enum": AVAILABLE_STACKS,
                    "description": "Tech stack to search.",
                },
                "max_results": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "description": f"Max results (default {MAX_RESULTS}).",
                },
            },
            "required": ["query", "stack"],
        },
    },
    {
        "name": "generate_design_system",
        "description": (
            "Generate a complete design-system recommendation for a project by "
            "aggregating product, style, color, landing, and typography searches "
            "with priority-based reasoning. Returns a formatted report (does not "
            "write any files)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Project description, e.g. 'fintech banking dashboard'.",
                },
                "project_name": {
                    "type": "string",
                    "description": "Optional project name for the report header.",
                },
                "format": {
                    "type": "string",
                    "enum": ["ascii", "markdown"],
                    "description": "Output format (default 'markdown').",
                },
            },
            "required": ["query"],
        },
    },
]

TOOLS_BY_NAME = {t["name"]: t for t in TOOLS}


# ============ TOOL DISPATCH ============
def _clamp_results(value):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return MAX_RESULTS
    return max(1, min(20, n))


def call_tool(name, arguments):
    """Execute a tool and return a text string. Raises ValueError on bad input."""
    arguments = arguments or {}

    if name == "search_design":
        query = arguments.get("query")
        if not query:
            raise ValueError("'query' is required")
        domain = arguments.get("domain")  # None -> auto-detect
        max_results = _clamp_results(arguments.get("max_results", MAX_RESULTS))
        return format_output(search(query, domain, max_results))

    if name == "search_stack":
        query = arguments.get("query")
        stack = arguments.get("stack")
        if not query:
            raise ValueError("'query' is required")
        if not stack:
            raise ValueError("'stack' is required")
        max_results = _clamp_results(arguments.get("max_results", MAX_RESULTS))
        return format_output(search_stack(query, stack, max_results))

    if name == "generate_design_system":
        query = arguments.get("query")
        if not query:
            raise ValueError("'query' is required")
        project_name = arguments.get("project_name")
        fmt = arguments.get("format", "markdown")
        if fmt not in ("ascii", "markdown"):
            fmt = "markdown"
        # persist disabled: an MCP server should not write files to the host.
        return generate_design_system(query, project_name, fmt, persist=False)

    raise ValueError(f"Unknown tool: {name}")


# ============ JSON-RPC / MCP TRANSPORT ============
def _send(message):
    """Write a single newline-delimited JSON-RPC message to stdout."""
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _result(req_id, result):
    _send({"jsonrpc": "2.0", "id": req_id, "result": result})


def _error(req_id, code, message):
    _send({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})


def handle_request(msg):
    """Handle one parsed JSON-RPC message. Returns nothing; sends responses."""
    method = msg.get("method")
    req_id = msg.get("id")
    is_notification = "id" not in msg

    if method == "initialize":
        _result(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
        })
        return

    if method in ("notifications/initialized", "initialized"):
        return  # notification, no response

    if method == "ping":
        _result(req_id, {})
        return

    if method == "tools/list":
        _result(req_id, {"tools": TOOLS})
        return

    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if name not in TOOLS_BY_NAME:
            _error(req_id, -32602, f"Unknown tool: {name}")
            return
        try:
            text = call_tool(name, arguments)
            _result(req_id, {"content": [{"type": "text", "text": text}]})
        except ValueError as e:
            # Tool-level error surfaced to the model, not a protocol error.
            _result(req_id, {
                "content": [{"type": "text", "text": f"Error: {e}"}],
                "isError": True,
            })
        except Exception as e:  # pragma: no cover - defensive
            _error(req_id, -32603, f"Internal error: {e}")
        return

    # Unknown method
    if not is_notification:
        _error(req_id, -32601, f"Method not found: {method}")


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            _send({"jsonrpc": "2.0", "id": None,
                   "error": {"code": -32700, "message": "Parse error"}})
            continue
        handle_request(msg)


if __name__ == "__main__":
    main()
