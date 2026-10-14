"""
Proxy deployment configuration.

Purpose is bound HERE, not taken from the agent. An agent that could declare
its own purpose per call would simply declare whichever one unlocks the data;
the guards would then be evaluating a string the adversary controls. Binding
purpose to the deployment makes it organisational configuration -- something a
privacy officer sets when an agent is provisioned, and something the agent
cannot vary at runtime.

One proxy process serves one agent identity with one assigned purpose. Give a
multi-purpose agent several proxy entries, each scoped to what that purpose
needs.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from moriti._config import reject_unknown_keys
from moriti.context import Destination, LegalBasis, Retention


class DownstreamServer(BaseModel):
    """The real MCP server the proxy fronts.

    Either a stdio `command` the proxy spawns, or the `url` of a server that
    speaks MCP over streamable HTTP (what cloud gateways and hosted servers
    expose). Exactly one of the two.

    `command: "{python}"` means the interpreter running the proxy, so a demo
    server ships in the same environment as the proxy regardless of what
    `python3` resolves to on the PATH. A real server uses a real command.
    """

    model_config = ConfigDict(extra="forbid")

    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] | None = None
    cwd: str | None = None
    #: Streamable-HTTP endpoint, e.g. http://tools.internal:8000/mcp
    url: str | None = None
    #: Extra headers for the HTTP downstream (bearer tokens, tenant ids).
    headers: dict[str, str] | None = None

    @model_validator(mode="after")
    def _one_transport(self) -> DownstreamServer:
        if bool(self.command) == bool(self.url):
            raise ValueError("downstream needs exactly one of `command` (stdio) or `url` (streamable HTTP)")
        return self

    @property
    def is_http(self) -> bool:
        return self.url is not None

    @property
    def resolved_command(self) -> str:
        assert self.command is not None
        return sys.executable if self.command == "{python}" else self.command


class ProxyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _no_unknown_keys(cls, data: Any) -> Any:
        return reject_unknown_keys(data, cls.model_fields, "proxy deployment")

    #: Agent identity this proxy instance serves.
    agent: str
    #: The purpose bound at provisioning time. The agent cannot override it.
    purpose: str
    #: Policy pack name under moriti/policies/.
    policy: str
    principal: str | None = None
    principal_role: str | None = None
    destination: Destination = Destination.INTERNAL_MODEL
    retention: Retention = Retention.EPHEMERAL
    jurisdiction: str | None = None
    legal_basis: LegalBasis | None = None
    consent_scopes: list[str] = Field(default_factory=list)
    #: Tools the agent may see and call. Empty = all downstream tools.
    allowed_tools: list[str] = Field(default_factory=list)
    downstream: DownstreamServer

    @classmethod
    def from_yaml(cls, path: str | Path) -> ProxyConfig:
        from moriti.adapters.common import _policy_beside

        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return cls.model_validate(_policy_beside(data, Path(path)))
