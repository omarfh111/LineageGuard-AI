$ErrorActionPreference = 'Stop'

python -c "import datahub" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw 'DataHub CLI missing. Install project requirements, then retry: python -m pip install -r requirements.txt'
}

python .\scripts\ingest_showcase_payloads.py
exit $LASTEXITCODE
