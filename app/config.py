from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings.

    Vercel can expose an environment variable as an empty string when a user
    creates it without a value. ``env_ignore_empty=True`` makes empty values
    fall back to the defaults below instead of crashing Pydantic validation.
    """

    app_name: str = "JobHunt AI"
    database_url: str = "sqlite:///./storage/job_hunt.db"
    secret_key: str = "change-me-in-production"
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    tavily_api_key: str = ""
    search_provider: str = "tavily"
    auto_submit: bool = False
    max_applications_per_day: int = 30
    minimum_match_score: float = 70
    max_required_years: int = 2
    blocked_role_terms: str = "senior,staff,principal,director,vp,head of"
    allowed_domains: str = "greenhouse.io,lever.co,ashbyhq.com,smartrecruiters.com,wellfound.com,weworkremotely.com,linkedin.com,indeed.com"
    browser_profile_dir: str = "storage/browser-profile"
    browser_headless: bool = True
    resume_path: str = ""
    follow_up_days: int = 7
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    cron_secret: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_ignore_empty=True,
        extra="ignore",
    )


settings = Settings()
