import requests
from bs4 import BeautifulSoup
import os
from datetime import datetime
import re
import base64
import time
import urllib3

# 禁用SSL警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 检查必需的库
def check_dependencies():
    """检查并提示安装必需的依赖"""
    missing = []
    try:
        import brotli
    except ImportError:
        try:
            import brotlicffi
        except ImportError:
            missing.append("brotli")
    
    if missing:
        print("⚠️  检测到缺少必需的依赖库:")
        for lib in missing:
            print(f"   - {lib}")
        print("\n请运行以下命令安装:")
        print("   pip install brotli")
        print("\n或者安装所有依赖:")
        print("   pip install -r requirements.txt")
        print("")
        return False
    return True

# 域名配置
LOCAL_DOMAIN = ""                     # 本地测试时可填入域名，如：ikuuu.org
DEFAULT_DOMAIN = "ikuuu.ch"           # 默认域名

# 初始值，会被 resolve_domain() 覆盖
BASE_DOMAIN = DEFAULT_DOMAIN
BASE_URL = f"https://{BASE_DOMAIN}"

# 域名自动发现配置
DOMAIN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "domain.txt")
NAVIGATION_URLS = [
    "https://ikuuu.ch",
]
DOMAIN_TEST_TIMEOUT = 5

# 本地测试变量，本地测试时可以在这里设置，环境变量优先级更高
LOCAL_EMAIL = ""     # 本地测试时填入邮箱
LOCAL_PASSWORD = ""  # 本地测试时填入密码
LOCAL_COOKIE = ""    # 可选：浏览器 Cookie（备用方案）
LOCAL_CAPTCHA_API_KEY = ""  # 可选：打码平台 API Key（浏览器路径失败时的备用）
LOCAL_CAPTCHA_PROVIDER = ""  # 可选: capsolver / yescaptcha，留空则自动识别
# 是否优先使用免费 Playwright 过 Geetest（默认开启，设 0/false 关闭）
LOCAL_USE_BROWSER_LOGIN = True

# 账号密码登录时，验证码/网络失败的最大重试次数
LOGIN_MAX_RETRIES = 3

def print_with_time(message, level="INFO"):
    """带时间戳和级别的打印"""
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    level_emoji = {
        "INFO": "ℹ️",
        "SUCCESS": "✅", 
        "WARNING": "⚠️",
        "ERROR": "❌",
        "DEBUG": "🔍"
    }
    emoji = level_emoji.get(level, "ℹ️")
    print(f"[{current_time}] {emoji} {message}")

def print_separator(char="=", length=60):
    """打印分隔线"""
    print(char * length)

def read_domain_from_file():
    """从 domain.txt 读取缓存的域名"""
    try:
        if os.path.exists(DOMAIN_FILE):
            with open(DOMAIN_FILE, 'r', encoding='utf-8') as f:
                domain = f.readline().strip()
            if domain and '.' in domain and ' ' not in domain:
                domain = domain.replace('https://', '').replace('http://', '').rstrip('/')
                print_with_time(f"从缓存文件读取域名: {domain}", "DEBUG")
                return domain
            else:
                print_with_time(f"缓存文件中的域名无效: '{domain}'", "WARNING")
    except Exception as e:
        print_with_time(f"读取域名缓存文件失败: {str(e)}", "WARNING")
    return None

def save_domain_to_file(domain):
    """将可用域名保存到 domain.txt"""
    try:
        with open(DOMAIN_FILE, 'w', encoding='utf-8') as f:
            f.write(domain.strip() + '\n')
        print_with_time(f"已保存域名到缓存文件: {domain}", "SUCCESS")
        return True
    except Exception as e:
        print_with_time(f"保存域名缓存文件失败: {str(e)}", "WARNING")
        return False

def parse_json_response(response, context="响应"):
    """安全地解析JSON响应"""
    import json
    try:
        return response.json()
    except Exception:
        # requests 已自动处理 gzip/brotli 解压，只需清理文本
        text = response.text.lstrip('\ufeff')
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise ValueError(f"{context}响应不含有效JSON")

def create_session():
    """创建配置完整的会话对象"""
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36 Edg/138.0.0.0',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1'
    })
    
    # 设置适配器，避免连接池问题
    adapter = requests.adapters.HTTPAdapter(pool_connections=1, pool_maxsize=1)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    
    return session

def test_domain(domain):
    """快速测试域名是否为可用的 ikuuu 服务（非导航页）

    判断逻辑：GET 根路径，真实服务会 302 跳转到 /auth/login，导航页返回 200
    """
    test_url = f"https://{domain}/"
    try:
        session = create_session()
        response = session.get(test_url, timeout=DOMAIN_TEST_TIMEOUT, verify=False, allow_redirects=False)
        session.close()

        # 真实服务：根路径 302 跳转到 /auth/login
        if response.status_code == 302:
            location = response.headers.get('Location', '')
            if '/auth/login' in location:
                print_with_time(f"域名 {domain} 可用（302 -> /auth/login）", "SUCCESS")
                return True
            else:
                print_with_time(f"域名 {domain} 302跳转到 {location}，非服务页面", "DEBUG")
                return False

        # 导航页：返回 200 的 HTML 页面
        if response.status_code == 200:
            print_with_time(f"域名 {domain} 返回200，可能是导航页", "DEBUG")
            return False

        print_with_time(f"域名 {domain} 返回状态码 {response.status_code}", "WARNING")
        return False
    except Exception as e:
        print_with_time(f"域名 {domain} 不可用: {str(e)}", "DEBUG")
        return False

def _decode_obfuscated_strings(html_text):
    """从导航页的混淆JS中解码字符串数组"""
    # 自定义 base64 字母表（小写在前，大写在后）
    custom = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+/='
    standard = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/='
    table = str.maketrans(custom, standard)

    decoded = []
    # 提取编码字符串数组
    arrays = re.findall(r"\[(?:'[^']*',?\s*){5,}\]", html_text)
    for arr in arrays:
        items = re.findall(r"'([^']*)'", arr)
        for s in items:
            try:
                translated = s.translate(table)
                padding = 4 - len(translated) % 4
                if padding != 4:
                    translated += '=' * padding
                raw = base64.b64decode(translated)
                decoded.append(raw.decode('utf-8', errors='ignore'))
            except Exception:
                pass
    return decoded

def discover_domains():
    """从导航页自动发现当前可用域名列表"""
    print_with_time("开始自动发现域名...", "INFO")
    discovered = []

    for nav_url in NAVIGATION_URLS:
        try:
            print_with_time(f"尝试从 {nav_url} 获取域名列表...", "DEBUG")
            session = create_session()
            response = session.get(nav_url, timeout=DOMAIN_TEST_TIMEOUT + 5, verify=False, allow_redirects=True)
            session.close()

            if response.status_code != 200:
                continue

            html_text = response.text

            # 策略1：从 h3 标签提取域名（适用于非JS渲染的导航页）
            soup = BeautifulSoup(html_text, 'html.parser')
            for h3 in soup.find_all('h3'):
                text = h3.get_text(strip=True)
                if re.match(r'^ikuuu\.\w{2,}$', text, re.IGNORECASE):
                    discovered.append(text.lower())

            # 策略2：从 a 标签 href 提取域名
            for a in soup.find_all('a', href=True):
                match = re.search(r'https?://(ikuuu\.\w{2,})/?', a['href'], re.IGNORECASE)
                if match:
                    domain = match.group(1).lower()
                    if domain not in discovered:
                        discovered.append(domain)

            # 策略3：从字符串拼接模式提取（如 'ikuuu'+'.nl'）
            for m in re.finditer(r"'ikuuu'\+'\.(\w{2,})'", html_text):
                domain = f"ikuuu.{m.group(1).lower()}"
                if domain not in discovered:
                    discovered.append(domain)

            # 策略4：解码混淆JS字符串数组，查找 TLD 片段（如 .fyi, .nl）
            for s in _decode_obfuscated_strings(html_text):
                if re.match(r'^\.\w{2,4}$', s):
                    domain = f"ikuuu{s}".lower()
                    if domain not in discovered:
                        discovered.append(domain)

            if discovered:
                # 过滤掉导航页自身的域名
                nav_domain = nav_url.replace('https://', '').replace('http://', '').rstrip('/')
                discovered = [d for d in discovered if d != nav_domain]
                print_with_time(f"发现 {len(discovered)} 个域名: {', '.join(discovered)}", "SUCCESS")
                break

        except Exception as e:
            print_with_time(f"从 {nav_url} 获取域名失败: {str(e)}", "DEBUG")
            continue

    if not discovered:
        print_with_time("自动域名发现未找到任何域名", "WARNING")

    return discovered

def _set_domain(domain):
    """设置当前使用的域名"""
    global BASE_DOMAIN, BASE_URL
    BASE_DOMAIN = domain
    BASE_URL = f"https://{BASE_DOMAIN}"

def resolve_domain():
    """按优先级解析可用域名：缓存文件 > 环境变量 > 本地变量 > 默认值 > 自动发现"""
    print_with_time("开始域名解析...", "INFO")

    # 构建候选列表（有序去重）
    candidates = []
    for domain in [read_domain_from_file(), os.getenv('IKUUU_DOMAIN'), LOCAL_DOMAIN, DEFAULT_DOMAIN]:
        if domain and domain not in candidates:
            candidates.append(domain)

    # 逐个测试
    for domain in candidates:
        if test_domain(domain):
            _set_domain(domain)
            save_domain_to_file(domain)
            print_with_time(f"使用域名: {domain}", "SUCCESS")
            return domain

    # 候选域名均不可用，自动发现
    print_with_time("候选域名不可用，尝试自动发现...", "WARNING")
    for domain in discover_domains():
        if domain not in candidates and test_domain(domain):
            _set_domain(domain)
            save_domain_to_file(domain)
            print_with_time(f"使用自动发现的域名: {domain}", "SUCCESS")
            return domain

    print_with_time(f"所有域名均不可用，使用默认域名: {DEFAULT_DOMAIN}", "ERROR")
    _set_domain(DEFAULT_DOMAIN)

def safe_request(method, url, **kwargs):
    """安全的网络请求，包含重试"""
    kwargs.setdefault('timeout', 8)
    kwargs['verify'] = False

    for attempt in range(2):
        try:
            if attempt > 0:
                time.sleep(attempt * 2)
                print_with_time(f"第 {attempt + 1} 次重试...", "WARNING")
            session = create_session()
            response = session.request(method, url, **kwargs)
            session.close()
            return response
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if attempt == 1:
                print_with_time(f"请求失败: {str(e)}", "ERROR")
    return None

def get_cookie_from_config():
    """读取 Cookie 配置（免费跳过验证码）"""
    cookie = (os.getenv('IKUUU_COOKIE') or LOCAL_COOKIE or '').strip()
    # 允许用户粘贴 document.cookie 或完整 Cookie 头
    cookie = cookie.replace('\n', ' ').strip()
    if cookie.lower().startswith('cookie:'):
        cookie = cookie[7:].strip()
    return cookie


def normalize_cookie_string(cookie):
    """规范化 Cookie 字符串"""
    if not cookie:
        return ''
    # 去掉多余空格，保留 name=value; name2=value2
    parts = []
    for item in cookie.split(';'):
        item = item.strip()
        if not item or '=' not in item:
            continue
        name, value = item.split('=', 1)
        name, value = name.strip(), value.strip()
        if name:
            parts.append(f"{name}={value}")
    return '; '.join(parts)


def cookie_looks_valid(cookie):
    """粗略判断 Cookie 是否包含登录会话字段"""
    if not cookie:
        return False
    lower = cookie.lower()
    # SSPanel 常见字段
    return any(k in lower for k in ['uid=', 'email=', 'key=', 'ip=', 'expire_in='])


def validate_cookie_session(cookie):
    """请求 /user 验证 Cookie 是否仍有效"""
    cookie = normalize_cookie_string(cookie)
    if not cookie:
        return False

    headers = {
        'Cookie': cookie,
        'Referer': f"{BASE_URL}/user",
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    }
    try:
        response = safe_request('GET', f"{BASE_URL}/user", headers=headers)
    except Exception as e:
        print_with_time(f"Cookie 校验请求失败: {e}", "WARNING")
        return False

    if not response or response.status_code != 200:
        print_with_time(f"Cookie 校验失败，状态码: {getattr(response, 'status_code', 'N/A')}", "WARNING")
        return False

    text = response.text or ''
    decoded = decode_page_html(text)
    # 登录页特征
    if re.search(r'/auth/login|name=["\']email["\']|登录\s*&mdash;|id=["\']password["\']', decoded, re.I):
        # 有些用户页也会包含脚本字符串，再看 title
        title_match = re.search(r'<title>(.*?)</title>', decoded, re.I | re.S)
        title = (title_match.group(1) if title_match else '').lower()
        if 'login' in title or '登录' in title:
            print_with_time("Cookie 已失效（跳转到登录页）", "WARNING")
            return False

    # 用户中心特征
    if re.search(r'checkin|/user/logout|剩余流量|会员|wallet|ann', decoded, re.I):
        return True

    # Cookie 字段齐全但页面特征不明显时，仍尝试使用
    if cookie_looks_valid(cookie) and len(decoded) > 500:
        print_with_time("Cookie 页面特征不明确，仍尝试使用", "WARNING")
        return True

    print_with_time("Cookie 看起来无效", "WARNING")
    return False


def get_account_credentials():
    """读取邮箱/密码配置"""
    email = (os.getenv('IKUUU_EMAIL') or LOCAL_EMAIL or '').strip()
    password = (os.getenv('IKUUU_PASSWORD') or LOCAL_PASSWORD or '').strip()
    return email, password


def use_browser_login_enabled():
    """是否启用免费 Playwright 过 Geetest（默认 True）"""
    env = os.getenv('IKUUU_USE_BROWSER_LOGIN')
    if env is not None and str(env).strip() != '':
        return str(env).strip().lower() in ('1', 'true', 'yes', 'on')
    return bool(LOCAL_USE_BROWSER_LOGIN)


def try_login_with_browser():
    """免费主路径：Playwright 点击 Geetest「点我开始验证」后登录拿 Cookie"""
    email, password = get_account_credentials()
    if not email or not password:
        return None
    if not use_browser_login_enabled():
        print_with_time("已关闭浏览器登录（IKUUU_USE_BROWSER_LOGIN=0）", "DEBUG")
        return None

    try:
        from browser_login import login_with_browser
    except ImportError as e:
        print_with_time(f"无法导入 browser_login: {e}", "WARNING")
        return None

    if '@' in email:
        masked = f"{email[:3]}***{email.split('@')[1]}"
    else:
        masked = f"{email[:3]}***"
    print_with_time(f"账号: {masked}，域名: {BASE_DOMAIN}（免费浏览器过验证码）", "INFO")

    cookie = login_with_browser(email, password, BASE_URL)
    if cookie and validate_cookie_session(cookie):
        return cookie
    if cookie:
        # Reason: 刚登录的 Cookie 偶发校验页特征不明显，仍可直接用于签到
        print_with_time("Cookie 校验页面特征不明确，仍尝试使用浏览器登录结果", "WARNING")
        return cookie
    return None


def try_login_with_cookie():
    """可选备用：使用已有 Cookie 跳过登录验证码（无账号密码或登录失败时）"""
    cookie = normalize_cookie_string(get_cookie_from_config())
    if not cookie:
        return None

    print_with_time("检测到 IKUUU_COOKIE，尝试 Cookie 登录...", "INFO")
    if not cookie_looks_valid(cookie):
        print_with_time("Cookie 缺少常见登录字段（uid/email/key），仍继续校验", "WARNING")

    if validate_cookie_session(cookie):
        print_with_time("Cookie 有效，登录成功", "SUCCESS")
        return cookie

    print_with_time("Cookie 无效或已过期", "WARNING")
    return None


def decode_page_html(html_text):
    """解码站点 base64 混淆页面（originBody）"""
    if not html_text:
        return html_text
    match = re.search(r'var\s+originBody\s*=\s*"([^"]+)"', html_text)
    if match:
        try:
            return base64.b64decode(match.group(1)).decode('utf-8', errors='replace')
        except Exception:
            pass
    return html_text


def extract_geetest_captcha_id(html_text):
    """从登录页提取 Geetest V4 captchaId"""
    decoded = decode_page_html(html_text)
    patterns = [
        r"captchaId\s*:\s*['\"]([0-9a-fA-F]{32})['\"]",
        r"captcha_id\s*[:=]\s*['\"]([0-9a-fA-F]{32})['\"]",
        r"initGeetest4\(\s*\{\s*captchaId\s*:\s*['\"]([0-9a-fA-F]{32})['\"]",
    ]
    for pattern in patterns:
        match = re.search(pattern, decoded)
        if match:
            return match.group(1)
    return None


def get_captcha_config():
    """读取打码配置：环境变量优先于本地变量"""
    api_key = (
        os.getenv('CAPSOLVER_API_KEY')
        or os.getenv('YESCAPTCHA_API_KEY')
        or os.getenv('CAPTCHA_API_KEY')
        or LOCAL_CAPTCHA_API_KEY
        or ''
    ).strip()
    provider = (
        os.getenv('CAPTCHA_PROVIDER')
        or LOCAL_CAPTCHA_PROVIDER
        or ''
    ).strip().lower()

    if not provider:
        if os.getenv('YESCAPTCHA_API_KEY') and not os.getenv('CAPSOLVER_API_KEY'):
            provider = 'yescaptcha'
        elif api_key:
            provider = 'capsolver'
    if provider in ('yes', 'yc', 'yescaptcha.com'):
        provider = 'yescaptcha'
    if provider in ('cap', 'capsolver.com'):
        provider = 'capsolver'
    return api_key, provider


def _poll_task_result(session, result_url, payload, provider_name, max_wait=120):
    """轮询打码任务结果"""
    start = time.time()
    while time.time() - start < max_wait:
        time.sleep(3)
        try:
            resp = session.post(result_url, json=payload, timeout=30, verify=False)
            data = resp.json()
        except Exception as e:
            print_with_time(f"{provider_name} 查询结果失败: {e}", "WARNING")
            continue

        status = str(data.get('status', '')).lower()
        error_id = data.get('errorId', 0)
        if error_id not in (0, '0', None, ''):
            msg = data.get('errorDescription') or data.get('errorCode') or str(data)
            raise RuntimeError(f"{provider_name} 打码失败: {msg}")

        if status in ('ready', 'success'):
            solution = data.get('solution') or {}
            # 兼容不同字段命名
            result = {
                'lot_number': solution.get('lot_number') or solution.get('lotNumber'),
                'captcha_output': solution.get('captcha_output') or solution.get('captchaOutput'),
                'pass_token': solution.get('pass_token') or solution.get('passToken'),
                'gen_time': str(solution.get('gen_time') or solution.get('genTime') or ''),
            }
            if result['lot_number'] and result['captcha_output'] and result['pass_token']:
                return result
            raise RuntimeError(f"{provider_name} 返回结果不完整: {solution}")

        if status in ('failed', 'error'):
            raise RuntimeError(f"{provider_name} 打码失败: {data}")

        # processing / idle
    raise TimeoutError(f"{provider_name} 打码超时（>{max_wait}s）")


def solve_geetest_v4(website_url, captcha_id):
    """调用打码平台解决 Geetest V4，返回 captcha_result 字段"""
    api_key, provider = get_captcha_config()
    if not api_key:
        print_with_time(
            "登录页需要 Geetest 点击验证，但未配置打码 API Key。"
            "请设置 Secrets: CAPSOLVER_API_KEY 或 YESCAPTCHA_API_KEY",
            "ERROR",
        )
        return None
    if not captcha_id:
        print_with_time("未能从登录页解析 captchaId", "ERROR")
        return None

    session = create_session()
    session.headers.update({'Content-Type': 'application/json', 'Accept': 'application/json'})
    try:
        if provider == 'yescaptcha':
            create_url = 'https://api.yescaptcha.com/createTask'
            result_url = 'https://api.yescaptcha.com/getTaskResult'
            task = {
                'type': 'GeeTestTaskProxyless',
                'websiteURL': website_url,
                'gt': captcha_id,
                'version': 4,
                'initParameters': {'captcha_id': captcha_id},
            }
            provider_name = 'YesCaptcha'
        else:
            # 默认 CapSolver
            create_url = 'https://api.capsolver.com/createTask'
            result_url = 'https://api.capsolver.com/getTaskResult'
            task = {
                'type': 'GeeTestTaskProxyLess',
                'websiteURL': website_url,
                'captchaId': captcha_id,
            }
            provider_name = 'CapSolver'

        print_with_time(f"正在通过 {provider_name} 解决 Geetest V4 验证码...", "INFO")
        create_payload = {'clientKey': api_key, 'task': task}
        resp = session.post(create_url, json=create_payload, timeout=30, verify=False)
        data = resp.json()
        error_id = data.get('errorId', 0)
        if error_id not in (0, '0', None, ''):
            msg = data.get('errorDescription') or data.get('errorCode') or str(data)
            print_with_time(f"{provider_name} 创建任务失败: {msg}", "ERROR")
            return None

        task_id = data.get('taskId')
        if not task_id and data.get('status') in ('ready', 'success') and data.get('solution'):
            solution = data['solution']
            result = {
                'lot_number': solution.get('lot_number') or solution.get('lotNumber'),
                'captcha_output': solution.get('captcha_output') or solution.get('captchaOutput'),
                'pass_token': solution.get('pass_token') or solution.get('passToken'),
                'gen_time': str(solution.get('gen_time') or solution.get('genTime') or ''),
            }
            print_with_time("验证码解决成功", "SUCCESS")
            return result

        if not task_id:
            print_with_time(f"{provider_name} 未返回 taskId: {data}", "ERROR")
            return None

        result = _poll_task_result(
            session,
            result_url,
            {'clientKey': api_key, 'taskId': task_id},
            provider_name,
        )
        print_with_time("验证码解决成功", "SUCCESS")
        return result
    except Exception as e:
        print_with_time(f"解决验证码失败: {e}", "ERROR")
        return None
    finally:
        session.close()


def build_login_form_data(email, password, captcha_result=None, page_loaded_at=None):
    """构造与前端一致的登录表单数据（含 captcha_result 嵌套字段）"""
    if page_loaded_at is None:
        page_loaded_at = int(time.time() * 1000)

    form = [
        ('host', BASE_DOMAIN),
        ('email', email),
        ('passwd', password),
        ('code', ''),
        ('twofa_step', '0'),
        ('remember_me', 'on'),
        ('pageLoadedAt', str(page_loaded_at)),
    ]
    if captcha_result:
        form.extend([
            ('captcha_result[lot_number]', captcha_result.get('lot_number', '')),
            ('captcha_result[captcha_output]', captcha_result.get('captcha_output', '')),
            ('captcha_result[pass_token]', captcha_result.get('pass_token', '')),
            ('captcha_result[gen_time]', str(captcha_result.get('gen_time', ''))),
        ])
    return form


def _do_login_once(email, password):
    """单次账号密码登录（含 Geetest V4）。成功返回 cookie 字符串，失败返回 None 或 'CAPTCHA_ERROR'。"""
    session = create_session()
    try:
        login_page_url = f"{BASE_URL}/auth/login"
        page_loaded_at = int(time.time() * 1000)
        try:
            response = session.get(login_page_url, timeout=15, verify=False)
        except Exception as e:
            print_with_time(f"获取登录页面失败: {str(e)}", "ERROR")
            return None

        if response.status_code != 200:
            print_with_time(f"无法访问登录页面，状态码: {response.status_code}", "ERROR")
            return None

        page_html = response.text
        decoded_html = decode_page_html(page_html)

        # CSRF token（部分主题仍可能使用）
        soup = BeautifulSoup(decoded_html, 'html.parser')
        csrf_input = soup.find('input', {'name': '_token'})

        captcha_id = extract_geetest_captcha_id(page_html)
        captcha_result = None
        if captcha_id:
            print_with_time(f"检测到 Geetest V4 验证码 (captchaId={captcha_id[:8]}...)", "INFO")
            captcha_result = solve_geetest_v4(login_page_url, captcha_id)
            if not captcha_result:
                return 'CAPTCHA_ERROR'
        else:
            print_with_time("未检测到 Geetest 验证码，尝试直接登录", "WARNING")

        login_data = build_login_form_data(email, password, captcha_result, page_loaded_at)
        if csrf_input and csrf_input.get('value'):
            login_data.append(('_token', csrf_input.get('value')))

        print_with_time("正在登录...", "INFO")
        headers = {
            'Origin': BASE_URL,
            'Referer': login_page_url,
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'X-Requested-With': 'XMLHttpRequest',
            'Accept': 'application/json, text/javascript, */*; q=0.01',
        }

        try:
            response = session.post(
                login_page_url,
                data=login_data,
                headers=headers,
                timeout=20,
                verify=False,
                allow_redirects=False,
            )
        except Exception as e:
            print_with_time(f"登录请求失败: {str(e)}", "ERROR")
            return None

        cookie_string = '; '.join([f"{c.name}={c.value}" for c in session.cookies])

        if response.status_code == 302 and '/user' in response.headers.get('Location', ''):
            print_with_time("登录成功", "SUCCESS")
            return cookie_string or None

        if response.status_code == 200:
            try:
                result = parse_json_response(response, "登录")
                if result.get('ret') == 1:
                    print_with_time("登录成功", "SUCCESS")
                    return cookie_string or None
                msg = result.get('msg', '未知错误')
                print_with_time(f"登录失败: {msg}", "ERROR")
                # Reason: 验证码类错误单独标记，便于重试时重新打码而不是立刻换域名
                if any(k in str(msg) for k in ['验证', 'captcha', 'Captcha', 'geetest', 'GeeTest']):
                    return 'CAPTCHA_ERROR'
                return None
            except Exception:
                if cookie_string and any(k in cookie_string for k in ['uid', 'email', 'key']):
                    print_with_time("登录成功（Cookie检测）", "SUCCESS")
                    return cookie_string

        print_with_time(f"登录失败，状态码: {response.status_code}", "ERROR")
        return None
    except KeyboardInterrupt:
        raise
    except Exception as e:
        print_with_time(f"登录错误: {str(e)}", "ERROR")
        return None
    finally:
        session.close()


def login_and_get_cookie(max_retries=None):
    """账号密码登录并获取 Cookie（可选打码平台过 Geetest V4，失败自动重试）"""
    if max_retries is None:
        max_retries = LOGIN_MAX_RETRIES

    email, password = get_account_credentials()
    if not email or not password:
        print_with_time(
            "请设置账户信息（环境变量 IKUUU_EMAIL/IKUUU_PASSWORD 或代码中 LOCAL_EMAIL/LOCAL_PASSWORD）",
            "ERROR",
        )
        return None

    api_key, _ = get_captcha_config()
    if not api_key:
        print_with_time(
            "未配置打码 API Key，跳过打码登录路径",
            "DEBUG",
        )
        return 'CAPTCHA_ERROR'

    # Reason: 邮箱可能不含 @（异常配置），mask 时兜底避免崩溃
    if '@' in email:
        masked_email = f"{email[:3]}***{email.split('@')[1]}"
    else:
        masked_email = f"{email[:3]}***"
    print_with_time(f"账号: {masked_email}，域名: {BASE_DOMAIN}（打码平台）", "INFO")

    last_result = None
    for attempt in range(1, max_retries + 1):
        if attempt > 1:
            wait = attempt * 2
            print_with_time(f"第 {attempt}/{max_retries} 次重试登录（等待 {wait}s）...", "WARNING")
            time.sleep(wait)
        else:
            print_with_time(f"开始打码登录（最多 {max_retries} 次）...", "INFO")

        result = _do_login_once(email, password)
        last_result = result

        # 成功拿到 cookie 字符串
        if result and result != 'CAPTCHA_ERROR':
            return result

        # 账号密码错误等非验证码失败：不必重试
        if result is None:
            print_with_time("登录失败且非验证码问题，停止重试", "WARNING")
            return None

        # CAPTCHA_ERROR：继续重试（重新拉页 + 重新打码）
        print_with_time(f"验证码校验失败（第 {attempt}/{max_retries} 次）", "WARNING")

    return last_result



def checkin(cookie):
    """执行签到操作"""
    print_with_time("开始执行签到...", "INFO")
    headers = {
        'Origin': BASE_URL, 'Referer': f"{BASE_URL}/user",
        'Cookie': cookie, 'X-Requested-With': 'XMLHttpRequest',
        'Content-Type': 'application/x-www-form-urlencoded'
    }

    try:
        response = safe_request('POST', f"{BASE_URL}/user/checkin", headers=headers)
        if not response:
            print_with_time("签到请求失败", "ERROR")
            return False

        data = parse_json_response(response, "签到")
        msg = data.get('msg', '')
        if data.get('ret') == 1:
            print_with_time(f"签到成功: {msg}", "SUCCESS")
            return True
        elif "已经签到" in msg:
            print_with_time(f"今日已签到: {msg}", "WARNING")
            return True
        else:
            print_with_time(f"签到失败: {msg or '未知错误'}", "ERROR")
            return False
    except KeyboardInterrupt:
        raise
    except Exception as e:
        print_with_time(f"签到失败: {str(e)}", "ERROR")
        return False

def extract_account_info(soup):
    """从解析的HTML中提取账户信息"""
    # 关键词 -> 显示标签映射
    label_map = [
        (['会员时长', '时长', '到期'], '会员状态'),
        (['剩余流量', '流量', '可用'], '剩余流量'),
        (['在线设备', '设备', '连接'], '在线设备'),
        (['钱包', '余额', '积分'], '账户余额'),
    ]

    stat_cards = (soup.find_all('div', class_='card-statistic-2')
                  or soup.find_all('div', class_='card-statistic')
                  or soup.find_all('div', class_='card'))

    info_found = False
    for card in stat_cards:
        header = card.find('h4') or card.find('h3') or card.find('h5')
        if not header:
            continue
        title = header.get_text(strip=True)
        body = card.find('div', class_='card-body') or card.find('div', class_='card-content')
        if not body:
            continue

        value = re.sub(r'\s+', ' ', body.get_text(strip=True))
        label = None
        for keywords, lbl in label_map:
            if any(k in title for k in keywords):
                label = lbl
                break

        if label:
            print(f"  {label}: {value}")
            info_found = True
        elif value and len(value) > 3:
            print(f"  {title.rstrip(':')}: {value}")
            info_found = True

    return info_found

def get_user_info(cookie):
    """获取用户信息和流量数据"""
    print_separator("─", 50)
    print_with_time("正在获取账户信息...", "INFO")
    
    headers = {
        'Cookie': cookie
    }
    url = f"{BASE_URL}/user"
    
    try:
        response = safe_request('GET', url, headers=headers)
        
        if not response:
            print_with_time("获取账户信息失败", "ERROR")
            return False
            
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 检查页面标题确认登录状态
        page_title = soup.find('title')
        if page_title:
            title_text = page_title.get_text(strip=True)
            if any(keyword in title_text.lower() for keyword in ['login', '登录']):
                print_with_time("登录状态已失效，请检查账户信息", "ERROR")
                return False
        
        # 检查是否有Base64编码的内容
        decoded_html = None
        for script in soup.find_all('script'):
            script_content = script.get_text()
            if 'originBody' in script_content and 'decodeBase64' in script_content:
                match = re.search(r'var originBody = "([^"]+)"', script_content)
                if match:
                    try:
                        decoded_html = base64.b64decode(match.group(1)).decode('utf-8')
                    except Exception:
                        pass
                    break

        target_soup = BeautifulSoup(decoded_html, 'html.parser') if decoded_html else soup
        info_extracted = extract_account_info(target_soup)

        if not info_extracted:
            print_with_time("未能提取到详细账户信息", "WARNING")
            all_text = decoded_html or soup.get_text()
            numbers = re.findall(r'(\d+(?:\.\d+)?)\s*(GB|MB|天|个|USD|CNY)', all_text)
            if numbers:
                for value, unit in set(numbers):
                    print(f"  {value} {unit}")
        
        print_separator("─", 50)
        return True
        
    except KeyboardInterrupt:
        print_with_time("用户中断信息获取操作", "WARNING")
        raise
    except Exception as e:
        print_with_time(f"获取用户信息失败: {str(e)}", "ERROR")
        return False

def main():
    """主程序入口：账号密码 + 免费浏览器过 Geetest → 签到（打码/Cookie 为备用）"""
    print_separator("=", 60)
    print_with_time("自动签到程序启动", "INFO")
    print_separator("=", 60)

    if not check_dependencies():
        return False

    resolve_domain()

    start_time = time.time()
    email, password = get_account_credentials()
    has_credentials = bool(email and password)
    has_cookie = bool(get_cookie_from_config())
    api_key, provider = get_captcha_config()
    browser_on = use_browser_login_enabled()

    cookie_data = None

    # Reason: 优先免费浏览器点击 Geetest；打码平台与手工 Cookie 仅作备用
    if has_credentials:
        if browser_on:
            print_with_time("优先使用免费浏览器路径登录（无需打码平台）", "INFO")
            cookie_data = try_login_with_browser()

        if not cookie_data and api_key:
            print_with_time(
                f"浏览器登录不可用，回退打码平台: {provider or 'capsolver'}",
                "WARNING",
            )
            cookie_data = login_and_get_cookie()

        if not cookie_data and has_cookie:
            print_with_time("回退使用 IKUUU_COOKIE...", "INFO")
            cookie_data = try_login_with_cookie()

        if not cookie_data or cookie_data == 'CAPTCHA_ERROR':
            print_with_time(
                "登录失败。请确认：1) 已安装 playwright 浏览器  2) 账号密码正确  "
                "3) 可选配置 CAPSOLVER_API_KEY / IKUUU_COOKIE 作备用",
                "ERROR",
            )
            return False
    elif has_cookie:
        print_with_time("未配置账号密码，使用 Cookie 登录", "INFO")
        cookie_data = try_login_with_cookie()
    else:
        print_with_time(
            "请配置 IKUUU_EMAIL + IKUUU_PASSWORD（推荐，免费浏览器过验证码），"
            "或配置 IKUUU_COOKIE",
            "ERROR",
        )
        return False

    if cookie_data == 'CAPTCHA_ERROR':
        if has_cookie and has_credentials:
            print_with_time("打码登录失败，尝试备用 Cookie...", "WARNING")
            cookie_data = try_login_with_cookie()
        if cookie_data == 'CAPTCHA_ERROR' or not cookie_data:
            print_with_time(
                "验证码校验失败。可改用免费浏览器路径（默认），或配置有效的打码 Key",
                "ERROR",
            )
            return False

    if not cookie_data:
        # 登录失败，尝试其他域名
        print_with_time("登录失败，尝试切换域名...", "WARNING")
        original = BASE_DOMAIN
        for domain in discover_domains():
            if domain != original and test_domain(domain):
                _set_domain(domain)
                save_domain_to_file(domain)
                print_with_time(f"切换到 {domain}，重试登录...", "INFO")
                if has_credentials and browser_on:
                    cookie_data = try_login_with_browser()
                if not cookie_data and has_credentials and api_key:
                    cookie_data = login_and_get_cookie()
                if not cookie_data and has_cookie:
                    cookie_data = try_login_with_cookie()
                if cookie_data and cookie_data != 'CAPTCHA_ERROR':
                    break
                if cookie_data == 'CAPTCHA_ERROR':
                    cookie_data = None

    if not cookie_data or cookie_data == 'CAPTCHA_ERROR':
        print_with_time("所有域名均无法登录", "ERROR")
        return False

    time.sleep(1)
    # 2026-09-30：浏览器登录时可能已在页面内完成签到，优先采用该结果，
    # 避免 Cookie 转交 requests 后被 Cloudflare 拦截导致误报失败。
    browser_checkin = None
    try:
        import browser_login as _browser_login
        browser_checkin = getattr(_browser_login, 'LAST_BROWSER_RESULT', None)
    except Exception:
        pass

    if browser_checkin and isinstance(browser_checkin.get('checkin'), dict):
        cr = browser_checkin['checkin']
        cr_msg = str(cr.get('msg', ''))
        if cr.get('ret') == 1 or '已经签到' in cr_msg or '已签到' in cr_msg:
            print_with_time(f"✅ 浏览器内签到已完成: {cr_msg}", "SUCCESS")
            checkin_result = True
            time.sleep(1)
            get_user_info(cookie_data)
        else:
            print_with_time(f"浏览器内签到未成功({cr_msg})，走 requests 路径重试...", "WARNING")
            checkin_result = checkin(cookie_data)
            time.sleep(1)
            get_user_info(cookie_data)
    else:
        checkin_result = checkin(cookie_data)
        time.sleep(1)
        get_user_info(cookie_data)

    elapsed = round(time.time() - start_time, 2)
    print_separator("=", 60)
    print_with_time(f"执行完成，耗时 {elapsed} 秒", "SUCCESS" if checkin_result else "ERROR")
    print_separator("=", 60)
    return checkin_result

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)