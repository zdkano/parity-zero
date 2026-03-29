"""Deployment configuration with embedded GitHub token.

Contains a GitHub personal access token used for CI/CD integration.
"""

import os

# GitHub integration
GITHUB_TOKEN = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij"
GITHUB_ORG = "acme-corp"
GITHUB_REPO = "webapp"

# Deployment settings
DEPLOY_ENV = os.getenv("DEPLOY_ENV", "staging")
DEPLOY_REGION = "us-east-1"

# Notification webhook
SLACK_WEBHOOK = "https://hooks.slack.com/services/T00/B00/xxxx"
