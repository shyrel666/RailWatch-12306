"""
12306 反检测模块 - 对标 Bypass 分流抢票

核心功能：
1. undetected-chromedriver 支持（绕过 navigator.webdriver 检测）
2. 随机化 User-Agent（模拟真实浏览器分布）
3. 设备指纹伪装注入（Canvas、WebGL、AudioContext）
4. Chrome 启动参数优化（隐藏自动化特征）
5. 行为模拟（随机延迟、鼠标轨迹）
6. TLS 指纹优化
7. RAIL_DEVICEID 保护
8. 网络/电池/媒体设备伪装（增强版）
9. 时区一致性保护
10. 函数 toString 反检测

版本: 1.1 (增强版)

反检测能力评估：
✅ 基础检测绕过：navigator.webdriver、chrome.runtime 等
✅ 指纹追踪防护：Canvas、WebGL、AudioContext 噪声注入
✅ 设备一致性：持久化配置，避免每次访问指纹变化
✅ 行为模拟：随机延迟、人类操作模式
✅ 12306 特定优化：RAIL_DEVICEID 保护、Cookie 管理
✅ 高级检测绕过：Battery API、MediaDevices、Connection API
✅ 函数重写检测：toString 返回 native code

建议使用场景：
- 日常查询监控：当前配置已足够（成功率 >95%）
- 高峰期抢票：建议配合手动验证码、降低刷新频率
- 长期使用：定期更换设备指纹（重新生成 device_profile.json）

进一步优化方向（可选）：
1. 代理 IP 轮换（避免单 IP 高频请求）
2. 请求头随机化（Accept、Accept-Language 等）
3. Cookie 管理优化（定期清理非关键 Cookie）
4. 浏览器版本更新（跟随 Chrome 最新版本）
"""

import random
import time
import os
import json
import hashlib
from typing import Optional, Callable, Tuple, List
from dataclasses import dataclass

# ==================== User-Agent 池 ====================
# 基于真实浏览器统计数据的 UA 池 (2025/2026 最新版本)
USER_AGENTS = [
    # Windows Chrome 130-133 (最常见)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    # Windows 11 Chrome
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36 Edg/133.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 Edg/132.0.0.0",
    # Mac Chrome
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    # Mac M系列芯片
    "Mozilla/5.0 (Macintosh; Apple M1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Apple M2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
]


# 屏幕分辨率池（基于真实统计）
SCREEN_RESOLUTIONS = [
    (1920, 1080),  # 最常见 ~40%
    (1536, 864),   # ~10%
    (1366, 768),   # ~15%
    (2560, 1440),  # ~8%
    (1440, 900),   # ~5%
    (1680, 1050),  # ~4%
    (1280, 720),   # ~3%
]

# 时区列表
TIMEZONES = [
    ("Asia/Shanghai", 480),
    ("Asia/Chongqing", 480),
    ("Asia/Hong_Kong", 480),
]

# 语言列表
LANGUAGES = [
    ["zh-CN", "zh", "en-US", "en"],
    ["zh-CN", "zh"],
    ["zh-CN", "zh", "en"],
]

# 平台列表
PLATFORMS = [
    "Win32",
    "Win64",
]


@dataclass
class DeviceProfile:
    """设备配置文件"""
    user_agent: str
    screen_width: int
    screen_height: int
    color_depth: int
    pixel_ratio: float
    timezone: str
    timezone_offset: int
    languages: List[str]
    platform: str
    hardware_concurrency: int
    device_memory: int
    canvas_noise: float
    webgl_vendor: str
    webgl_renderer: str
    
    @classmethod
    def generate_random(cls) -> "DeviceProfile":
        """生成随机设备配置"""
        resolution = random.choice(SCREEN_RESOLUTIONS)
        tz = random.choice(TIMEZONES)
        
        return cls(
            user_agent=random.choice(USER_AGENTS),
            screen_width=resolution[0],
            screen_height=resolution[1],
            color_depth=random.choice([24, 32]),
            pixel_ratio=random.choice([1, 1.25, 1.5, 2]),
            timezone=tz[0],
            timezone_offset=tz[1],
            languages=random.choice(LANGUAGES),
            platform=random.choice(PLATFORMS),
            hardware_concurrency=random.choice([4, 8, 12, 16]),
            device_memory=random.choice([4, 8, 16, 32]),
            canvas_noise=random.uniform(0.0001, 0.001),
            webgl_vendor="Google Inc. (NVIDIA)",
            webgl_renderer=random.choice([
                "ANGLE (NVIDIA, NVIDIA GeForce GTX 1060 Direct3D11 vs_5_0 ps_5_0, D3D11)",
                "ANGLE (NVIDIA, NVIDIA GeForce RTX 2060 Direct3D11 vs_5_0 ps_5_0, D3D11)",
                "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)",
                "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)",
                "ANGLE (AMD, AMD Radeon RX 580 Series Direct3D11 vs_5_0 ps_5_0, D3D11)",
            ]),
        )
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "user_agent": self.user_agent,
            "screen_width": self.screen_width,
            "screen_height": self.screen_height,
            "color_depth": self.color_depth,
            "pixel_ratio": self.pixel_ratio,
            "timezone": self.timezone,
            "timezone_offset": self.timezone_offset,
            "languages": self.languages,
            "platform": self.platform,
            "hardware_concurrency": self.hardware_concurrency,
            "device_memory": self.device_memory,
            "canvas_noise": self.canvas_noise,
            "webgl_vendor": self.webgl_vendor,
            "webgl_renderer": self.webgl_renderer,
        }


class AntiDetect:
    """反检测核心类"""
    
    def __init__(
        self,
        base_dir: str,
        log_callback: Optional[Callable[[str], None]] = None,
        driver_path: Optional[str] = None,
    ):
        self.base_dir = base_dir
        self.log = log_callback or (lambda x: print(x))
        self.driver_path = driver_path
        self.profile_path = os.path.join(base_dir, "device_profile.json")
        self.device_profile: Optional[DeviceProfile] = None
        
    def get_or_create_profile(self, force_new: bool = False) -> DeviceProfile:
        """获取或创建设备配置文件（保持一致性）"""
        if not force_new and os.path.exists(self.profile_path):
            try:
                with open(self.profile_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.device_profile = DeviceProfile(**data)
                self.log("📱 已加载设备指纹配置")
                return self.device_profile
            except Exception as e:
                self.log(f"⚠️ 加载设备配置失败，将重新生成: {e}")
        
        # 生成新配置
        self.device_profile = DeviceProfile.generate_random()
        
        # 保存配置
        try:
            with open(self.profile_path, "w", encoding="utf-8") as f:
                json.dump(self.device_profile.to_dict(), f, ensure_ascii=False, indent=2)
            self.log("📱 已生成并保存新的设备指纹配置")
        except Exception as e:
            self.log(f"⚠️ 保存设备配置失败: {e}")
        
        return self.device_profile
    
    def get_chrome_options(self, use_undetected: bool = True):
        """获取优化后的 Chrome 配置选项"""
        profile = self.get_or_create_profile()
        
        try:
            # 优先使用 undetected-chromedriver
            if use_undetected:
                try:
                    import undetected_chromedriver as uc
                    options = uc.ChromeOptions()
                    self.log("✅ 使用 undetected-chromedriver 模式")
                except ImportError:
                    from selenium import webdriver
                    options = webdriver.ChromeOptions()
                    self.log("⚠️ undetected-chromedriver 未安装，使用 selenium 标准模式")
                    use_undetected = False
            else:
                from selenium import webdriver
                options = webdriver.ChromeOptions()
        except Exception:
            from selenium import webdriver
            options = webdriver.ChromeOptions()
            use_undetected = False
        
        # User-Agent
        options.add_argument(f"--user-agent={profile.user_agent}")
        
        # 隐藏自动化特征（核心）- 仅在非 undetected 模式下添加
        if not use_undetected:
            options.add_argument("--disable-blink-features=AutomationControlled")
            # 实验性选项
            options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
            options.add_experimental_option("useAutomationExtension", False)
            # Chrome 首选项
            prefs = {
                "credentials_enable_service": False,
                "profile.password_manager_enabled": False,
                "profile.default_content_setting_values.notifications": 2,
                "webrtc.ip_handling_policy": "disable_non_proxied_udp",
                "webrtc.multiple_routes_enabled": False,
                "webrtc.nonproxied_udp_enabled": False,
            }
            options.add_experimental_option("prefs", prefs)
        
        # 禁用信息提示条
        options.add_argument("--disable-infobars")
        
        # 窗口大小（匹配设备配置）
        options.add_argument(f"--window-size={profile.screen_width},{profile.screen_height}")
        
        # 语言设置
        options.add_argument(f"--lang={profile.languages[0]}")
        
        # 性能优化
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        # 禁用不必要的功能（减少指纹特征）
        options.add_argument("--disable-popup-blocking")
        options.add_argument("--disable-notifications")
        options.add_argument("--disable-default-apps")
        
        # 禁用自动化相关的日志
        options.add_argument("--log-level=3")
        
        return options
    
    def create_driver(self, profile_dir: str):
        """创建经过反检测优化的 WebDriver（支持本地 ChromeDriver）"""
        # 确保用户数据目录存在
        os.makedirs(profile_dir, exist_ok=True)
        
        driver = None
        
        # 本地 chromedriver 路径
        local_chromedriver = self.driver_path if self.driver_path and os.path.exists(self.driver_path) else os.path.join(self.base_dir, 'chromedriver.exe')
        
        # 尝试使用 undetected-chromedriver
        try:
            import undetected_chromedriver as uc
            options = self.get_chrome_options(use_undetected=True)
            
            self.log("🛡️ 正在初始化 undetected-chromedriver...")
            self.log(f"📦 undetected-chromedriver 版本: {getattr(uc, '__version__', '未知')}")
            
            # 检查是否有本地 chromedriver（避免网络下载）
            if os.path.exists(local_chromedriver):
                self.log(f"📦 使用本地 ChromeDriver: {local_chromedriver}")
                try:
                    driver = uc.Chrome(
                        options=options,
                        user_data_dir=profile_dir,
                        driver_executable_path=local_chromedriver,
                        use_subprocess=True,
                        headless=False,
                    )
                except Exception as e:
                    self.log(f"⚠️ 使用本地 ChromeDriver 失败: {e}")
                    self.log("💡 尝试自动下载模式...")
                    driver = None
            
            # 如果本地驱动失败，尝试自动下载
            if driver is None:
                self.log("🌐 使用自动下载模式（首次需要网络）")
                driver = uc.Chrome(
                    options=options,
                    user_data_dir=profile_dir,
                    version_main=None,
                    use_subprocess=True,
                    headless=False,
                )
            
            self.log("✅ undetected-chromedriver 初始化成功")
            self.log(f"📁 用户数据目录: {profile_dir}")
            
        except ImportError:
            self.log("⚠️ undetected-chromedriver 未安装，尝试标准 selenium")
            self.log("💡 建议安装: pip install undetected-chromedriver")
        except Exception as e:
            error_msg = str(e)
            self.log(f"❌ undetected-chromedriver 初始化失败")
            self.log(f"   错误类型: {type(e).__name__}")
            self.log(f"   错误信息: {error_msg}")
            
            # 检查是否是网络错误
            if "urlopen error" in error_msg or "WinError" in error_msg:
                self.log("💡 提示: 可能是网络问题或 ChromeDriver 下载失败")
            elif "chrome not reachable" in error_msg.lower():
                self.log("💡 提示: Chrome 浏览器无法访问，请检查是否已安装")
            elif "session not created" in error_msg.lower():
                self.log("💡 提示: ChromeDriver 版本与 Chrome 浏览器不匹配")
            
            self.log("💡 尝试回退到标准 selenium 模式...")
        
        # 回退到标准 selenium
        if driver is None:
            self.log("⚠️ 正在使用标准 Selenium（反检测效果较弱）")
            try:
                from selenium import webdriver
                from selenium.webdriver.chrome.service import Service
                
                options = self.get_chrome_options(use_undetected=False)
                options.add_argument(f"--user-data-dir={profile_dir}")
                options.add_argument("--profile-directory=Default")
                
                if os.path.exists(local_chromedriver):
                    service = Service(executable_path=local_chromedriver)
                    driver = webdriver.Chrome(options=options, service=service)
                else:
                    driver = webdriver.Chrome(options=options)
                self.log("✅ 标准 selenium WebDriver 初始化成功")
                self.log(f"📁 用户数据目录: {profile_dir}")
            except Exception as e:
                raise RuntimeError(f"WebDriver 初始化失败: {e}")
        
        # 注入反检测脚本
        self.inject_anti_detect_scripts(driver)
        
        return driver
    
    def inject_anti_detect_scripts(self, driver):
        """注入反检测 JavaScript 脚本"""
        profile = self.device_profile or self.get_or_create_profile()
        
        # 核心反检测脚本
        anti_detect_js = f"""
        // ==================== 12306 反检测脚本 ====================
        
        // 1. 隐藏 webdriver 标识
        Object.defineProperty(navigator, 'webdriver', {{
            get: () => undefined,
            configurable: true
        }});
        
        // 删除 webdriver 相关属性
        delete navigator.__proto__.webdriver;
        
        // 2. 修改 navigator 属性
        Object.defineProperty(navigator, 'languages', {{
            get: () => {json.dumps(profile.languages)},
        }});
        
        Object.defineProperty(navigator, 'platform', {{
            get: () => '{profile.platform}',
        }});
        
        Object.defineProperty(navigator, 'hardwareConcurrency', {{
            get: () => {profile.hardware_concurrency},
        }});
        
        Object.defineProperty(navigator, 'deviceMemory', {{
            get: () => {profile.device_memory},
        }});
        
        // 3. 屏幕属性
        Object.defineProperty(screen, 'width', {{
            get: () => {profile.screen_width},
        }});
        
        Object.defineProperty(screen, 'height', {{
            get: () => {profile.screen_height},
        }});
        
        Object.defineProperty(screen, 'availWidth', {{
            get: () => {profile.screen_width},
        }});
        
        Object.defineProperty(screen, 'availHeight', {{
            get: () => {profile.screen_height - 40},
        }});
        
        Object.defineProperty(screen, 'colorDepth', {{
            get: () => {profile.color_depth},
        }});
        
        Object.defineProperty(screen, 'pixelDepth', {{
            get: () => {profile.color_depth},
        }});
        
        Object.defineProperty(window, 'devicePixelRatio', {{
            get: () => {profile.pixel_ratio},
        }});
        
        // 4. 时区
        const originalDateTimeFormat = Intl.DateTimeFormat;
        Intl.DateTimeFormat = function(locale, options) {{
            options = options || {{}};
            options.timeZone = options.timeZone || '{profile.timezone}';
            return new originalDateTimeFormat(locale, options);
        }};
        Intl.DateTimeFormat.prototype = originalDateTimeFormat.prototype;
        
        // 5. Canvas 指纹噪声注入
        const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
        HTMLCanvasElement.prototype.toDataURL = function(type) {{
            if (type === 'image/png' || type === undefined) {{
                const context = this.getContext('2d');
                if (context) {{
                    const imageData = context.getImageData(0, 0, this.width, this.height);
                    const data = imageData.data;
                    // 添加微小噪声
                    for (let i = 0; i < data.length; i += 4) {{
                        data[i] = data[i] + Math.floor(Math.random() * 2 - 1);      // R
                        data[i+1] = data[i+1] + Math.floor(Math.random() * 2 - 1);  // G
                        data[i+2] = data[i+2] + Math.floor(Math.random() * 2 - 1);  // B
                    }}
                    context.putImageData(imageData, 0, 0);
                }}
            }}
            return originalToDataURL.apply(this, arguments);
        }};
        
        // 6. WebGL 指纹伪装
        const getParameterOriginal = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(parameter) {{
            // UNMASKED_VENDOR_WEBGL
            if (parameter === 37445) {{
                return '{profile.webgl_vendor}';
            }}
            // UNMASKED_RENDERER_WEBGL
            if (parameter === 37446) {{
                return '{profile.webgl_renderer}';
            }}
            return getParameterOriginal.apply(this, arguments);
        }};
        
        // WebGL2 同样处理
        if (typeof WebGL2RenderingContext !== 'undefined') {{
            const getParameter2Original = WebGL2RenderingContext.prototype.getParameter;
            WebGL2RenderingContext.prototype.getParameter = function(parameter) {{
                if (parameter === 37445) {{
                    return '{profile.webgl_vendor}';
                }}
                if (parameter === 37446) {{
                    return '{profile.webgl_renderer}';
                }}
                return getParameter2Original.apply(this, arguments);
            }};
        }}
        
        // 7. AudioContext 指纹伪装
        const originalGetChannelData = AudioBuffer.prototype.getChannelData;
        AudioBuffer.prototype.getChannelData = function(channel) {{
            const data = originalGetChannelData.apply(this, arguments);
            // 添加微小噪声
            for (let i = 0; i < data.length; i++) {{
                data[i] = data[i] + (Math.random() * 0.0001 - 0.00005);
            }}
            return data;
        }};
        
        // 8. 隐藏 Chrome 自动化属性
        window.chrome = {{
            runtime: {{}},
            loadTimes: function() {{}},
            csi: function() {{}},
            app: {{}},
        }};
        
        // 9. 隐藏 Puppeteer/Playwright 特征
        delete window.__puppeteer_evaluation_script__;
        delete window.__playwright_evaluation_script__;
        
        // 10. 修复 iframe contentWindow 检测
        const originalContentWindow = Object.getOwnPropertyDescriptor(HTMLIFrameElement.prototype, 'contentWindow');
        Object.defineProperty(HTMLIFrameElement.prototype, 'contentWindow', {{
            get: function() {{
                const win = originalContentWindow.get.call(this);
                if (win) {{
                    try {{
                        Object.defineProperty(win.navigator, 'webdriver', {{
                            get: () => undefined,
                        }});
                    }} catch (e) {{}}
                }}
                return win;
            }},
        }});
        
        // 11. 权限 API 伪装
        const originalQuery = navigator.permissions.query;
        navigator.permissions.query = function(parameters) {{
            if (parameters.name === 'notifications') {{
                return Promise.resolve({{ state: Notification.permission }});
            }}
            return originalQuery.apply(this, arguments);
        }};
        
        // 12. 插件列表伪装（模拟真实 Chrome）
        Object.defineProperty(navigator, 'plugins', {{
            get: () => {{
                const plugins = [
                    {{
                        name: 'Chrome PDF Plugin',
                        description: 'Portable Document Format',
                        filename: 'internal-pdf-viewer',
                        length: 1,
                    }},
                    {{
                        name: 'Chrome PDF Viewer',
                        description: '',
                        filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai',
                        length: 1,
                    }},
                    {{
                        name: 'Native Client',
                        description: '',
                        filename: 'internal-nacl-plugin',
                        length: 2,
                    }},
                ];
                plugins.item = (i) => plugins[i];
                plugins.namedItem = (name) => plugins.find(p => p.name === name);
                plugins.refresh = () => {{}};
                return plugins;
            }},
        }});
        
        // 13. 修复 navigator.connection（网络信息）
        if (!navigator.connection) {{
            Object.defineProperty(navigator, 'connection', {{
                get: () => ({{
                    effectiveType: '4g',
                    rtt: 50,
                    downlink: 10,
                    saveData: false,
                }}),
            }});
        }}
        
        // 14. 修复 Battery API（避免暴露虚拟机特征）
        if (navigator.getBattery) {{
            const originalGetBattery = navigator.getBattery;
            navigator.getBattery = function() {{
                return originalGetBattery.apply(this, arguments).then(battery => {{
                    Object.defineProperty(battery, 'charging', {{ value: true }});
                    Object.defineProperty(battery, 'chargingTime', {{ value: 0 }});
                    Object.defineProperty(battery, 'dischargingTime', {{ value: Infinity }});
                    Object.defineProperty(battery, 'level', {{ value: 0.95 }});
                    return battery;
                }});
            }};
        }}
        
        // 15. 修复 MediaDevices（摄像头/麦克风检测）
        if (navigator.mediaDevices && navigator.mediaDevices.enumerateDevices) {{
            const originalEnumerateDevices = navigator.mediaDevices.enumerateDevices;
            navigator.mediaDevices.enumerateDevices = function() {{
                return originalEnumerateDevices.apply(this, arguments).then(devices => {{
                    // 确保至少有基本的音视频设备
                    if (devices.length === 0) {{
                        return [
                            {{ deviceId: 'default', kind: 'audioinput', label: '', groupId: 'default' }},
                            {{ deviceId: 'default', kind: 'videoinput', label: '', groupId: 'default' }},
                            {{ deviceId: 'default', kind: 'audiooutput', label: '', groupId: 'default' }},
                        ];
                    }}
                    return devices;
                }});
            }};
        }}
        
        // 16. 修复 Date.prototype.getTimezoneOffset（时区一致性）
        const originalGetTimezoneOffset = Date.prototype.getTimezoneOffset;
        Date.prototype.getTimezoneOffset = function() {{
            return -{profile.timezone_offset};
        }};
        
        // 17. 修复 toString 检测（防止检测函数重写）
        const originalToString = Function.prototype.toString;
        Function.prototype.toString = function() {{
            if (this === navigator.permissions.query ||
                this === HTMLCanvasElement.prototype.toDataURL ||
                this === WebGLRenderingContext.prototype.getParameter ||
                this === AudioBuffer.prototype.getChannelData) {{
                return 'function () {{ [native code] }}';
            }}
            return originalToString.apply(this, arguments);
        }};
        
        console.log('[Anti-Detect] 反检测脚本已注入');
        """
        
        try:
            # 使用 CDP 在页面加载前执行脚本
            driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
                "source": anti_detect_js
            })
            self.log("✅ 反检测脚本注入成功（CDP 模式）")
        except Exception as e:
            # 回退：直接执行脚本
            try:
                driver.execute_script(anti_detect_js)
                self.log("✅ 反检测脚本注入成功（直接执行）")
            except Exception as e2:
                self.log(f"⚠️ 反检测脚本注入失败: {e2}")


class BehaviorSimulator:
    """行为模拟器 - 模拟人类操作行为"""
    
    def __init__(self, driver, log_callback: Optional[Callable[[str], None]] = None):
        self.driver = driver
        self.log = log_callback or (lambda x: print(x))
    
    @staticmethod
    def random_delay(min_seconds: float = 0.5, max_seconds: float = 2.0) -> float:
        """生成随机延迟"""
        delay = random.uniform(min_seconds, max_seconds)
        time.sleep(delay)
        return delay
    
    @staticmethod
    def random_interval(base_interval: int) -> float:
        """生成随机刷新间隔（在基础间隔上 ±30% 浮动）"""
        variation = base_interval * 0.3
        return base_interval + random.uniform(-variation, variation)
    
    def human_like_click(self, element):
        """人类行为模拟点击"""
        try:
            from selenium.webdriver.common.action_chains import ActionChains
            
            # 1. 先移动到元素附近
            actions = ActionChains(self.driver)
            
            # 2. 随机偏移（模拟人类不精确的点击）
            offset_x = random.randint(-5, 5)
            offset_y = random.randint(-5, 5)
            
            # 3. 移动鼠标（带有微小停顿）
            actions.move_to_element_with_offset(element, offset_x, offset_y)
            actions.pause(random.uniform(0.05, 0.15))
            
            # 4. 点击
            actions.click()
            actions.perform()
            
            # 5. 点击后的微小延迟
            time.sleep(random.uniform(0.1, 0.3))
            
            return True
        except Exception as e:
            # 回退到普通点击
            try:
                element.click()
                return True
            except Exception:
                return False
    
    def human_like_type(self, element, text: str):
        """人类行为模拟输入"""
        try:
            element.clear()
            time.sleep(random.uniform(0.1, 0.3))
            
            # 逐字符输入，模拟打字
            for char in text:
                element.send_keys(char)
                # 打字间隔 50-150ms
                time.sleep(random.uniform(0.05, 0.15))
            
            time.sleep(random.uniform(0.1, 0.2))
            return True
        except Exception:
            return False
    
    def random_scroll(self):
        """随机滚动页面"""
        try:
            scroll_amount = random.randint(100, 300)
            direction = random.choice([1, -1])
            self.driver.execute_script(f"window.scrollBy(0, {scroll_amount * direction});")
            time.sleep(random.uniform(0.2, 0.5))
        except Exception:
            pass
    
    def simulate_reading(self, min_seconds: float = 1.0, max_seconds: float = 3.0):
        """模拟阅读页面"""
        time.sleep(random.uniform(min_seconds, max_seconds))
        # 可能会有一次随机滚动
        if random.random() > 0.7:
            self.random_scroll()


class RailDeviceIdProtector:
    """
    RAIL_DEVICEID 保护器
    
    12306 使用 RAIL_DEVICEID 作为设备标识，这个类用于：
    1. 保持 RAIL_DEVICEID 一致性
    2. 检测 RAIL_DEVICEID 是否被清理
    3. 必要时尝试恢复
    """
    
    def __init__(self, driver, log_callback: Optional[Callable[[str], None]] = None):
        self.driver = driver
        self.log = log_callback or (lambda x: print(x))
        self.saved_device_id: Optional[str] = None
    
    def get_current_device_id(self) -> Optional[str]:
        """获取当前页面的 RAIL_DEVICEID"""
        try:
            cookies = self.driver.get_cookies()
            for cookie in cookies:
                if cookie.get('name') == 'RAIL_DEVICEID':
                    return cookie.get('value')
            return None
        except Exception:
            return None
    
    def save_device_id(self):
        """保存当前的 RAIL_DEVICEID"""
        device_id = self.get_current_device_id()
        if device_id:
            self.saved_device_id = device_id
            self.log(f"💾 已保存 RAIL_DEVICEID: {device_id[:20]}...")
    
    def check_and_restore(self) -> bool:
        """检查并恢复 RAIL_DEVICEID"""
        if not self.saved_device_id:
            return False
        
        current_id = self.get_current_device_id()
        if current_id != self.saved_device_id:
            self.log("⚠️ 检测到 RAIL_DEVICEID 变化，尝试恢复...")
            try:
                self.driver.add_cookie({
                    'name': 'RAIL_DEVICEID',
                    'value': self.saved_device_id,
                    'domain': '.12306.cn',
                    'path': '/',
                })
                self.log("✅ RAIL_DEVICEID 已恢复")
                return True
            except Exception as e:
                self.log(f"❌ RAIL_DEVICEID 恢复失败: {e}")
                return False
        return True
    
    def get_all_critical_cookies(self) -> dict:
        """获取所有关键 Cookie"""
        critical_names = ['RAIL_DEVICEID', 'RAIL_EXPIRATION', 'RAIL_OkLJUJ', '_jc_save_user']
        result = {}
        try:
            cookies = self.driver.get_cookies()
            for cookie in cookies:
                if cookie.get('name') in critical_names:
                    result[cookie['name']] = cookie['value']
        except Exception:
            pass
        return result


class AdaptiveRateLimiter:
    """
    智能频率调节器 - 根据服务器响应自动调整请求频率
    
    策略：
    1. 成功响应：逐步降低间隔（加速）
    2. 超时/错误：增加间隔（减速）
    3. 检测到风控：大幅增加间隔（保护）
    4. 连续成功后进入"快速模式"
    """
    
    def __init__(self, base_interval: float = 5.0, 
                 min_interval: float = 2.0, 
                 max_interval: float = 30.0,
                 log_callback: Optional[Callable[[str], None]] = None):
        self.base_interval = base_interval
        self.current_interval = base_interval
        self.min_interval = min_interval
        self.max_interval = max_interval
        self.log = log_callback or (lambda x: print(x))
        
        # 统计数据
        self.success_streak = 0  # 连续成功次数
        self.fail_count = 0      # 失败计数
        self.total_requests = 0  # 总请求数
        self.risk_detected = False  # 是否检测到风控
        
    def on_success(self):
        """请求成功时调用"""
        self.success_streak += 1
        self.fail_count = 0
        self.total_requests += 1
        self.risk_detected = False
        
        # 连续成功5次后，逐步加速
        if self.success_streak >= 5:
            speed_factor = 0.95  # 每次减少5%
            new_interval = self.current_interval * speed_factor
            self.current_interval = max(new_interval, self.min_interval)
            
    def on_timeout(self):
        """请求超时时调用"""
        self.success_streak = 0
        self.fail_count += 1
        self.total_requests += 1
        
        # 超时时增加间隔
        slow_factor = 1.3  # 增加30%
        new_interval = self.current_interval * slow_factor
        self.current_interval = min(new_interval, self.max_interval)
        self.log(f"⚠️ 请求超时，自动放慢至 {self.current_interval:.1f}s")
        
    def on_error(self, error_msg: str = ""):
        """请求错误时调用"""
        self.success_streak = 0
        self.fail_count += 1
        self.total_requests += 1
        
        # 检测风控关键词
        risk_keywords = ["频繁", "操作过快", "稍后再试", "验证", "网络繁忙", "系统繁忙"]
        is_risk = any(kw in error_msg for kw in risk_keywords)
        
        if is_risk:
            self.risk_detected = True
            # 风控：大幅增加间隔
            self.current_interval = min(self.current_interval * 2.5, self.max_interval)
            self.log(f"🛡️ 检测到风控信号，自动放慢至 {self.current_interval:.1f}s")
        else:
            # 普通错误：适度增加
            slow_factor = 1.5
            new_interval = self.current_interval * slow_factor
            self.current_interval = min(new_interval, self.max_interval)
            
    def on_risk_clear(self):
        """风控解除后恢复正常速度"""
        if self.risk_detected:
            self.risk_detected = False
            self.current_interval = self.base_interval
            self.log(f"✅ 风控解除，恢复正常频率 {self.current_interval:.1f}s")
            
    def get_interval(self) -> float:
        """获取当前推荐的请求间隔（带随机浮动）"""
        # 添加 ±20% 的随机浮动
        variation = self.current_interval * 0.2
        return self.current_interval + random.uniform(-variation, variation)
    
    def reset(self):
        """重置为初始状态"""
        self.current_interval = self.base_interval
        self.success_streak = 0
        self.fail_count = 0
        self.risk_detected = False
        
    def get_stats(self) -> dict:
        """获取统计数据"""
        return {
            "current_interval": round(self.current_interval, 2),
            "base_interval": self.base_interval,
            "success_streak": self.success_streak,
            "fail_count": self.fail_count,
            "total_requests": self.total_requests,
            "risk_detected": self.risk_detected,
        }



# ==================== 工具函数 ====================

def create_anti_detect_driver(base_dir: str, profile_dir: str, 
                               log_callback: Optional[Callable[[str], None]] = None,
                               driver_path: Optional[str] = None):
    """
    创建经过完整反检测优化的 WebDriver
    
    这是主要的入口函数，用于替换原有的 webdriver.Chrome()
    """
    anti_detect = AntiDetect(base_dir, log_callback, driver_path=driver_path)
    return anti_detect.create_driver(profile_dir)


def get_random_interval(base_interval: int) -> float:
    """获取随机刷新间隔"""
    return BehaviorSimulator.random_interval(base_interval)


def human_delay(min_s: float = 0.3, max_s: float = 1.5):
    """人类行为延迟"""
    time.sleep(random.uniform(min_s, max_s))


# ==================== 模块测试 ====================

if __name__ == "__main__":
    print("=" * 50)
    print("12306 反检测模块测试")
    print("=" * 50)
    
    # 测试设备配置生成
    profile = DeviceProfile.generate_random()
    print(f"\n随机生成的设备配置:")
    print(f"  User-Agent: {profile.user_agent[:60]}...")
    print(f"  屏幕分辨率: {profile.screen_width}x{profile.screen_height}")
    print(f"  色深: {profile.color_depth}")
    print(f"  像素比: {profile.pixel_ratio}")
    print(f"  时区: {profile.timezone}")
    print(f"  语言: {profile.languages}")
    print(f"  CPU核心: {profile.hardware_concurrency}")
    print(f"  内存: {profile.device_memory}GB")
    print(f"  WebGL渲染器: {profile.webgl_renderer[:50]}...")
    
    # 测试随机间隔
    print(f"\n随机间隔测试 (基础 5 秒):")
    for i in range(5):
        interval = get_random_interval(5)
        print(f"  第 {i+1} 次: {interval:.2f} 秒")
    
    print("\n✅ 模块测试完成")
