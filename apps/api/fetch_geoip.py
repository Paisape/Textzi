"""Downloads the free DB-IP "IP to Country Lite" database (CC BY 4.0, no account needed) at image
build time for services.country_for_ip. Never fails the build: without the file, country lookups
return None and the CF-IPCountry header is used instead."""
import gzip
import os
import shutil
import sys
import urllib.request
from datetime import date

DEST = "/app/geoip/dbip-country-lite.mmdb"


def candidate_urls():
    today = date.today()
    last_month = date(today.year - (today.month == 1), (today.month - 2) % 12 + 1, 1)
    for d in (today, last_month):  # a new month's file can lag the 1st
        yield f"https://download.db-ip.com/free/dbip-country-lite-{d.year}-{d.month:02d}.mmdb.gz"


def main() -> None:
    os.makedirs(os.path.dirname(DEST), exist_ok=True)
    for url in candidate_urls():
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "textzi-build/1.0"})  # urllib's default agent gets a 403
            with urllib.request.urlopen(request, timeout=60) as response, gzip.GzipFile(fileobj=response) as src, open(DEST, "wb") as out:
                shutil.copyfileobj(src, out)
            if os.path.getsize(DEST) > 1_000_000:
                print(f"geoip: downloaded {url}")
                return
        except OSError as exc:
            print(f"geoip: {url} failed: {exc}", file=sys.stderr)
    if os.path.exists(DEST):
        os.remove(DEST)
    print("geoip: database not downloaded; country lookups will use CF-IPCountry only", file=sys.stderr)


main()
