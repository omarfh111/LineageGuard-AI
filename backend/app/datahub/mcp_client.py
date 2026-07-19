"""Narrow, read-only client for the self-hosted DataHub MCP server."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.core.config import Settings, get_settings

READ_ONLY_TOOLS = frozenset(
    {
        "search",
        "get_entities",
        "list_schema_fields",
        "get_lineage",
        "get_lineage_paths_between",
        "get_dataset_queries",
    }
)


class DataHubConfigurationError(RuntimeError):
    """Raised before an MCP process is started with incomplete configuration."""


class DataHubMcpClient:
    """Call only allowlisted DataHub MCP read tools via an isolated stdio process."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _server_environment(self) -> dict[str, str]:
        if not self._settings.datahub_gms_url:
            raise DataHubConfigurationError("DATAHUB_GMS_URL is not configured")
        if not self._settings.datahub_gms_token and not _is_local_gms(
            self._settings.datahub_gms_url
        ):
            raise DataHubConfigurationError("DATAHUB_GMS_TOKEN is not configured")

        environment = os.environ.copy()
        environment.update(
            {
                "DATAHUB_GMS_URL": self._settings.datahub_gms_url,
                "DATAHUB_MUTATIONS_ENABLED": "false",
                "TOOLS_IS_MUTATION_ENABLED": "false",
                "DATAHUB_MCP_DOCUMENT_TOOLS_DISABLED": "true",
            }
        )
        if self._settings.datahub_gms_token:
            environment["DATAHUB_GMS_TOKEN"] = self._settings.datahub_gms_token
        else:
            environment.pop("DATAHUB_GMS_TOKEN", None)
        return environment

    async def call_tool(
        self, tool_name: str, arguments: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Run one read-only MCP tool and return its protocol result as JSON data."""

        if tool_name not in READ_ONLY_TOOLS:
            raise ValueError(f"MCP tool {tool_name!r} is not allowlisted")

        parameters = StdioServerParameters(
            command="mcp-server-datahub",
            env=self._server_environment(),
        )
        async with stdio_client(parameters) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, dict(arguments))
                return result.model_dump(mode="json")

    async def search(self, query: str) -> dict[str, Any]:
        return await self.call_tool("search", {"query": query})

    async def list_schema_fields(self, urn: str) -> dict[str, Any]:
        return await self.call_tool("list_schema_fields", {"urn": urn})

    async def get_lineage(
        self, urn: str, direction: str, max_hops: int
    ) -> dict[str, Any]:
        """Map the API direction to the MCP server's ``upstream`` flag."""

        return await self.call_tool(
            "get_lineage",
            {
                "urn": urn,
                "upstream": direction == "UPSTREAM",
                "max_hops": max_hops,
            },
        )


def get_datahub_client() -> DataHubMcpClient:
    """FastAPI dependency factory for the read-only MCP client."""

    return DataHubMcpClient(get_settings())


def _is_local_gms(url: str) -> bool:
    """Allow tokenless access only to the unauthenticated local Quickstart."""

    return urlparse(url).hostname in {
        "localhost",
        "127.0.0.1",
        "::1",
        "host.docker.internal",
    }
