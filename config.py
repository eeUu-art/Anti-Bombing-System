import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

class Config:
    # 应用基础配置
    SECRET_KEY = os.environ.get('SECRET_KEY')
    DEBUG = os.environ.get('DEBUG', 'False').lower() == 'true'
    
    # Redis配置
    REDIS_URL = os.environ.get('REDIS_URL') or 'redis://localhost:6379/0'
    
    # 数据库配置 - 修改为使用SQLite数据库
    DB_CONNECTION_STRING = os.environ.get('DB_CONNECTION_STRING') or 'mysql://root:root123@127.0.0.1:3306/anti_bomb_db'  # MySQL数据库连接
    
    # 缓存配置
    CACHE_EXPIRATION = {
        'MINUTE': 60,
        'HOUR': 3600,
        'DAY': 86400
    }
    
    # 数据库表名配置
    TABLES = {
        'SCENE_STRATEGY': 'sys_sms_scene_strategy',
        'STRATEGY_RULE': 'sys_sms_strategy_rule',
        'STRATEGY_RULE_DETAIL': 'sys_sms_strategy_rule_detail',
        'VERIFY_CODE_CONFIG': 'sys_verify_code_config',
        'VERIFY_CODE_RECORD': 'sys_verify_code_record',
        'SYS_USER': 'sys_user'
    }
    
    # 图形验证码配置
    CAPTCHA_DEFAULT_CONFIG = {
        'char_type': '02',  # 数字+字母
        'length': 4,
        'expire_seconds': 300,  # 5分钟
        'max_error_count': 5
    }
    
    # 记录清理配置
    CLEANUP_CONFIG = {
        'VERIFY_CODE_RETENTION_DAYS': 3,
        'RULE_DETAIL_RETENTION_DAYS': 3,
        'CLEANUP_SCHEDULE': '0 2 * * *'  # 每天凌晨2点执行
    }
    
    # 加密配置
    ENCRYPTION_CONFIG = {
        'algorithm': 'AES',
        'key': os.environ.get('ENCRYPTION_KEY')
    }