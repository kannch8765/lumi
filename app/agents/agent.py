"""Lumi's ADK root_agent entry point.

This file is the ADK CLI discovery contract. The ``adk run``,
``adk web``, and ``adk eval`` commands all look for a module-level
``root_agent: BaseAgent`` in either ``<folder>/agent.py`` or
``<folder>/root_agent.yaml`` (see ``google.adk.cli.agent_loader``).

Exposing the full Lumi pipeline as ``root_agent`` lets users run::

    adk run app/agents "I'm a CS undergrad in Brazil, want to learn LLMs"
    adk web app/agents --port 8000

without needing to know Lumi's internal factory layout.

IMPORTANT: This file is intentionally thin. Do NOT add tools, LLM
calls, or business logic here. Per ``CONTEXT.md #10``, the tool
whitelist is the kill switch, and the orchestrator is tool-free by
design (see ``test_pipeline_orchestrator_has_no_tools`` in
``tests/integration/test_orchestrator.py``).
"""

from app.orchestrator import create_lumi_pipeline

root_agent = create_lumi_pipeline()
