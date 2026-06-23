"""JWT 权限管控模块"""
import jwt
import datetime
import functools
import logging
from flask import request, jsonify, current_app

logger = logging.getLogger(__name__)


def generate_token(user_id, role='admin', expires_hours=24):
    """生成 JWT Token
    
    Args:
        user_id: 用户ID
        role: 用户角色 (admin/operator)
        expires_hours: 过期时间（小时）
    
    Returns:
        str: JWT Token
    """
    secret_key = current_app.config.get('JWT_SECRET_KEY', current_app.config['SECRET_KEY'])
    payload = {
        'user_id': user_id,
        'role': role,
        'iat': datetime.datetime.now(datetime.timezone.utc),
        'exp': datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=expires_hours)
    }
    token = jwt.encode(payload, secret_key, algorithm='HS256')
    return token


def jwt_required(roles=None):
    """JWT 认证装饰器
    
    Args:
        roles: 允许的角色列表，如 ['admin']，None 表示不限制角色
    """
    def decorator(f):
        @functools.wraps(f)
        def decorated_function(*args, **kwargs):
            token = None
            
            # 从 Authorization header 获取 token
            auth_header = request.headers.get('Authorization')
            if auth_header and auth_header.startswith('Bearer '):
                token = auth_header.split(' ')[1]
            
            if not token:
                return jsonify({
                    'code': 401,
                    'message': '缺少认证令牌',
                    'data': None
                }), 401
            
            try:
                secret_key = current_app.config.get('JWT_SECRET_KEY', current_app.config['SECRET_KEY'])
                payload = jwt.decode(token, secret_key, algorithms=['HS256'])
                
                # 检查角色权限
                if roles and payload.get('role') not in roles:
                    return jsonify({
                        'code': 403,
                        'message': '权限不足',
                        'data': None
                    }), 403
                
                # 将用户信息注入请求上下文
                request.current_user = {
                    'user_id': payload['user_id'],
                    'role': payload['role']
                }
                
            except jwt.ExpiredSignatureError:
                return jsonify({
                    'code': 401,
                    'message': '令牌已过期',
                    'data': None
                }), 401
            except jwt.InvalidTokenError as e:
                logger.warning(f"JWT 验证失败: {e}")
                return jsonify({
                    'code': 401,
                    'message': '无效的认证令牌',
                    'data': None
                }), 401
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator
