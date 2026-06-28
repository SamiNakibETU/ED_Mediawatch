# Script de Test Local - OLJ Advanced Scraper (Windows PowerShell)
# Usage: .\test_local.ps1 -Url "https://example.com/article"

param(
    [Parameter(Mandatory=$false)]
    [string]$Url = "",
    
    [Parameter(Mandatory=$false)]
    [string]$ServiceUrl = "http://localhost:8080"
)

function Test-Health {
    Write-Host "`n=== Test 1: Health Check ===" -ForegroundColor Cyan
    try {
        $response = Invoke-RestMethod -Uri "$ServiceUrl/health" -Method GET -TimeoutSec 10
        Write-Host "✅ Service status: $($response.status)" -ForegroundColor Green
        Write-Host "   Version: $($response.version)" -ForegroundColor Gray
        Write-Host "   curl_cffi: $($response.curl_cffi_available)" -ForegroundColor Gray
        Write-Host "   Playwright: $($response.playwright_available)" -ForegroundColor Gray
        Write-Host "   Scrapling: $($response.scrapling_available)" -ForegroundColor Gray
        return $true
    } catch {
        Write-Host "❌ Health check failed: $_" -ForegroundColor Red
        return $false
    }
}

function Test-Extract {
    param([string]$TestUrl)
    
    Write-Host "`n=== Test 2: Extraction ===" -ForegroundColor Cyan
    Write-Host "URL: $TestUrl" -ForegroundColor Gray
    
    $body = @{
        url = $TestUrl
        force_complete = $true
    } | ConvertTo-Json
    
    try {
        $response = Invoke-RestMethod -Uri "$ServiceUrl/extract" -Method POST `
            -ContentType "application/json" -Body $body -TimeoutSec 60
        
        Write-Host "✅ Extraction successful!" -ForegroundColor Green
        Write-Host "   Title: $($response.title)" -ForegroundColor White
        Write-Host "   Word count: $($response.word_count)" -ForegroundColor Gray
        Write-Host "   Complete: $($response.is_complete)" -ForegroundColor $(if($response.is_complete){"Green"}else{"Yellow"})
        Write-Host "   Method: $($response.extraction_method)" -ForegroundColor Gray
        Write-Host "   Duration: $($response.total_duration_ms)ms" -ForegroundColor Gray
        
        if ($response.content) {
            $preview = $response.content.Substring(0, [Math]::Min(200, $response.content.Length))
            Write-Host "`n   Preview: $preview..." -ForegroundColor DarkGray
        }
        
        return $response
    } catch {
        Write-Host "❌ Extraction failed: $_" -ForegroundColor Red
        return $null
    }
}

function Test-Verify {
    param([string]$Content)
    
    Write-Host "`n=== Test 3: Verify Content ===" -ForegroundColor Cyan
    
    $body = @{
        content = $Content
        min_words = 150
    } | ConvertTo-Json
    
    try {
        $response = Invoke-RestMethod -Uri "$ServiceUrl/verify" -Method POST `
            -ContentType "application/json" -Body $body -TimeoutSec 10
        
        Write-Host "✅ Verification complete" -ForegroundColor Green
        Write-Host "   Is complete: $($response.is_complete)" -ForegroundColor $(if($response.is_complete){"Green"}else{"Yellow"})
        Write-Host "   Word count: $($response.word_count)" -ForegroundColor Gray
        Write-Host "   Score: $($response.completeness_score)" -ForegroundColor Gray
        
        return $response
    } catch {
        Write-Host "❌ Verification failed: $_" -ForegroundColor Red
        return $null
    }
}

function Test-Stats {
    Write-Host "`n=== Test 4: Service Stats ===" -ForegroundColor Cyan
    try {
        $response = Invoke-RestMethod -Uri "$ServiceUrl/stats" -Method GET -TimeoutSec 10
        Write-Host "✅ Stats retrieved" -ForegroundColor Green
        Write-Host "   Total requests: $($response.total_requests)" -ForegroundColor Gray
        Write-Host "   Success rate: $([math]::Round($response.successful_requests / [math]::Max(1, $response.total_requests) * 100, 1))%" -ForegroundColor Gray
        Write-Host "   Avg duration: $([math]::Round($response.average_duration_ms, 0))ms" -ForegroundColor Gray
        return $response
    } catch {
        Write-Host "❌ Stats failed: $_" -ForegroundColor Red
        return $null
    }
}

# ========== MAIN ==========

Write-Host @"
╔══════════════════════════════════════════════════════════╗
║     OLJ Advanced Scraper - Test Local                    ║
╚══════════════════════════════════════════════════════════╝
"@ -ForegroundColor Cyan

Write-Host "Service URL: $ServiceUrl" -ForegroundColor Gray

# Test 1: Health
$healthOk = Test-Health
if (-not $healthOk) {
    Write-Host "`n⚠️  Service not responding. Is it running?" -ForegroundColor Yellow
    Write-Host "   Start with: uvicorn src.main:app --host 0.0.0.0 --port 8080 --reload" -ForegroundColor Gray
    exit 1
}

# Test 2: Root endpoint
Write-Host "`n=== Service Info ===" -ForegroundColor Cyan
try {
    $info = Invoke-RestMethod -Uri $ServiceUrl -Method GET -TimeoutSec 5
    Write-Host "   Service: $($info.service)" -ForegroundColor Gray
    Write-Host "   Version: $($info.version)" -ForegroundColor Gray
} catch {}

# Test 3: Extraction (si URL fournie)
if ($Url) {
    $result = Test-Extract -TestUrl $Url
    
    # Test 4: Verify (si extraction réussie)
    if ($result -and $result.content) {
        Test-Verify -Content $result.content
    }
} else {
    Write-Host "`n⚠️  No URL provided. Skipping extraction test." -ForegroundColor Yellow
    Write-Host "   Usage: .\test_local.ps1 -Url 'https://example.com/article'" -ForegroundColor Gray
}

# Test 5: Stats
Test-Stats

Write-Host "`n✨ Tests completed!" -ForegroundColor Cyan
