#!/bin/sh
set -e

# uploads_data is a named Docker volume that outlives any single image build -- every deploy
# before this one ran as root, so its existing content (invoices, DLT/KYC uploads, local
# archives) is root-owned. Running the app as appuser (see Dockerfile) without this would mean
# every write -- generating an invoice PDF, saving an upload, the daily archive job -- fails with
# a permission error on an existing deployment's volume, even though a brand-new empty volume
# would have worked fine (Docker seeds a new named volume from the image's own directory
# ownership, which the Dockerfile already sets correctly). Fixing ownership here, on every
# container start, closes that gap regardless of the volume's history.
chown -R appuser:appuser /app/uploads

# gosu (not su/sudo) execs the real process directly rather than wrapping it in a shell, so
# signals -- notably the SIGTERM Coolify sends on redeploy -- reach uvicorn directly instead of
# being swallowed by an intermediate shell and forcing a slow, ungraceful kill.
exec gosu appuser "$@"
