"""Secret scrubber: planted secrets are removed; only counts are logged.

Secrets are assembled at run time so that this file itself does not trip
tests/test_no_secrets.py."""

from __future__ import annotations

import logging

import pytest

from supervisor.onboard.scrub import Scrubber, scrub_text

HEX32 = "0123456789abcdef" * 2
DAPI = "da" + "pi" + HEX32
AWS_ID = "AK" + "IA" + "ABCDEFGHIJKLMNOP"
AWS_SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
PEM = (
    "-----BEGIN RSA PRI"
    + "VATE KEY-----\nMIIEowIBAAKCAQEAx1\nabc\n-----END RSA PRI"
    + "VATE KEY-----"
)
GH = "gh" + "p_" + "A" * 36
OPENAI = "s" + "k-" + "proj-" + "B" * 30
GCP = "AI" + "za" + "C" * 35
AZ_KEY = "AccountKey=" + "D" * 86 + "=="
AZ_SECRET = "abc" + "8Q~" + "E" * 32
JWT = "eyJ" + "hbGciOiJIUzI1" + "." + "eyJ" + "zdWIiOiIxMjM0" + "." + "SflKxwRJSMeKKF2QT4"
SLACK = "xo" + "xb-" + "1234567890-abcdefghij"

PLANTED = {
    "databricks_token": f'host = "x"\ntoken = "{DAPI}"\n',
    "aws_access_key": f"AWS_ACCESS_KEY_ID={AWS_ID}\n",
    "aws_secret_key": f"aws_secret_access_key = {AWS_SECRET}\n",
    "pem_private_key": PEM + "\n",
    "github_token": f"GH={GH}\n",
    "llm_api_key": f"client = OpenAI(api_key_value={OPENAI})\n",
    "gcp_api_key": f"url = 'https://maps.example.invalid/?k={GCP}'\n",
    "azure_storage_key": f"conn = 'DefaultEndpointsProtocol=https;AccountName=a;{AZ_KEY}'\n",
    "azure_client_secret": f"AZ = {AZ_SECRET}\n",
    "jwt": f"auth: {JWT}\n",
    "slack_token": f"hook {SLACK}\n",
    "url_password": "DB_URL = 'postgresql://admin:Hunter2pass@db.example.invalid:5432/x'\n",
    "assigned_secret": "password = 'S3cr3t-Value!'\n",
    "bearer_token": "headers = {'Authorization': 'Bearer abcdefghijklmnopqrstuvwxyz012345'}\n",
    "basic_auth": "headers = {'Authorization': 'Basic dXNlcjpwYXNzd29yZDEyMw=='}\n",
    "gcp_oauth_token": "creds = ya" + "29." + "a0AfH6SMBx" * 3 + "\n",
    "assigned_secret_unquoted": "db:\n  host: db.example.invalid\n  password: hunter22x\n",
}


@pytest.mark.parametrize(
    "text",
    [
        "api_key: abc123def456\n",
        "client_secret = Zx9-very-secret-value\n",
        "SERVICE_TOKEN: 7f3a9c2e1b\n",
        "[db]\npassword=Pa55word!\n",
    ],
)
def test_unquoted_config_secrets(text: str) -> None:
    res = scrub_text(text)
    assert res.total == 1, (text, res.counts)
    assert "[REDACTED:" in res.text


def test_url_password_with_empty_user() -> None:
    res = scrub_text("REDIS = 'redis://:S3cretPass@cache.example.invalid:6379/0'\n")
    assert res.counts == {"url_password": 1}
    assert "S3cretPass" not in res.text


@pytest.mark.parametrize("kind", sorted(PLANTED))
def test_each_planted_secret_is_removed(kind: str) -> None:
    text = PLANTED[kind]
    res = scrub_text(text)
    assert res.total >= 1, kind
    assert res.counts == {kind: 1}
    assert f"[REDACTED:{kind}]" in res.text
    for secret in (DAPI, AWS_ID, AWS_SECRET, GH, OPENAI, GCP, AZ_SECRET, JWT, SLACK):
        assert secret not in res.text
    assert "Hunter2pass" not in res.text
    assert "S3cr3t-Value!" not in res.text
    assert "MIIEowIBAAKCAQEAx1" not in res.text


def test_all_in_one_file_and_idempotent() -> None:
    text = "".join(PLANTED.values())
    first = scrub_text(text)
    assert first.total >= len(PLANTED)
    again = scrub_text(first.text)
    assert again.total == 0
    assert again.text == first.text


def test_clean_code_is_unchanged() -> None:
    code = (
        "def transfer(args):\n"
        "    amount = args['amount_minor']\n"
        "    token_count: int = 3\n"
        "    password_field = args.get('password')\n"
        "    DATABRICKS_HOST = 'FILL-ME-host'\n"
        "    api_key = 'FILL-ME-key'\n"
        "    api_key = settings.llm_api_key\n"
        "    token: str\n"
        "    secret_ref: ${DB_PASSWORD}\n"
        "    password = os.environ['DB_PASSWORD']\n"
    )
    res = scrub_text(code)
    assert res.total == 0
    assert res.text == code


def test_logs_counts_only(caplog: pytest.LogCaptureFixture) -> None:
    s = Scrubber()
    with caplog.at_level(logging.WARNING, logger="supervisor.onboard.scrub"):
        s.scrub(PLANTED["databricks_token"] + PLANTED["aws_access_key"], source="cfg.py")
    assert s.total == 2
    assert s.summary() == {
        "texts_scrubbed": 1,
        "secrets_redacted": 2,
        "by_kind": {"aws_access_key": 1, "databricks_token": 1},
        "files_with_secrets": 1,
    }
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "databricks_token=1" in joined
    assert DAPI not in joined and AWS_ID not in joined
