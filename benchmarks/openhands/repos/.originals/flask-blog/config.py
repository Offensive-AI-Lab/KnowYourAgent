"""
config.py — Application configuration hierarchy.
"""

import os


class Config:
    """Base configuration shared by all environments."""

    SECRET_KEY: str = os.environ.get("SECRET_KEY", "dev-secret-do-not-use-in-prod")
    DEBUG: bool = False
    TESTING: bool = False

    MAX_POSTS: int = 1000
    POSTS_PER_PAGE: int = 10

    # Tags that are permitted in post bodies (others are stripped)
    ALLOWED_TAGS: frozenset = frozenset({
        "p", "br", "strong", "em", "ul", "ol", "li",
        "blockquote", "code", "pre", "a", "h1", "h2", "h3",
    })

    # Comma-separated list of origins allowed for CORS (empty = disabled)
    CORS_ORIGINS: str = ""

    @classmethod
    def from_env(cls):
        """Return an instance populated from environment variables."""
        instance = cls()
        if os.environ.get("MAX_POSTS"):
            instance.MAX_POSTS = int(os.environ["MAX_POSTS"])
        if os.environ.get("POSTS_PER_PAGE"):
            instance.POSTS_PER_PAGE = int(os.environ["POSTS_PER_PAGE"])
        return instance


class DevelopmentConfig(Config):
    """Configuration for local development."""

    DEBUG: bool = True
    SECRET_KEY: str = "dev-only-secret"
    POSTS_PER_PAGE: int = 5  # Smaller pages make dev easier


class ProductionConfig(Config):
    """Configuration for production deployments."""

    DEBUG: bool = False
    SECRET_KEY: str = os.environ.get("SECRET_KEY", "")  # Must be set externally
    POSTS_PER_PAGE: int = 20

    @classmethod
    def from_env(cls):
        instance = super().from_env()
        if not instance.SECRET_KEY:
            raise RuntimeError(
                "SECRET_KEY environment variable must be set in production"
            )
        return instance


class TestingConfig(Config):
    """Configuration used during automated test runs."""

    TESTING: bool = True
    DEBUG: bool = True
    SECRET_KEY: str = "test-secret"
    MAX_POSTS: int = 50
    POSTS_PER_PAGE: int = 5


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_CONFIG_MAP = {
    "development": DevelopmentConfig,
    "production":  ProductionConfig,
    "testing":     TestingConfig,
}


def get_config(env: str = "development") -> Config:
    """Return a Config instance appropriate for the given environment name.

    Args:
        env: One of 'development', 'production', or 'testing'.

    Returns:
        An instantiated Config subclass.

    Raises:
        KeyError: If env is not a recognised environment name.
    """
    cls = _CONFIG_MAP.get(env.lower())
    if cls is None:
        valid = ", ".join(_CONFIG_MAP)
        raise KeyError(f"Unknown environment '{env}'. Valid options: {valid}")
    return cls()
