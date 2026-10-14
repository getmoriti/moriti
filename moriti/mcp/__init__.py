"""
MCP interception for the moriti privacy control plane.

`proxy` is the enforcement point: an MCP server on the front, an MCP client on
the back, with PrivacyPlane.mediate() between them. `demo_hr_server` is a toy
downstream server that deliberately over-returns sensitive fields, so the demo
can show the proxy withholding them.
"""
