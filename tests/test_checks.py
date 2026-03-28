"""Tests for the parity-zero deterministic checks.

Validates:
  - CORS wildcard detection (positive and negative)
  - Debug mode detection (positive and negative)
  - Security disablement detection (positive and negative)
  - Finding schema compliance
"""

import pytest

from schemas.findings import Category, Confidence, Finding, Severity
from reviewer.checks import (
    run_deterministic_checks,
    _check_cors_wildcard,
    _check_debug_mode,
    _check_security_disablement,
    _check_secrets,
)


# ---------------------------------------------------------------------------
# CORS wildcard detection
# ---------------------------------------------------------------------------

class TestCorsWildcard:
    def test_detects_allow_origins_wildcard(self):
        content = 'app.add_middleware(CORSMiddleware, allow_origins=["*"])\n'
        findings = _check_cors_wildcard("server.py", content)
        assert len(findings) == 1
        assert findings[0].category == Category.INSECURE_CONFIGURATION
        assert findings[0].severity == Severity.MEDIUM

    def test_detects_cors_allow_all_true(self):
        content = "CORS_ALLOW_ALL = True\n"
        findings = _check_cors_wildcard("settings.py", content)
        assert len(findings) == 1

    def test_detects_cors_origin_allow_all(self):
        content = "CORS_ORIGIN_ALLOW_ALL = True\n"
        findings = _check_cors_wildcard("settings.py", content)
        assert len(findings) == 1

    def test_detects_access_control_header(self):
        content = "Access-Control-Allow-Origin: *\n"
        findings = _check_cors_wildcard("config.yaml", content)
        assert len(findings) == 1

    def test_no_finding_for_specific_origin(self):
        content = 'allow_origins=["https://example.com"]\n'
        findings = _check_cors_wildcard("server.py", content)
        assert findings == []

    def test_no_finding_for_clean_file(self):
        content = "APP_NAME = 'my-app'\nPORT = 8080\n"
        findings = _check_cors_wildcard("config.py", content)
        assert findings == []

    def test_correct_line_number(self):
        content = "line1\nline2\nallow_origins=[\"*\"]\nline4\n"
        findings = _check_cors_wildcard("server.py", content)
        assert len(findings) == 1
        assert findings[0].start_line == 3


# ---------------------------------------------------------------------------
# Debug mode detection
# ---------------------------------------------------------------------------

class TestDebugMode:
    def test_detects_debug_true_uppercase(self):
        content = "DEBUG = True\n"
        findings = _check_debug_mode("settings.py", content)
        assert len(findings) == 1
        assert findings[0].severity == Severity.LOW

    def test_detects_debug_true_lowercase(self):
        content = "debug = True\n"
        findings = _check_debug_mode("config.py", content)
        assert len(findings) == 1

    def test_detects_yaml_debug_true(self):
        content = "debug: true\n"
        findings = _check_debug_mode("config.yaml", content)
        assert len(findings) == 1

    def test_no_finding_for_debug_false(self):
        content = "DEBUG = False\n"
        findings = _check_debug_mode("settings.py", content)
        assert findings == []

    def test_no_finding_for_clean_code(self):
        content = "app = FastAPI()\nresult = process()\n"
        findings = _check_debug_mode("main.py", content)
        assert findings == []

    def test_no_false_positive_on_substring(self):
        """Should not match 'DEBUGGER' or 'debug_mode'."""
        content = "DEBUGGER = True\n"
        findings = _check_debug_mode("settings.py", content)
        assert findings == []


# ---------------------------------------------------------------------------
# Security disablement detection
# ---------------------------------------------------------------------------

class TestSecurityDisablement:
    def test_detects_verify_ssl_false(self):
        content = "VERIFY_SSL = False\n"
        findings = _check_security_disablement("config.py", content)
        assert len(findings) == 1
        assert findings[0].severity == Severity.HIGH
        assert "SSL" in findings[0].title

    def test_detects_verify_false(self):
        content = "verify = False\n"
        findings = _check_security_disablement("http_client.py", content)
        assert len(findings) == 1

    def test_detects_csrf_enabled_false(self):
        content = "CSRF_ENABLED = False\n"
        findings = _check_security_disablement("settings.py", content)
        assert len(findings) == 1
        assert "CSRF" in findings[0].title

    def test_detects_wtf_csrf_false(self):
        content = "WTF_CSRF_ENABLED = False\n"
        findings = _check_security_disablement("flask_config.py", content)
        assert len(findings) == 1

    def test_no_finding_for_verify_true(self):
        content = "VERIFY_SSL = True\n"
        findings = _check_security_disablement("config.py", content)
        assert findings == []

    def test_no_finding_for_csrf_enabled(self):
        content = "CSRF_ENABLED = True\n"
        findings = _check_security_disablement("settings.py", content)
        assert findings == []

    def test_no_finding_for_clean_file(self):
        content = "TIMEOUT = 30\nRETRIES = 3\n"
        findings = _check_security_disablement("config.py", content)
        assert findings == []


# ---------------------------------------------------------------------------
# Secrets detection
# ---------------------------------------------------------------------------

class TestSecretsDetection:
    """Validate hardcoded secret detection — positive and negative cases."""

    # -- AWS access key ID --

    def test_detects_aws_access_key_id(self):
        content = "AWS_ACCESS_KEY_ID = 'AKIAIOSFODNN7EXAMPLE'\n"
        findings = _check_secrets("config.py", content)
        assert len(findings) == 1
        assert findings[0].category == Category.SECRETS
        assert findings[0].severity == Severity.HIGH
        assert findings[0].confidence == Confidence.HIGH
        assert "AWS" in findings[0].title

    def test_detects_aws_key_inline(self):
        content = 'client = boto3.client("s3", aws_access_key_id="AKIAI44QH8DHBEXAMPLE")\n'
        findings = _check_secrets("deploy.py", content)
        assert len(findings) == 1

    def test_no_finding_for_non_akia_prefix(self):
        """Should not flag non-AKIA strings that happen to be 20 chars."""
        content = "SOME_ID = 'ABCDEFGHIJKLMNOPQRST'\n"
        findings = _check_secrets("config.py", content)
        assert findings == []

    def test_no_finding_for_partial_akia(self):
        """AKIA prefix alone is not enough — needs 16 uppercase chars after."""
        content = "KEY = 'AKIA_short'\n"
        findings = _check_secrets("config.py", content)
        assert findings == []

    # -- Private key headers --

    def test_detects_rsa_private_key(self):
        content = "-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n-----END RSA PRIVATE KEY-----\n"
        findings = _check_secrets("key.pem", content)
        assert len(findings) == 1
        assert "private key" in findings[0].title.lower()

    def test_detects_generic_private_key(self):
        content = "-----BEGIN PRIVATE KEY-----\nMIIE...\n"
        findings = _check_secrets("cert.pem", content)
        assert len(findings) == 1

    def test_detects_ec_private_key(self):
        content = "-----BEGIN EC PRIVATE KEY-----\ndata\n"
        findings = _check_secrets("ec.pem", content)
        assert len(findings) == 1

    def test_detects_openssh_private_key(self):
        content = "-----BEGIN OPENSSH PRIVATE KEY-----\nb3Bl...\n"
        findings = _check_secrets("id_ed25519", content)
        assert len(findings) == 1

    def test_no_finding_for_public_key(self):
        content = "-----BEGIN PUBLIC KEY-----\nMIIB...\n"
        findings = _check_secrets("pub.pem", content)
        assert findings == []

    def test_no_finding_for_certificate(self):
        content = "-----BEGIN CERTIFICATE-----\nMIID...\n"
        findings = _check_secrets("cert.crt", content)
        assert findings == []

    # -- GitHub tokens --

    def test_detects_github_personal_access_token(self):
        content = "GITHUB_TOKEN = 'ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij'\n"
        findings = _check_secrets("ci.py", content)
        assert len(findings) == 1
        assert "GitHub" in findings[0].title

    def test_detects_github_app_token(self):
        content = "token = 'ghs_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij'\n"
        findings = _check_secrets("auth.py", content)
        assert len(findings) == 1

    def test_no_finding_for_short_gh_prefix(self):
        """Token must have exactly 36 chars after ghp_/ghs_ prefix."""
        content = "token = 'ghp_short'\n"
        findings = _check_secrets("config.py", content)
        assert findings == []

    def test_no_finding_for_gho_prefix(self):
        """Only ghp_ and ghs_ prefixes are targeted."""
        content = "token = 'gho_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij'\n"
        findings = _check_secrets("config.py", content)
        assert findings == []

    # -- General negative cases --

    def test_no_finding_for_clean_file(self):
        content = "APP_NAME = 'my-app'\nPORT = 8080\n"
        findings = _check_secrets("config.py", content)
        assert findings == []

    def test_no_finding_for_placeholder_secret(self):
        """Generic placeholder strings should not be flagged."""
        content = "SECRET_KEY = 'change-me'\nAPI_KEY = 'your-key-here'\n"
        findings = _check_secrets("settings.py", content)
        assert findings == []

    def test_correct_line_number(self):
        content = "line1\nline2\nAKIAIOSFODNN7EXAMPLE0\nline4\n"
        findings = _check_secrets("deploy.py", content)
        assert len(findings) == 1
        assert findings[0].start_line == 3

    def test_finding_schema_shape(self):
        """Secrets finding conforms to the Finding schema contract."""
        content = "KEY = 'AKIAIOSFODNN7EXAMPLE'\n"
        findings = _check_secrets("config.py", content)
        assert len(findings) == 1
        data = findings[0].model_dump()
        expected_keys = {
            "id", "category", "severity", "confidence", "title",
            "description", "file", "start_line", "end_line", "recommendation",
        }
        assert set(data.keys()) == expected_keys

    def test_multiple_secrets_in_file(self):
        content = (
            "AWS_KEY = 'AKIAIOSFODNN7EXAMPLE'\n"
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij\n"
        )
        findings = _check_secrets("secrets.py", content)
        assert len(findings) == 3


# ---------------------------------------------------------------------------
# Integration: run_deterministic_checks
# ---------------------------------------------------------------------------

class TestRunDeterministicChecks:
    def test_empty_input_returns_empty(self):
        assert run_deterministic_checks({}) == []

    def test_clean_files_return_empty(self):
        files = {
            "src/app.py": "app = FastAPI()\n",
            "src/models.py": "class User: pass\n",
        }
        assert run_deterministic_checks(files) == []

    def test_insecure_file_produces_findings(self):
        files = {
            "config.py": "DEBUG = True\nVERIFY_SSL = False\n",
        }
        findings = run_deterministic_checks(files)
        assert len(findings) >= 2

    def test_multiple_files_produce_findings(self):
        files = {
            "settings.py": "DEBUG = True\n",
            "server.py": 'allow_origins=["*"]\n',
        }
        findings = run_deterministic_checks(files)
        assert len(findings) == 2

    def test_all_findings_are_insecure_configuration(self):
        files = {
            "config.py": "DEBUG = True\nVERIFY_SSL = False\n",
        }
        for f in run_deterministic_checks(files):
            assert f.category == Category.INSECURE_CONFIGURATION

    def test_secrets_findings_included(self):
        files = {
            "deploy.py": "AWS_KEY = 'AKIAIOSFODNN7EXAMPLE'\n",
        }
        findings = run_deterministic_checks(files)
        assert len(findings) == 1
        assert findings[0].category == Category.SECRETS

    def test_mixed_categories(self):
        files = {
            "config.py": "DEBUG = True\n",
            "deploy.py": "KEY = 'AKIAIOSFODNN7EXAMPLE'\n",
        }
        findings = run_deterministic_checks(files)
        categories = {f.category for f in findings}
        assert Category.INSECURE_CONFIGURATION in categories
        assert Category.SECRETS in categories

    def test_findings_are_valid_finding_objects(self):
        files = {"config.py": "CSRF_ENABLED = False\n"}
        findings = run_deterministic_checks(files)
        assert len(findings) == 1
        f = findings[0]
        assert isinstance(f, Finding)
        assert f.id
        assert f.title
        assert f.description
        assert f.file == "config.py"
        assert f.start_line >= 1
        assert f.recommendation

    def test_finding_schema_shape(self):
        """Finding from checks conforms to the schema contract shape."""
        files = {"settings.py": "DEBUG = True\n"}
        findings = run_deterministic_checks(files)
        data = findings[0].model_dump()
        expected_keys = {
            "id", "category", "severity", "confidence", "title",
            "description", "file", "start_line", "end_line", "recommendation",
        }
        assert set(data.keys()) == expected_keys
