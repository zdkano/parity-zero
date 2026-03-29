"""Application session and cookie configuration.

Demonstrates insecure session defaults: debug mode enabled, session
cookie without secure/httponly flags, and overly permissive CORS.
"""

# Application settings
DEBUG = True
TESTING = False
SECRET_KEY = "development-key-change-in-production"

# Session configuration
SESSION_COOKIE_SECURE = False
SESSION_COOKIE_HTTPONLY = False
SESSION_COOKIE_SAMESITE = None
PERMANENT_SESSION_LIFETIME = 86400 * 30  # 30 days

# CORS
CORS_ORIGINS = "*"
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = "*"

# Security headers (all disabled)
CONTENT_SECURITY_POLICY = None
X_FRAME_OPTIONS = None
STRICT_TRANSPORT_SECURITY = None
