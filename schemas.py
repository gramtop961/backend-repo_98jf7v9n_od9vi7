"""
Database Schemas for MovieVerse

Each Pydantic model represents a collection in MongoDB.
Collection name is lowercase of the class name.
"""

from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List
from datetime import datetime

class User(BaseModel):
    name: str = Field(..., description="Full name")
    email: EmailStr = Field(..., description="Unique email")
    password_hash: str = Field(..., description="Hashed password")
    role: str = Field("user", description="Role: user | admin")
    is_active: bool = Field(True, description="Active flag")

class Movie(BaseModel):
    tmdb_id: int = Field(..., description="TMDb movie id")
    title: str
    overview: Optional[str] = None
    poster_path: Optional[str] = None
    backdrop_path: Optional[str] = None
    genres: Optional[List[str]] = None
    release_date: Optional[str] = None
    rating: Optional[float] = Field(None, ge=0, le=10)

class Review(BaseModel):
    movie_id: int = Field(..., description="TMDb movie id")
    user_id: str = Field(..., description="User ObjectId as string")
    rating: int = Field(..., ge=1, le=5)
    comment: Optional[str] = None
    created_at: Optional[datetime] = None

class Theatre(BaseModel):
    name: str
    city: str
    address: Optional[str] = None

class Show(BaseModel):
    theatre_id: str
    movie_id: int
    show_time: datetime
    price: float = Field(..., ge=0)
    seats_total: int = Field(80, ge=1, le=300)

class Booking(BaseModel):
    user_id: str
    show_id: str
    seats: List[str]  # e.g., ["A1","A2"]
    amount: float
    payment_status: str = Field("pending")
    payment_provider: Optional[str] = Field(None, description="stripe|razorpay")
