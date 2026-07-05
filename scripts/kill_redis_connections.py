#!/usr/bin/env python3
"""Emergency script to kill leaked Redis client connections.

Use this when Redis connection leaks have exhausted the connection limit.
It connects via REDIS_URL, enumerates CLIENT LIST, and kills every client
except its own. On Redis versions that expose the `type` field, only
`normal` (non-pub/sub) connections are killed.

Example:
    REDIS_URL=redis://localhost:6379/0 python scripts/kill_redis_connections.py
"""

import os

import redis


def main() -> None:
    url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    client = redis.from_url(url, decode_responses=True)

    try:
        own_id = client.execute_command("CLIENT ID")
        clients = client.execute_command("CLIENT LIST")

        killed = 0
        skipped_type = 0
        for info in clients:
            if not isinstance(info, dict):
                continue

            # Redis versions differ in whether CLIENT LIST includes a `type`
            # field. If present, skip pub/sub clients so we don't tear down
            # active subscriptions; otherwise fall back to killing everything
            # except our own connection (emergency mode).
            ctype = info.get("type")
            if ctype is not None and ctype != "normal":
                skipped_type += 1
                continue

            cid = info.get("id")
            if not cid or str(cid) == str(own_id):
                continue

            try:
                client.execute_command("CLIENT KILL", "ID", cid)
                killed += 1
            except Exception as exc:  # noqa: BLE001
                print(f"Failed to kill client {cid}: {exc}")

        suffix = ""
        if skipped_type:
            suffix = f" (skipped {skipped_type} pub/sub connection(s))"
        print(f"Killed {killed} connection(s) (skipped own ID {own_id}){suffix}.")
    finally:
        client.close()


if __name__ == "__main__":
    main()
