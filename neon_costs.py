#!/usr/bin/env python3
"""
Neon Database Cost Data Generator

Fetches daily consumption data from Neon API and converts it to FOCUS format
for upload to Datadog Cloud Cost Management.

Supports Neon's new Scale plan (Feb 2026+) with 100% usage-based pricing.
Tracks costs per-project for cost allocation and chargeback.
"""

import os
import sys
import argparse
import calendar
import json
from datetime import datetime, timedelta
from decimal import Decimal
import requests
from typing import Dict, List
import logging

from datadog_uploader import DatadogCostUploader

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Neon Scale Plan Pricing (Feb 2026+)
PRICING = {
    "compute_per_cu_hour": Decimal("0.222"),      # $0.222 per CU-hour
    "storage_per_gb_month": Decimal("0.35"),      # $0.35 per GB-month
    "data_transfer_per_gb": Decimal("0.10"),      # $0.10 per GB (after 100GB free)
    "data_transfer_free_gb": Decimal("100"),      # 100 GB free per month
    "branch_per_month": Decimal("1.50"),          # $1.50 per branch-month
    "instant_restore_per_gb_month": Decimal("0.20"),  # $0.20 per GB-month
}


class NeonCostFetcher:
    """Fetch and convert Neon database consumption data to FOCUS format."""

    def __init__(self, api_key: str = None, org_id: str = None):
        """
        Initialize fetcher with Neon credentials.

        Args:
            api_key: Neon API key (falls back to NEON_API_KEY env var)
            org_id: Neon organization ID (falls back to NEON_ORG_ID env var)
        """
        self.api_key = api_key or os.getenv("NEON_API_KEY")
        self.org_id = org_id or os.getenv("NEON_ORG_ID")

        # Validate credentials
        if not self.api_key:
            logger.error("Neon API key not found. Set NEON_API_KEY environment variable.")
            raise ValueError("Neon API key required. Set NEON_API_KEY environment variable.")

        if not self.org_id:
            logger.error("Neon org ID not found. Set NEON_ORG_ID environment variable.")
            raise ValueError("Neon organization ID required. Set NEON_ORG_ID environment variable.")

        self.base_url = "https://console.neon.tech/api/v2"
        logger.info(f"Initialized Neon cost fetcher for organization: {self.org_id}")

    def fetch_project_metadata(self) -> Dict[str, str]:
        """
        Fetch all projects metadata to get project names.

        Returns:
            Dictionary mapping project_id to project_name
        """
        url = f"{self.base_url}/projects"
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        params = {
            "org_id": self.org_id,
            "limit": 100
        }

        logger.info("Fetching project metadata for names")

        try:
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()

            projects = data.get("projects", [])
            logger.info(f"Metadata API returned {len(projects)} projects")

            # Build lookup map: project_id -> project_name
            project_map = {
                project.get("id"): project.get("name", project.get("id"))
                for project in projects
            }

            logger.info(f"Retrieved metadata for {len(project_map)} projects")
            if projects:
                # Log a sample to see the structure
                sample = projects[0]
                logger.info(f"Sample project structure: id={sample.get('id')}, name={sample.get('name')}")
            return project_map

        except requests.exceptions.HTTPError as e:
            logger.warning(f"Failed to fetch project metadata: {e}")
            return {}
        except requests.exceptions.RequestException as e:
            logger.warning(f"Request failed for project metadata: {e}")
            return {}

    def fetch_projects_with_consumption(self, date: datetime) -> List[Dict]:
        """
        Fetch all projects with their consumption data for a specific date.
        Uses the bulk endpoint that returns all projects and consumption in one call.

        Args:
            date: Date to fetch consumption data for

        Returns:
            List of project dictionaries with embedded consumption data
        """
        # Build date range (full 24-hour period in UTC)
        # For daily granularity: from = start of day, to = start of next day
        from_time = date.replace(hour=0, minute=0, second=0, microsecond=0)
        to_time = (date + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

        url = f"{self.base_url}/consumption_history/projects"
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        all_projects = []
        cursor = None

        logger.info("Fetching projects with consumption data")

        while True:
            params = {
                "limit": 100,
                "from": from_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "to": to_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "granularity": "daily",
                "org_id": self.org_id
            }

            if cursor:
                params["cursor"] = cursor

            try:
                response = requests.get(url, headers=headers, params=params)
                response.raise_for_status()
                data = response.json()

                projects = data.get("projects", [])
                all_projects.extend(projects)

                logger.info(f"Retrieved {len(projects)} projects (total: {len(all_projects)})")

                # Check for pagination
                pagination = data.get("pagination", {})
                cursor = pagination.get("cursor")

                # If no cursor, we've fetched all projects
                if not cursor:
                    break

            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 401:
                    logger.error("Authentication failed. Check your NEON_API_KEY.")
                elif e.response.status_code == 403:
                    logger.error("Forbidden. API key may lack required permissions.")
                raise
            except requests.exceptions.RequestException as e:
                logger.error(f"Request failed: {e}")
                raise

        logger.info(f"Total projects retrieved: {len(all_projects)}")
        return all_projects

    def extract_daily_metrics(self, daily_record: Dict) -> Dict:
        """
        Extract metrics from a single daily consumption record.

        Args:
            daily_record: Single daily consumption record from API

        Returns:
            Dictionary with daily metrics
        """
        return {
            "timeframe_start": daily_record.get("timeframe_start", ""),
            "timeframe_end": daily_record.get("timeframe_end", ""),
            "compute_seconds": daily_record.get("compute_time_seconds", 0),
            "active_seconds": daily_record.get("active_time_seconds", 0),
            "written_bytes": daily_record.get("written_data_bytes", 0),
            "storage_bytes": daily_record.get("synthetic_storage_size_bytes", 0)
        }

    def calculate_daily_costs(self, metrics: Dict, date: datetime) -> Dict:
        """
        Calculate costs from daily metrics using Neon's usage-based pricing.

        Args:
            metrics: Daily metrics (from extract_daily_metrics)
            date: Date for the calculation (used to determine days in month for storage proration)

        Returns:
            Dictionary with calculated daily costs and details
        """
        days_in_month = calendar.monthrange(date.year, date.month)[1]

        # 1. Compute cost - $0.222 per CU-hour
        compute_hours = Decimal(str(metrics["compute_seconds"])) / Decimal("3600")
        compute_cost = compute_hours * PRICING["compute_per_cu_hour"]

        # 2. Storage cost - $0.35 per GB-month, prorated daily
        # storage_bytes is the average for the day
        storage_gb = Decimal(str(metrics["storage_bytes"])) / Decimal("1073741824")
        # Convert to daily cost: (GB * $0.35/GB-month) / days_in_month
        storage_cost = (storage_gb * PRICING["storage_per_gb_month"]) / Decimal(str(days_in_month))

        # 3. Data transfer (egress) - $0.10/GB after 100GB/month
        # Note: Current API doesn't provide egress data separately
        data_transfer_cost = Decimal("0")

        return {
            "compute_cost": float(compute_cost),
            "storage_cost": float(storage_cost),
            "data_transfer_cost": float(data_transfer_cost),
            "compute_hours": float(compute_hours),
            "storage_gb": float(storage_gb),
            "compute_rate": float(PRICING["compute_per_cu_hour"]),
            "storage_rate": float(PRICING["storage_per_gb_month"]),
            "days_in_month": days_in_month
        }

    def convert_to_focus(self, costs: Dict, metrics: Dict, date: datetime, project: Dict = None) -> List[Dict]:
        """
        Convert calculated daily costs to FOCUS format records.

        Args:
            costs: Calculated daily costs dictionary
            metrics: Daily metrics dictionary (for operational context)
            date: Billing date
            project: Optional project dictionary with id, name, etc.

        Returns:
            List of FOCUS-format cost records (1-2 per day, depending on usage)
        """
        charge_date = date.strftime("%Y-%m-%d")
        focus_records = []

        # Build project tags if available
        project_tags = {}
        if project:
            project_id = project.get("id", "unknown")
            project_name = project.get("name", "unknown")

            project_tags["project_id"] = project_id
            project_tags["project_name"] = project_name

            # Parse service and env from project_name (format: <service>-<env>)
            # Split on last hyphen to handle multi-part service names like "game-ops-stage"
            if "-" in project_name:
                parts = project_name.rsplit("-", 1)
                project_tags["service"] = parts[0]
                project_tags["env"] = parts[1]
            else:
                # No hyphen, use whole name as service, env unknown
                project_tags["service"] = project_name
                project_tags["env"] = "unknown"

        # Record 1: Compute cost (only if > 0)
        if costs["compute_cost"] > 0:
            focus_records.append({
                "ProviderName": "Neon",
                "ChargeDescription": "Compute",
                "ChargePeriodStart": charge_date,
                "ChargePeriodEnd": charge_date,
                "BilledCost": costs["compute_cost"],
                "BillingCurrency": "USD",
                "Tags": {
                    **project_tags,
                    "charge_type": "compute",
                    "compute_hours": f"{costs['compute_hours']:.4f}",
                    "rate_per_cu_hour": str(costs["compute_rate"]),
                    "active_seconds": str(metrics["active_seconds"])
                }
            })

        # Record 2: Storage cost (only if > 0)
        if costs["storage_cost"] > 0:
            focus_records.append({
                "ProviderName": "Neon",
                "ChargeDescription": "Storage",
                "ChargePeriodStart": charge_date,
                "ChargePeriodEnd": charge_date,
                "BilledCost": costs["storage_cost"],
                "BillingCurrency": "USD",
                "Tags": {
                    **project_tags,
                    "charge_type": "storage",
                    "storage_gb": f"{costs['storage_gb']:.2f}",
                    "rate_per_gb_month": str(costs["storage_rate"]),
                    "written_bytes": str(metrics["written_bytes"])
                }
            })

        return focus_records


def main():
    """Main entry point for Neon cost data generation."""
    parser = argparse.ArgumentParser(
        description='Fetch Neon database daily consumption data and upload to Datadog Cloud Cost Management',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Dry run - fetch and calculate costs without uploading (recommended for testing)
  python neon_costs.py --date 2026-01-05 --dry-run

  # Fetch yesterday's data (default - captures complete 24-hour period)
  python neon_costs.py

  # Fetch data for a specific date and upload to Datadog
  python neon_costs.py --date 2026-01-05
        '''
    )

    parser.add_argument('--date', type=str, help='Date to fetch in YYYY-MM-DD format')
    parser.add_argument('--dry-run', action='store_true',
                       help='Fetch and calculate costs without uploading to Datadog')

    args = parser.parse_args()

    try:
        # Initialize fetcher
        fetcher = NeonCostFetcher()

        # Initialize uploader (only needed for non-dry-run)
        if not args.dry_run:
            uploader = DatadogCostUploader()

        # Determine target date (default to yesterday)
        if args.date:
            target_date = datetime.strptime(args.date, '%Y-%m-%d')
        else:
            target_date = datetime.now() - timedelta(days=1)

        logger.info(f"Processing Neon costs for {target_date.strftime('%Y-%m-%d')}")

        # Fetch project metadata (names) first
        project_name_map = fetcher.fetch_project_metadata()
        logger.info(f"Project name map contains {len(project_name_map)} entries")
        if project_name_map:
            logger.info(f"Sample project names: {list(project_name_map.items())[:3]}")

        # Fetch all projects with consumption data (single API call)
        projects = fetcher.fetch_projects_with_consumption(target_date)

        if not projects:
            logger.warning("No projects found in organization")
            sys.exit(0)

        # Process each project
        all_focus_records = []
        total_org_cost = Decimal("0")
        projects_with_data = 0

        for project in projects:
            project_id = project.get("project_id")

            # Skip projects not in our organization
            if project_id not in project_name_map:
                logger.debug(f"Skipping project {project_id} - not in organization")
                continue

            # Build project info dict for tagging
            project_info = {
                "id": project_id,
                "name": project_name_map[project_id]
            }

            project_name = project_info["name"]
            logger.info(f"Processing project: {project_name} ({project_id})")

            # Extract periods and consumption data
            periods = project.get("periods", [])
            if not periods:
                # logger.info(f"  No consumption periods for project {project_id}")
                continue

            # Get consumption from first period (should be single daily record)
            consumption = periods[0].get("consumption", [])
            if not consumption:
                # logger.info(f"  No consumption data for project {project_id}")
                continue

            projects_with_data += 1

            # Process the daily record (should be just one record for the day)
            if len(consumption) > 1:
                logger.warning(f"  Expected 1 daily record but got {len(consumption)}, using first")

            daily_record = consumption[0]

            # Extract metrics for the day
            metrics = fetcher.extract_daily_metrics(daily_record)

            # Calculate costs for the day
            costs = fetcher.calculate_daily_costs(metrics, target_date)

            # Track project total
            project_cost = Decimal(str(costs["compute_cost"])) + Decimal(str(costs["storage_cost"]))
            total_org_cost += project_cost

            # Log project metrics
            logger.info(f"  Compute: {costs['compute_hours']:.2f} hours, Storage: {costs['storage_gb']:.2f} GB")
            logger.info(f"  Project cost: ${float(project_cost):.4f}")

            # Convert to FOCUS format (generates 1-2 records per project)
            focus_records = fetcher.convert_to_focus(costs, metrics, target_date, project_info)
            all_focus_records.extend(focus_records)

        logger.info(f"Total organization cost: ${float(total_org_cost):.4f}")
        logger.info(f"Generated {len(all_focus_records)} total FOCUS records across {projects_with_data} projects with data")

        # Handle dry-run mode
        if args.dry_run:
            logger.info("DRY RUN MODE - Not uploading to Datadog")
            print("\n" + "="*80)
            print("FOCUS COST RECORDS (would be uploaded to Datadog):")
            print("="*80)
            print(json.dumps(all_focus_records, indent=2))
            print("="*80)

            total_cost = sum(record["BilledCost"] for record in all_focus_records)
            print(f"\nTotal daily cost: ${total_cost:.4f}")
            print(f"FOCUS records generated: {len(all_focus_records)}")
            print(f"Projects with data: {projects_with_data}")
            print(f"Total projects: {len(projects)}")
            logger.info("Dry run completed successfully")
            sys.exit(0)

        # Upload to Datadog
        success = uploader.upload_costs(all_focus_records, provider_name="Neon")

        if success:
            logger.info("Neon cost data successfully uploaded to Datadog")
            sys.exit(0)
        else:
            logger.error("Failed to upload Neon cost data to Datadog")
            sys.exit(1)

    except Exception as e:
        logger.error(f"Neon cost processing failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
