from __future__ import annotations

from sqlalchemy import Boolean, Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from db.database import Base

class Site(Base):
    __tablename__ = "sites"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False, index=True)
    url = Column(String(500), nullable=False)
    client_key_encrypted = Column(String(500), default="")
    client_secret_encrypted = Column(String(500), default="")
    wp_user = Column(String(100), default="")
    wp_app_password_encrypted = Column(String(500), default="")
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    posts = relationship('PostHistory', back_populates='site', cascade='all, delete-orphan')


class PostHistory(Base):
    __tablename__ = "post_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    site_id = Column(Integer, ForeignKey('sites.id'), nullable=False, index=True)
    product_name = Column(String(300), nullable=False)
    title = Column(String(500), default="")
    raw_html = Column(Text, default="")
    post_type = Column(String(20), default="product")
    wp_post_id = Column(String(50), nullable=True)
    wp_post_url = Column(String(500), nullable=True)
    status = Column(String(20), default="generated")
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now())
    published_at = Column(DateTime, nullable=True)

    site = relationship('Site', back_populates='posts')


class PromptTemplate(Base):
    __tablename__ = "prompt_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False)
    category = Column(String(50), default="general")
    content = Column(Text, nullable=False)
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
