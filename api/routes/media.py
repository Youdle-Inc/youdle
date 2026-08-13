"""
Media API Routes
Endpoints for managing media library (image uploads).
"""
import sys
import os
import base64
from uuid import uuid4
from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, UploadFile, File, Form
from pydantic import BaseModel

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

router = APIRouter()

# Configuration
ALLOWED_MIME_TYPES = ["image/jpeg", "image/png", "image/gif", "image/webp"]
MIME_EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
MEDIA_FOLDER = "media"


class MediaItem(BaseModel):
    id: str
    filename: str
    original_filename: str
    public_url: str
    mime_type: str
    file_size: int
    width: Optional[int] = None
    height: Optional[int] = None
    alt_text: Optional[str] = None
    created_at: str


class MediaListResponse(BaseModel):
    items: List[MediaItem]
    total: int


@router.get("", response_model=MediaListResponse)
async def list_media(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0)
):
    """List all media items with pagination."""
    try:
        from supabase_storage import get_supabase_client
        supabase = get_supabase_client()

        if not supabase:
            raise HTTPException(status_code=503, detail="Database not configured")

        # Get total count
        count_result = supabase.table("media").select(
            "id", count="exact", head=True
        ).execute()
        total = count_result.count if count_result.count is not None else 0

        # Get paginated items
        result = supabase.table("media").select("*").order(
            "created_at", desc=True
        ).range(offset, offset + limit - 1).execute()

        items = [
            MediaItem(
                id=item["id"],
                filename=item["filename"],
                original_filename=item["original_filename"],
                public_url=item["public_url"],
                mime_type=item["mime_type"],
                file_size=item["file_size"],
                width=item.get("width"),
                height=item.get("height"),
                alt_text=item.get("alt_text"),
                created_at=item["created_at"]
            )
            for item in (result.data or [])
        ]

        return MediaListResponse(items=items, total=total)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list media: {str(e)}")


@router.post("/upload", response_model=MediaItem)
async def upload_media(
    file: UploadFile = File(...),
    alt_text: Optional[str] = Form(None)
):
    """Upload a new media file to Supabase Storage."""
    try:
        # Validate file type
        if file.content_type not in ALLOWED_MIME_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file type. Allowed types: {', '.join(ALLOWED_MIME_TYPES)}"
            )

        # Read file content
        content = await file.read()

        # Validate file size
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"File too large. Maximum size: {MAX_FILE_SIZE // (1024 * 1024)}MB"
            )

        from supabase_storage import get_supabase_storage, get_supabase_client

        storage = get_supabase_storage()
        supabase = get_supabase_client()

        if not storage or not supabase:
            raise HTTPException(status_code=503, detail="Storage not configured")

        # Generate unique filename
        original_filename = file.filename or "upload"
        ext = MIME_EXTENSIONS[file.content_type]
        unique_filename = f"{uuid4().hex[:12]}.{ext}"

        # Upload to Supabase Storage
        image_base64 = base64.b64encode(content).decode("utf-8")
        upload_result = storage.upload_image(
            image_data=image_base64,
            filename=unique_filename,
            folder=MEDIA_FOLDER,
            content_type=file.content_type
        )

        if not upload_result.get("success"):
            raise HTTPException(
                status_code=500,
                detail=f"Failed to upload file: {upload_result.get('error', 'Unknown error')}"
            )

        # Save metadata to database
        media_data = {
            "filename": unique_filename,
            "original_filename": original_filename,
            "file_path": upload_result["path"],
            "public_url": upload_result["url"],
            "mime_type": file.content_type,
            "file_size": len(content),
            "alt_text": alt_text,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }

        try:
            result = supabase.table("media").insert(media_data).execute()
            if not result.data:
                raise RuntimeError("Supabase did not return the saved media row")
        except Exception as metadata_error:
            # Compensate for the already-completed object upload so a database
            # failure cannot leave an undiscoverable public storage object.
            try:
                storage.client.storage.from_(storage.bucket).remove(
                    [upload_result["path"]]
                )
            except Exception:
                pass
            raise HTTPException(
                status_code=500,
                detail=f"Failed to save media metadata: {metadata_error}",
            ) from metadata_error

        item = result.data[0]
        return MediaItem(
            id=item["id"],
            filename=item["filename"],
            original_filename=item["original_filename"],
            public_url=item["public_url"],
            mime_type=item["mime_type"],
            file_size=item["file_size"],
            width=item.get("width"),
            height=item.get("height"),
            alt_text=item.get("alt_text"),
            created_at=item["created_at"]
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload media: {str(e)}")


@router.delete("/{media_id}")
async def delete_media(media_id: str):
    """Delete a media item from storage and database."""
    try:
        from supabase_storage import get_supabase_storage, get_supabase_client

        storage = get_supabase_storage()
        supabase = get_supabase_client()

        if not storage or not supabase:
            raise HTTPException(status_code=503, detail="Storage not configured")

        # Get media item to find file path
        result = supabase.table("media").select("*").eq("id", media_id).maybe_single().execute()

        if result is None or not result.data:
            raise HTTPException(status_code=404, detail="Media not found")

        media_item = result.data
        file_path = media_item.get("file_path")

        # Delete from storage
        if file_path:
            try:
                storage.client.storage.from_(storage.bucket).remove([file_path])
            except Exception as e:
                # Keep the metadata row so the orphan remains discoverable and
                # the deletion can be retried safely.
                raise HTTPException(
                    status_code=502,
                    detail="Could not delete the storage object; metadata was retained",
                ) from e

        # Delete from database
        supabase.table("media").delete().eq("id", media_id).execute()

        return {"message": "Media deleted successfully", "id": media_id}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete media: {str(e)}")


@router.get("/{media_id}", response_model=MediaItem)
async def get_media(media_id: str):
    """Get a single media item by ID."""
    try:
        from supabase_storage import get_supabase_client
        supabase = get_supabase_client()

        if not supabase:
            raise HTTPException(status_code=503, detail="Database not configured")

        result = supabase.table("media").select("*").eq("id", media_id).maybe_single().execute()

        if result is None or not result.data:
            raise HTTPException(status_code=404, detail="Media not found")

        item = result.data
        return MediaItem(
            id=item["id"],
            filename=item["filename"],
            original_filename=item["original_filename"],
            public_url=item["public_url"],
            mime_type=item["mime_type"],
            file_size=item["file_size"],
            width=item.get("width"),
            height=item.get("height"),
            alt_text=item.get("alt_text"),
            created_at=item["created_at"]
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get media: {str(e)}")
