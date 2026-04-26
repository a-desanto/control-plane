"""Management CLI for api-gateway API keys.

Usage:
  python -m app.cli create-key --app-id X --caller-type n8n --capabilities a,b --budget-pool default --rate 60
  python -m app.cli revoke-key --key-id X
  python -m app.cli list-keys
"""

import argparse
import asyncio
import os
import sys
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from ulid import ULID

from app.auth.keys import generate_api_key
from app.db.models import ApiKey, Base


def _engine():
    url = os.environ.get(
        "API_GATEWAY_DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/api_gateway",
    )
    return create_async_engine(url, pool_pre_ping=True)


async def _ensure_tables(engine):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def cmd_create_key(args: argparse.Namespace) -> None:
    engine = _engine()
    await _ensure_tables(engine)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    caller_type = args.caller_type
    if caller_type not in ("n8n", "client_app"):
        print(f"error: caller_type must be 'n8n' or 'client_app', got '{caller_type}'", file=sys.stderr)
        sys.exit(1)

    capabilities = [c.strip() for c in args.capabilities.split(",") if c.strip()] if args.capabilities else []
    plaintext, prefix, hashed = generate_api_key()
    key_id = str(ULID())

    async with session_factory() as session:
        row = ApiKey(
            id=key_id,
            app_id=args.app_id,
            caller_type=caller_type,
            key_prefix=prefix,
            key_hash=hashed,
            capabilities=capabilities,
            budget_pool=args.budget_pool or "default",
            rate_limit_per_minute=args.rate,
        )
        session.add(row)
        await session.commit()

    print(f"Key ID:        {key_id}")
    print(f"App ID:        {args.app_id}")
    print(f"Caller type:   {caller_type}")
    print(f"Capabilities:  {capabilities}")
    print(f"Budget pool:   {args.budget_pool or 'default'}")
    print(f"Rate limit:    {args.rate}/min")
    print(f"")
    print(f"API key (shown once — store it now):")
    print(f"  {plaintext}")
    await engine.dispose()


async def cmd_revoke_key(args: argparse.Namespace) -> None:
    engine = _engine()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        row = await session.scalar(select(ApiKey).where(ApiKey.id == args.key_id))
        if row is None:
            print(f"error: key '{args.key_id}' not found", file=sys.stderr)
            sys.exit(1)
        if row.revoked_at is not None:
            print(f"key '{args.key_id}' is already revoked (at {row.revoked_at.isoformat()})")
            await engine.dispose()
            return
        row.revoked_at = datetime.now(UTC)
        await session.commit()

    print(f"Revoked key {args.key_id} (app_id={row.app_id})")
    await engine.dispose()


async def cmd_list_keys(args: argparse.Namespace) -> None:
    engine = _engine()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        result = await session.execute(select(ApiKey).order_by(ApiKey.created_at))
        rows = result.scalars().all()

    if not rows:
        print("No API keys found.")
        await engine.dispose()
        return

    fmt = "{:<26}  {:<20}  {:<12}  {:<10}  {:<8}  {}"
    print(fmt.format("ID", "App ID", "Caller Type", "Prefix", "Rate/min", "Status"))
    print("-" * 100)
    for r in rows:
        status = "REVOKED" if r.revoked_at else "active"
        print(fmt.format(r.id, r.app_id[:20], r.caller_type, r.key_prefix, r.rate_limit_per_minute, status))

    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="api-gateway key management")
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create-key", help="Create a new API key")
    p_create.add_argument("--app-id", required=True)
    p_create.add_argument("--caller-type", required=True, choices=["n8n", "client_app"])
    p_create.add_argument("--capabilities", default="", help="comma-separated list")
    p_create.add_argument("--budget-pool", default="default")
    p_create.add_argument("--rate", type=int, default=60, help="requests per minute")

    p_revoke = sub.add_parser("revoke-key", help="Revoke an API key by ID")
    p_revoke.add_argument("--key-id", required=True)

    sub.add_parser("list-keys", help="List all API keys")

    args = parser.parse_args()

    if args.command == "create-key":
        asyncio.run(cmd_create_key(args))
    elif args.command == "revoke-key":
        asyncio.run(cmd_revoke_key(args))
    elif args.command == "list-keys":
        asyncio.run(cmd_list_keys(args))


if __name__ == "__main__":
    main()
