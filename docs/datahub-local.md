# Local DataHub for development

LineageGuard uses a local DataHub Core instance during the DataHub vertical slice. This is for development and the hackathon demo only; it is not a production deployment.

## Start DataHub and sample metadata

From the repository root, after installing `requirements.txt` into an active Python environment:

```powershell
.\scripts\start-datahub.ps1
```

The script starts DataHub 1.6.0 and loads the official `showcase-ecommerce` payloads through DataHub's REST emitter. Local token-signing values are generated in the user's `.datahub` folder, outside the repository.

DataHub is then available at <http://localhost:9002> with `datahub` / `datahub` for local development.

To reload the official sample metadata without restarting DataHub:

```powershell
.\scripts\load-showcase-data.ps1
```

The loader skips only aspects rejected by the local DataHub version; it reports each skipped aspect and ingests every compatible official proposal.

## Configure the MCP bridge

Create a personal access token from the DataHub UI, then keep it only in the ignored `.env` file:

```env
DATAHUB_GMS_URL=http://host.docker.internal:8080
DATAHUB_GMS_TOKEN=replace-with-local-personal-access-token
DATAHUB_MUTATIONS_ENABLED=false
TOOLS_IS_MUTATION_ENABLED=false
```

When running the API outside Docker, use `http://localhost:8080` for `DATAHUB_GMS_URL` instead. Never commit the token.

The local Quickstart has development authentication disabled, so LineageGuard permits a blank token only for `localhost` and `host.docker.internal`. Any non-local DataHub URL requires `DATAHUB_GMS_TOKEN`.

## Verify the vertical slice

Start the LineageGuard containers, then use the OpenAPI UI at <http://localhost:8000/docs> to invoke:

- `GET /api/v1/datahub/search?query=orders`
- `GET /api/v1/datahub/schema?asset_urn=<dataset-urn-from-search>`
- `GET /api/v1/datahub/lineage?asset_urn=<dataset-urn-from-search>&direction=DOWNSTREAM&max_hops=3`

The service invokes the official self-hosted DataHub MCP server as an isolated subprocess. It allowlists only read tools; mutation flags remain disabled.

Run the automated end-to-end check after both DataHub and LineageGuard containers are healthy:

```powershell
$env:RUN_DATAHUB_INTEGRATION = '1'
$env:PYTHONPATH = (Join-Path (Get-Location) 'backend')
python -m pytest backend\tests\integration
```
