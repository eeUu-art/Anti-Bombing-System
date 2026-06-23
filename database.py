"""数据库连接模块 - 支持 SQLite 和 MySQL"""
try:
    import redis
except ImportError:
    redis = None
import sqlite3
import pymysql
from dbutils.pooled_db import PooledDB
from config import Config
import re
import hashlib
import logging

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Redis连接配置
class MockRedis:
    """Redis不可用时的模拟类"""
    def __init__(self):
        self.data = {}
    
    def set(self, key, value, ex=None):
        self.data[key] = value
        return True
    
    def get(self, key):
        return self.data.get(key)
    
    def delete(self, key):
        if key in self.data:
            del self.data[key]
        return 1 if key in self.data else 0
    
    def exists(self, key):
        return 1 if key in self.data else 0
    
    def expire(self, key, seconds):
        return True
    
    def incr(self, key):
        if key not in self.data:
            self.data[key] = 0
        self.data[key] = int(self.data[key]) + 1
        return self.data[key]
    
    def hset(self, name, key, value):
        if name not in self.data:
            self.data[name] = {}
        self.data[name][key] = value
        return 1
    
    def hget(self, name, key):
        if name in self.data and key in self.data[name]:
            return self.data[name][key]
        return None
    
    def hdel(self, name, key):
        if name in self.data and key in self.data[name]:
            del self.data[name][key]
        return 1
    
    def hgetall(self, name):
        return self.data.get(name, {})

# 创建Redis客户端或Mock对象
if redis:
    try:
        redis_client = redis.Redis(
            host='localhost',
            port=6379,
            db=0,
            decode_responses=True,
            protocol=2  # 使用 RESP2 协议兼容 Redis 3.x
        )
        redis_client.ping()
        logger.info("Redis连接成功")
    except Exception as e:
        logger.warning(f"Redis连接失败，使用MockRedis: {e}")
        redis_client = MockRedis()
else:
    logger.warning("Redis模块未安装，使用MockRedis")
    redis_client = MockRedis()

# 数据库连接配置
class DatabaseConnection:
    def __init__(self):
        self.connection = None
        self.db_type = 'sqlite'  # 'sqlite' or 'mysql'
        self.db_path = None
        self.mysql_pool = None
        self.parse_connection_string()
        self.connect()
    
    def parse_connection_string(self):
        conn_str = Config.DB_CONNECTION_STRING
        if conn_str.startswith('sqlite:///'):
            self.db_type = 'sqlite'
            self.db_path = conn_str.replace('sqlite:///', '')
            logger.info(f"使用SQLite数据库: {self.db_path}")
        elif conn_str.startswith('mysql://') or conn_str.startswith('mysql+pymysql://'):
            self.db_type = 'mysql'
            # 解析MySQL连接字符串: mysql://user:pass@host:port/dbname
            pattern = r'mysql(?:\+pymysql)?://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)'
            match = re.match(pattern, conn_str)
            if match:
                self.mysql_config = {
                    'host': match.group(3),
                    'port': int(match.group(4)),
                    'user': match.group(1),
                    'password': match.group(2),
                    'database': match.group(5),
                    'charset': 'utf8mb4',
                    'cursorclass': pymysql.cursors.DictCursor
                }
                logger.info(f"使用MySQL数据库: {match.group(3)}:{match.group(4)}/{match.group(5)}")
            else:
                logger.error("无效的MySQL连接字符串格式")
                self.db_type = 'sqlite'
                self.db_path = 'anti_bomb.db'
        else:
            logger.error("无效的数据库连接字符串格式，默认使用SQLite")
            self.db_type = 'sqlite'
            self.db_path = 'anti_bomb.db'
    
    def connect(self):
        try:
            if self.db_type == 'sqlite':
                self.connection = sqlite3.connect(
                    self.db_path,
                    check_same_thread=False,
                    timeout=10
                )
                self.connection.execute("PRAGMA foreign_keys = ON")
                logger.info("SQLite数据库连接成功")
            elif self.db_type == 'mysql':
                # 使用DBUtils连接池
                self.mysql_pool = PooledDB(
                    creator=pymysql,
                    mincached=2,
                    maxcached=10,
                    maxconnections=20,
                    blocking=True,
                    **self.mysql_config
                )
                # 测试连接
                conn = self.mysql_pool.connection()
                conn.close()
                logger.info("MySQL连接池创建成功")
        except Exception as e:
            logger.error(f"数据库连接失败: {e}")
            self.connection = None
            self.mysql_pool = None
    
    def get_cursor(self):
        if self.db_type == 'sqlite':
            if not self.connection:
                self.connect()
            if self.connection:
                try:
                    return self.connection.cursor()
                except Exception as e:
                    logger.error(f"获取SQLite游标失败: {e}")
                    return None
        elif self.db_type == 'mysql':
            if not self.mysql_pool:
                self.connect()
            if self.mysql_pool:
                try:
                    conn = self.mysql_pool.connection()
                    return conn.cursor()
                except Exception as e:
                    logger.error(f"获取MySQL游标失败: {e}")
                    return None
        return None
    
    def get_connection(self):
        """获取数据库连接（用于事务管理）"""
        if self.db_type == 'sqlite':
            return self.connection
        elif self.db_type == 'mysql':
            if self.mysql_pool:
                return self.mysql_pool.connection()
        return None
    
    def close(self):
        if self.db_type == 'sqlite' and self.connection:
            try:
                self.connection.close()
                logger.info("SQLite数据库连接已关闭")
            except Exception as e:
                logger.error(f"关闭SQLite连接失败: {e}")
            finally:
                self.connection = None
        elif self.db_type == 'mysql' and self.mysql_pool:
            try:
                self.mysql_pool.closeall()
                logger.info("MySQL连接池已关闭")
            except Exception as e:
                logger.error(f"关闭MySQL连接池失败: {e}")
            finally:
                self.mysql_pool = None

# 创建全局数据库连接实例
db_conn = DatabaseConnection()

# Redis Key生成工具
def generate_redis_key(prefix, *args):
    """生成Redis键"""
    parts = [prefix] + [str(arg) for arg in args]
    return ":".join(parts)

# 数据加密工具
def encrypt_sensitive_data(data):
    """加密敏感数据"""
    return hashlib.sha256((data + Config.ENCRYPTION_CONFIG['key']).encode()).hexdigest()

# 雪花算法ID生成器
class SnowflakeIDGenerator:
    def __init__(self, datacenter_id=1, worker_id=1):
        self.datacenter_id = datacenter_id
        self.worker_id = worker_id
        self.sequence = 0
        self.last_timestamp = -1
        self.max_sequence = 4095
        self.timestamp_left_shift = 22
        self.datacenter_id_shift = 17
        self.worker_id_shift = 12
    
    def _get_timestamp(self):
        import time
        return int(time.time() * 1000)
    
    def generate_id(self):
        timestamp = self._get_timestamp()
        
        if timestamp < self.last_timestamp:
            raise ValueError("时间戳回退")
        
        if timestamp == self.last_timestamp:
            self.sequence = (self.sequence + 1) & self.max_sequence
            if self.sequence == 0:
                while timestamp <= self.last_timestamp:
                    timestamp = self._get_timestamp()
        else:
            self.sequence = 0
        
        self.last_timestamp = timestamp
        
        snowflake_id = ((timestamp - 1609459200000) << self.timestamp_left_shift) | \
                      (self.datacenter_id << self.datacenter_id_shift) | \
                      (self.worker_id << self.worker_id_shift) | \
                      self.sequence
        
        return str(snowflake_id)

# 创建雪花ID生成器实例
snowflake_generator = SnowflakeIDGenerator()

# MySQL 建表语句（与 SQLite 语法略有不同）
MYSQL_TABLES = {
    'SCENE_STRATEGY': """
    CREATE TABLE IF NOT EXISTS {table} (
        scene_id VARCHAR(3) PRIMARY KEY,
        scene_name VARCHAR(100) NOT NULL,
        strategy_types VARCHAR(200) NOT NULL,
        allow_area_codes VARCHAR(200) NOT NULL,
        success_reset_flag TINYINT DEFAULT 0,
        status TINYINT DEFAULT 1,
        create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
        update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    'STRATEGY_RULE': """
    CREATE TABLE IF NOT EXISTS {table} (
        strategy_id VARCHAR(3) PRIMARY KEY,
        strategy_name VARCHAR(100) NOT NULL,
        strategy_type VARCHAR(2) NOT NULL,
        time_unit VARCHAR(10) NOT NULL,
        time_value INT NOT NULL,
        max_count INT DEFAULT NULL,
        fail_threshold INT DEFAULT NULL,
        status TINYINT DEFAULT 1,
        create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
        update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    'STRATEGY_RULE_DETAIL': """
    CREATE TABLE IF NOT EXISTS {table} (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        uuid VARCHAR(19) NOT NULL,
        scene_id VARCHAR(3) NOT NULL,
        strategy_id VARCHAR(3) NOT NULL,
        identifier VARCHAR(100) NOT NULL,
        sms_req_count INT DEFAULT 0,
        error_count INT DEFAULT 0,
        time_minute VARCHAR(16) NOT NULL,
        window_end_time DATETIME NOT NULL,
        create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
        update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    'VERIFY_CODE_CONFIG': """
    CREATE TABLE IF NOT EXISTS {table} (
        scene_code VARCHAR(3) PRIMARY KEY,
        char_type VARCHAR(2) DEFAULT '02',
        length INT DEFAULT 4,
        expire_seconds INT DEFAULT 300,
        max_error_count INT DEFAULT 5,
        status TINYINT DEFAULT 1,
        create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
        update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    'VERIFY_CODE_RECORD': """
    CREATE TABLE IF NOT EXISTS {table} (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        uuid VARCHAR(19) NOT NULL,
        scene_code VARCHAR(3) NOT NULL,
        identifier VARCHAR(100) NOT NULL,
        encrypt_verify_code VARCHAR(100) NOT NULL,
        error_count INT DEFAULT 0,
        generate_time DATETIME NOT NULL,
        expire_time DATETIME NOT NULL,
        create_time DATETIME DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
}

# 初始化数据库表结构
def init_tables():
    """初始化数据库表结构"""
    cursor = db_conn.get_cursor()
    if cursor is None:
        logger.error("无法获取数据库游标，初始化表结构失败")
        return False
    
    try:
        if db_conn.db_type == 'sqlite':
            _init_sqlite_tables(cursor)
        elif db_conn.db_type == 'mysql':
            _init_mysql_tables(cursor)
        
        logger.info("数据库表结构初始化完成")
        return True
    except Exception as e:
        logger.error(f"初始化数据库表失败: {e}")
        if db_conn.db_type == 'sqlite' and db_conn.connection:
            db_conn.connection.rollback()
        return False
    finally:
        cursor.close()

def _init_sqlite_tables(cursor):
    """初始化 SQLite 表"""
    # 创建场景策略表
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS {Config.TABLES['SCENE_STRATEGY']} (
        scene_id VARCHAR(3) PRIMARY KEY,
        scene_name VARCHAR(100) NOT NULL,
        strategy_types VARCHAR(200) NOT NULL,
        allow_area_codes VARCHAR(200) NOT NULL,
        success_reset_flag INTEGER DEFAULT 0,
        status INTEGER DEFAULT 1,
        create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
        update_time DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # 创建策略规则表
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS {Config.TABLES['STRATEGY_RULE']} (
        strategy_id VARCHAR(3) PRIMARY KEY,
        strategy_name VARCHAR(100) NOT NULL,
        strategy_type VARCHAR(2) NOT NULL,
        time_unit VARCHAR(10) NOT NULL,
        time_value INTEGER NOT NULL,
        max_count INTEGER,
        fail_threshold INTEGER,
        status INTEGER DEFAULT 1,
        create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
        update_time DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # 创建规则详情表
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS {Config.TABLES['STRATEGY_RULE_DETAIL']} (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        uuid VARCHAR(19) NOT NULL,
        scene_id VARCHAR(3) NOT NULL,
        strategy_id VARCHAR(3) NOT NULL,
        identifier VARCHAR(100) NOT NULL,
        sms_req_count INTEGER DEFAULT 0,
        error_count INTEGER DEFAULT 0,
        time_minute VARCHAR(16) NOT NULL,
        window_end_time DATETIME NOT NULL,
        create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
        update_time DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # 创建索引（SQLite中单独创建）
    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_identifier ON {Config.TABLES['STRATEGY_RULE_DETAIL']} (identifier)")
    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_scene_strategy ON {Config.TABLES['STRATEGY_RULE_DETAIL']} (scene_id, strategy_id)")
    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_window_end ON {Config.TABLES['STRATEGY_RULE_DETAIL']} (window_end_time)")
    
    # 创建图形验证码配置表
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS {Config.TABLES['VERIFY_CODE_CONFIG']} (
        scene_code VARCHAR(3) PRIMARY KEY,
        char_type VARCHAR(2) DEFAULT '02',
        length INTEGER DEFAULT 4,
        expire_seconds INTEGER DEFAULT 300,
        max_error_count INTEGER DEFAULT 5,
        status INTEGER DEFAULT 1,
        create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
        update_time DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # 创建图形验证码记录表
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS {Config.TABLES['VERIFY_CODE_RECORD']} (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        uuid VARCHAR(19) NOT NULL,
        scene_code VARCHAR(3) NOT NULL,
        identifier VARCHAR(100) NOT NULL,
        encrypt_verify_code VARCHAR(100) NOT NULL,
        error_count INTEGER DEFAULT 0,
        generate_time DATETIME NOT NULL,
        expire_time DATETIME NOT NULL,
        create_time DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # 创建索引
    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_identifier_scene ON {Config.TABLES['VERIFY_CODE_RECORD']} (identifier, scene_code)")
    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_create_time ON {Config.TABLES['VERIFY_CODE_RECORD']} (create_time)")
    
    # 创建系统用户表（JWT 权限管控）
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS {Config.TABLES['SYS_USER']} (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username VARCHAR(50) UNIQUE NOT NULL,
        password_hash VARCHAR(255) NOT NULL,
        role VARCHAR(20) NOT NULL DEFAULT 'operator',  -- admin/operator
        status INTEGER DEFAULT 1,  -- 1-启用, 0-禁用
        create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
        update_time DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    if db_conn.connection:
        db_conn.connection.commit()

def _init_mysql_tables(cursor):
    """初始化 MySQL 表（含联合索引优化）"""
    # 创建场景策略表
    cursor.execute(MYSQL_TABLES['SCENE_STRATEGY'].format(table=Config.TABLES['SCENE_STRATEGY']))
    
    # 创建策略规则表
    cursor.execute(MYSQL_TABLES['STRATEGY_RULE'].format(table=Config.TABLES['STRATEGY_RULE']))
    
    # 创建规则详情表
    cursor.execute(MYSQL_TABLES['STRATEGY_RULE_DETAIL'].format(table=Config.TABLES['STRATEGY_RULE_DETAIL']))
    
    # MySQL 联合索引优化高频查询
    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_scene_identifier ON {Config.TABLES['STRATEGY_RULE_DETAIL']} (scene_id, identifier)")
    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_scene_strategy_window ON {Config.TABLES['STRATEGY_RULE_DETAIL']} (scene_id, strategy_id, window_end_time)")
    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_identifier_time ON {Config.TABLES['STRATEGY_RULE_DETAIL']} (identifier, time_minute)")
    
    # 创建图形验证码配置表
    cursor.execute(MYSQL_TABLES['VERIFY_CODE_CONFIG'].format(table=Config.TABLES['VERIFY_CODE_CONFIG']))
    
    # 创建图形验证码记录表
    cursor.execute(MYSQL_TABLES['VERIFY_CODE_RECORD'].format(table=Config.TABLES['VERIFY_CODE_RECORD']))
    
    # MySQL 联合索引优化验证码查询
    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_scene_identifier ON {Config.TABLES['VERIFY_CODE_RECORD']} (scene_code, identifier)")
    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_identifier_expire ON {Config.TABLES['VERIFY_CODE_RECORD']} (identifier, expire_time)")
    
    # 创建系统用户表（JWT 权限管控）
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS {Config.TABLES['SYS_USER']} (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        username VARCHAR(50) UNIQUE NOT NULL,
        password_hash VARCHAR(255) NOT NULL,
        role VARCHAR(20) NOT NULL DEFAULT 'operator',
        status TINYINT DEFAULT 1,
        create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
        update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """)
    
    # 提交事务
    conn = db_conn.get_connection()
    if conn:
        conn.commit()
        if hasattr(conn, 'close'):
            conn.close()

# 初始化数据库
def init_db():
    if init_tables():
        add_default_data()
    else:
        logger.error("数据库表初始化失败，跳过默认数据添加")

def add_default_data():
    """添加默认数据"""
    cursor = db_conn.get_cursor()
    try:
        if db_conn.db_type == 'sqlite':
            cursor.execute(f"SELECT COUNT(*) FROM {Config.TABLES['SCENE_STRATEGY']}")
            if cursor.fetchone()[0] == 0:
                cursor.execute(f"""
                INSERT INTO {Config.TABLES['SCENE_STRATEGY']} (scene_id, scene_name, strategy_types, allow_area_codes, success_reset_flag)
                VALUES (?, ?, ?, ?, ?),
                       (?, ?, ?, ?, ?)
                """, ('001', '登录场景', '001,002', '86', 0, '002', '注册场景', '001,003', '86', 1))
            
            cursor.execute(f"SELECT COUNT(*) FROM {Config.TABLES['STRATEGY_RULE']}")
            if cursor.fetchone()[0] == 0:
                cursor.execute(f"""
                INSERT INTO {Config.TABLES['STRATEGY_RULE']} (strategy_id, strategy_name, strategy_type, time_unit, time_value, max_count, fail_threshold)
                VALUES (?, ?, ?, ?, ?, ?, ?),
                       (?, ?, ?, ?, ?, ?, ?),
                       (?, ?, ?, ?, ?, ?, ?)
                """, ('001', '5分钟频率限制', '01', 'MINUTE', 5, 5, None, 
                       '002', '1小时频率限制', '01', 'HOUR', 1, 20, None, 
                       '003', '5分钟失败次数限制', '02', 'MINUTE', 5, None, 3))
            
            cursor.execute(f"SELECT COUNT(*) FROM {Config.TABLES['VERIFY_CODE_CONFIG']}")
            if cursor.fetchone()[0] == 0:
                cursor.execute(f"""
                INSERT INTO {Config.TABLES['VERIFY_CODE_CONFIG']} (scene_code, char_type, length, expire_seconds, max_error_count)
                VALUES (?, ?, ?, ?, ?),
                       (?, ?, ?, ?, ?)
                """, ('001', '02', 4, 300, 5, '002', '02', 4, 300, 5))
            
            # 添加默认系统用户（密码使用 SHA256 哈希）
            cursor.execute(f"SELECT COUNT(*) FROM {Config.TABLES['SYS_USER']}")
            if cursor.fetchone()[0] == 0:
                admin_hash = hashlib.sha256('admin123'.encode()).hexdigest()
                operator_hash = hashlib.sha256('operator123'.encode()).hexdigest()
                cursor.execute(f"""
                INSERT INTO {Config.TABLES['SYS_USER']} (username, password_hash, role)
                VALUES (?, ?, ?),
                       (?, ?, ?)
                """, ('admin', admin_hash, 'admin', 'operator', operator_hash, 'operator'))
        
        elif db_conn.db_type == 'mysql':
            cursor.execute(f"SELECT COUNT(*) as cnt FROM {Config.TABLES['SCENE_STRATEGY']}")
            if cursor.fetchone()['cnt'] == 0:
                cursor.execute(f"""
                INSERT INTO {Config.TABLES['SCENE_STRATEGY']} (scene_id, scene_name, strategy_types, allow_area_codes, success_reset_flag)
                VALUES (%s, %s, %s, %s, %s),
                       (%s, %s, %s, %s, %s)
                """, ('001', '登录场景', '001,002', '86', 0, '002', '注册场景', '001,003', '86', 1))
            
            cursor.execute(f"SELECT COUNT(*) as cnt FROM {Config.TABLES['STRATEGY_RULE']}")
            if cursor.fetchone()['cnt'] == 0:
                cursor.execute(f"""
                INSERT INTO {Config.TABLES['STRATEGY_RULE']} (strategy_id, strategy_name, strategy_type, time_unit, time_value, max_count, fail_threshold)
                VALUES (%s, %s, %s, %s, %s, %s, %s),
                       (%s, %s, %s, %s, %s, %s, %s),
                       (%s, %s, %s, %s, %s, %s, %s)
                """, ('001', '5分钟频率限制', '01', 'MINUTE', 5, 5, None, 
                       '002', '1小时频率限制', '01', 'HOUR', 1, 20, None, 
                       '003', '5分钟失败次数限制', '02', 'MINUTE', 5, None, 3))
            
            cursor.execute(f"SELECT COUNT(*) as cnt FROM {Config.TABLES['VERIFY_CODE_CONFIG']}")
            if cursor.fetchone()['cnt'] == 0:
                cursor.execute(f"""
                INSERT INTO {Config.TABLES['VERIFY_CODE_CONFIG']} (scene_code, char_type, length, expire_seconds, max_error_count)
                VALUES (%s, %s, %s, %s, %s),
                       (%s, %s, %s, %s, %s)
                """, ('001', '02', 4, 300, 5, '002', '02', 4, 300, 5))
            
            # 添加默认系统用户
            cursor.execute(f"SELECT COUNT(*) as cnt FROM {Config.TABLES['SYS_USER']}")
            if cursor.fetchone()['cnt'] == 0:
                admin_hash = hashlib.sha256('admin123'.encode()).hexdigest()
                operator_hash = hashlib.sha256('operator123'.encode()).hexdigest()
                cursor.execute(f"""
                INSERT INTO {Config.TABLES['SYS_USER']} (username, password_hash, role)
                VALUES (%s, %s, %s),
                       (%s, %s, %s)
                """, ('admin', admin_hash, 'admin', 'operator', operator_hash, 'operator'))
        
        conn = db_conn.get_connection()
        if conn:
            conn.commit()
            # 注意：不要关闭主连接，它会被其他操作继续使用
        logger.info("默认数据添加成功")
    except Exception as e:
        logger.error(f"添加默认数据失败: {e}")
        if db_conn.db_type == 'sqlite' and db_conn.connection:
            db_conn.connection.rollback()
    finally:
        try:
            cursor.close()
        except Exception:
            pass
