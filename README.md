# Datadog Custom Costs

Upload cloud provider cost data to Datadog Cloud Cost Management using the [Custom Costs API](https://docs.datadoghq.com/cloud_cost_management/custom/).

## Overview

This application fetches billing/usage data from cloud providers, converts it to the [FinOps FOCUS specification](https://focus.finops.org/), and uploads it to Datadog for unified cost visibility and analysis.

## Current Integrations

### GitHub
- **Data Source**: GitHub Organization Billing API
- **Metrics**: Actions, Packages, Storage, Codespaces, Copilot, etc.
- **Format**: FOCUS-compliant JSON with comprehensive tagging
- **Service Tagging**: Supports `service-*` GitHub topics for cost grouping
- **Schedule**: Daily at 06:00 UTC via ECS Fargate

### Neon
- **Data Source**: Neon Database Consumption API
- **Metrics**: Compute (CU-hours), Storage (GB), Data Transfer
- **Pricing**: Usage-based - $0.222/CU-hour, $0.35/GB-month
- **Format**: FOCUS-compliant JSON with per-project cost allocation
- **Tags**: project_id, project_name, service, env (parsed from project name)
- **Schedule**: Daily at 06:30 UTC via ECS Fargate

## How It Works

1. **Fetch**: Retrieves billing data from GitHub API for the current day
2. **Transform**: Converts to Datadog Custom Costs format with detailed tags
3. **Upload**: Sends data to Datadog via Custom Costs API
4. **Visibility**: Cost data appears in Datadog within 24-48 hours

## Environment Variables

### Job Selector (Required for Docker/ECS)
- `JOB` - Specifies which integration to run: `GITHUB` or `NEON`

### GitHub Integration
- `GITHUB_TOKEN` - GitHub Personal Access Token
  - **Classic PAT**: Requires `admin:org` (for billing) and `repo` (for private repo metadata/topics) scopes
  - **Fine-grained PAT**: Requires "Administration" organization permissions (read) and "Repository" permissions (read)
- `GITHUB_ORG` - GitHub organization name (e.g., "CruGlobal")

### Neon Integration
- `NEON_API_KEY` - Neon API key with billing/consumption read access
- `NEON_ORG_ID` - Neon organization ID

### Datadog (Required for both)
- `DD_API_KEY` - Datadog API key
- `DD_APP_KEY` - Datadog Application key

## Local Development

### Setup
```bash
# Clone repository
git clone https://github.com/CruGlobal/datadog-custom-costs.git
cd datadog-custom-costs

# Install dependencies
pip install -r requirements.txt

# Create .env file with credentials
cat > .env << EOF
# GitHub Integration
GITHUB_TOKEN=ghp_your_token_here
GITHUB_ORG=CruGlobal

# Neon Integration
NEON_API_KEY=your_neon_api_key
NEON_ORG_ID=org-your-org-id

# Datadog (shared)
DD_API_KEY=your_datadog_api_key
DD_APP_KEY=your_datadog_app_key
EOF
```

### Run Locally

#### GitHub Costs
```bash
# Dry run - test without uploading (recommended first)
python github_costs.py --date 2025-12-22 --dry-run

# Run for yesterday's data (default)
python github_costs.py

# Run for a specific date
python github_costs.py --date 2025-12-22

# Run for entire month
python github_costs.py --year 2025 --month 12
```

#### Neon Costs
```bash
# Dry run - test without uploading (recommended first)
python neon_costs.py --date 2026-01-05 --dry-run

# Run for yesterday's data (default)
python neon_costs.py

# Run for a specific date
python neon_costs.py --date 2026-01-05
```

### Test Docker Build
```bash
# Build image
docker build -t datadog-custom-costs .

# Run GitHub job
docker run --env-file .env -e JOB=GITHUB datadog-custom-costs

# Run Neon job
docker run --env-file .env -e JOB=NEON datadog-custom-costs
```

## Deployment

This application runs as ECS Fargate scheduled tasks managed by Terraform in the [cru-terraform](https://github.com/CruGlobal/cru-terraform) repository.

**Infrastructure**: `cru-terraform/applications/datadog-custom-costs/`

## Data Format

Uploads follow the [Datadog Custom Costs schema](https://docs.datadoghq.com/cloud_cost_management/custom/) (FOCUS-compliant).

### GitHub Example
```json
{
  "ProviderName": "GitHub",
  "ChargeDescription": "Actions",
  "ChargePeriodStart": "2025-12-22",
  "ChargePeriodEnd": "2025-12-22",
  "BilledCost": 15.50,
  "BillingCurrency": "USD",
  "Tags": {
    "sku": "actions-linux",
    "repository": "my-repo",
    "service": "my-service",
    "unit_type": "minute",
    "quantity": "1000"
  }
}
```

#### Service Tagging

GitHub costs support service-level cost attribution using repository topics:

1. **Add a `service-*` topic** to your repository (e.g., `service-terraform`, `service-godtools`)
2. **Cost attribution**: All costs for that repo will be tagged with the extracted service name
3. **Default behavior**: If no `service-*` topic exists, uses the repository name as the service

**Topic Requirements** (GitHub restrictions):
- Lowercase letters, numbers, and hyphens only
- Maximum 50 characters
- Maximum 20 topics per repository

**Analyze your repositories** to find service grouping opportunities:
```bash
python analyze_repos.py
```

This script will:
- Identify existing `service-*` topics
- Recommend which repos should share service tags
- Show potential cost groupings based on naming patterns

### Neon Example
```json
{
  "ProviderName": "Neon",
  "ChargeDescription": "Compute",
  "ChargePeriodStart": "2026-01-05",
  "ChargePeriodEnd": "2026-01-05",
  "BilledCost": 2.45,
  "BillingCurrency": "USD",
  "Tags": {
    "project_id": "calm-boat-12345678",
    "project_name": "game-ops-prod",
    "service": "game-ops",
    "env": "prod",
    "charge_type": "compute",
    "compute_hours": "11.0432",
    "rate_per_cu_hour": "0.222",
    "active_seconds": "39755"
  }
}
```
