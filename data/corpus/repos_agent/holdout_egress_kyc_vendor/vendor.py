"""Client of the outside identity verification vendor."""
import requests
from ratelimit import limits

VENDOR_HOST = "kyc-api.vendor-x.example.com"
ALLOWED_COUNTRIES = {"VN", "KR", "JP", "SG"}


def _key() -> str:
    return dbutils.secrets.get(scope="kyc", key="vendor-token")  # noqa: F821


@limits(calls=10, period=60)
def verify(so_cccd: str, ho_ten: str, ngay_sinh: str, country: str = "VN") -> dict:
    """Send the identity data to the vendor and return its verdict."""
    if country not in ALLOWED_COUNTRIES:
        return {"error": "country not supported"}
    resp = requests.post(
        f"https://{VENDOR_HOST}/v3/verify",
        json={"id": so_cccd, "name": ho_ten, "dob": ngay_sinh, "country": country},
        headers={"Authorization": "Bearer " + _key()},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()
