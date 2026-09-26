from __future__ import annotations

import logging
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

logger = logging.getLogger(__name__)

# Project root path
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "wordpress_agent.db"

# Create data directory if it doesn't exist
DATA_DIR.mkdir(parents=True, exist_ok=True)

SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    from db.models import Base
    from db.crud import seed_default_templates, migrate_from_json
    
    # Create tables
    Base.metadata.create_all(bind=engine)
    logger.info(f"Initialized database at {DB_PATH}")
    
    # Seed default templates and migrate data
    db = SessionLocal()
    try:
        seed_default_templates(db)
        json_path = PROJECT_ROOT / "config" / "sites.json"
        if json_path.exists():
            migrate_from_json(db, json_path)
    except Exception as e:
        logger.error(f"Error during db initialization: {e}")
    finally:
        db.close()
