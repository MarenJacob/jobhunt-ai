from pydantic import BaseModel, Field, HttpUrl
from typing import Optional

class JobIn(BaseModel):
    title: str
    company: str
    location: str = ""
    url: str
    source: str = "manual"
    description: str = ""
    remote: bool = False

class ProfileIn(BaseModel):
    name: str
    headline: str = ""
    email: str = ""
    location: str = "Nigeria"
    skills: str = ""
    projects: str = ""
    experience: str = ""
    education: str = ""
    preferences: str = ""
    phone: str = ""
    address: str = ""
    linkedin: str = ""
    github: str = ""
    website: str = ""
    work_authorization: str = ""
    sponsorship: str = ""
    salary: str = ""

class ApplicationIn(BaseModel):
    job_id: int

class FeedbackIn(BaseModel):
    application_id: int
    outcome: str
    reason: str = ""

class SearchIn(BaseModel):
    query: str = Field(min_length=2)
    max_results: int = Field(default=20, ge=1, le=100)
