"""Enrichment tools: a company profile from an external vendor and a partner webhook."""
import requests
import yaml

from secrets_loader import vendor_key

with open("config.yaml", encoding="utf-8") as fh:
    CFG = yaml.safe_load(fh)


def lookup_company(tax_code: str) -> dict:
    """Look up a company profile at the vendor by tax code."""
    resp = requests.get(
        f"{CFG['vendor']['base_url']}/companies/{tax_code}",
        headers={"X-Api-Key": vendor_key()},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def notify_partner(customer_id: str, ho_ten: str, message: str) -> dict:
    """Send a notice about a customer to the partner webhook."""
    resp = requests.post(
        CFG["vendor"]["webhook"],
        json={"customer": customer_id, "name": ho_ten, "text": message},
        timeout=10,
    )
    return {"sent": resp.ok}
