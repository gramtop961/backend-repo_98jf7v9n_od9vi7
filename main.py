import os
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
import jwt
from passlib.context import CryptContext

from database import db, create_document, get_documents
from schemas import User, Review, Theatre, Show, Booking

JWT_SECRET = os.getenv("JWT_SECRET", "devsecret")
JWT_ALGO = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

app = FastAPI(title="MovieVerse API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AuthPayload(BaseModel):
    email: EmailStr
    password: str
    name: Optional[str] = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ReviewPayload(BaseModel):
    movie_id: int
    rating: int
    comment: Optional[str] = None


class TheatrePayload(BaseModel):
    name: str
    city: str
    address: Optional[str] = None


class ShowPayload(BaseModel):
    theatre_id: str
    movie_id: int
    show_time: datetime
    price: float
    seats_total: int = 80


class BookingPayload(BaseModel):
    show_id: str
    seats: List[str]
    amount: float


# Utils

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGO)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def get_current_user(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise ValueError("Invalid auth scheme")
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        return payload
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


@app.get("/")
def root():
    return {"message": "MovieVerse API is running"}


# Auth
@app.post("/auth/register", response_model=TokenResponse)
def register(payload: AuthPayload):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")

    existing = db["user"].find_one({"email": payload.email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user_doc = User(
        name=payload.name or payload.email.split("@")[0],
        email=payload.email,
        password_hash=get_password_hash(payload.password),
        role="user",
    )

    user_id = create_document("user", user_doc)

    token = create_access_token({"sub": str(user_id), "email": payload.email, "role": "user"})
    return TokenResponse(access_token=token)


@app.post("/auth/login", response_model=TokenResponse)
def login(payload: AuthPayload):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")

    doc = db["user"].find_one({"email": payload.email})
    if not doc:
        raise HTTPException(status_code=400, detail="Invalid credentials")

    if not verify_password(payload.password, doc.get("password_hash", "")):
        raise HTTPException(status_code=400, detail="Invalid credentials")

    token = create_access_token({"sub": str(doc.get("_id")), "email": doc["email"], "role": doc.get("role", "user")})
    return TokenResponse(access_token=token)


# Reviews
@app.post("/reviews")
def add_review(payload: ReviewPayload, user=Depends(get_current_user)):
    review = Review(movie_id=payload.movie_id, user_id=user["sub"], rating=payload.rating, comment=payload.comment)
    review_id = create_document("review", review)
    return {"id": review_id}


@app.get("/reviews/{movie_id}")
def get_reviews(movie_id: int):
    docs = get_documents("review", {"movie_id": movie_id})
    # hide internal fields
    for d in docs:
        d["_id"] = str(d["_id"])  # stringify ids
    return {"items": docs}


# Theatres & Shows (basic admin endpoints)
@app.post("/theatres")
def create_theatre(payload: TheatrePayload, user=Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    theatre = Theatre(name=payload.name, city=payload.city, address=payload.address)
    _id = create_document("theatre", theatre)
    return {"id": _id}


@app.get("/theatres")
def list_theatres(city: Optional[str] = None):
    query = {"city": city} if city else {}
    docs = get_documents("theatre", query)
    for d in docs:
        d["_id"] = str(d["_id"])  # stringify ids
    return {"items": docs}


@app.post("/shows")
def create_show(payload: ShowPayload, user=Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    show = Show(**payload.model_dump())
    _id = create_document("show", show)
    return {"id": _id}


@app.get("/shows")
def list_shows(theatre_id: Optional[str] = None, movie_id: Optional[int] = None):
    query: Dict[str, Any] = {}
    if theatre_id:
        query["theatre_id"] = theatre_id
    if movie_id is not None:
        query["movie_id"] = movie_id
    docs = get_documents("show", query)
    for d in docs:
        d["_id"] = str(d["_id"])  # stringify ids
    return {"items": docs}


# Bookings (without payment integration for now)
@app.post("/bookings")
def create_booking(payload: BookingPayload, user=Depends(get_current_user)):
    # naive seat conflict check: ensure seat not already booked for show
    taken = db["booking"].find_one({"show_id": payload.show_id, "seats": {"$in": payload.seats}})
    if taken:
        raise HTTPException(status_code=400, detail="Some seats already booked")
    booking = Booking(user_id=user["sub"], show_id=payload.show_id, seats=payload.seats, amount=payload.amount)
    _id = create_document("booking", booking)
    return {"id": _id, "status": "pending_payment"}


@app.get("/bookings/me")
def my_bookings(user=Depends(get_current_user)):
    docs = get_documents("booking", {"user_id": user["sub"]})
    for d in docs:
        d["_id"] = str(d["_id"])  # stringify ids
    return {"items": docs}


# Simple health and schema exposure
@app.get("/test")
def test_database():
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
            response["database_url"] = "✅ Set"
            response["database_name"] = db.name
            response["connection_status"] = "Connected"
            response["collections"] = db.list_collection_names()
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"
    return response


@app.get("/schema")
def get_schema():
    # Minimal schema exposure for tooling
    return {
        "collections": [
            "user",
            "movie",
            "review",
            "theatre",
            "show",
            "booking",
        ]
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
