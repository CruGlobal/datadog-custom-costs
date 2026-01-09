#!/usr/bin/env python3
"""
GitHub Cost Data Generator

Fetches billing data from GitHub API and converts it to FOCUS format
for upload to Datadog Cloud Cost Management.
"""

import os
import sys
import argparse
import json
from datetime import datetime, timedelta
from decimal import Decimal
import requests
from typing import Dict, List, Optional
import logging

from datadog_uploader import DatadogCostUploader

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class GitHubCostFetcher:
    """Fetch and convert GitHub billing data to FOCUS format."""

    def __init__(self, github_token: str = None, org_name: str = None):
        """
        Initialize fetcher with GitHub credentials.

        Args:
            github_token: GitHub PAT with billing:read scope
            org_name: GitHub organization name
        """
        self.token = github_token or os.getenv("GITHUB_TOKEN")
        self.org = org_name or os.getenv("GITHUB_ORG")

        # Validate credentials
        if not self.token:
            logger.error("GitHub token not found. Set GITHUB_TOKEN environment variable.")
            raise ValueError("GitHub token required. Set GITHUB_TOKEN environment variable.")

        if not self.org:
            logger.error("GitHub org not found. Set GITHUB_ORG environment variable.")
            raise ValueError("GitHub organization required. Set GITHUB_ORG environment variable.")

        self.base_url = "https://api.github.com"
        logger.info(f"Initialized GitHub cost fetcher for organization: {self.org}")

    def fetch_billing_data(self, year: int, month: int = None, day: int = None) -> List[Dict]:
        """
        Fetch billing data from GitHub API.

        Args:
            year: Year to fetch
            month: Optional month to fetch
            day: Optional day to fetch

        Returns:
            List of usage items from GitHub API
        """
        url = f"{self.base_url}/orgs/{self.org}/settings/billing/usage"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28"
        }
        params = {"year": year}
        if month:
            params["month"] = month
        if day:
            params["day"] = day

        date_str = f"{year}"
        if month:
            date_str += f"-{month:02d}"
        if day:
            date_str += f"-{day:02d}"
        logger.info(f"Fetching GitHub billing data for {date_str}")

        try:
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()
            usage_items = data.get("usageItems", [])
            logger.info(f"Retrieved {len(usage_items)} usage items from GitHub")
            return usage_items

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                logger.error("Authentication failed. Check your GITHUB_TOKEN.")
            elif e.response.status_code == 403:
                logger.error("Forbidden. Token may lack billing:read scope.")
            elif e.response.status_code == 404:
                logger.error(f"Organization '{self.org}' not found.")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed: {e}")
            raise

    def get_repository_metadata(self, repository_name: str) -> Dict:
        """
        Fetch repository metadata including topics.

        Args:
            repository_name: Name of the repository

        Returns:
            Repository metadata dict with topics
        """
        url = f"{self.base_url}/repos/{self.org}/{repository_name}"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28"
        }

        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            topics = data.get("topics", [])

            # Log service topic detection
            service_topics = [t for t in topics if t.startswith("service-")]
            if service_topics:
                logger.info(f"Repository '{repository_name}' has service topic: {service_topics[0]}")
            else:
                logger.debug(f"Repository '{repository_name}' has no service topic, using repo name")

            return data
        except requests.exceptions.HTTPError as e:
            logger.warning(f"Failed to fetch metadata for '{repository_name}': HTTP {e.response.status_code}")
            return {}
        except requests.exceptions.RequestException as e:
            logger.warning(f"Failed to fetch metadata for '{repository_name}': {e}")
            return {}

    def convert_to_focus(self, usage_item: Dict, billing_start: datetime, billing_end: datetime) -> Dict:
        """
        Convert GitHub usage item to Datadog Custom Costs (FOCUS) format.

        Args:
            usage_item: GitHub API usage item
            billing_start: Charge period start date
            billing_end: Charge period end date

        Returns:
            Cost record in FOCUS format
        """
        # Format timestamps in YYYY-MM-DD format (Datadog requirement)
        charge_period_start = billing_start.strftime("%Y-%m-%d")
        charge_period_end = billing_end.strftime("%Y-%m-%d")

        # Extract fields from GitHub API
        product = usage_item.get("product", "Unknown")
        sku = usage_item.get("sku", "Unknown")
        repository = usage_item.get("repositoryName", "")
        quantity = usage_item.get("quantity", 0)
        unit_type = usage_item.get("unitType", "")
        price_per_unit = usage_item.get("pricePerUnit", 0)
        net_amount = usage_item.get("netAmount", 0)

        # Calculate cost
        billed_cost = Decimal(str(quantity)) * Decimal(str(price_per_unit))

        # Build FOCUS record
        focus_record = {
            "ProviderName": "GitHub",
            "ChargeDescription": product,
            "ChargePeriodStart": charge_period_start,
            "ChargePeriodEnd": charge_period_end,
            "BilledCost": float(billed_cost),
            "BillingCurrency": "USD",
            "Tags": {}
        }

        # Add tags for cost attribution
        tags = focus_record["Tags"]
        tags["sku"] = sku

        if repository:
            tags["repository"] = repository

            # Try to determine service:
            # 1. Check for service-* topic (override)
            # 2. Default to repository name
            service = repository  # Default

            # Fetch repo metadata to check for service topic
            # GitHub topics use format: service-<name> (lowercase, hyphens only)
            repo_metadata = self.get_repository_metadata(repository)
            topics = repo_metadata.get("topics", [])

            for topic in topics:
                if topic.startswith("service-"):
                    service = topic[8:]  # Remove "service-" prefix
                    break

            tags["service"] = service
        if unit_type:
            tags["unit_type"] = unit_type
        if quantity:
            tags["quantity"] = str(quantity)
        if price_per_unit:
            tags["unit_price"] = str(price_per_unit)
        if net_amount:
            tags["net_amount"] = str(net_amount)

        return focus_record


def main():
    """Main entry point for GitHub cost data generation."""
    parser = argparse.ArgumentParser(
        description='Fetch GitHub billing data and upload to Datadog Cloud Cost Management',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Dry run - fetch and calculate costs without uploading (recommended for testing)
  python github_costs.py --date 2025-12-22 --dry-run

  # Fetch yesterday's data (default - captures complete 24-hour period)
  python github_costs.py

  # Fetch data for a specific date
  python github_costs.py --date 2025-12-22

  # Fetch data for entire month
  python github_costs.py --year 2025 --month 12
        '''
    )

    parser.add_argument('--date', type=str, help='Date to fetch in YYYY-MM-DD format')
    parser.add_argument('--year', type=int, help='Year to fetch')
    parser.add_argument('--month', type=int, help='Month to fetch (1-12)')
    parser.add_argument('--day', type=int, help='Day to fetch (1-31)')
    parser.add_argument('--dry-run', action='store_true',
                       help='Fetch and calculate costs without uploading to Datadog')

    args = parser.parse_args()

    try:
        # Initialize fetcher
        fetcher = GitHubCostFetcher()

        # Initialize uploader (only needed for non-dry-run)
        if not args.dry_run:
            uploader = DatadogCostUploader()

        # Determine date to fetch
        if args.date:
            target_date = datetime.strptime(args.date, '%Y-%m-%d')
            year = target_date.year
            month = target_date.month
            day = target_date.day
        elif args.year:
            year = args.year
            month = args.month
            day = args.day
        else:
            # Default to yesterday (to capture complete 24-hour period)
            yesterday = datetime.now() - timedelta(days=1)
            year = yesterday.year
            month = yesterday.month
            day = yesterday.day

        # Fetch billing data from GitHub
        usage_data = fetcher.fetch_billing_data(year=year, month=month, day=day)

        if not usage_data:
            logger.warning("No billing data found for the specified date")
            return

        # Set charge period (same date for both start and end to prevent spreading)
        if day:
            billing_start = datetime(year, month, day)
            billing_end = datetime(year, month, day)
        elif month:
            billing_start = datetime(year, month, 1)
            billing_end = datetime(year, month, 1)
        else:
            billing_start = datetime(year, 1, 1)
            billing_end = datetime(year, 1, 1)

        # Convert to FOCUS format
        focus_data = [
            fetcher.convert_to_focus(item, billing_start, billing_end)
            for item in usage_data
        ]

        logger.info(f"Converted {len(focus_data)} GitHub usage items to FOCUS format")

        # Handle dry-run mode
        if args.dry_run:
            logger.info("DRY RUN MODE - Not uploading to Datadog")
            print("\n" + "="*80)
            print("FOCUS COST RECORDS (would be uploaded to Datadog):")
            print("="*80)
            print(json.dumps(focus_data, indent=2))
            print("="*80)

            total_cost = sum(record["BilledCost"] for record in focus_data)
            print(f"\nTotal cost: ${total_cost:.4f}")
            print(f"FOCUS records generated: {len(focus_data)}")
            print(f"Usage items processed: {len(usage_data)}")
            logger.info("Dry run completed successfully")
            sys.exit(0)

        # Upload to Datadog
        success = uploader.upload_costs(focus_data, provider_name="GitHub")

        if success:
            logger.info("GitHub cost data successfully uploaded to Datadog")
            sys.exit(0)
        else:
            logger.error("Failed to upload GitHub cost data to Datadog")
            sys.exit(1)

    except Exception as e:
        logger.error(f"GitHub cost processing failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
