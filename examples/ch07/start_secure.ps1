param(
    [Parameter(Mandatory = $true)][string]$Issuer,
    [Parameter(Mandatory = $true)][string]$ClientId,
    [string]$Resource = "https://mcp.example.com/mcp"
)

$ErrorActionPreference = "Stop"
Push-Location (Resolve-Path (Join-Path $PSScriptRoot "../.."))
$corpusFixture = $null
$previous = @{}
try {
    $corpusJson = uv run --frozen python examples/ch07/prepare_corpus.py
    if ($LASTEXITCODE -ne 0) { throw "Corpus preparation failed." }
    $corpusFixture = $corpusJson | ConvertFrom-Json
    $settings = @{
        MCP_HTTP_REQUIRE_AUTH = "true"
        MCP_SECURITY_PROFILE = "read-only"
        MCP_ENABLE_WORKSPACE = "true"
        MCP_ENABLE_MUTATION = "false"
        MCP_ENABLE_GITHUB = "false"
        MCP_ENABLE_BROWSER = "false"
        MCP_AUTH_REQUIRED_SCOPES = "workspace:read"
        MCP_WORKSPACE_ROOTS = $corpusFixture.root
        MCP_CORPUS_APPROVAL_FILE = $corpusFixture.approval
        MCP_AUTH_ISSUER_URL = $Issuer
        MCP_AUTH_RESOURCE_URL = $Resource
        MCP_JWKS_URL = ($Issuer.TrimEnd('/') + "/.well-known/jwks.json")
        MCP_ALLOWED_CLIENT_IDS = $ClientId
        MCP_HTTP_HOST = "127.0.0.1"
        MCP_HTTP_PORT = "8000"
    }
    foreach ($name in $settings.Keys) {
        $previous[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
        [Environment]::SetEnvironmentVariable($name, [string]$settings[$name], "Process")
    }
    Write-Output "Serving the synthetic-g1 read-only corpus. Use Ctrl+C to stop."
    uv run --frozen build-an-mcp-server-secure
    if ($LASTEXITCODE -ne 0) { throw "Secured server exited unsuccessfully." }
}
finally {
    foreach ($name in $previous.Keys) {
        [Environment]::SetEnvironmentVariable($name, $previous[$name], "Process")
    }
    if ($null -ne $corpusFixture) {
        Remove-Item -LiteralPath $corpusFixture.directory -Recurse -Force
    }
    Pop-Location
}
