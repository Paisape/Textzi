"""Local-disk storage for WhatsApp media (both inbound, downloaded from Meta, and outbound,
uploaded by an agent before being sent to Meta) -- same uploads_dir convention as
services.save_upload, but its own allowlist since WhatsApp media types (video, audio, common
document formats) are far broader than the KYC-document allowlist that function enforces.
Deliberately its own module, never touching dispatch.py/providers.py/webhooks.py."""
import os
import uuid

from .config import settings

# Meta's own per-type caps (developers.facebook.com/docs/whatsapp/cloud-api -- media guidance),
# not a single flat number -- a flat 16MB cap previously let an oversized image through (Meta's
# real image limit is 5MB, so that would have failed at send time) while also blocking valid
# documents up to 100MB.
MAX_MEDIA_BYTES = {
    "image": 5 * 1024 * 1024,
    "video": 16 * 1024 * 1024,
    "audio": 16 * 1024 * 1024,
    "document": 100 * 1024 * 1024,
    "sticker": 500 * 1024,  # animated stickers up to 500KB; static ones up to 100KB, checked separately below
}

# Maps a WhatsApp message_type to the MIME types Meta accepts for it (per Meta's own media docs).
MEDIA_TYPE_MIME = {
    "image": {"image/jpeg", "image/png", "image/webp"},
    "video": {"video/mp4", "video/3gpp"},
    "audio": {"audio/aac", "audio/mp4", "audio/mpeg", "audio/amr", "audio/ogg"},
    "document": {"application/pdf", "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/vnd.ms-excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "text/plain"},
    "sticker": {"image/webp"},
}

_EXTENSION_FOR_MIME = {
    "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
    "video/mp4": ".mp4", "video/3gpp": ".3gp",
    "audio/aac": ".aac", "audio/mp4": ".m4a", "audio/mpeg": ".mp3", "audio/amr": ".amr", "audio/ogg": ".ogg",
    "application/pdf": ".pdf", "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "text/plain": ".txt",
}


def message_type_for_mime(mime_type: str) -> str | None:
    # Checks non-sticker types first -- "image/webp" is shared between "image" and "sticker", and
    # a plain webp upload from an agent's file picker is almost always meant as an image, not a
    # sticker (stickers need Meta's exact 512x512 dimension requirement, which a generic file
    # picker upload can't guarantee -- callers that specifically want to send a sticker should
    # pass message_type="sticker" explicitly rather than relying on MIME sniffing for it).
    for message_type, mimes in MEDIA_TYPE_MIME.items():
        if message_type != "sticker" and mime_type in mimes:
            return message_type
    return None


def save_media(entity_id: str, content: bytes, mime_type: str, message_type: str = "document") -> str:
    """Returns a stored_path (relative to uploads_dir) -- never the original filename, same
    path-traversal reasoning as services.save_upload."""
    max_bytes = MAX_MEDIA_BYTES.get(message_type, MAX_MEDIA_BYTES["document"])
    if len(content) > max_bytes:
        raise ValueError(f"Media file is too large (max {max_bytes // 1024}KB)" if max_bytes < 1024 * 1024 else f"Media file is too large (max {max_bytes // (1024 * 1024)}MB)")
    ext = _EXTENSION_FOR_MIME.get(mime_type, "")
    directory = os.path.join(settings.uploads_dir, "waba-media", entity_id)
    os.makedirs(directory, exist_ok=True)
    stored_name = f"{uuid.uuid4()}{ext}"
    with open(os.path.join(directory, stored_name), "wb") as f:
        f.write(content)
    return os.path.join("waba-media", entity_id, stored_name)


def read_media(stored_path: str) -> bytes:
    with open(os.path.join(settings.uploads_dir, stored_path), "rb") as f:
        return f.read()
