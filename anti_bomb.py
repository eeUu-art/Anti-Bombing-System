import datetime
import random
import re
import string
import logging
from config import Config
from database import (
    db_conn, redis_client, generate_redis_key, encrypt_sensitive_data,
    snowflake_generator, init_db
)

# 配置日志
logger = logging.getLogger(__name__)

class SmsAntiBombSystem:
    def __init__(self):
        # 初始化数据库
        init_db()
    
    def get_scene_strategy(self, scene_id):
        """获取场景策略配置"""
        cursor = db_conn.get_cursor()
        try:
            cursor.execute(f"""
            SELECT * FROM {Config.TABLES['SCENE_STRATEGY']} 
            WHERE scene_id = %s AND status = 1
            """, (scene_id,))
            return cursor.fetchone()
        finally:
            cursor.close()
    
    def get_strategy_rules(self, strategy_ids):
        """获取策略规则列表"""
        cursor = db_conn.get_cursor()
        try:
            placeholders = ','.join(['%s'] * len(strategy_ids))
            cursor.execute(f"""
            SELECT * FROM {Config.TABLES['STRATEGY_RULE']} 
            WHERE strategy_id IN ({placeholders}) AND status = 1
            """, strategy_ids)
            return cursor.fetchall()
        finally:
            cursor.close()
    
    def get_captcha_config(self, scene_code):
        """获取图形验证码配置"""
        cursor = db_conn.get_cursor()
        try:
            cursor.execute(f"""
            SELECT * FROM {Config.TABLES['VERIFY_CODE_CONFIG']} 
            WHERE scene_code = %s AND status = 1
            """, (scene_code,))
            config = cursor.fetchone()
            if not config:
                # 返回默认配置
                return Config.CAPTCHA_DEFAULT_CONFIG.copy()
            return config
        finally:
            cursor.close()
    
    def generate_captcha(self, scene_code, identifier):
        """生成图形验证码"""
        # 获取配置
        config = self.get_captcha_config(scene_code)
        
        # 检查是否已达到错误次数限制
        if self.check_captcha_error_limit(scene_code, identifier, config['max_error_count']):
            return None, '图形验证码错误次数过多，请稍后再试'
        
        # 生成验证码
        if config['char_type'] == '01':
            # 纯数字
            captcha = ''.join(random.choices(string.digits, k=config['length']))
        else:
            # 数字+字母
            captcha = ''.join(random.choices(string.digits + string.ascii_letters, k=config['length']))
        
        # 加密验证码
        encrypted_captcha = encrypt_sensitive_data(captcha)
        
        # 计算过期时间
        generate_time = datetime.datetime.now()
        expire_time = generate_time + datetime.timedelta(seconds=config['expire_seconds'])
        
        # 保存记录
        uuid = snowflake_generator.generate_id()
        encrypted_identifier = encrypt_sensitive_data(identifier)
        
        cursor = db_conn.get_cursor()
        try:
            cursor.execute(f"""
            INSERT INTO {Config.TABLES['VERIFY_CODE_RECORD']} 
            (uuid, scene_code, identifier, encrypt_verify_code, generate_time, expire_time)
            VALUES (%s, %s, %s, %s, %s, %s)
            """, (uuid, scene_code, encrypted_identifier, encrypted_captcha, generate_time, expire_time))
            db_conn.connection.commit()
            
            # 在Redis中缓存验证码（可选，提高校验性能）
            redis_key = generate_redis_key('captcha', scene_code, encrypted_identifier)
            redis_client.setex(redis_key, config['expire_seconds'], encrypted_captcha)
            
            return captcha, uuid
        except Exception as e:
            db_conn.connection.rollback()
            logger.error(f"生成图形验证码失败: {e}")
            return None, '生成图形验证码失败'
        finally:
            cursor.close()
    
    def verify_captcha(self, scene_code, identifier, captcha):
        """校验图形验证码"""
        encrypted_identifier = encrypt_sensitive_data(identifier)
        encrypted_captcha = encrypt_sensitive_data(captcha)
        
        # 先尝试从Redis获取
        redis_key = generate_redis_key('captcha', scene_code, encrypted_identifier)
        redis_captcha = redis_client.get(redis_key)
        
        if redis_captcha and redis_captcha == encrypted_captcha:
            # 验证成功，删除Redis缓存
            redis_client.delete(redis_key)
            return True, ''
        
        # 从数据库查询
        cursor = db_conn.get_cursor()
        try:
            cursor.execute(f"""
            SELECT * FROM {Config.TABLES['VERIFY_CODE_RECORD']} 
            WHERE scene_code = %s AND identifier = %s AND expire_time > NOW()
            ORDER BY generate_time DESC LIMIT 1
            """, (scene_code, encrypted_identifier))
            record = cursor.fetchone()
            
            if not record:
                # 验证码不存在或已过期
                return False, '图形验证码不存在或已过期'
            
            if record['encrypt_verify_code'] == encrypted_captcha:
                # 验证成功
                return True, ''
            else:
                # 验证失败，增加错误次数
                cursor.execute(f"""
                UPDATE {Config.TABLES['VERIFY_CODE_RECORD']} 
                SET error_count = error_count + 1 
                WHERE id = %s
                """, (record['id'],))
                db_conn.connection.commit()
                return False, '图形验证码错误'
        finally:
            cursor.close()
    
    def check_captcha_error_limit(self, scene_code, identifier, max_error_count):
        """检查图形验证码错误次数限制"""
        encrypted_identifier = encrypt_sensitive_data(identifier)
        cursor = db_conn.get_cursor()
        try:
            cursor.execute(f"""
            SELECT SUM(error_count) as total_errors 
            FROM {Config.TABLES['VERIFY_CODE_RECORD']} 
            WHERE scene_code = %s AND identifier = %s 
            AND generate_time > DATE_SUB(NOW(), INTERVAL 1 HOUR)
            """, (scene_code, encrypted_identifier))
            result = cursor.fetchone()
            return result['total_errors'] and result['total_errors'] >= max_error_count
        finally:
            cursor.close()
    
    def check_area_code(self, scene_id, phone_number):
        """检查手机号区号是否允许"""
        scene_strategy = self.get_scene_strategy(scene_id)
        if not scene_strategy:
            return False, '场景不存在或已禁用'
        
        # 提取区号（假设手机号格式为：+8613800138000）
        match = re.match(r'\+?(\d{1,3})(\d+)', phone_number)
        if not match:
            return False, '手机号格式不正确'
        
        area_code = match.group(1)
        allowed_area_codes = scene_strategy['allow_area_codes'].split(',')
        
        if area_code not in allowed_area_codes:
            return False, '手机号区号不允许'
        
        return True, ''
    
    def check_rate_limit(self, scene_id, strategy_id, identifier, max_count, time_unit, time_value):
        """检查频率限制"""
        encrypted_identifier = encrypt_sensitive_data(identifier)
        
        # 使用Redis进行频率计数
        expire_seconds = Config.CACHE_EXPIRATION[time_unit] * time_value
        redis_key = generate_redis_key('sms:freq', scene_id, encrypted_identifier, strategy_id)
        
        # 获取当前计数
        current_count = redis_client.get(redis_key)
        if current_count and int(current_count) >= max_count:
            return False, '发送频率过高，请稍后再试'
        
        # 增加计数
        if not current_count:
            redis_client.setex(redis_key, expire_seconds, 1)
        else:
            redis_client.incr(redis_key)
        
        return True, ''
    
    def check_fail_limit(self, scene_id, strategy_id, identifier, fail_threshold, time_unit, time_value):
        """检查失败次数限制"""
        encrypted_identifier = encrypt_sensitive_data(identifier)
        
        # 检查是否被锁定
        lock_key = generate_redis_key('sms:lock', scene_id, encrypted_identifier, strategy_id)
        if redis_client.exists(lock_key):
            return False, '验证失败次数过多，请稍后再试'
        
        # 检查失败次数
        expire_seconds = Config.CACHE_EXPIRATION[time_unit] * time_value
        fail_key = generate_redis_key('sms:fail', scene_id, encrypted_identifier, strategy_id)
        
        current_fail_count = redis_client.get(fail_key)
        if current_fail_count and int(current_fail_count) >= fail_threshold:
            # 锁定用户
            redis_client.setex(lock_key, expire_seconds, 1)
            return False, '验证失败次数过多，请稍后再试'
        
        return True, ''
    
    def pre_check_sms_request(self, scene_id, identifier, captcha, phone_number=None):
        """短信发送前的预检查"""
        # 1. 校验图形验证码
        if captcha:
            captcha_valid, captcha_msg = self.verify_captcha(scene_id, identifier, captcha)
            if not captcha_valid:
                return False, captcha_msg
        
        # 2. 校验手机号区号（如果提供了手机号）
        if phone_number:
            area_valid, area_msg = self.check_area_code(scene_id, phone_number)
            if not area_valid:
                return False, area_msg
        
        # 3. 获取场景策略
        scene_strategy = self.get_scene_strategy(scene_id)
        if not scene_strategy:
            return False, '场景不存在或已禁用'
        
        # 4. 获取策略规则
        strategy_ids = scene_strategy['strategy_types'].split(',')
        rules = self.get_strategy_rules(strategy_ids)
        
        # 5. 检查所有规则
        for rule in rules:
            if rule['strategy_type'] == '01':
                # 频率类规则
                valid, msg = self.check_rate_limit(
                    scene_id, rule['strategy_id'], identifier,
                    rule['max_count'], rule['time_unit'], rule['time_value']
                )
                if not valid:
                    return False, msg
            elif rule['strategy_type'] == '02':
                # 失败次数类规则
                valid, msg = self.check_fail_limit(
                    scene_id, rule['strategy_id'], identifier,
                    rule['fail_threshold'], rule['time_unit'], rule['time_value']
                )
                if not valid:
                    return False, msg
        
        # 6. 记录短信请求
        self.record_sms_request(scene_id, identifier, strategy_ids)
        
        return True, '验证通过'
    
    def record_sms_request(self, scene_id, identifier, strategy_ids):
        """记录短信请求"""
        encrypted_identifier = encrypt_sensitive_data(identifier)
        current_time = datetime.datetime.now()
        time_minute = current_time.strftime('%Y-%m-%d %H:%M')
        
        for strategy_id in strategy_ids:
            # 生成19位UUID
            uuid = snowflake_generator.generate_id()
            
            # 计算窗口结束时间（创建时间 + 25小时）
            window_end_time = current_time + datetime.timedelta(hours=25)
            
            cursor = db_conn.get_cursor()
            try:
                # 尝试更新已存在的记录
                cursor.execute(f"""
                UPDATE {Config.TABLES['STRATEGY_RULE_DETAIL']} 
                SET sms_req_count = sms_req_count + 1, update_time = NOW()
                WHERE scene_id = %s AND strategy_id = %s AND identifier = %s AND time_minute = %s
                """, (scene_id, strategy_id, encrypted_identifier, time_minute))
                
                if cursor.rowcount == 0:
                    # 不存在则插入新记录
                    cursor.execute(f"""
                    INSERT INTO {Config.TABLES['STRATEGY_RULE_DETAIL']} 
                    (uuid, scene_id, strategy_id, identifier, sms_req_count, time_minute, window_end_time)
                    VALUES (%s, %s, %s, %s, 1, %s, %s)
                    """, (uuid, scene_id, strategy_id, encrypted_identifier, time_minute, window_end_time))
                
                db_conn.connection.commit()
            except Exception as e:
                logger.error(f"记录短信请求失败: {e}")
                db_conn.connection.rollback()
            finally:
                cursor.close()
    
    def record_verify_failure(self, scene_id, identifier, strategy_ids):
        """记录验证失败"""
        encrypted_identifier = encrypt_sensitive_data(identifier)
        
        for strategy_id in strategy_ids:
            # 在Redis中增加失败计数
            fail_key = generate_redis_key('sms:fail', scene_id, encrypted_identifier, strategy_id)
            redis_client.incr(fail_key)
            
            # 查询对应的规则获取过期时间
            cursor = db_conn.get_cursor()
            try:
                cursor.execute(f"""
                SELECT time_unit, time_value FROM {Config.TABLES['STRATEGY_RULE']} 
                WHERE strategy_id = %s
                """, (strategy_id,))
                rule = cursor.fetchone()
                if rule:
                    expire_seconds = Config.CACHE_EXPIRATION[rule['time_unit']] * rule['time_value']
                    redis_client.expire(fail_key, expire_seconds)
                
                # 更新数据库记录
                current_time = datetime.datetime.now()
                time_minute = current_time.strftime('%Y-%m-%d %H:%M')
                
                cursor.execute(f"""
                UPDATE {Config.TABLES['STRATEGY_RULE_DETAIL']} 
                SET error_count = error_count + 1, update_time = NOW()
                WHERE scene_id = %s AND strategy_id = %s AND identifier = %s AND time_minute = %s
                """, (scene_id, strategy_id, encrypted_identifier, time_minute))
                
                db_conn.connection.commit()
            except Exception as e:
                logger.error(f"记录验证失败失败: {e}")
                db_conn.connection.rollback()
            finally:
                cursor.close()
    
    def reset_counts_on_success(self, scene_id, identifier):
        """验证成功后重置计数"""
        # 获取场景策略
        scene_strategy = self.get_scene_strategy(scene_id)
        if not scene_strategy or scene_strategy['success_reset_flag'] != 1:
            return
        
        encrypted_identifier = encrypt_sensitive_data(identifier)
        strategy_ids = scene_strategy['strategy_types'].split(',')
        
        # 清除Redis中的计数
        for strategy_id in strategy_ids:
            freq_key = generate_redis_key('sms:freq', scene_id, encrypted_identifier, strategy_id)
            fail_key = generate_redis_key('sms:fail', scene_id, encrypted_identifier, strategy_id)
            lock_key = generate_redis_key('sms:lock', scene_id, encrypted_identifier, strategy_id)
            
            redis_client.delete(freq_key, fail_key, lock_key)
        
        # 更新数据库记录
        cursor = db_conn.get_cursor()
        try:
            placeholders = ','.join(['%s'] * len(strategy_ids))
            cursor.execute(f"""
            UPDATE {Config.TABLES['STRATEGY_RULE_DETAIL']} 
            SET sms_req_count = 0, error_count = 0, update_time = NOW()
            WHERE scene_id = %s AND strategy_id IN ({placeholders}) AND identifier = %s
            """, (scene_id,) + tuple(strategy_ids) + (encrypted_identifier,))
            
            db_conn.connection.commit()
        except Exception as e:
            logger.error(f"重置计数失败: {e}")
            db_conn.connection.rollback()
        finally:
            cursor.close()
    
    def cleanup_old_records(self):
        """清理历史记录（含敏感数据脱敏与日志归档）"""
        cursor = db_conn.get_cursor()
        try:
            # 1. 日志归档：将即将删除的记录备份到归档表
            verify_code_days = int(Config.CLEANUP_CONFIG.get('VERIFY_CODE_RETENTION_DAYS', 3))
            rule_detail_days = int(Config.CLEANUP_CONFIG.get('RULE_DETAIL_RETENTION_DAYS', 3))
            
            # 创建归档表（如果不存在）
            archive_tables = [
                f"""CREATE TABLE IF NOT EXISTS {Config.TABLES['VERIFY_CODE_RECORD']}_archive AS 
                SELECT * FROM {Config.TABLES['VERIFY_CODE_RECORD']} WHERE 1=0""",
                f"""CREATE TABLE IF NOT EXISTS {Config.TABLES['STRATEGY_RULE_DETAIL']}_archive AS 
                SELECT * FROM {Config.TABLES['STRATEGY_RULE_DETAIL']} WHERE 1=0"""
            ]
            for sql in archive_tables:
                try:
                    cursor.execute(sql)
                except Exception:
                    pass  # 表已存在时忽略错误
            
            # 归档即将过期的验证码记录
            cursor.execute(f"""
            INSERT INTO {Config.TABLES['VERIFY_CODE_RECORD']}_archive 
            SELECT * FROM {Config.TABLES['VERIFY_CODE_RECORD']} 
            WHERE create_time < date('now', '-{verify_code_days} days')
            """)
            verify_archived = cursor.rowcount
            
            # 归档即将过期的规则详情记录
            cursor.execute(f"""
            INSERT INTO {Config.TABLES['STRATEGY_RULE_DETAIL']}_archive 
            SELECT * FROM {Config.TABLES['STRATEGY_RULE_DETAIL']} 
            WHERE window_end_time < date('now', '-{rule_detail_days} days')
            """)
            rule_archived = cursor.rowcount
            
            # 2. 敏感数据脱敏：对归档表中的 identifier 进行脱敏处理
            # 保留前3位和后4位，中间用*替换
            cursor.execute(f"""
            UPDATE {Config.TABLES['VERIFY_CODE_RECORD']}_archive 
            SET identifier = substr(identifier, 1, 3) || '****' || substr(identifier, -4)
            WHERE LENGTH(identifier) > 7
            """)
            cursor.execute(f"""
            UPDATE {Config.TABLES['STRATEGY_RULE_DETAIL']}_archive 
            SET identifier = substr(identifier, 1, 3) || '****' || substr(identifier, -4)
            WHERE LENGTH(identifier) > 7
            """)
            
            # 3. 清理原始表中的过期记录
            cursor.execute(f"""
            DELETE FROM {Config.TABLES['VERIFY_CODE_RECORD']} 
            WHERE create_time < date('now', '-{verify_code_days} days')
            """)
            verify_deleted = cursor.rowcount
            
            cursor.execute(f"""
            DELETE FROM {Config.TABLES['STRATEGY_RULE_DETAIL']} 
            WHERE window_end_time < date('now', '-{rule_detail_days} days')
            """)
            rule_deleted = cursor.rowcount
            
            db_conn.connection.commit()
            total_archived = verify_archived + rule_archived
            total_deleted = verify_deleted + rule_deleted
            msg = f"归档{total_archived}条记录（已脱敏），清理{total_deleted}条历史记录"
            logger.info(f"清理任务执行成功: {msg}")
            return msg
        except Exception as e:
            logger.error(f"清理历史记录失败: {e}")
            db_conn.connection.rollback()
            return f"清理失败: {str(e)}"
        finally:
            cursor.close()

# 创建系统实例
anti_bomb_system = SmsAntiBombSystem()

# 导出主要方法
def generate_captcha(scene_code, identifier):
    return anti_bomb_system.generate_captcha(scene_code, identifier)

def verify_captcha(scene_code, identifier, captcha):
    return anti_bomb_system.verify_captcha(scene_code, identifier, captcha)

def pre_check_sms_request(scene_id, identifier, captcha, phone_number=None):
    return anti_bomb_system.pre_check_sms_request(scene_id, identifier, captcha, phone_number)

def record_verify_failure(scene_id, identifier, strategy_ids=None):
    if not strategy_ids:
        # 如果没有提供策略ID，从场景中获取
        scene_strategy = anti_bomb_system.get_scene_strategy(scene_id)
        if scene_strategy:
            strategy_ids = scene_strategy['strategy_types'].split(',')
    return anti_bomb_system.record_verify_failure(scene_id, identifier, strategy_ids)

def reset_counts_on_success(scene_id, identifier):
    return anti_bomb_system.reset_counts_on_success(scene_id, identifier)

def cleanup_old_records():
    return anti_bomb_system.cleanup_old_records()