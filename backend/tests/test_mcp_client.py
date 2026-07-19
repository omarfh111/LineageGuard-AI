import pytest

from app.core.config import Settings
from app.datahub.mcp_client import DataHubConfigurationError, DataHubMcpClient


@pytest.mark.asyncio
async def test_client_refuses_mutating_tool_before_starting_a_process() -> None:
    client = DataHubMcpClient(
        Settings(
            app_env="test",
            database_url="sqlite:///./test.db",
            datahub_gms_url="http://localhost:8080",
            datahub_gms_token="test-token",
        )
    )

    with pytest.raises(ValueError, match="not allowlisted"):
        await client.call_tool("update_description", {})


def test_client_requires_datahub_configuration() -> None:
    client = DataHubMcpClient(
        Settings(
            app_env="test",
            database_url="sqlite:///./test.db",
            datahub_gms_url="",
            datahub_gms_token=None,
        )
    )

    with pytest.raises(DataHubConfigurationError, match="GMS_URL"):
        client._server_environment()


def test_client_permits_a_tokenless_local_quickstart() -> None:
    client = DataHubMcpClient(
        Settings(
            app_env="test",
            database_url="sqlite:///./test.db",
            datahub_gms_url="http://host.docker.internal:8080",
            datahub_gms_token=None,
        )
    )

    assert client._server_environment()["TOOLS_IS_MUTATION_ENABLED"] == "false"


def test_client_requires_a_token_for_remote_datahub() -> None:
    client = DataHubMcpClient(
        Settings(
            app_env="test",
            database_url="sqlite:///./test.db",
            datahub_gms_url="https://datahub.example.com",
            datahub_gms_token=None,
        )
    )

    with pytest.raises(DataHubConfigurationError, match="GMS_TOKEN"):
        client._server_environment()


@pytest.mark.asyncio
async def test_client_maps_downstream_lineage_to_the_mcp_upstream_flag() -> None:
    client = DataHubMcpClient(
        Settings(
            app_env="test",
            database_url="sqlite:///./test.db",
            datahub_gms_url="http://localhost:8080",
            datahub_gms_token=None,
        )
    )
    captured: dict[str, object] = {}

    async def fake_call_tool(tool_name: str, arguments: dict[str, object]) -> dict:
        captured["tool_name"] = tool_name
        captured["arguments"] = arguments
        return {}

    client.call_tool = fake_call_tool  # type: ignore[method-assign]

    await client.get_lineage("urn:li:dataset:orders", "DOWNSTREAM", 3)

    assert captured == {
        "tool_name": "get_lineage",
        "arguments": {
            "urn": "urn:li:dataset:orders",
            "upstream": False,
            "max_hops": 3,
        },
    }
