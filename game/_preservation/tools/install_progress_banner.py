"""Install a maintainer-authorized custom offline-progress banner into the game's local cache.

The PC client reads its offline-progress banner from the local CDN cache
(game/storage/cache/banner/offline_progress.png), so installing custom art is a plain file
replacement -- the game must be closed, or the copy races the running client. This tool never
edits the image: it validates the source and copies it byte-for-byte.

Validation happens entirely before any write; an invalid source or an open game process aborts
with nothing touched:
  - the source must exist and be a PNG (89 50 4E 47 0D 0A 1A 0A signature);
  - its first chunk must be IHDR with square dimensions (width == height > 0; the generated
    1254x1254 source passes);
  - the game process (default "KOF ALLSTAR.exe", Windows tasklist) must not be running;
  - the destination directory must exist.

With everything valid: the current banner, if present, is backed up to a unique
offline_progress.png.bak-<timestamp> in a separate banner-backups folder (a collision appends
-1, -2, ... -- an existing
backup is never overwritten), then the source is copied to a temporary file in the destination
directory and moved into place with os.replace (atomic on the same volume). kofallstar.prefs,
options.json, saves and every *.orig stay untouched; the source file is only ever read.

usage: install_progress_banner.py --source <png> [--dest <file>] [--process <name>]
"""
import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DEST = os.path.join(HERE, "..", "..", "storage", "cache", "banner", "offline_progress.png")
DEFAULT_PROCESS = "KOF ALLSTAR.exe"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def png_size(data):
    """(width, height) from the IHDR chunk, or None when `data` is not a PNG with IHDR first."""
    if len(data) < 24 or data[:8] != PNG_SIGNATURE or data[12:16] != b"IHDR":
        return None
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def process_running(name):
    """True when Windows tasklist shows a process image called `name` (case-insensitive)."""
    listing = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True)
    if listing.returncode:
        sys.exit("could not verify whether the game process is running")
    return name.lower() in listing.stdout.decode("utf-8", "replace").lower()


def unique_backup_path(dest):
    """`dest.bak-<timestamp>`, suffixed -1, -2, ... on collision -- never an existing file."""
    directory = os.path.abspath(os.path.dirname(dest)) + "-backups"
    stem = os.path.join(directory, f"{os.path.basename(dest)}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
    candidate, attempt = stem, 0
    while os.path.exists(candidate):
        attempt += 1
        candidate = f"{stem}-{attempt}"
    return candidate


def install(source, dest, process):
    """Validate everything, back up the current banner, then atomically install `source`."""
    if not os.path.isfile(source):
        sys.exit(f"source not found: {source}")
    data = open(source, "rb").read()
    size = png_size(data)
    if size is None:
        sys.exit(f"source is not a PNG (signature or leading IHDR chunk invalid): {source}")
    width, height = size
    if width != height or width <= 0:
        sys.exit(f"source PNG must have square dimensions, got {width}x{height}: {source}")
    if process_running(process):
        sys.exit(f"refusing to write while the game process is running: {process}")
    directory = os.path.dirname(os.path.abspath(dest))
    if not os.path.isdir(directory):
        sys.exit(f"destination directory not found: {directory}")

    backup = None
    if os.path.exists(dest):
        backup = unique_backup_path(dest)
        os.makedirs(os.path.dirname(backup), exist_ok=True)
        shutil.copyfile(dest, backup)
    tmp = f"{dest}.tmp-{os.getpid()}"
    try:
        with open(tmp, "wb") as output:
            output.write(data)
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    installed = hashlib.sha256(open(dest, "rb").read()).hexdigest()
    print(f"installed {width}x{height} PNG ({len(data)} bytes) -> {os.path.abspath(dest)}")
    if backup:
        print(f"previous banner backed up -> {backup}")
    print(f"sha256 source   {hashlib.sha256(data).hexdigest()}")
    print(f"sha256 installed {installed}")
    if hashlib.sha256(data).hexdigest() != installed:
        sys.exit("installed file does not match the source byte-for-byte")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", required=True, help="custom banner PNG to install")
    parser.add_argument("--dest", default=DEFAULT_DEST, help=f"banner path (default: {DEFAULT_DEST})")
    parser.add_argument("--process", default=DEFAULT_PROCESS,
                        help=f"game process image to refuse running against (default: {DEFAULT_PROCESS})")
    args = parser.parse_args()
    install(args.source, args.dest, args.process)


if __name__ == "__main__":
    main()
