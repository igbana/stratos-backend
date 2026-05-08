import cloudinary
import cloudinary.uploader
import os

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True,  # always use HTTPS
)

def upload_image(file_bytes: bytes, folder: str = "stratos/avatars") -> dict:
    """Upload an image and return the secure URL and public_id."""
    result = cloudinary.uploader.upload(
        file_bytes,
        folder=folder,
        resource_type="image",
        transformation=[
            {"width": 400, "height": 400, "crop": "fill", "gravity": "face"},
            {"quality": "auto", "fetch_format": "auto"},
        ],
    )
    return {
        "url": result["secure_url"],
        "public_id": result["public_id"],
    }

def upload_video(file_bytes: bytes, folder: str = "stratos/videos") -> dict:
    """Upload a video and return secure URL, thumbnail URL, duration."""
    result = cloudinary.uploader.upload(
        file_bytes,
        folder=folder,
        resource_type="video",
        eager=[
            # Auto-generate a thumbnail at 1 second
            {"width": 640, "height": 360, "crop": "fill",
             "start_offset": "1", "format": "jpg"},
        ],
        eager_async=False,
    )
    thumbnail_url = None
    if result.get("eager"):
        thumbnail_url = result["eager"][0]["secure_url"]

    print(result["secure_url"])

    return {
        "url": result["secure_url"],
        "public_id": result["public_id"],
        "thumbnail_url": thumbnail_url,
        "duration": int(result.get("duration", 0)),
    }

def delete_file(public_id: str, resource_type: str = "image") -> bool:
    """Delete a file from Cloudinary by its public_id."""
    result = cloudinary.uploader.destroy(
        public_id, resource_type=resource_type)
    return result.get("result") == "ok"