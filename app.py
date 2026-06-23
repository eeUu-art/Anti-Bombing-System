# 基础导入 - 确保核心功能可用
import hashlib
import logging
import random
import sys

# 立即配置日志，确保所有环境下都能记录日志
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 定义全局标志
APSCHEDULER_AVAILABLE = False

# 核心模块导入
try:
    from flask import Flask, request, jsonify
    from flask.json.provider import DefaultJSONProvider
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False
    logger.error("Flask模块导入失败！")

try:
    from config import Config
    CONFIG_AVAILABLE = True
except ImportError:
    CONFIG_AVAILABLE = False
    logger.warning("Config模块导入失败，使用默认配置")

try:
    # 尝试导入anti_bomb模块中的函数
    from anti_bomb import (
        generate_captcha, verify_captcha, pre_check_sms_request,
        record_verify_failure, reset_counts_on_success, cleanup_old_records
    )
    ANTI_BOMB_AVAILABLE = True
except ImportError:
    ANTI_BOMB_AVAILABLE = False
    logger.warning("anti_bomb模块导入失败，部分功能将不可用")

# 改进的APScheduler导入逻辑，包含更详细的诊断信息
try:
    # 检查是否已安装apscheduler包
    import importlib.util
    spec = importlib.util.find_spec("apscheduler")
    if spec is None:
        raise ImportError("apscheduler包未找到")
    
    # 尝试导入apscheduler
    from apscheduler.schedulers.background import BackgroundScheduler
    APSCHEDULER_AVAILABLE = True
    logger.info("成功导入apscheduler")
except Exception as e:
    APSCHEDULER_AVAILABLE = False
    logger.warning(f"apscheduler导入失败: {str(e)}")
    # 在调试模式下显示更多信息
    logger.warning(f"当前Python可执行路径: {sys.executable if 'sys' in globals() else 'unknown'}")
    logger.warning(f"请确认在正确的Python环境中已安装apscheduler: pip install apscheduler==3.10.4")

# 导入认证模块
try:
    from auth import jwt_required, generate_token
    AUTH_AVAILABLE = True
except ImportError:
    AUTH_AVAILABLE = False
    logger.warning("认证模块导入失败")

# 创建Flask应用
try:
    if FLASK_AVAILABLE:
        # 自定义JSON Provider，确保中文不被转义且格式化输出
        class PrettyJSONProvider(DefaultJSONProvider):
            ensure_ascii = False
            compact = False
            sort_keys = False
        
        app = Flask(__name__)
        app.json_provider_class = PrettyJSONProvider
        app.json = PrettyJSONProvider(app)
        
        # 配置Flask应用
        if CONFIG_AVAILABLE:
            try:
                app.config.from_object(Config)
                logger.info("已加载配置")
            except Exception as e:
                logger.error(f"加载配置失败: {str(e)}")
                # 使用默认配置
                app.config['DEBUG'] = True
        else:
            # 使用默认配置
            logger.warning("使用默认配置")
            app.config['DEBUG'] = True
        
        # JWT配置
        app.config['JWT_SECRET_KEY'] = app.config.get('JWT_SECRET_KEY', app.config['SECRET_KEY'] + '-jwt')
        
        logger.info(f"JSON配置: ensure_ascii={app.json.ensure_ascii}, compact={app.json.compact}")
    else:
        app = None
        logger.error("无法创建Flask应用，Flask模块不可用")
except Exception as e:
    app = None
    logger.error(f"创建Flask应用失败: {str(e)}")

# 初始化定时任务
def init_scheduler():
    """安全地初始化定时任务，处理各种依赖缺失情况"""
    # 检查必要的依赖
    if not APSCHEDULER_AVAILABLE:
        logger.warning("apscheduler模块不可用，无法启动定时任务")
        return None
    
    if not ANTI_BOMB_AVAILABLE:
        logger.warning("anti_bomb模块不可用，无法添加清理任务")
        return None
    
    try:
        # 安全创建scheduler实例
        scheduler = BackgroundScheduler()
        
        # 尝试添加清理任务
        try:
            scheduler.add_job(
                cleanup_old_records,
                'cron',
                minute='*',  # 每分钟执行一次，用于测试
                id='cleanup_old_records',
                replace_existing=True
            )
            logger.info("清理任务已添加到调度器，任务ID: cleanup_old_records")
        except Exception as e:
            logger.error(f"添加清理任务失败: {str(e)}")
            return None
        
        # 尝试启动调度器
        try:
            scheduler.start()
            logger.info("定时任务已启动，当前调度器状态: 运行中")
            # 打印所有已添加的任务信息
            jobs = scheduler.get_jobs()
            for job in jobs:
                logger.info(f"已添加的任务: ID={job.id}, 函数={job.func.__name__ if hasattr(job.func, '__name__') else str(job.func)}, 下次执行时间={job.next_run_time}")
            return scheduler
        except Exception as e:
            logger.error(f"启动定时任务失败: {str(e)}")
            return None
            
    except Exception as e:
        logger.error(f"初始化调度器失败: {str(e)}")
        return None

# 生成图形验证码
@app.route('/api/captcha/generate', methods=['POST'])
def generate_captcha_api():
    try:
        data = request.get_json()
        scene_code = data.get('scene_code')
        identifier = data.get('identifier')  # 可以是手机号、设备ID等
        
        if not scene_code or not identifier:
            return jsonify({
                'code': 400,
                'message': '缺少必要参数',
                'data': None
            }), 400
        
        captcha, uuid = generate_captcha(scene_code, identifier)
        if not captcha:
            return jsonify({
                'code': 400,
                'message': uuid,  # uuid包含错误信息
                'data': None
            }), 400
        
        return jsonify({
            'code': 200,
            'message': '成功',
            'data': {
                'captcha': captcha,  # 在实际生产环境中，应该返回图片而不是明文
                'uuid': uuid,
                'expire_time': '5分钟后'  # 实际应该返回具体的过期时间戳
            }
        })
    except Exception as e:
        logger.error(f"生成图形验证码异常: {e}")
        return jsonify({
            'code': 500,
            'message': '系统异常',
            'data': None
        }), 500

# 校验图形验证码
@app.route('/api/captcha/verify', methods=['POST'])
def verify_captcha_api():
    try:
        data = request.get_json()
        scene_code = data.get('scene_code')
        identifier = data.get('identifier')
        captcha = data.get('captcha')
        
        if not scene_code or not identifier or not captcha:
            return jsonify({
                'code': 400,
                'message': '缺少必要参数',
                'data': None
            }), 400
        
        valid, message = verify_captcha(scene_code, identifier, captcha)
        if valid:
            return jsonify({
                'code': 200,
                'message': '验证成功',
                'data': {'valid': True}
            })
        else:
            return jsonify({
                'code': 400,
                'message': message,
                'data': {'valid': False}
            }), 400
    except Exception as e:
        logger.error(f"校验图形验证码异常: {e}")
        return jsonify({
            'code': 500,
            'message': '系统异常',
            'data': None
        }), 500

# 短信发送前预检查
@app.route('/api/sms/pre-check', methods=['POST'])
def sms_pre_check_api():
    try:
        data = request.get_json()
        scene_id = data.get('scene_id')
        identifier = data.get('identifier')  # 手机号或设备ID
        captcha = data.get('captcha')
        phone_number = data.get('phone_number')
        
        if not scene_id or not identifier:
            return jsonify({
                'code': 400,
                'message': '缺少必要参数',
                'data': None
            }), 400
        
        # 执行预检查
        valid, message = pre_check_sms_request(scene_id, identifier, captcha, phone_number)
        
        if valid:
            # 生成短信验证码（这里只是示例，实际应该调用短信服务）
            sms_code = ''.join([str(random.randint(0, 9)) for _ in range(6)])
            # 在实际应用中，应该将验证码存储起来用于后续验证
            
            return jsonify({
                'code': 200,
                'message': '验证通过，短信已发送',
                'data': {
                    'valid': True,
                    'sms_code': sms_code,  # 仅用于测试，生产环境不应返回验证码
                    'expire_time': '5分钟后'
                }
            })
        else:
            return jsonify({
                'code': 400,
                'message': message,
                'data': {'valid': False}
            }), 400
    except Exception as e:
        logger.error(f"短信预检查异常: {e}")
        return jsonify({
            'code': 500,
            'message': '系统异常',
            'data': None
        }), 500

# 短信验证码验证
@app.route('/api/sms/verify', methods=['POST'])
def sms_verify_api():
    try:
        data = request.get_json()
        scene_id = data.get('scene_id')
        identifier = data.get('identifier')
        sms_code = data.get('sms_code')
        
        if not scene_id or not identifier or not sms_code:
            return jsonify({
                'code': 400,
                'message': '缺少必要参数',
                'data': None
            }), 400
        
        # 这里应该从缓存或数据库中获取之前发送的验证码进行比对
        # 为了演示，我们假设验证码是123456
        is_valid = sms_code == '123456'  # 实际应用中应该从缓存或数据库中获取
        
        if is_valid:
            # 验证成功，重置计数
            reset_counts_on_success(scene_id, identifier)
            return jsonify({
                'code': 200,
                'message': '验证码验证成功',
                'data': {'valid': True}
            })
        else:
            # 验证失败，记录失败次数
            record_verify_failure(scene_id, identifier)
            return jsonify({
                'code': 400,
                'message': '验证码错误',
                'data': {'valid': False}
            }), 400
    except Exception as e:
        logger.error(f"短信验证码验证异常: {e}")
        return jsonify({
            'code': 500,
            'message': '系统异常',
            'data': None
        }), 500

# 性能监控中间件（记录接口响应时间）
@app.before_request
def before_request_perf():
    from time import perf_counter
    request.start_time = perf_counter()

@app.after_request
def after_request_perf(response):
    from time import perf_counter
    if hasattr(request, 'start_time'):
        elapsed_ms = (perf_counter() - request.start_time) * 1000
        response.headers['X-Response-Time'] = f'{elapsed_ms:.2f}ms'
        logger.info(f"请求 {request.method} {request.path} 响应时间: {elapsed_ms:.2f}ms")
    return response

# JWT 登录接口
@app.route('/api/auth/login', methods=['POST'])
def login():
    if not AUTH_AVAILABLE:
        return jsonify({
            'code': 500,
            'message': '认证模块不可用',
            'data': None
        }), 500
    
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    if not username or not password:
        return jsonify({
            'code': 400,
            'message': '缺少用户名或密码',
            'data': None
        }), 400
    
    # 从数据库查询用户
    cursor = db_conn.get_cursor()
    try:
        if db_conn.db_type == 'sqlite':
            cursor.execute(f"""
            SELECT username, password_hash, role, status FROM {Config.TABLES['SYS_USER']} 
            WHERE username = ?
            """, (username,))
        else:
            cursor.execute(f"""
            SELECT username, password_hash, role, status FROM {Config.TABLES['SYS_USER']} 
            WHERE username = %s
            """, (username,))
        
        user = cursor.fetchone()
        if not user:
            return jsonify({
                'code': 401,
                'message': '用户名或密码错误',
                'data': None
            }), 401
        
        # 兼容 dict cursor 和 tuple cursor
        if isinstance(user, dict):
            db_password = user['password_hash']
            db_role = user['role']
            db_status = user['status']
            db_username = user['username']
        else:
            db_username, db_password, db_role, db_status = user
        
        # 检查用户状态
        if db_status != 1:
            return jsonify({
                'code': 403,
                'message': '用户已被禁用',
                'data': None
            }), 403
        
        # 验证密码（SHA256 哈希比对）
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        if password_hash != db_password:
            return jsonify({
                'code': 401,
                'message': '用户名或密码错误',
                'data': None
            }), 401
        
        # 生成 JWT Token
        token = generate_token(user_id=db_username, role=db_role)
        return jsonify({
            'code': 200,
            'message': '登录成功',
            'data': {
                'token': token,
                'user_id': db_username,
                'role': db_role,
                'expires_in': '24小时'
            }
        })
    except Exception as e:
        logger.error(f"登录异常: {e}")
        return jsonify({
            'code': 500,
            'message': '登录失败，请稍后重试',
            'data': None
        }), 500
    finally:
        try:
            cursor.close()
        except Exception:
            pass

# 手动触发清理任务（管理员接口）
@app.route('/api/admin/cleanup', methods=['POST'])
@jwt_required(roles=['admin'])
def manual_cleanup_api():
    try:
        cleanup_old_records()
        return jsonify({
            'code': 200,
            'message': '清理完成',
            'data': None
        })
    except Exception as e:
        logger.error(f"手动清理异常: {e}")
        return jsonify({
            'code': 500,
            'message': '清理失败',
            'data': None
        }), 500

# 健康检查
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        'status': 'healthy',
        'service': 'sms-anti-bomb-system'
    })

# 根路径路由
@app.route('/', methods=['GET'])
def index():
    return jsonify({
        'message': '短信防轰炸系统API服务',
        'status': 'running',
        'version': '1.0.0',
        'available_apis': [
            '/api/captcha/generate - 生成图形验证码',
            '/api/captcha/verify - 校验图形验证码',
            '/api/sms/pre-check - 短信发送前预检查',
            '/api/sms/verify - 短信验证码验证',
            '/api/admin/cleanup - 手动触发清理任务',
            '/health - 健康检查'
        ],
        'docs': '请参考API调用指南.md获取详细的接口使用说明'
    })

# 启动应用
if __name__ == '__main__':
    """应用入口点 - 安全启动，处理各种环境问题"""
    logger.info("正在启动应用...")
    
    # 初始化定时任务（即使失败也继续运行）
    scheduler = None
    try:
        scheduler = init_scheduler()
    except Exception as e:
        logger.error(f"定时任务初始化异常: {str(e)}")
    
    # 检查Flask应用是否可用
    if app is not None and FLASK_AVAILABLE:
        try:
            # 获取调试模式配置
            # 禁用调试模式，避免自动重启影响定时任务
            debug_mode = False
            
            logger.info(f"准备启动Flask服务，调试模式: {debug_mode}")
            logger.info(f"服务将运行在 http://127.0.0.1:5000")
            
            # 启动Flask应用
            app.run(host='0.0.0.0', port=5000, debug=debug_mode)
            
        except KeyboardInterrupt:
            logger.info("应用已被用户中断")
        except Exception as e:
            logger.error(f"启动Flask应用时发生异常: {str(e)}")
    else:
        logger.error("无法启动Flask应用，请检查环境配置")
        # 输出诊断信息
        logger.info("=== 环境诊断信息 ===")
        logger.info(f"Flask可用: {FLASK_AVAILABLE}")
        logger.info(f"Config可用: {CONFIG_AVAILABLE}")
        logger.info(f"Anti-Bomb可用: {ANTI_BOMB_AVAILABLE}")
        logger.info(f"APScheduler可用: {APSCHEDULER_AVAILABLE}")
        logger.info("====================")
        logger.info("请安装必要的依赖: pip install -r requirements.txt")