"""Audio serving route — streams WAV files from MinIO."""

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from io import BytesIO

from server.api.deps import get_storage
from server.core.domain import DomainError
from server.core.storage import MinIOStorage

router = APIRouter()


@router.get("/audio/{audio_key:path}")
async def serve_audio(
    audio_key: str,
    storage: MinIOStorage = Depends(get_storage),
) -> StreamingResponse:
    """Stream a WAV file from MinIO.

    audio_key is the MinIO object key, e.g.
    episodes/ch04/chunks/ch04:shot01:1/takes/abc123.wav
    """
    # Strip s3://bucket/ prefix if present (audioUri from DB includes it)
    key = audio_key
    if key.startswith("s3://"):
        # s3://tts-harness/episodes/... → episodes/...
        key = key.split("/", 3)[-1] if key.count("/") >= 3 else key

    try:
        data = await storage.download_bytes(key)
    except Exception:
        raise DomainError("not_found", f"audio not found: {audio_key}")

    return StreamingResponse(
        BytesIO(data),
        media_type="audio/wav",
        headers={
            "Content-Length": str(len(data)),
            "Cache-Control": "public, max-age=3600",
        },
    )
