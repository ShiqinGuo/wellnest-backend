"""Local workerd + simulated Cloudflare Queues + isolated PostgreSQL."""

import json
import os
import subprocess
from pathlib import Path

from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ORIGIN = "http://127.0.0.1:18090"
DB_PORT = 55449


def main():
    values = dict(
        line.split("=", 1)
        for line in (ROOT / ".env.payments").read_text().splitlines()
        if line and not line.startswith("#")
    )
    database_url = (
        f"postgresql://wellnest:{values['PAYMENT_DB_PASSWORD']}@127.0.0.1:{DB_PORT}/wellnest_test"
    )
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["connection_url"] = database_url
    command.upgrade(config, "head")
    variables = {
        "WELLNEST_PAYMENT_PROVIDER_KEY": values["WELLNEST_PAYMENT_PROVIDER_KEY"],
        "WELLNEST_PAYMENT_WEBHOOK_SECRET": values["WELLNEST_PAYMENT_WEBHOOK_SECRET"],
        "WELLNEST_PAYMENT_PUBLIC_URL": LOCAL_ORIGIN,
        "WELLNEST_ORIGIN": "http://127.0.0.1:5174",
        "WELLNEST_SECURE_COOKIES": "false",
    }
    (ROOT / ".dev.vars").write_text(
        "".join(f"{key}={json.dumps(value)}\n" for key, value in variables.items()),
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["CLOUDFLARE_HYPERDRIVE_LOCAL_CONNECTION_STRING_HYPERDRIVE"] = database_url
    raise SystemExit(
        subprocess.call(
            [
                "uv",
                "run",
                "--group",
                "deploy",
                "pywrangler",
                "dev",
                "--port",
                "18090",
                "--test-scheduled",
            ],
            cwd=ROOT,
            env=environment,
        )
    )


if __name__ == "__main__":
    main()
