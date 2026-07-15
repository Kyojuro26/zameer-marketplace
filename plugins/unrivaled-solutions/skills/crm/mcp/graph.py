#!/usr/bin/env python3
"""Microsoft Graph write layer for the Unrivaled CRM MCP (Phase 5).

Gate passed 2026-07-02 (graph_write_spike.py green on the sandbox tenant):
Contacts.ReadWrite + MailboxSettings.ReadWrite + Mail.ReadWrite.

Guardrails (crm-hybrid-build-plan.md Phase 5):
- DRAFTS ONLY — nothing here can send mail.
- NEVER DELETE — this module has no delete operation at all.
- Idempotent upserts: contacts keyed by email (PATCH if found, POST if not);
  categories created only if absent; existing non-CRM categories on a
  contact are preserved, never removed.

Auth: MSAL device-code flow with a persistent token cache file, so the
operator signs in once and silent refresh covers every later call. Establish
the cache with graph_login.py; tools fail with a clear message when no
cached sign-in exists (they never block waiting for a human).

Config: no env vars in production (Claude spawns plugin servers with a
sanitized environment) — GRAPH_CLIENT_ID/GRAPH_TENANT_ID/GRAPH_TOKEN_CACHE
below are a dev-only convenience. Production reads
<store>/.secrets/.graph_config.json and persists the token cache to
<store>/.secrets/.graph_token_cache.json. That subdirectory exists so a
backup that mirrors the whole store (e.g. the daily robocopy into OneDrive)
can exclude it with a single /XD .secrets flag — see the setup docs. v0.1.8
and earlier kept both files at the top of the store, where a "back up the
whole store" task had no way to leave out a live OAuth token; v0.1.9
auto-migrates existing installs into .secrets/ the first time this runs.
The transport is injectable for tests.
"""

import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path


def _launch_log(msg):
    """Append to the shared launch log (same file server.py uses). Never raises."""
    try:
        p = Path(tempfile.gettempdir()) / "unrivaled-crm-launch.log"
        if p.exists() and p.stat().st_size > 262144:
            tail = p.read_text(encoding="utf-8", errors="replace")[-32768:]
            p.write_text(tail, encoding="utf-8")
        with open(p, "a", encoding="utf-8") as _f:
            _f.write(f"{datetime.now(timezone.utc).isoformat()} graph: {msg}\n")
    except Exception:
        pass


def _read_text_tolerant(path):
    """Read a config file written by any Windows tool: utf-8-sig strips a BOM;
    PowerShell Out-File/Set-Content default to UTF-16, so fall back to that."""
    try:
        return Path(path).read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return Path(path).read_text(encoding="utf-16")


SECRETS_DIRNAME = ".secrets"


def _secrets_dir(store_root):
    """Directory for OAuth secrets, kept out of the top-level store folder so
    a whole-store backup can exclude it with one /XD flag."""
    d = Path(store_root) / SECRETS_DIRNAME
    d.mkdir(exist_ok=True)
    return d


def _migrate_legacy_secret(store_root, filename):
    """v0.1.9: secrets moved from <store>/<filename> to <store>/.secrets/<filename>
    so a store-wide backup can exclude the whole directory instead of relying on
    every backup command remembering to name each secret file. One-time, silent,
    non-fatal migration on first launch after upgrading; a brand-new install just
    gets the new location directly. If the move itself fails (e.g. a transient
    Windows lock), fall back to reading the old location for this run rather than
    raising — the file is still safe, just not yet relocated."""
    new_path = _secrets_dir(store_root) / filename
    old_path = Path(store_root) / filename
    if not new_path.exists() and old_path.exists():
        try:
            os.replace(old_path, new_path)
            _launch_log(f"migrated {filename} into .secrets/ (v0.1.9)")
        except OSError as e:
            # Two concurrent Graph calls can both see "not migrated yet" and
            # race here; the loser's os.replace fails because old_path was
            # already moved by the winner, not because of a real lock. Check
            # for that before falling back to the (now-deleted) old path.
            if new_path.exists():
                return new_path
            _launch_log(f"could not migrate {filename} into .secrets/: {e!r}; "
                        f"reading from the old location this run instead")
            return old_path
    return new_path


GRAPH = "https://graph.microsoft.com/v1.0"
SCOPES = [
    "https://graph.microsoft.com/Contacts.ReadWrite",
    "https://graph.microsoft.com/MailboxSettings.ReadWrite",
    "https://graph.microsoft.com/Mail.ReadWrite",
]

# CRM status -> Outlook master-category (name, preset color)
CRM_CATEGORIES = {
    "won": ("CRM: Won", "preset4"),        # green
    "pending": ("CRM: Pending", "preset7"),  # amber
    "lost": ("CRM: Lost", "preset0"),      # red
}


class GraphError(Exception):
    pass


class GraphAuth:
    """Silent-first MSAL auth backed by a file token cache."""

    def __init__(self, client_id, tenant_id, cache_path):
        import msal
        self.cache_path = Path(cache_path)
        self.cache = msal.SerializableTokenCache()
        if self.cache_path.exists():
            try:
                self.cache.deserialize(
                    self.cache_path.read_text(encoding="utf-8-sig"))
            except Exception as ex:
                # A truncated/corrupt cache must degrade to "sign in again",
                # not crash the tool call with a raw ValueError.
                _launch_log(f"token cache unreadable ({ex!r}); starting empty")
        self.app = msal.PublicClientApplication(
            client_id,
            authority=f"https://login.microsoftonline.com/{tenant_id}",
            token_cache=self.cache,
        )

    def _persist(self):
        if not self.cache.has_state_changed:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write + Windows-lock retry, matching Store._write in server.py —
        # this file holds a live OAuth token, so a torn write on a transient
        # OneDrive/AV lock is worse here than for ordinary CRM records.
        fd, tmp = tempfile.mkstemp(dir=self.cache_path.parent, prefix=".~", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(self.cache.serialize())
                f.flush()
                os.fsync(f.fileno())
            last = None
            for delay in (0, 0.15, 0.4, 0.8, 1.5):
                if delay:
                    time.sleep(delay)
                try:
                    os.replace(tmp, self.cache_path)
                    tmp = None
                    break
                except PermissionError as e:
                    last = e
            else:
                raise GraphError(
                    f"could not save the Outlook token cache: the file is "
                    f"locked by another process (OneDrive/backup/antivirus). "
                    f"Sign-in not persisted — retry in a moment. ({last})")
        finally:
            if tmp and os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
        try:
            os.chmod(self.cache_path, 0o600)  # POSIX only; no-op on Windows —
            # real protection on Windows is the .secrets/ backup exclusion,
            # not this permission bit.
        except OSError:
            pass

    def token_silent(self):
        accounts = self.app.get_accounts()
        if accounts:
            result = self.app.acquire_token_silent(SCOPES, account=accounts[0])
            self._persist()
            if result and "access_token" in result:
                return result["access_token"]
        raise GraphError(
            "No cached Outlook sign-in. Run graph_login.py once to sign in; "
            "until then click-to-draft falls back to a compose link.")

    def login_device_flow(self, on_code):
        """Interactive: blocks until the user completes device sign-in.
        on_code(message) receives the 'go to ... enter CODE' instruction."""
        flow = self.app.initiate_device_flow(scopes=SCOPES)
        if "user_code" not in flow:
            raise GraphError(f"device flow failed to start: {flow}")
        on_code(flow["message"])
        result = self.app.acquire_token_by_device_flow(flow)
        self._persist()
        if "access_token" not in result:
            raise GraphError(result.get("error_description", str(result)))
        return result["access_token"]


class GraphClient:
    """Thin, guard-railed wrapper over the handful of Graph writes the CRM
    needs. `http` is any requests-compatible session (injectable for tests);
    `token_provider` is a zero-arg callable returning a bearer token."""

    def __init__(self, token_provider, http=None):
        if http is None:
            import requests
            http = requests.Session()
        self.http = http
        self.token_provider = token_provider

    def _call(self, method, path, **kw):
        if method.upper() == "DELETE":  # guardrail: physically impossible
            raise GraphError("delete operations are not permitted")
        headers = {"Authorization": f"Bearer {self.token_provider()}",
                   "Content-Type": "application/json"}
        r = self.http.request(method, f"{GRAPH}{path}", headers=headers, **kw)
        if not r.ok:
            raise GraphError(f"{method} {path} -> HTTP {r.status_code}: {r.text[:300]}")
        return r.json() if r.text else {}

    # -- reads used by the writes --
    def me(self):
        return self._call("GET", "/me?$select=userPrincipalName,displayName")

    def find_contact_by_email(self, email):
        e = email.replace("'", "''")
        res = self._call(
            "GET",
            f"/me/contacts?$filter=emailAddresses/any(a:a/address eq '{e}')"
            "&$select=id,displayName,companyName,categories")
        hits = res.get("value", [])
        return hits[0] if hits else None

    def list_categories(self):
        return self._call("GET", "/me/outlook/masterCategories").get("value", [])

    # -- idempotent writes --
    def ensure_category(self, name, color="preset9"):
        """Create the master category only if it doesn't exist."""
        for cat in self.list_categories():
            if cat["displayName"] == name:
                return {"id": cat["id"], "created": False}
        cat = self._call("POST", "/me/outlook/masterCategories",
                         json={"displayName": name, "color": color})
        return {"id": cat["id"], "created": True}

    def upsert_contact(self, *, email, name, company, title=None, phone=None,
                       add_categories=()):
        """PATCH the existing Outlook contact (matched by email) or POST a new
        one. Existing categories are merged, never removed."""
        parts = (name or "").split(" ", 1)
        body = {
            "givenName": parts[0] or email,
            "surname": parts[1] if len(parts) > 1 else "",
            "companyName": company or "",
            "emailAddresses": [{"address": email, "name": name or email}],
        }
        if title:
            body["jobTitle"] = title
        if phone:
            body["businessPhones"] = [phone]
        existing = self.find_contact_by_email(email)
        if existing:
            merged = sorted(set(existing.get("categories") or []) | set(add_categories))
            body["categories"] = merged
            self._call("PATCH", f"/me/contacts/{existing['id']}", json=body)
            return {"id": existing["id"], "op": "patch", "categories": merged}
        body["categories"] = sorted(add_categories)
        c = self._call("POST", "/me/contacts", json=body)
        return {"id": c["id"], "op": "post", "categories": body["categories"]}

    def create_draft(self, *, to_email, to_name=None, subject, body):
        """Create a real DRAFT in the mailbox. Never sends."""
        d = self._call("POST", "/me/messages", json={
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": to_email,
                                               "name": to_name or to_email}}],
        })
        if d.get("isDraft") is False:  # paranoia: refuse anything not a draft
            raise GraphError("Graph returned a non-draft message; aborting")
        return {"id": d["id"], "webLink": d.get("webLink"), "isDraft": True}


def from_env(store_root):
    """Build (auth, client) from env, or raise GraphError with the fallback
    story if Graph isn't configured."""
    client_id = os.environ.get("GRAPH_CLIENT_ID")
    tenant_id = os.environ.get("GRAPH_TENANT_ID")
    if not client_id or not tenant_id:
        # Claude spawns plugin servers with a sanitized env, so env vars never
        # arrive in production. Fall back to a config file in the store's
        # .secrets/ directory (auto-migrated there from the pre-v0.1.9
        # top-level location so a store-wide backup can exclude it).
        _cfg_path = _migrate_legacy_secret(store_root, ".graph_config.json")
        if _cfg_path.exists():
            try:
                _cfg = json.loads(_read_text_tolerant(_cfg_path))
                client_id = client_id or _cfg.get("client_id")
                tenant_id = tenant_id or _cfg.get("tenant_id")
            except Exception as ex:
                _launch_log(f"failed to parse {_cfg_path.name}: {ex!r}")
                raise GraphError(
                    f"Outlook config file {_cfg_path.name} exists but could "
                    f"not be parsed ({type(ex).__name__}). Re-save it as "
                    "plain JSON (UTF-8). Store edits still persist; "
                    "click-to-draft falls back to a compose link.")
    if not client_id or not tenant_id:
        raise GraphError(
            "Outlook writes not configured (set GRAPH_CLIENT_ID / "
            "GRAPH_TENANT_ID, or write client_id/tenant_id into "
            "<store>/.secrets/.graph_config.json). Store edits still "
            "persist; click-to-draft falls back to a compose link.")
    cache = os.environ.get(
        "GRAPH_TOKEN_CACHE",
        str(_migrate_legacy_secret(store_root, ".graph_token_cache.json")))
    auth = GraphAuth(client_id, tenant_id, cache)
    return auth, GraphClient(auth.token_silent)
