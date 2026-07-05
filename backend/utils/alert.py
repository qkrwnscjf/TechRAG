import os
import requests
import logging

logger = logging.getLogger(__name__)

def send_slack_alert(url: str, error_message: str):
    """
    Send an error alert to a Slack channel via Webhook.
    Reads SLACK_WEBHOOK_URL from environment variables.
    """
    webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    
    if not webhook_url:
        logger.warning("SLACK_WEBHOOK_URL is not set. Cannot send Slack alert.")
        return

    payload = {
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "🚨 TechDoc Agent Ingestion Error",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Failed URL:*\n{url}"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Error Message:*\n```{error_message}```"
                }
            }
        ]
    }

    try:
        response = requests.post(webhook_url, json=payload, timeout=10)
        if response.status_code != 200:
            logger.error(f"Failed to send Slack alert. Status: {response.status_code}, Response: {response.text}")
        else:
            logger.info("Successfully sent Slack alert.")
    except Exception as e:
        logger.error(f"Exception occurred while sending Slack alert: {e}")
