"""Lumi agent package.

Multi-agent system that helps students worldwide find free AI learning
resources. See ARCHITECTURE.md for the 4-layer pipeline design and the
Two-Layer L0-L5 control model.

Subpackages:
    agents      — the L-layer agent factories (L1-L4) and the ADK
                  ``root_agent`` discovery entry at
                  ``app/agents/agent.py`` (Task 56)
    mcp_servers  — the two MCP servers: resource_catalog + web_search
    fast_api_app — FastAPI wrapper for adk (added in Task 27)
"""
