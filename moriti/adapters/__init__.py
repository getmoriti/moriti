"""
Gateway adapters.

The privacy engine is one thing; the gateways it can run inside are many.
Each adapter here is a thin translation layer: it receives whatever hook a
particular gateway fires, hands the tool result to ``PrivacyPlane.mediate()``,
and hands the rewritten result back in that gateway's own shape. No privacy
semantics live in an adapter -- if you find yourself putting a decision here,
it belongs in the engine.
"""
