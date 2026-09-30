"""免费浏览器登录：用 Playwright 点击 Geetest V4「点我开始验证」完成登录，无需打码平台。

Reason: 站点 Geetest 为 captcha_type=ai 的自适应一键验证，真实浏览器点击雷达按钮
后通常直接 verify success，再提交账号密码即可拿到会话 Cookie。
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse


def print_with_time(message, level="INFO"):
    """与 main.py 风格一致的带时间戳日志（模块可独立运行）。"""
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    level_emoji = {
        "INFO": "ℹ️",
        "SUCCESS": "✅",
        "WARNING": "⚠️",
        "ERROR": "❌",
        "DEBUG": "🔍",
    }
    emoji = level_emoji.get(level, "ℹ️")
    print(f"[{current_time}] {emoji} {message}")


# 会话 Cookie 关键字段（SSPanel）
SESSION_COOKIE_NAMES = ("uid", "email", "key", "ip", "expire_in", "PHPSESSID")


def _import_playwright():
    """延迟导入 Playwright，避免未安装时影响 Cookie/打码路径。"""
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except ImportError as e:
        raise ImportError(
            "未安装 playwright。请执行: pip install playwright && playwright install chromium"
        ) from e


def _launch_browser(playwright):
    """启动可用浏览器：优先系统 Chrome/Edge，其次 Playwright Chromium。"""
    launch_args = [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-dev-shm-usage",
    ]
    # Reason: CI 通常只有 playwright chromium；本地 macOS 常有系统 Chrome
    for channel in ("chrome", "msedge", None):
        try:
            kwargs = {
                "headless": True,
                "args": launch_args,
            }
            if channel:
                kwargs["channel"] = channel
            browser = playwright.chromium.launch(**kwargs)
            print_with_time(
                f"浏览器启动成功（{'channel=' + channel if channel else 'playwright-chromium'}）",
                "DEBUG",
            )
            return browser
        except Exception as e:
            print_with_time(f"浏览器启动失败 ({channel or 'chromium'}): {e}", "DEBUG")
            continue
    raise RuntimeError(
        "无法启动浏览器。请安装 Chrome/Edge，或执行: playwright install chromium"
    )


def _cookie_header_from_context(context, base_url: str) -> str:
    """从浏览器上下文提取登录相关 Cookie 字符串。"""
    host = urlparse(base_url).hostname or ""
    cookies = context.cookies()
    # Reason: 只保留本站会话字段，避免把一堆分析 Cookie 带进后续 requests
    parts = []
    seen = set()
    for name in SESSION_COOKIE_NAMES:
        for c in cookies:
            domain = (c.get("domain") or "").lstrip(".")
            if c.get("name") != name:
                continue
            if host and domain and host != domain and not host.endswith("." + domain) and not domain.endswith(host):
                # 域名不完全匹配时仍允许包含 ikuuu 的 cookie
                if "ikuuu" not in domain and "ikuuu" not in host:
                    continue
            if name in seen:
                continue
            parts.append(f"{name}={c.get('value', '')}")
            seen.add(name)
    # 2026-09-30 修复：站点在 Cloudflare 后面，浏览器会拿到 cf_clearance 等
    # 防 Bot Cookie，且服务端校验与 UA 绑定。白名单外的 Cookie 也必须带上，
    # 否则转交 requests 后会被打回登录页（实测跳转 /auth/login）。
    for c in cookies:
        domain = c.get("domain") or ""
        if "ikuuu" in domain or (host and host in domain):
            n = c.get("name")
            if n and n not in seen:
                parts.append(f"{n}={c.get('value', '')}")
                seen.add(n)
    return "; ".join(parts)


def _wait_and_pass_geetest(page, timeout_sec: int = 25) -> bool:
    """等待 Geetest 加载，点击「点我开始验证」，直到 Captcha.isReady()。"""
    deadline = time.time() + timeout_sec
    clicked = False

    while time.time() < deadline:
        try:
            state = page.evaluate(
                """() => {
                    const ready = !!(window.Captcha && window.Captcha.isReady && window.Captcha.isReady());
                    const loaded = !!(window.Captcha && window.Captcha.isLoaded && window.Captcha.isLoaded());
                    const err = (window.Captcha && window.Captcha.getError) ? window.Captcha.getError() : null;
                    const text = (document.querySelector('.embed-captcha') || {}).innerText || '';
                    return {ready, loaded, err, text: String(text).slice(0, 80)};
                }"""
            )
        except Exception:
            state = {"ready": False, "loaded": False, "err": None, "text": ""}

        if state.get("ready"):
            print_with_time("Geetest 验证已通过", "SUCCESS")
            return True

        if state.get("err"):
            print_with_time(f"Geetest 错误: {state['err']}", "WARNING")

        # 未通过时尝试点击雷达/按钮
        if not clicked or (time.time() + timeout_sec - deadline) % 3 < 0.6:
            selectors = [
                ".geetest_radar_btn",
                ".geetest_btn_click",
                ".geetest_btn",
                ".geetest_holder",
                ".geetest_btn_svg",
                "text=点我开始验证",
            ]
            for sel in selectors:
                try:
                    loc = page.locator(sel).first
                    if loc.count() > 0 and loc.is_visible():
                        loc.click(timeout=2000)
                        clicked = True
                        print_with_time(f"已点击 Geetest 控件: {sel}", "DEBUG")
                        page.wait_for_timeout(1200)
                        break
                except Exception:
                    continue

        page.wait_for_timeout(500)

    # 最后再查一次
    try:
        ready = page.evaluate(
            "() => !!(window.Captcha && window.Captcha.isReady && window.Captcha.isReady())"
        )
        if ready:
            print_with_time("Geetest 验证已通过", "SUCCESS")
            return True
    except Exception:
        pass

    print_with_time("等待 Geetest 通过超时", "ERROR")
    return False


def login_with_browser(
    email: str,
    password: str,
    base_url: str,
    timeout_ms: int = 60000,
) -> Optional[str]:
    """用无头浏览器完成 Geetest + 登录，返回 Cookie 字符串；失败返回 None。"""
    if not email or not password:
        print_with_time("浏览器登录缺少邮箱或密码", "ERROR")
        return None

    base_url = base_url.rstrip("/")
    login_url = f"{base_url}/auth/login"
    sync_playwright = _import_playwright()

    print_with_time("使用免费浏览器路径过 Geetest 并登录...", "INFO")
    browser = None
    try:
        with sync_playwright() as p:
            browser = _launch_browser(p)
            context = browser.new_context(
                locale="zh-CN",
                viewport={"width": 1280, "height": 800},
                # Reason: UA 必须与 main.py create_session 的 UA 完全一致，
                # Cloudflare 的 cf_clearance 与 UA 绑定，不一致会导致
                # 提取的 Cookie 在后续 requests 中失效。
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/138.0.0.0 Safari/537.36 Edg/138.0.0.0"
                ),
            )
            # Reason: 降低自动化指纹，Geetest 对 webdriver 更敏感
            context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )
            page = context.new_page()
            page.goto(login_url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_selector("#email", timeout=20000)
            page.wait_for_timeout(800)

            page.fill("#email", email)
            # 部分主题密码框 id 为 password，name 为 passwd
            if page.locator("#password").count():
                page.fill("#password", password)
            else:
                page.fill("input[name='passwd'], input[type='password']", password)

            page.wait_for_timeout(1000)

            if not _wait_and_pass_geetest(page, timeout_sec=30):
                browser.close()
                return None

            page.click("button.login, button[type='submit'].login, .login")
            # 登录成功会跳转 /user；失败可能弹 swal 仍停在 login
            try:
                page.wait_for_url("**/user**", timeout=20000)
            except Exception:
                # 再等一下网络
                page.wait_for_timeout(2000)

            final_url = page.url
            if "/user" not in final_url:
                # 读错误提示
                try:
                    msg = page.evaluate(
                        """() => {
                            const a = document.querySelector(
                              '.swal2-html-container, .swal2-content, .swal2-title'
                            );
                            return a ? a.innerText : '';
                        }"""
                    )
                except Exception:
                    msg = ""
                print_with_time(
                    f"浏览器登录未进入用户中心（url={final_url}）{('，' + msg) if msg else ''}",
                    "ERROR",
                )
                browser.close()
                return None

            cookie = _cookie_header_from_context(context, base_url)
            browser.close()
            browser = None

            if not cookie or "uid=" not in cookie.lower():
                print_with_time(f"登录后 Cookie 不完整: {cookie[:80]}...", "ERROR")
                return None

            print_with_time("浏览器登录成功（免费过 Geetest）", "SUCCESS")
            return cookie
    except ImportError as e:
        print_with_time(str(e), "ERROR")
        return None
    except Exception as e:
        print_with_time(f"浏览器登录失败: {e}", "ERROR")
        return None
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass


if __name__ == "__main__":
    import os
    import sys

    email = os.getenv("IKUUU_EMAIL", "")
    password = os.getenv("IKUUU_PASSWORD", "")
    domain = os.getenv("IKUUU_DOMAIN", "ikuuu.org")
    cookie = login_with_browser(email, password, f"https://{domain}")
    print("cookie:", cookie)
    sys.exit(0 if cookie else 1)
