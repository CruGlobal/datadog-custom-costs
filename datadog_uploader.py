"""
Shared module for uploading cost data to Datadog Cloud Cost Management.

This module provides functionality to upload FOCUS-compliant cost data
to Datadog's Custom Costs API. It can be used by any SaaS cost provider.
"""

import os
import logging
from typing import List, Dict
import requests
import json

logger = logging.getLogger(__name__)


class DatadogCostUploader:
    """Upload cost data to Datadog Custom Costs API."""

    def __init__(self, api_key: str = None, app_key: str = None):
        """
        Initialize uploader with Datadog credentials.

        Args:
            api_key: Datadog API key (falls back to DD_API_KEY env var)
            app_key: Datadog Application key (falls back to DD_APP_KEY env var)
        """
        self.api_key = api_key or os.getenv("DD_API_KEY")
        self.app_key = app_key or os.getenv("DD_APP_KEY")
        self.api_url = "https://api.datadoghq.com"

        if not self.api_key or not self.app_key:
            logger.warning("Datadog credentials not found. Set DD_API_KEY and DD_APP_KEY environment variables.")

    def upload_costs(self, cost_data: List[Dict], provider_name: str = None) -> bool:
        """
        Upload cost data to Datadog Custom Costs API.

        Args:
            cost_data: List of cost records in FOCUS format
            provider_name: Optional provider name for logging

        Returns:
            bool: True if upload successful, False otherwise
        """
        if not self.api_key or not self.app_key:
            logger.error("Cannot upload: Datadog credentials not configured")
            return False

        if not cost_data:
            logger.warning("No cost data to upload")
            return False

        provider_info = f" from {provider_name}" if provider_name else ""
        logger.info(f"Uploading {len(cost_data)} cost records{provider_info} to Datadog...")

        # Extract date range from cost data for filename
        start_dates = [record.get("ChargePeriodStart") for record in cost_data if record.get("ChargePeriodStart")]
        end_dates = [record.get("ChargePeriodEnd") for record in cost_data if record.get("ChargePeriodEnd")]

        date_range = ""
        if start_dates and end_dates:
            earliest_start = min(start_dates)
            latest_end = max(end_dates)
            if earliest_start == latest_end:
                date_range = f"_{earliest_start}"
            else:
                date_range = f"_{earliest_start}_to_{latest_end}"

        # Create temporary JSON file for upload
        temp_filename = f"{provider_name or 'data'}{date_range}.json"
        logger.info(f"Creating upload file: {temp_filename}")
        try:
            # Write data to temporary file
            with open(temp_filename, 'w') as f:
                json.dump(cost_data, f, indent=2)

            # Upload to Datadog
            url = f"{self.api_url}/api/v2/cost/custom_costs"
            headers = {
                "DD-API-KEY": self.api_key,
                "DD-APPLICATION-KEY": self.app_key
            }

            with open(temp_filename, 'rb') as f:
                files = {'file': (temp_filename, f, 'application/json')}
                response = requests.put(url, headers=headers, files=files)
                response.raise_for_status()

            logger.info(f"Successfully uploaded {len(cost_data)} cost records to Datadog")
            logger.info("Cost data will appear in Datadog Cloud Cost Management within 24-48 hours")
            return True

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                logger.error("Authentication failed. Check your DD_API_KEY.")
            elif e.response.status_code == 403:
                logger.error("Forbidden. Check your DD_APPLICATION_KEY permissions.")
            else:
                logger.error(f"Upload failed with status {e.response.status_code}: {e.response.text}")
            return False

        except requests.exceptions.RequestException as e:
            logger.error(f"Upload request failed: {e}")
            return False

        except Exception as e:
            logger.error(f"Failed to upload costs: {e}")
            return False

        finally:
            # Clean up temporary file
            if os.path.exists(temp_filename):
                os.remove(temp_filename)
                logger.debug(f"Cleaned up temporary file: {temp_filename}")

    def validate_focus_format(self, cost_record: Dict) -> bool:
        """
        Validate a cost record matches FOCUS/Datadog Custom Costs format.

        Required fields per Datadog:
        - ProviderName
        - ChargeDescription
        - ChargePeriodStart (YYYY-MM-DD)
        - ChargePeriodEnd (YYYY-MM-DD)
        - BilledCost
        - BillingCurrency

        Args:
            cost_record: Single cost record to validate

        Returns:
            bool: True if valid, False otherwise
        """
        required_fields = [
            "ProviderName",
            "ChargeDescription",
            "ChargePeriodStart",
            "ChargePeriodEnd",
            "BilledCost",
            "BillingCurrency"
        ]

        for field in required_fields:
            if field not in cost_record:
                logger.error(f"Missing required field: {field}")
                return False

        return True
