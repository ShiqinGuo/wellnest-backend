"""Generate local-only demo credentials without printing them."""

import secrets
from pathlib import Path

path = Path(__file__).resolve().parents[1] / ".env.payments"
if path.exists():
    raise SystemExit(".env.payments already exists; left unchanged")
values = {
    "PAYMENT_DB_PASSWORD": secrets.token_hex(24),
    "WELLNEST_PAYMENT_PROVIDER_KEY": secrets.token_hex(32),
    "WELLNEST_PAYMENT_WEBHOOK_SECRET": secrets.token_hex(32),
}
path.write_text("".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8")
print("Created ignored .env.payments for the isolated local payment stack")
