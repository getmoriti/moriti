"""
moriti inside IBM ContextForge.

ContextForge is an Apache-2.0 MCP gateway; its plugin framework (``cpex``)
fires ``tool_post_invoke`` after every tool call with the raw result in hand.
:class:`MoritiPrivacyPlugin` runs there as an *external* plugin -- its own
process the gateway calls over Streamable HTTP -- and rewrites the result
field-by-field before it ever reaches the agent.

Requires the ``contextforge`` extra (``pip install "moriti[contextforge]"``)
and Python 3.12, which ``cpex`` / ContextForge require.
"""

from moriti.adapters.contextforge.plugin import DeploymentConfig, MoritiPrivacyPlugin

__all__ = ["DeploymentConfig", "MoritiPrivacyPlugin"]
