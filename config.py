import os
from datetime import timedelta

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'estacle-dev-secret-key-change-in-production-2024'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(BASE_DIR, 'instance', 'estacle.sqlite')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
    }
    
    # Session
    PERMANENT_SESSION_LIFETIME = timedelta(days=30)
    SESSION_COOKIE_SECURE = False  # Set True in production with HTTPS
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_DURATION = timedelta(days=30)
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SECURE = False
    
    # Uploads
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
    MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100 MB
    ALLOWED_EXTENSIONS = {
        'image': {'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp'},
        'video': {'mp4', 'webm', 'mov', 'avi', 'mkv'},
        'audio': {'mp3', 'wav', 'ogg', 'webm', 'm4a', 'aac'},
        'document': {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'csv'},
        'archive': {'zip', 'rar', '7z', 'tar', 'gz'},
        'other': {'json', 'xml', 'html', 'css', 'js'}
    }
    
    # WebRTC STUN/TURN
    WEBRTC_STUN_SERVERS = [
        {'urls': 'stun:stun.l.google.com:19302'},
        {'urls': 'stun:stun1.l.google.com:19302'},
        {'urls': 'stun:stun2.l.google.com:19302'},
    ]
    WEBRTC_TURN_SERVERS = []  # Add TURN servers for production
    
    # Web Push (VAPID)
    VAPID_PRIVATE_KEY = os.environ.get('VAPID_PRIVATE_KEY') or None
    VAPID_PUBLIC_KEY = os.environ.get('VAPID_PUBLIC_KEY') or None
    VAPID_CLAIMS = {'sub': 'mailto:admin@estacle.app'}
    
    # Rate limiting
    RATELIMIT_DEFAULT = "200 per hour"
    RATELIMIT_STORAGE_URL = "memory://"
    
    # App
    APP_NAME = "ESTACLE"
    APP_VERSION = "1.0.0"
    ITEMS_PER_PAGE = 50
    MESSAGE_PAGE_SIZE = 40
    
    # CSRF
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600

class DevelopmentConfig(Config):
    DEBUG = True
    TESTING = False

class ProductionConfig(Config):
    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True

class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False

config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}
