#!/usr/bin/env python3
"""One-time interactive Outlook sign-in for the Unrivaled CRM MCP.

Runs the device-code flow and persists the token cache so the MCP's Outlook
tools (draft_email, sync_outlook) work silently afterwards.

    export GRAPH_CLIENT_ID=... GRAPH_TENANT_ID=...
    python3 graph_login.py --store ../store

Sign in with the SANDBOX account during development — never a production
mailbox until delivery.
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import graph  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=os.environ.get("UNRIVALED_CRM_STORE"))
    args = ap.parse_args()
    if not args.store:
        sys.exit("no store: set UNRIVALED_CRM_STORE or pass --store")
    try:
        auth, client = graph.from_env(args.store)
    except graph.GraphError as e:
        sys.exit(str(e))
    auth.login_device_flow(lambda msg: print("\n" + "=" * 70 + f"\n{msg}\n" + "=" * 70))
    me = client.me()
    print(f"\nSigned in as {me.get('userPrincipalName')} ({me.get('displayName')})")
    print(f"Token cache: {auth.cache_path} — Outlook tools are now live.")


if __name__ == "__main__":
    main()
