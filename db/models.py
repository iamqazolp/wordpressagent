from __future__ import annotations

from sqlalchemy import Boolean, Column, Integer, String, Text, DateTime, ForeignKey, Float, UniqueConstraint
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
    watermark_path = Column(String(500), default="", nullable=True)
    watermark_position = Column(String(50), default="bottom-right", nullable=True)
    watermark_opacity = Column(Float, default=0.7, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    posts = relationship('PostHistory', back_populates='site', cascade='all, delete-orphan')
    taxonomies = relationship('SiteTaxonomy', back_populates='site', cascade='all, delete-orphan')


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
    short_description = Column(Text, nullable=True, default="")
    regular_price = Column(String(50), nullable=True, default="")
    sale_price = Column(String(50), nullable=True, default="")
    image_paths_json = Column(Text, nullable=True, default="[]")
    category_ids_json = Column(Text, nullable=True, default="[]")   # JSON [wp_category_id, ...] (id theo từng site)
    tags_json = Column(Text, nullable=True, default="[]")           # JSON ["tag name", ...] (tạo/tra id lúc đăng)
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


class ScheduledPost(Base):
    __tablename__ = "scheduled_posts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_name = Column(String(300), nullable=False)
    article_data_json = Column(Text, nullable=False)      # JSON {site_name: {title, raw_html, short_description}}
    site_names_json = Column(Text, nullable=False)        # JSON ["site1", "site2"]
    post_type = Column(String(50), default="product")     # product or post
    post_status = Column(String(20), default="draft")     # draft or publish
    regular_price = Column(String(50), default="")
    sale_price = Column(String(50), default="")
    image_paths_json = Column(Text, default="[]")         # JSON list of image paths
    scheduled_time = Column(DateTime, nullable=False)     # When to run
    status = Column(String(20), default="pending")        # pending, running, completed, failed, cancelled
    result_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now())
    executed_at = Column(DateTime, nullable=True)


class SiteTaxonomy(Base):
    """Cache danh mục (category) của từng website, tách theo loại nội dung (post | product)."""
    __tablename__ = "site_taxonomy"
    __table_args__ = (UniqueConstraint("site_id", "kind", "scope", "wp_id", name="uq_site_taxonomy"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False, index=True)
    kind = Column(String(20), nullable=False, default="category")   # hiện chỉ dùng 'category'
    scope = Column(String(20), nullable=False)                      # 'post' (wp/v2) | 'product' (wc/v3)
    wp_id = Column(Integer, nullable=False)
    name = Column(String(300), nullable=False)
    parent_id = Column(Integer, nullable=True)
    fetched_at = Column(DateTime, default=func.now())

    site = relationship("Site", back_populates="taxonomies")
