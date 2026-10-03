from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path
from cryptography.fernet import Fernet
from sqlalchemy.orm import Session
from sqlalchemy import desc

from datetime import datetime, timedelta

from core.timeutil import now_vn
from db.models import Site, PostHistory, PromptTemplate, ScheduledPost, SiteTaxonomy

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_fernet = None

def _get_fernet() -> Fernet:
    global _fernet
    if _fernet:
        return _fernet
    
    env_path = Path(__file__).parent.parent / '.env'
    load_dotenv(env_path, override=False)
    key = os.getenv('ENCRYPTION_KEY', '').strip()
    
    if not key:
        # Check if key is already in .env file before appending
        if env_path.exists():
            with open(env_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip().startswith('ENCRYPTION_KEY='):
                        key = line.strip().split('=', 1)[1].strip()
                        if key:
                            os.environ['ENCRYPTION_KEY'] = key
                            break

    if not key:
        # Generate new key only if completely absent
        key = Fernet.generate_key().decode()
        try:
            with open(env_path, 'a', encoding='utf-8') as f:
                f.write(f'\nENCRYPTION_KEY={key}\n')
            os.environ['ENCRYPTION_KEY'] = key
            logger.info('Generated new ENCRYPTION_KEY and saved to .env')
        except Exception as e:
            logger.error(f"Failed to write ENCRYPTION_KEY to .env: {e}")
            os.environ['ENCRYPTION_KEY'] = key
    
    _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    return _fernet

def _encrypt(value: str) -> str:
    if not value:
        return ''
    return _get_fernet().encrypt(value.encode()).decode()

def _decrypt(value: str) -> str:
    if not value:
        return ''
    try:
        return _get_fernet().decrypt(value.encode()).decode()
    except Exception:
        return value  # Return as-is if decryption fails (backward compat)


# --- Site CRUD ---

def get_all_sites(db: Session) -> list[Site]:
    try:
        return db.query(Site).all()
    except Exception as e:
        logger.error(f"Lỗi khi lấy danh sách sites: {e}")
        return []

def get_site(db: Session, site_id: int) -> Site | None:
    try:
        return db.query(Site).filter(Site.id == site_id).first()
    except Exception as e:
        logger.error(f"Lỗi khi lấy site theo id: {e}")
        return None

def get_site_by_name(db: Session, name: str) -> Site | None:
    try:
        return db.query(Site).filter(Site.name == name).first()
    except Exception as e:
        logger.error(f"Lỗi khi lấy site theo name: {e}")
        return None

def create_site(
    db: Session,
    name: str,
    url: str,
    client_key: str,
    client_secret: str,
    wp_user: str = '',
    wp_app_password: str = '',
    watermark_path: str = '',
    watermark_position: str = 'bottom-right',
    watermark_opacity: float = 0.7,
) -> Site | None:
    try:
        site = Site(
            name=name,
            url=url,
            client_key_encrypted=_encrypt(client_key),
            client_secret_encrypted=_encrypt(client_secret),
            wp_user=wp_user,
            wp_app_password_encrypted=_encrypt(wp_app_password),
            watermark_path=watermark_path,
            watermark_position=watermark_position,
            watermark_opacity=watermark_opacity,
        )
        db.add(site)
        db.commit()
        db.refresh(site)
        return site
    except Exception as e:
        db.rollback()
        logger.error(f"Lỗi khi tạo site: {e}")
        return None

def update_site(db: Session, site_id: int, **kwargs) -> Site | None:
    try:
        site = get_site(db, site_id)
        if not site:
            return None
        
        if 'client_key' in kwargs:
            kwargs['client_key_encrypted'] = _encrypt(kwargs.pop('client_key'))
        if 'client_secret' in kwargs:
            kwargs['client_secret_encrypted'] = _encrypt(kwargs.pop('client_secret'))
        if 'wp_app_password' in kwargs:
            kwargs['wp_app_password_encrypted'] = _encrypt(kwargs.pop('wp_app_password'))
            
        for key, value in kwargs.items():
            setattr(site, key, value)
            
        db.commit()
        db.refresh(site)
        return site
    except Exception as e:
        db.rollback()
        logger.error(f"Lỗi khi cập nhật site: {e}")
        return None

def delete_site(db: Session, site_id: int) -> bool:
    try:
        count = db.query(Site).count()
        if count <= 1:
            logger.warning("Không thể xóa site cuối cùng.")
            return False
            
        site = get_site(db, site_id)
        if site:
            db.delete(site)
            db.commit()
            return True
        return False
    except Exception as e:
        db.rollback()
        logger.error(f"Lỗi khi xóa site: {e}")
        return False

def get_site_config(db: Session, site_id: int) -> dict | None:
    site = get_site(db, site_id)
    if not site:
        return None
    return {
        "name": site.name,
        "url": site.url,
        "client_key": _decrypt(site.client_key_encrypted),
        "client_secret": _decrypt(site.client_secret_encrypted),
        "wp_user": site.wp_user,
        "wp_app_password": _decrypt(site.wp_app_password_encrypted),
        "watermark_path": getattr(site, "watermark_path", "") or "",
        "watermark_position": getattr(site, "watermark_position", "bottom-right") or "bottom-right",
        "watermark_opacity": getattr(site, "watermark_opacity", 0.7) if getattr(site, "watermark_opacity", None) is not None else 0.7,
    }

def get_all_site_configs(db: Session) -> dict[str, dict]:
    sites = get_all_sites(db)
    configs = {}
    for site in sites:
        configs[site.name] = {
            "name": site.name,
            "url": site.url,
            "client_key": _decrypt(site.client_key_encrypted),
            "client_secret": _decrypt(site.client_secret_encrypted),
            "wp_user": site.wp_user,
            "wp_app_password": _decrypt(site.wp_app_password_encrypted),
            "watermark_path": getattr(site, "watermark_path", "") or "",
            "watermark_position": getattr(site, "watermark_position", "bottom-right") or "bottom-right",
            "watermark_opacity": getattr(site, "watermark_opacity", 0.7) if getattr(site, "watermark_opacity", None) is not None else 0.7,
        }
    return configs

def get_site_names(db: Session) -> list[str]:
    sites = get_all_sites(db)
    return [site.name for site in sites]

# --- Migration ---

def migrate_from_json(db: Session, json_path: Path) -> int:
    try:
        bak_path = json_path.with_suffix('.json.bak')
        if bak_path.exists():
            return 0
            
        if not json_path.exists():
            return 0
            
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        count = 0
        for name, config in data.items():
            existing = get_site_by_name(db, name)
            if not existing:
                create_site(
                    db,
                    name=name,
                    url=config.get('url', ''),
                    client_key=config.get('client_key', ''),
                    client_secret=config.get('client_secret', ''),
                    wp_user=config.get('wp_user', ''),
                    wp_app_password=config.get('wp_app_password', '')
                )
                count += 1
                
        shutil.move(str(json_path), str(bak_path))
        logger.info(f"Đã di chuyển {json_path} sang {bak_path}")
        return count
    except Exception as e:
        logger.error(f"Lỗi khi migrate từ JSON: {e}")
        return 0

# --- Post History ---

def create_post_history(
    db: Session,
    site_id: int,
    product_name: str,
    title: str = '',
    raw_html: str = '',
    post_type: str = 'product',
    status: str = 'generated',
    wp_post_id: str | None = None,
    wp_post_url: str | None = None,
    error_message: str | None = None,
    short_description: str = '',
    regular_price: str = '',
    sale_price: str = '',
    image_paths_json: str = '[]',
    category_ids_json: str = '[]',
    tags_json: str = '[]',
) -> PostHistory | None:
    try:
        history = PostHistory(
            site_id=site_id,
            product_name=product_name,
            title=title,
            raw_html=raw_html,
            post_type=post_type,
            status=status,
            wp_post_id=wp_post_id,
            wp_post_url=wp_post_url,
            error_message=error_message,
            short_description=short_description,
            regular_price=regular_price,
            sale_price=sale_price,
            image_paths_json=image_paths_json,
            category_ids_json=category_ids_json,
            tags_json=tags_json,
        )
        db.add(history)
        db.commit()
        db.refresh(history)
        return history
    except Exception as e:
        db.rollback()
        logger.error(f"Lỗi khi tạo post history: {e}")
        return None

def get_post_history_by_id(db: Session, history_id: int) -> PostHistory | None:
    try:
        return db.query(PostHistory).filter(PostHistory.id == history_id).first()
    except Exception as e:
        logger.error(f"Lỗi khi lấy post history theo id {history_id}: {e}")
        return None

def delete_post_history(db: Session, history_id: int) -> bool:
    try:
        item = get_post_history_by_id(db, history_id)
        if item:
            db.delete(item)
            db.commit()
            return True
        return False
    except Exception as e:
        db.rollback()
        logger.error(f"Lỗi khi xóa post history {history_id}: {e}")
        return False

def update_post_history(db: Session, history_id: int, **kwargs) -> PostHistory | None:
    try:
        history = db.query(PostHistory).filter(PostHistory.id == history_id).first()
        if not history:
            return None
        
        for key, value in kwargs.items():
            setattr(history, key, value)
            
        db.commit()
        db.refresh(history)
        return history
    except Exception as e:
        db.rollback()
        logger.error(f"Lỗi khi cập nhật post history: {e}")
        return None

def get_post_history(db: Session, site_id: int = None, limit: int = 50, offset: int = 0) -> list[PostHistory]:
    try:
        query = db.query(PostHistory)
        if site_id is not None:
            query = query.filter(PostHistory.site_id == site_id)
        return query.order_by(desc(PostHistory.created_at)).offset(offset).limit(limit).all()
    except Exception as e:
        logger.error(f"Lỗi khi lấy post history: {e}")
        return []

def get_recent_posts(db: Session, limit: int = 10) -> list[PostHistory]:
    try:
        return db.query(PostHistory).order_by(desc(PostHistory.created_at)).limit(limit).all()
    except Exception as e:
        logger.error(f"Lỗi khi lấy recent posts: {e}")
        return []

def check_duplicate_product(db: Session, site_id: int, product_name: str) -> PostHistory | None:
    try:
        # Case insensitive
        return db.query(PostHistory).filter(
            PostHistory.site_id == site_id,
            PostHistory.product_name.ilike(product_name)
        ).first()
    except Exception as e:
        logger.error(f"Lỗi khi kiểm tra duplicate product: {e}")
        return None

# --- Prompt Templates ---

def get_all_templates(db: Session) -> list[PromptTemplate]:
    try:
        return db.query(PromptTemplate).all()
    except Exception as e:
        logger.error(f"Lỗi khi lấy danh sách templates: {e}")
        return []

def get_template(db: Session, template_id: int) -> PromptTemplate | None:
    try:
        return db.query(PromptTemplate).filter(PromptTemplate.id == template_id).first()
    except Exception as e:
        logger.error(f"Lỗi khi lấy template theo id: {e}")
        return None

def get_default_template(db: Session) -> PromptTemplate | None:
    try:
        return db.query(PromptTemplate).filter(PromptTemplate.is_default == True).first()
    except Exception as e:
        logger.error(f"Lỗi khi lấy default template: {e}")
        return None

def create_template(db: Session, name: str, content: str, category: str = 'general', is_default: bool = False) -> PromptTemplate | None:
    try:
        if is_default:
            db.query(PromptTemplate).update({"is_default": False})
            
        template = PromptTemplate(
            name=name,
            content=content,
            category=category,
            is_default=is_default
        )
        db.add(template)
        db.commit()
        db.refresh(template)
        return template
    except Exception as e:
        db.rollback()
        logger.error(f"Lỗi khi tạo template: {e}")
        return None

def update_template(db: Session, template_id: int, **kwargs) -> PromptTemplate | None:
    try:
        template = get_template(db, template_id)
        if not template:
            return None
            
        if kwargs.get('is_default'):
            db.query(PromptTemplate).update({"is_default": False})
            
        for key, value in kwargs.items():
            setattr(template, key, value)
            
        db.commit()
        db.refresh(template)
        return template
    except Exception as e:
        db.rollback()
        logger.error(f"Lỗi khi cập nhật template: {e}")
        return None

def delete_template(db: Session, template_id: int) -> bool:
    try:
        count = db.query(PromptTemplate).count()
        if count <= 1:
            logger.warning("Không thể xóa template cuối cùng.")
            return False
            
        template = get_template(db, template_id)
        if template:
            db.delete(template)
            db.commit()
            return True
        return False
    except Exception as e:
        db.rollback()
        logger.error(f"Lỗi khi xóa template: {e}")
        return False

def seed_default_templates(db: Session) -> None:
    try:
        defaults = [
            {
                "name": "Thiết bị Công nghiệp (Mặc định)",
                "category": "industrial",
                "is_default": True,
                "file": Path(__file__).parent.parent / "prompts" / "write_post.txt",
                "fallback": "Default industrial prompt template",
            },
            {
                "name": "Điện tử & Công nghệ",
                "category": "electronics",
                "is_default": False,
                "file": Path(__file__).parent.parent / "config" / "defaults" / "templates" / "electronics.txt",
                "fallback": "Default electronics prompt template",
            },
            {
                "name": "Sản phẩm Đa dụng",
                "category": "general",
                "is_default": False,
                "file": Path(__file__).parent.parent / "config" / "defaults" / "templates" / "general.txt",
                "fallback": "Default general prompt template",
            },
            {
                "name": "Thời trang & Phụ kiện",
                "category": "fashion",
                "is_default": False,
                "file": Path(__file__).parent.parent / "config" / "defaults" / "templates" / "fashion.txt",
                "fallback": "Default fashion prompt template",
            },
        ]

        for item in defaults:
            existing = db.query(PromptTemplate).filter(PromptTemplate.name == item["name"]).first()
            if not existing:
                content = item["fallback"]
                if item["file"].exists():
                    with open(item["file"], "r", encoding="utf-8") as f:
                        content = f.read()

                create_template(
                    db,
                    name=item["name"],
                    content=content,
                    category=item["category"],
                    is_default=item["is_default"],
                )
                logger.info(f"Đã tạo template mặc định: {item['name']}")
    except Exception as e:
        logger.error(f"Lỗi khi seed default templates: {e}")


# --- Scheduled Posts CRUD ---

def create_scheduled_post(
    db: Session,
    product_name: str,
    article_data_json: str,
    site_names_json: str,
    scheduled_time,
    post_type: str = "product",
    post_status: str = "draft",
    regular_price: str = "",
    sale_price: str = "",
    image_paths_json: str = "[]",
) -> ScheduledPost | None:
    try:
        job = ScheduledPost(
            product_name=product_name,
            article_data_json=article_data_json,
            site_names_json=site_names_json,
            scheduled_time=scheduled_time,
            post_type=post_type,
            post_status=post_status,
            regular_price=regular_price,
            sale_price=sale_price,
            image_paths_json=image_paths_json,
            status="pending",
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        return job
    except Exception as e:
        db.rollback()
        logger.error(f"Lỗi khi tạo scheduled post: {e}")
        return None

def get_scheduled_posts(db: Session, status: str = None, limit: int = 100) -> list[ScheduledPost]:
    try:
        query = db.query(ScheduledPost)
        if status:
            query = query.filter(ScheduledPost.status == status)
        return query.order_by(desc(ScheduledPost.created_at)).limit(limit).all()
    except Exception as e:
        logger.error(f"Lỗi khi lấy scheduled posts: {e}")
        return []

def get_scheduled_post(db: Session, job_id: int) -> ScheduledPost | None:
    try:
        return db.query(ScheduledPost).filter(ScheduledPost.id == job_id).first()
    except Exception as e:
        logger.error(f"Lỗi khi lấy scheduled post #{job_id}: {e}")
        return None

def update_scheduled_post(db: Session, job_id: int, **kwargs) -> ScheduledPost | None:
    try:
        job = get_scheduled_post(db, job_id)
        if not job:
            return None
        for key, value in kwargs.items():
            setattr(job, key, value)
        db.commit()
        db.refresh(job)
        return job
    except Exception as e:
        db.rollback()
        logger.error(f"Lỗi khi cập nhật scheduled post #{job_id}: {e}")
        return None

def delete_scheduled_post(db: Session, job_id: int) -> bool:
    try:
        job = get_scheduled_post(db, job_id)
        if job:
            db.delete(job)
            db.commit()
            return True
        return False
    except Exception as e:
        db.rollback()
        logger.error(f"Lỗi khi xóa scheduled post #{job_id}: {e}")
        return False


# ═════════════════════════════════════════════════════════════
# Taxonomy cache (category theo từng website)
# ═════════════════════════════════════════════════════════════

TAXONOMY_TTL = timedelta(hours=24)


def replace_site_categories(db: Session, site_id: int, scope: str, categories: list[dict]) -> int:
    """
    Thay toàn bộ cache category của (site, scope) bằng danh sách mới trong 1 transaction.
    Chỉ gọi khi đã lấy được danh sách THÀNH CÔNG — lỗi mạng không được xoá cache cũ.
    categories: [{"id": int, "name": str, "parent": int}]
    """
    try:
        db.query(SiteTaxonomy).filter(
            SiteTaxonomy.site_id == site_id,
            SiteTaxonomy.kind == "category",
            SiteTaxonomy.scope == scope,
        ).delete(synchronize_session=False)
        now = now_vn()
        seen: set[int] = set()
        for c in categories:
            wp_id = int(c["id"])
            if wp_id in seen:
                continue
            seen.add(wp_id)
            db.add(SiteTaxonomy(
                site_id=site_id, kind="category", scope=scope, wp_id=wp_id,
                name=str(c.get("name", "")), parent_id=int(c.get("parent") or 0) or None,
                fetched_at=now,
            ))
        db.commit()
        return len(seen)
    except Exception:
        db.rollback()
        logger.exception("Lỗi khi lưu cache category")
        raise


def get_site_categories(db: Session, site_id: int, scope: str) -> list[SiteTaxonomy]:
    return (
        db.query(SiteTaxonomy)
        .filter(SiteTaxonomy.site_id == site_id, SiteTaxonomy.kind == "category", SiteTaxonomy.scope == scope)
        .order_by(SiteTaxonomy.name)
        .all()
    )


def get_categories_fetched_at(db: Session, site_id: int, scope: str) -> datetime | None:
    row = (
        db.query(SiteTaxonomy.fetched_at)
        .filter(SiteTaxonomy.site_id == site_id, SiteTaxonomy.kind == "category", SiteTaxonomy.scope == scope)
        .order_by(desc(SiteTaxonomy.fetched_at))
        .first()
    )
    return row[0] if row else None


def is_categories_stale(db: Session, site_id: int, scope: str, now: datetime | None = None) -> bool:
    """True nếu chưa có cache hoặc cache cũ hơn TTL (24h)."""
    fetched = get_categories_fetched_at(db, site_id, scope)
    if fetched is None:
        return True
    return (now or now_vn()) - fetched > TAXONOMY_TTL
