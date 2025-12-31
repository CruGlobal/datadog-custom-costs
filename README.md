# Datadog Custom Costs

Upload cloud provider cost data to Datadog Cloud Cost Management using the [Custom Costs API](https://docs.datadoghq.com/cloud_cost_management/custom/).

## Overview

This application fetches billing/usage data from cloud providers, converts it to the [FinOps FOCUS specification](https://focus.finops.org/), and uploads it to Datadog for unified cost visibility and analysis.

## Current Integrations

### GitHub
- **Data Source**: GitHub Organization Billing API
- **Metrics**: Actions, Packages, Storage, Codespaces, Copilot, etc.
- **Format**: FOCUS-compliant JSON with comprehensive tagging
- **Schedule**: Daily at 06:00 UTC via ECS Fargate

## How It Works

1. **Fetch**: Retrieves billing data from GitHub API for the current day
2. **Transform**: Converts to Datadog Custom Costs format with detailed tags
3. **Upload**: Sends data to Datadog via Custom Costs API
4. **Visibility**: Cost data appears in Datadog within 24-48 hours

## Environment Variables

### Required
- `GITHUB_TOKEN` - GitHub Personal Access Token
  - **Classic PAT**: Requires `admin:org` scope
  - **Fine-grained PAT**: Requires "Administration" organization permissions (read)
- `GITHUB_ORG` - GitHub organization name (e.g., "CruGlobal")
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
GITHUB_TOKEN=ghp_your_token_here
GITHUB_ORG=CruGlobal
DD_API_KEY=your_datadog_api_key
DD_APP_KEY=your_datadog_app_key
EOF
```

### Run Locally
```bash
# Install python-dotenv for .env support
pip install python-dotenv

# Run for today's data
python github_costs.py

# Run for a specific date
python github_costs.py --date 2025-12-22

# Run for entire month
python github_costs.py --year 2025 --month 12
```

### Test Docker Build
```bash
# Build image
docker build -t datadog-custom-costs .

# Run container (with environment variables)
docker run --env-file .env datadog-custom-costs
```

## Deployment

This application runs as an ECS Fargate scheduled task managed by Terraform in the [cru-terraform](https://github.com/CruGlobal/cru-terraform) repository.

**Infrastructure**: `cru-terraform/applications/datadog-custom-costs/`


## Data Format

Uploads follow the [Datadog Custom Costs schema](https://docs.datadoghq.com/cloud_cost_management/custom/):

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
    "unit_type": "minute",
    "quantity": "1000"
  }
}
```
