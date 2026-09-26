from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path
from cryptography.fernet import Fernet
from sqlalchemy.orm import Session
from sqlalchemy import desc

from db.models import Site, PostHistory, PromptTemplate

logger = logging.getLogger(__name__)

_fernet = None

def _get_fernet() -> Fernet:
    global _fernet
    if _fernet:
        return _fernet
    
    env_path = Path(__file__).parent.parent / '.env'
    key = os.getenv('ENCRYPTION_KEY', '')
    
    if not key:
        # Generate new key and append to .env
        key = Fernet.generate_key().decode()
        try:
            with open(env_path, 'a') as f:
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

def create_site(db: Session, name: str, url: str, client_key: str, client_secret: str, wp_user: str = '', wp_app_password: str = '') -> Site | None:
    try:
        site = Site(
            name=name,
            url=url,
            client_key_encrypted=_encrypt(client_key),
            client_secret_encrypted=_encrypt(client_secret),
            wp_user=wp_user,
            wp_app_password_encrypted=_encrypt(wp_app_password)
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
        "wp_app_password": _decrypt(site.wp_app_password_encrypted)
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
            "wp_app_password": _decrypt(site.wp_app_password_encrypted)
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
        )
        db.add(history)
        db.commit()
        db.refresh(history)
        return history
    except Exception as e:
        db.rollback()
        logger.error(f"Lỗi khi tạo post history: {e}")
        return None

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
        count = db.query(PromptTemplate).count()
        if count == 0:
            prompts_path = Path(__file__).parent.parent / "prompts" / "write_post.txt"
            content = "Default template content"
            if prompts_path.exists():
                with open(prompts_path, "r", encoding="utf-8") as f:
                    content = f.read()
            
            create_template(
                db,
                name="Thiết bị Công nghiệp (Mặc định)",
                content=content,
                category="industrial",
                is_default=True
            )
            logger.info("Đã tạo template mặc định.")
    except Exception as e:
        logger.error(f"Lỗi khi seed default templates: {e}")
