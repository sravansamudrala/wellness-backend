from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

engine = create_engine(
    settings.database_url,
    echo=settings.sql_echo,
    # Validate a pooled connection before handing it out; if the Supabase
    # pooler (or a Render idle spin-down) dropped it, reconnect transparently
    # instead of failing the next query with "connection closed".
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False
)