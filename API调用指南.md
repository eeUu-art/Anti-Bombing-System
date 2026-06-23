# API调用指南

本文档提供了短信防轰炸系统的所有API接口详细说明，包括接口URL、请求方法、参数说明、响应格式以及调用示例。

## 系统API列表

1. [生成图形验证码](#生成图形验证码)
2. [校验图形验证码](#校验图形验证码)
3. [短信发送前预检查](#短信发送前预检查)
4. [短信验证码验证](#短信验证码验证)
5. [手动触发清理任务](#手动触发清理任务)
6. [健康检查](#健康检查)

## 基础信息

- 服务地址：`http://localhost:5000`
- 请求数据格式：JSON
- 响应数据格式：JSON

## 生成图形验证码

### 接口信息
- URL: `/api/captcha/generate`
- 方法: POST
- 功能: 生成用于防止机器人攻击的图形验证码

### 请求参数
| 参数名 | 类型 | 必填 | 说明 |
| :--- | :--- | :--- | :--- |
| `scene_code` | String | 是 | 场景代码，用于标识验证码使用场景 |
| `identifier` | String | 是 | 标识符，可以是手机号、设备ID等 |

### 响应格式

#### 成功响应
```json
{
    "code": 200,
    "message": "成功",
    "data": {
        "captcha": "1234",  // 实际生产环境中应该返回图片而不是明文
        "uuid": "验证码唯一ID",
        "expire_time": "5分钟后"  // 实际应该返回具体的过期时间戳
    }
}
```

#### 失败响应
```json
{
    "code": 400,
    "message": "错误信息",
    "data": null
}
```

### 调用示例

#### 使用curl调用
```bash
curl -X POST http://localhost:5000/api/captcha/generate \
     -H "Content-Type: application/json" \
     -d '{"scene_code": "login", "identifier": "13800138000"}'
```

#### 使用Python调用
```python
import requests

url = "http://localhost:5000/api/captcha/generate"
payload = {
    "scene_code": "login",
    "identifier": "13800138000"
}
headers = {
    "Content-Type": "application/json"
}

response = requests.post(url, json=payload, headers=headers)
print(response.json())
```

## 校验图形验证码

### 接口信息
- URL: `/api/captcha/verify`
- 方法: POST
- 功能: 验证用户输入的图形验证码是否正确

### 请求参数
| 参数名 | 类型 | 必填 | 说明 |
| :--- | :--- | :--- | :--- |
| `scene_code` | String | 是 | 场景代码，必须与生成时一致 |
| `identifier` | String | 是 | 标识符，必须与生成时一致 |
| `captcha` | String | 是 | 用户输入的验证码 |

### 响应格式

#### 验证成功
```json
{
    "code": 200,
    "message": "验证成功",
    "data": {"valid": true}
}
```

#### 验证失败
```json
{
    "code": 400,
    "message": "验证码错误或已过期",
    "data": {"valid": false}
}
```

### 调用示例

#### 使用curl调用
```bash
curl -X POST http://localhost:5000/api/captcha/verify \
     -H "Content-Type: application/json" \
     -d '{"scene_code": "login", "identifier": "13800138000", "captcha": "1234"}'
```

#### 使用Python调用
```python
import requests

url = "http://localhost:5000/api/captcha/verify"
payload = {
    "scene_code": "login",
    "identifier": "13800138000",
    "captcha": "1234"
}
headers = {
    "Content-Type": "application/json"
}

response = requests.post(url, json=payload, headers=headers)
print(response.json())
```

## 短信发送前预检查

### 接口信息
- URL: `/api/sms/pre-check`
- 方法: POST
- 功能: 在发送短信前进行频率控制和验证码验证

### 请求参数
| 参数名 | 类型 | 必填 | 说明 |
| :--- | :--- | :--- | :--- |
| `scene_id` | String | 是 | 场景ID，标识短信使用场景 |
| `identifier` | String | 是 | 标识符，可以是手机号、设备ID等 |
| `captcha` | String | 否 | 图形验证码（可选） |
| `phone_number` | String | 否 | 手机号（可选，用于更精确的频率控制） |

### 响应格式

#### 验证通过
```json
{
    "code": 200,
    "message": "验证通过，短信已发送",
    "data": {
        "valid": true,
        "sms_code": "123456",  // 仅用于测试，生产环境不应返回验证码
        "expire_time": "5分钟后"
    }
}
```

#### 验证失败
```json
{
    "code": 400,
    "message": "请求过于频繁，请稍后再试",
    "data": {"valid": false}
}
```

### 调用示例

#### 使用curl调用
```bash
curl -X POST http://localhost:5000/api/sms/pre-check \
     -H "Content-Type: application/json" \
     -d '{"scene_id": "register", "identifier": "13800138000", "captcha": "1234", "phone_number": "13800138000"}'
```

#### 使用Python调用
```python
import requests

url = "http://localhost:5000/api/sms/pre-check"
payload = {
    "scene_id": "register",
    "identifier": "13800138000",
    "captcha": "1234",
    "phone_number": "13800138000"
}
headers = {
    "Content-Type": "application/json"
}

response = requests.post(url, json=payload, headers=headers)
print(response.json())
```

## 短信验证码验证

### 接口信息
- URL: `/api/sms/verify`
- 方法: POST
- 功能: 验证用户输入的短信验证码

### 请求参数
| 参数名 | 类型 | 必填 | 说明 |
| :--- | :--- | :--- | :--- |
| `scene_id` | String | 是 | 场景ID，必须与发送时一致 |
| `identifier` | String | 是 | 标识符，必须与发送时一致 |
| `sms_code` | String | 是 | 用户输入的短信验证码 |

### 响应格式

#### 验证成功
```json
{
    "code": 200,
    "message": "验证码验证成功",
    "data": {"valid": true}
}
```

#### 验证失败
```json
{
    "code": 400,
    "message": "验证码错误",
    "data": {"valid": false}
}
```

### 调用示例

#### 使用curl调用
```bash
curl -X POST http://localhost:5000/api/sms/verify \
     -H "Content-Type: application/json" \
     -d '{"scene_id": "register", "identifier": "13800138000", "sms_code": "123456"}'
```

#### 使用Python调用
```python
import requests

url = "http://localhost:5000/api/sms/verify"
payload = {
    "scene_id": "register",
    "identifier": "13800138000",
    "sms_code": "123456"
}
headers = {
    "Content-Type": "application/json"
}

response = requests.post(url, json=payload, headers=headers)
print(response.json())
```

## 手动触发清理任务

### 接口信息
- URL: `/api/admin/cleanup`
- 方法: POST
- 功能: 手动触发系统清理任务，清理过期记录
- 注意: 此接口应为管理员权限调用，当前版本未实现权限验证

### 请求参数
无

### 响应格式

#### 清理成功
```json
{
    "code": 200,
    "message": "清理完成",
    "data": null
}
```

#### 清理失败
```json
{
    "code": 500,
    "message": "清理失败",
    "data": null
}
```

### 调用示例

#### 使用curl调用
```bash
curl -X POST http://localhost:5000/api/admin/cleanup
```

#### 使用Python调用
```python
import requests

url = "http://localhost:5000/api/admin/cleanup"
response = requests.post(url)
print(response.json())
```

## 健康检查

### 接口信息
- URL: `/health`
- 方法: GET
- 功能: 检查服务是否正常运行

### 请求参数
无

### 响应格式

#### 服务正常
```json
{
    "status": "healthy",
    "service": "sms-anti-bomb-system"
}
```

### 调用示例

#### 使用curl调用
```bash
curl http://localhost:5000/health
```

#### 使用Python调用
```python
import requests

url = "http://localhost:5000/health"
response = requests.get(url)
print(response.json())
```

## 完整调用流程示例

下面是一个完整的短信验证流程示例，使用Python实现：

```python
import requests
import time

def sms_verification_flow(phone_number):
    # 1. 生成图形验证码
    print("1. 生成图形验证码...")
    captcha_url = "http://localhost:5000/api/captcha/generate"
    captcha_payload = {
        "scene_code": "login",
        "identifier": phone_number
    }
    captcha_response = requests.post(captcha_url, json=captcha_payload)
    captcha_data = captcha_response.json()
    print(f"验证码: {captcha_data['data']['captcha']}")
    
    # 2. 验证图形验证码（模拟用户输入正确的验证码）
    print("\n2. 验证图形验证码...")
    verify_captcha_url = "http://localhost:5000/api/captcha/verify"
    verify_captcha_payload = {
        "scene_code": "login",
        "identifier": phone_number,
        "captcha": captcha_data['data']['captcha']
    }
    verify_captcha_response = requests.post(verify_captcha_url, json=verify_captcha_payload)
    print(f"验证码验证结果: {verify_captcha_response.json()}")
    
    # 3. 短信发送前预检查
    print("\n3. 短信发送前预检查...")
    pre_check_url = "http://localhost:5000/api/sms/pre-check"
    pre_check_payload = {
        "scene_id": "register",
        "identifier": phone_number,
        "captcha": captcha_data['data']['captcha'],
        "phone_number": phone_number
    }
    pre_check_response = requests.post(pre_check_url, json=pre_check_payload)
    pre_check_data = pre_check_response.json()
    print(f"预检查结果: {pre_check_data}")
    
    # 4. 短信验证码验证（使用预检查返回的验证码）
    if pre_check_data['code'] == 200:
        print("\n4. 短信验证码验证...")
        sms_code = pre_check_data['data']['sms_code']
        print(f"收到的短信验证码: {sms_code}")
        
        verify_sms_url = "http://localhost:5000/api/sms/verify"
        verify_sms_payload = {
            "scene_id": "register",
            "identifier": phone_number,
            "sms_code": sms_code
        }
        verify_sms_response = requests.post(verify_sms_url, json=verify_sms_payload)
        print(f"短信验证码验证结果: {verify_sms_response.json()}")

# 执行完整流程
sms_verification_flow("13800138000")
```

## 注意事项

1. 生产环境中，图形验证码应该返回图片而不是明文
2. 生产环境中，短信验证码不应该在响应中返回
3. 生产环境中，管理员接口应该增加权限验证
4. 生产环境中，应该使用实际的短信服务发送验证码
5. 所有敏感信息如API密钥、数据库连接信息等应该通过环境变量配置

## 常见错误处理

1. 验证码错误：返回错误代码400，提示"验证码错误或已过期"
2. 请求过于频繁：返回错误代码400，提示"请求过于频繁，请稍后再试"
3. 缺少必要参数：返回错误代码400，提示"缺少必要参数"
4. 系统异常：返回错误代码500，提示"系统异常"

请确保在调用API时处理这些可能的错误情况。