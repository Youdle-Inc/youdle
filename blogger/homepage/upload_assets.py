#!/usr/bin/env python3
"""Upload the homepage images to Supabase Storage and record their URLs.

    python blogger/homepage/upload_assets.py --dry-run   # show what would happen
    python blogger/homepage/upload_assets.py             # upload
    python blogger/homepage/upload_assets.py --write-config
    python blogger/homepage/upload_assets.py --file hero /path/to/real-photo.webp

Why this exists: Blogger cannot host theme assets, so the five static images
need absolute public URLs baked into the theme. Putting them in git does NOT
host them -- the repo is source control, not a web server.

Two properties this deliberately gets right, both different from
supabase_storage.upload_image():

  * Fixed paths, no timestamp. The public URL for a Supabase object is derived
    from its path, so a stable path means a stable URL. You can replace the
    photography later by re-uploading to the same path and the live theme picks
    it up with no rebuild and no re-upload to Blogger.
  * upsert. Supabase's upload() returns 409 on an existing path rather than
    replacing it, so a plain re-run of a timestamp-free upload would fail.

Credentials come from the same env vars the rest of the repo uses:
SUPABASE_URL plus SUPABASE_SERVICE_ROLE_KEY (or the legacy SUPABASE_KEY).
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO))

ASSETS = HERE / "assets" / "img"
CONFIG = HERE / "src" / "config.json"

BUCKET = "blog-images"
FOLDER = "homepage"

# Which local file backs which config key. The remote name is fixed on purpose:
# the URL must not change when the picture does.
SLOTS = {
    "hero": ("hero-tote.webp", ("images", "hero")),
    "grocery": ("grocery-visual.webp", ("images", "grocery")),
    "community-1": ("community-1.webp", ("community_posts", "one", "image")),
    "community-2": ("community-2.webp", ("community_posts", "two", "image")),
    "community-3": ("community-3.webp", ("community_posts", "three", "image")),
}


def public_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/storage/v1/object/public/{BUCKET}/{path}"


def set_in(data: dict, keys: tuple, value: str) -> None:
    node = data
    for key in keys[:-1]:
        node = node[key]
    node[keys[-1]] = value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true",
                        help="print the plan and the resulting URLs, upload nothing")
    parser.add_argument("--write-config", action="store_true",
                        help="write the URLs into src/config.json when done")
    parser.add_argument("--file", nargs=2, metavar=("SLOT", "PATH"), action="append",
                        default=[], help="override one slot with a different local "
                                         "file, e.g. --file hero ~/photos/tote.webp")
    parser.add_argument("--slot", action="append", default=[],
                        help="only upload these slots (default: all)")
    args = parser.parse_args()

    overrides = {}
    for slot, path in args.file:
        if slot not in SLOTS:
            raise SystemExit(f"ERROR: unknown slot {slot!r}. Known: {', '.join(SLOTS)}")
        source = Path(path).expanduser()
        if not source.is_file():
            raise SystemExit(f"ERROR: not a file: {source}")
        overrides[slot] = source

    wanted = args.slot or list(SLOTS)
    for slot in wanted:
        if slot not in SLOTS:
            raise SystemExit(f"ERROR: unknown slot {slot!r}. Known: {', '.join(SLOTS)}")

    # Build the plan before touching the network, so --dry-run is honest.
    plan = []
    for slot in wanted:
        remote_name, config_keys = SLOTS[slot]
        source = overrides.get(slot, ASSETS / remote_name)
        if not source.is_file():
            raise SystemExit(f"ERROR: missing local file for {slot}: {source}")
        # Keep the remote extension honest if a different format was supplied.
        remote = f"{FOLDER}/{Path(remote_name).stem}{source.suffix.lower()}"
        content_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        plan.append((slot, source, remote, content_type, config_keys))

    # Load .env up front so even --dry-run prints the real URLs.
    try:
        from dotenv import load_dotenv

        load_dotenv(REPO / ".env")
    except ImportError:
        pass  # the env may already be exported

    base_url = os.getenv("SUPABASE_URL", "")
    if not base_url and not args.dry_run:
        raise SystemExit(
            "ERROR: SUPABASE_URL is not set, and .env was not read."
            + chr(10) +
            "       Run it with the project venv, which has python-dotenv:"
            + chr(10) +
            "           .venv/Scripts/python blogger/homepage/upload_assets.py"
        )

    print(f"\n  bucket: {BUCKET}/{FOLDER}/    ({len(plan)} file(s))\n")
    for slot, source, remote, content_type, _ in plan:
        size = source.stat().st_size
        print(f"    {slot:13s} {source.name:22s} {size:>8,} B  {content_type}")
        print(f"    {'':13s} -> {public_url(base_url or 'https://<project>.supabase.co', remote)}")

    if args.dry_run:
        print("\n  dry run - nothing uploaded.\n")
        return

    venv_hint = (
        "       Run it with the project venv, which has the dependencies:\n"
        "           .venv/Scripts/python blogger/homepage/upload_assets.py"
    )

    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    if not base_url or not key:
        raise SystemExit(
            "ERROR: need SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_KEY).\n"
            "       They are in the repo's .env, but reading it needs python-dotenv.\n"
            + venv_hint
        )

    try:
        from supabase import create_client
    except ImportError:
        raise SystemExit("ERROR: the supabase package is missing.\n" + venv_hint)

    client = create_client(base_url, key)
    store = client.storage.from_(BUCKET)

    print()
    results = {}
    for slot, source, remote, content_type, config_keys in plan:
        try:
            store.upload(
                path=remote,
                file=source.read_bytes(),
                # upsert so re-running replaces in place instead of 409-ing.
                file_options={"content-type": content_type,
                              "cache-control": "31536000",
                              "upsert": "true"},
            )
        except Exception as exc:  # noqa: BLE001 - report and keep going
            print(f"    FAILED  {slot:13s} {exc}")
            continue
        url = public_url(base_url, remote)
        results[slot] = (url, config_keys)
        print(f"    ok      {slot:13s} {url}")

    if not results:
        raise SystemExit("\n  nothing uploaded.\n")

    if args.write_config:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        for url, config_keys in results.values():
            set_in(cfg, config_keys, url)
        CONFIG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n",
                          encoding="utf-8")
        print(f"\n  wrote {len(results)} URL(s) into {CONFIG.relative_to(REPO)}")
        print("  next: python blogger/homepage/build_theme.py")
    else:
        print("\n  Paste these into blogger/homepage/src/config.json, then rebuild:")
        for slot, (url, config_keys) in results.items():
            print(f'    {".".join(config_keys)}: "{url}"')
        print("\n  Or re-run with --write-config to do it automatically.")
    print()


if __name__ == "__main__":
    main()
