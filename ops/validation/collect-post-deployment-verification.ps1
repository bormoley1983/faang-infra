[CmdletBinding()]
param(
    [string]$Context = "",
    [ValidateRange(5, 120)][int]$TimeoutSeconds = 20,
    [string]$Namespace = "faang",
    [string]$IngressUri = "",
    [string]$ReadinessUri = "",
    [switch]$RequireReadiness,
    [string]$JenkinsUri = "",
    [string]$JenkinsJob = "",
    [string]$JenkinsBuild = "lastCompletedBuild"
)

# DEP-052 collector. It intentionally issues only GET/raw DNS/HTTPS requests.
# It never reads Secret data, creates diagnostic resources, or invokes Argo sync.
$ErrorActionPreference = "Stop"
$kubectl = @("--request-timeout=$($TimeoutSeconds)s")
if (-not [string]::IsNullOrWhiteSpace($Context)) { $kubectl += @("--context", $Context) }

function Invoke-ReadOnlyKubectl {
    param([Parameter(Mandatory)][string[]]$Arguments)
    $result = & kubectl @kubectl @Arguments
    if ($LASTEXITCODE -ne 0) { throw "read_only_collection_failed" }
    return ($result | ConvertFrom-Json)
}

function Condition-True {
    param($Item, [string]$Type)
    return @($Item.status.conditions | Where-Object { $_.type -eq $Type -and $_.status -eq "True" }).Count -gt 0
}

function Image-Identity {
    param([string]$Image)
    if ($Image -match "@sha256:([a-f0-9]{64})$") { return "sha256:" + $Matches[1] }
    return "not-digest-pinned"
}

function Get-JenkinsBuildEvidence {
    param([string]$BaseUri, [string]$Job, [string]$Build)
    $notCollected = [ordered]@{ status = "not-collected"; result = "not-collected"; building = $false; durationMilliseconds = $null }
    if ([string]::IsNullOrWhiteSpace($BaseUri) -and [string]::IsNullOrWhiteSpace($Job)) { return $notCollected }
    if ([string]::IsNullOrWhiteSpace($BaseUri) -or [string]::IsNullOrWhiteSpace($Job)) { throw "jenkins_uri_and_job_required" }
    if ($Job -notmatch "^[A-Za-z0-9_. -]+(?:/[A-Za-z0-9_. -]+)*$" -or $Build -notmatch "^(lastCompletedBuild|[0-9]+)$") { throw "invalid_jenkins_build_selector" }
    $reviewedBaseUri = [uri]$BaseUri
    if ($reviewedBaseUri.Scheme -ne "https" -or -not [string]::IsNullOrWhiteSpace($reviewedBaseUri.UserInfo)) { throw "jenkins_https_uri_required" }
    $user = [Environment]::GetEnvironmentVariable("FAANG_JENKINS_API_USER")
    $token = [Environment]::GetEnvironmentVariable("FAANG_JENKINS_API_TOKEN")
    if ([string]::IsNullOrWhiteSpace($user) -or [string]::IsNullOrWhiteSpace($token)) { throw "jenkins_read_only_credentials_unavailable" }
    try {
        $jobPath = (($Job -split "/" | ForEach-Object { "job/" + [uri]::EscapeDataString($_) }) -join "/")
        $base = $reviewedBaseUri.AbsoluteUri.TrimEnd("/")
        $uri = [uri]("$base/$jobPath/$Build/api/json?tree=result,building,duration")
        $handler = [System.Net.Http.HttpClientHandler]::new()
        $client = [System.Net.Http.HttpClient]::new($handler)
        $client.Timeout = [TimeSpan]::FromSeconds($TimeoutSeconds)
        $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("${user}:$token"))
        $client.DefaultRequestHeaders.Authorization = [System.Net.Http.Headers.AuthenticationHeaderValue]::new("Basic", $encoded)
        $response = $client.GetAsync($uri).GetAwaiter().GetResult()
        if (-not $response.IsSuccessStatusCode) { return [ordered]@{ status = "http-" + [int]$response.StatusCode; result = "unavailable"; building = $false; durationMilliseconds = $null } }
        $payload = ($response.Content.ReadAsStringAsync().GetAwaiter().GetResult() | ConvertFrom-Json)
        return [ordered]@{ status = "collected"; result = ($payload.result ?? "unknown"); building = [bool]$payload.building; durationMilliseconds = [int64]($payload.duration ?? 0) }
    } catch {
        return [ordered]@{ status = "failed-or-untrusted"; result = "unavailable"; building = $false; durationMilliseconds = $null }
    }
}

function Get-ReadinessEvidence {
    param([string]$UriText)
    $notRequested = [ordered]@{ requested = $false; dns = "not-run"; httpStatus = "not-run"; tls = "not-run"; contract = "not-run" }
    if ([string]::IsNullOrWhiteSpace($UriText)) { return $notRequested }

    $evidence = [ordered]@{ requested = $true; dns = "not-run"; httpStatus = "not-run"; tls = "not-run"; contract = "failed" }
    try {
        $uri = [uri]$UriText
        if ($uri.Scheme -ne "https" -or -not [string]::IsNullOrWhiteSpace($uri.UserInfo) -or
            $uri.AbsolutePath -ne "/actuator/health/readiness" -or -not [string]::IsNullOrWhiteSpace($uri.Query)) {
            throw "readiness_https_contract_uri_required"
        }
        $evidence.dns = if ([System.Net.Dns]::GetHostAddresses($uri.Host).Count -gt 0) { "resolved" } else { "not-resolved" }
        $handler = [System.Net.Http.HttpClientHandler]::new(); $handler.AllowAutoRedirect = $false
        $client = [System.Net.Http.HttpClient]::new($handler); $client.Timeout = [TimeSpan]::FromSeconds($TimeoutSeconds)
        $response = $client.GetAsync($uri).GetAwaiter().GetResult()
        $evidence.httpStatus = [int]$response.StatusCode
        $evidence.tls = "validated"
        if ($response.StatusCode -eq [System.Net.HttpStatusCode]::OK) {
            $payload = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult() | ConvertFrom-Json
            if ($payload.status -eq "UP") { $evidence.contract = "passed" }
        }
    } catch {
        $evidence.tls = "failed-or-untrusted"
        if ($evidence.dns -eq "not-run") { $evidence.dns = "failed" }
    }
    return $evidence
}

$expectedApplications = @(
    "faang-system", "faang-runtime-foundation", "faang-selected-dependencies",
    "faang-bootstrap", "faang-workloads"
)
$expectedJobs = @(
    "faang-bootstrap-postgres-v1", "faang-bootstrap-kafka-v1",
    "faang-bootstrap-elasticsearch-v1", "faang-bootstrap-s3-v1"
)

$applications = Invoke-ReadOnlyKubectl @("-n", "argocd", "get", "applications.argoproj.io", "-o", "json")
$deployments = Invoke-ReadOnlyKubectl @("-n", $Namespace, "get", "deployments", "-o", "json")
$services = Invoke-ReadOnlyKubectl @("-n", $Namespace, "get", "services", "-o", "json")
$ingresses = Invoke-ReadOnlyKubectl @("-n", $Namespace, "get", "ingress", "-o", "json")
$slices = Invoke-ReadOnlyKubectl @("-n", $Namespace, "get", "endpointslice", "-o", "json")
$jobs = Invoke-ReadOnlyKubectl @("-n", $Namespace, "get", "jobs", "-o", "json")

$applicationEvidence = foreach ($name in $expectedApplications) {
    $item = @($applications.items | Where-Object { $_.metadata.name -eq $name }) | Select-Object -First 1
    [ordered]@{
        application = $name
        present = $null -ne $item
        sync = if ($item) { ($item.status.sync.status ?? "Unknown") } else { "Missing" }
        health = if ($item) { ($item.status.health.status ?? "Unknown") } else { "Missing" }
        revision = if ($item -and $item.status.sync.revision -match "^[a-f0-9]{7,64}$") { $item.status.sync.revision } else { "unavailable" }
    }
}
$workloadEvidence = foreach ($item in @($deployments.items | Sort-Object metadata.name)) {
    $containers = @($item.spec.template.spec.containers)
    [ordered]@{
        deployment = $item.metadata.name
        desired = [int]($item.spec.replicas ?? 0)
        ready = [int]($item.status.readyReplicas ?? 0)
        available = [int]($item.status.availableReplicas ?? 0)
        images = @($containers | ForEach-Object { Image-Identity $_.image })
    }
}
$serviceEvidence = foreach ($item in @($services.items | Where-Object { $_.metadata.name -like "faang-*-service" } | Sort-Object metadata.name)) {
    $matching = @($slices.items | Where-Object { $_.metadata.labels.'kubernetes.io/service-name' -eq $item.metadata.name })
    [ordered]@{
        service = $item.metadata.name
        endpointSlices = $matching.Count
        readyEndpoints = @($matching | ForEach-Object { $_.endpoints } | Where-Object { $_.conditions.ready -eq $true }).Count
    }
}
$jobEvidence = foreach ($name in $expectedJobs) {
    $item = @($jobs.items | Where-Object { $_.metadata.name -eq $name }) | Select-Object -First 1
    [ordered]@{ job = $name; present = $null -ne $item; completed = if ($item) { Condition-True $item "Complete" } else { $false }; failed = if ($item) { Condition-True $item "Failed" } else { $false } }
}

$ingress = @($ingresses.items | Where-Object { $_.metadata.name -eq "faang-ingress" }) | Select-Object -First 1
$external = [ordered]@{ requested = -not [string]::IsNullOrWhiteSpace($IngressUri); dns = "not-run"; httpStatus = "not-run"; tls = "not-run"; redirect = "not-run" }
if ($external.requested) {
    try {
        $uri = [uri]$IngressUri
        $external.dns = if ([System.Net.Dns]::GetHostAddresses($uri.Host).Count -gt 0) { "resolved" } else { "not-resolved" }
        $handler = [System.Net.Http.HttpClientHandler]::new(); $handler.AllowAutoRedirect = $false
        $client = [System.Net.Http.HttpClient]::new($handler); $client.Timeout = [TimeSpan]::FromSeconds($TimeoutSeconds)
        $response = $client.GetAsync($uri).GetAwaiter().GetResult()
        $external.httpStatus = [int]$response.StatusCode
        $external.redirect = if ([int]$response.StatusCode -in 301,302,303,307,308) { "present" } else { "absent" }
        $external.tls = if ($uri.Scheme -eq "https") { "validated" } else { "not-applicable" }
    } catch {
        $external.tls = if ($IngressUri -match "^https://") { "failed-or-untrusted" } else { "not-applicable" }
        if ($external.dns -eq "not-run") { $external.dns = "failed" }
    }
}
$jenkins = Get-JenkinsBuildEvidence -BaseUri $JenkinsUri -Job $JenkinsJob -Build $JenkinsBuild
$readiness = Get-ReadinessEvidence -UriText $ReadinessUri
if ($RequireReadiness -and $readiness.contract -ne "passed") {
    throw "readiness_contract_failed"
}

$result = [ordered]@{
    schemaVersion = 1
    collectedAtUtc = [DateTime]::UtcNow.ToString("o")
    mutationPerformed = $false
    argo = $applicationEvidence
    workloads = $workloadEvidence
    services = $serviceEvidence
    ingress = [ordered]@{ present = $null -ne $ingress; ruleCount = if ($ingress) { @($ingress.spec.rules).Count } else { 0 }; external = $external; readiness = $readiness }
    bootstrap = $jobEvidence
    dependencies = [ordered]@{ postgresql = "not-probed"; redis = "not-probed"; kafka = "not-probed"; elasticsearch = "not-probed"; s3 = "not-probed"; note = "Use a separately approved, scoped read-only in-cluster probe; do not use mutation-capable preflights for this baseline." }
    jenkins = $jenkins
}
$result | ConvertTo-Json -Depth 8
