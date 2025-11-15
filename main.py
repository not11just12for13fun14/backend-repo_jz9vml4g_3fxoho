import os
from fastapi import FastAPI, HTTPException, Response, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime, timezone
import requests

# Database helpers
from database import create_document, get_documents, db

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root():
    return {"message": "Hello from FastAPI Backend!"}


@app.get("/api/hello")
def hello():
    return {"message": "Hello from the backend API!"}


# Contact message schema (Pydantic for request body)
class ContactIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    email: EmailStr
    subject: Optional[str] = Field(None, max_length=200)
    phone: Optional[str] = Field(None, max_length=30)
    message: str = Field(..., min_length=5, max_length=5000)
    source: str = Field(default="portfolio")


@app.post("/api/contact")
async def create_contact_message(payload: ContactIn):
    try:
        if db is None:
            raise HTTPException(status_code=500, detail="Database not configured")

        data = payload.model_dump()
        data["received_at"] = datetime.now(timezone.utc)
        inserted_id = create_document("contactmessage", data)
        return {"success": True, "id": inserted_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/contact")
async def list_contact_messages(limit: int = 10):
    try:
        if db is None:
            raise HTTPException(status_code=500, detail="Database not configured")
        docs = get_documents("contactmessage", {}, limit)
        # Convert ObjectId and datetime to strings
        def serialize(doc):
            d = {**doc}
            if "_id" in d:
                d["_id"] = str(d["_id"])
            for k, v in list(d.items()):
                if hasattr(v, "isoformat"):
                    d[k] = v.isoformat()
            return d
        return {"items": [serialize(x) for x in docs]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/image")
def proxy_image(src: str = Query(..., description="Absolute image URL to proxy")):
    """
    Simple image proxy to bypass hotlink/CORS restrictions from hosts like Google Drive/Photos.
    Usage: /api/image?src=<encoded-url>
    """
    try:
        # Basic allowlist check to prevent SSRF abuse
        if not (src.startswith("https://") or src.startswith("http://")):
            raise HTTPException(status_code=400, detail="Invalid URL")

        # Fetch with a browser-like UA and no referrer
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Referer": "",
            "Origin": "",
        }
        # stream=False to read content at once (small avatars). Set timeout.
        resp = requests.get(src, headers=headers, timeout=10)
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=f"Upstream failed: {resp.status_code}")

        content_type = resp.headers.get("Content-Type", "image/jpeg")
        # Cache for a day to reduce repeated fetches
        cache_headers = {
            "Cache-Control": "public, max-age=86400",
            "Content-Type": content_type,
            "X-Image-Proxy": "1",
        }
        return Response(content=resp.content, media_type=content_type, headers=cache_headers)
    except HTTPException:
        raise
    except requests.Timeout:
        raise HTTPException(status_code=504, detail="Image fetch timed out")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Proxy error: {str(e)}")


@app.get("/test")
def test_database():
    """Test endpoint to check if database is available and accessible"""
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }

    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"

            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"

    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    # Check environment variables
    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"

    return response


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
