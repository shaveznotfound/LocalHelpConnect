import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'localhelp-secret-key-v6-change-in-production')
    DB_HOST     = os.environ.get('DB_HOST', 'localhost')
    DB_USER     = os.environ.get('DB_USER', 'root')
    DB_PASSWORD = os.environ.get('DB_PASSWORD', 'Shah@#1909')
    DB_NAME     = os.environ.get('DB_NAME', 'lhc_v7')
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
    MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB
    ALLOWED_IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp', 'gif'}
    ALLOWED_FILE_EXTENSIONS  = {'jpg', 'jpeg', 'png', 'webp', 'gif', 'pdf', 'doc', 'docx', 'txt', 'zip'}
