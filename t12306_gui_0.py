"""
RailWatch 12306 legacy Tkinter GUI（合规：查询/监控提醒）- 风控优化增强版

⚠️ 免责声明 / DISCLAIMER：
1. 本程序仅供学习和个人使用，不得用于商业用途或非法抢票
2. 使用本程序造成的任何后果（包括但不限于账号封禁）由用户自行承担
3. 本程序不涉及破解、绕过验证码、伪造请求等非法行为
4. 请遵守 12306 用户协议和相关法律法规
5. 建议刷新间隔 ≥ 5 秒，避免对服务器造成压力

改进点：
1) 使用 Chrome user-data-dir 保存登录态（cookie/session）
2) 页面分析时自动填入 出发/到达/日期 并自动点击"查询"
3) [优化] 配置持久化，无需每次重新输入
4) [优化] 支持多车次、多席别监控
5) [优化] 改进 UI 和用户体验
6) [优化] 跨平台语音提示
7) [优化] 日志持久化
8) [风控优化] 设备指纹伪装（Canvas/WebGL/AudioContext）
9) [风控优化] 随机化 User-Agent 和刷新间隔
10) [风控优化] 隐藏 Selenium 自动化特征
11) [风控优化] RAIL_DEVICEID 保护
12) [风控优化] 人类行为模拟（随机延迟/鼠标轨迹）
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import time
import sys
import os
import random
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Callable

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.chrome.service import Service
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False
    webdriver = None
    By = None
    Service = None

# 导入核心模块
try:
    from gui_12306_0 import ConfigManager, QueryConfig
    CONFIG_AVAILABLE = True
except ImportError:
    CONFIG_AVAILABLE = False

# 导入反检测模块
try:
    from anti_detect import (
        AntiDetect, 
        BehaviorSimulator, 
        RailDeviceIdProtector,
        get_random_interval,
        human_delay
    )
    ANTI_DETECT_AVAILABLE = True
except ImportError:
    ANTI_DETECT_AVAILABLE = False

LOGIN_URL = "https://kyfw.12306.cn/otn/resources/login.html"
APP_DISPLAY_NAME = "RailWatch 12306"
APP_SLUG = "railwatch-12306"

# ==================== 路径处理 (支持 PyInstaller) ====================
def get_resource_path(relative_path):
    """获取资源文件路径（支持开发模式和打包模式）"""
    if hasattr(sys, '_MEIPASS'):
        # PyInstaller 打包后的临时解压目录
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

def get_data_path(filename=""):
    """获取数据文件路径（保存在用户本地数据目录，避免把登录态写入源码目录）"""
    if sys.platform == "win32":
        base_path = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
        base_path = os.path.join(base_path, APP_SLUG)
    elif sys.platform == "darwin":
        base_path = os.path.join(os.path.expanduser("~/Library/Application Support"), APP_SLUG)
    else:
        base_path = os.path.join(os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")), APP_SLUG)
    
    if filename:
        return os.path.join(base_path, filename)
    return base_path

# 基础目录（用于数据存储：配置、日志、浏览器配置）
DATA_DIR = get_data_path()
os.makedirs(DATA_DIR, exist_ok=True)

# 自定义驱动路径（优先用户数据目录覆盖，找不到则使用项目/打包资源）
CHROMEDRIVER_PATH = get_data_path('chromedriver.exe')
if not os.path.exists(CHROMEDRIVER_PATH):
    CHROMEDRIVER_PATH = get_resource_path('chromedriver.exe')

service = Service(executable_path=CHROMEDRIVER_PATH) if Service and os.path.exists(CHROMEDRIVER_PATH) else None

# 日志文件
LOG_FILE = os.path.join(DATA_DIR, "railwatch.log")


class NotificationManager:
    """跨平台通知管理器"""
    
    @staticmethod
    def speak(text: str, log_callback: Optional[Callable[[str], None]] = None):
        """语音播报（跨平台）"""
        def _speak():
            try:
                # Windows 优先使用 SAPI
                if sys.platform == "win32":
                    try:
                        import win32com.client
                        speaker = win32com.client.Dispatch("SAPI.SpVoice")
                        speaker.Speak(text)
                        return
                    except ImportError:
                        pass
                
                # 跨平台方案：pyttsx3
                try:
                    import pyttsx3
                    engine = pyttsx3.init()
                    engine.say(text)
                    engine.runAndWait()
                    return
                except ImportError:
                    pass
                
                # macOS 方案
                if sys.platform == "darwin":
                    os.system(f'say "{text}"')
                    return
                
                if log_callback:
                    log_callback("⚠️ 未安装语音库，请安装 pyttsx3: pip install pyttsx3")
                    
            except Exception as e:
                if log_callback:
                    log_callback(f"⚠️ 语音播报失败：{e}")
        
        threading.Thread(target=_speak, daemon=True).start()


class T12306GUI:
    """RailWatch 12306 legacy Tkinter GUI."""
    
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(f"{APP_DISPLAY_NAME} Legacy")
        self.root.geometry("1200x800")
        self.root.minsize(1100, 700)
        
        # 设置深色主题背景
        self.root.configure(bg="#1a1a2e")
        
        # 设置图标（如果存在）
        icon_path = os.path.join(DATA_DIR, "icon.ico")
        if os.path.exists(icon_path):
            try:
                self.root.iconbitmap(icon_path)
            except Exception:
                pass

        self.driver = None
        self.is_monitoring = False
        self.query_cfg = {}
        self.rate_limiter = None  # 智能频率调节器
        
        # 配置管理器
        if CONFIG_AVAILABLE:
            self.config_manager = ConfigManager(DATA_DIR)
        else:
            self.config_manager = None

        # 现代风格字体配置
        self.fonts = {
            "title": ("Microsoft YaHei UI", 20, "bold"),
            "subtitle": ("Microsoft YaHei UI", 11),
            "body": ("Microsoft YaHei UI", 10),
            "small": ("Microsoft YaHei UI", 9),
            "mono": ("Consolas", 10),
        }
        
        # 现代护眼浅色主题（柔和背景）
        self.theme = {
            "bg_dark": "#f5f7f9",        # 主背景（浅灰青，不再刺眼）
            "bg_card": "#ffffff",         # 卡片背景（保持洁净）
            "bg_input": "#ffffff",        # 输入框背景
            "accent": "#00a65a",          # 科技绿
            "accent2": "#3c8dbc",         # 辅助蓝
            "success": "#00a65a",
            "warning": "#f39c12",
            "text": "#2c3e50",            # 深灰蓝文字
            "text_dim": "#7f8c8d",        # 次要文字
            "border": "#dcdfe6",          # 柔和边框颜色
        }
        
        # 配置ttk样式
        self._setup_styles()
        
        self.create_interface()
        self._load_saved_config()

        if not SELENIUM_AVAILABLE:
            self.log("[警告] 未安装 selenium，请执行: pip install selenium")
    
    def _setup_styles(self):
        """配置现代浅色主题的ttk样式"""
        style = ttk.Style()
        
        # 尝试使用更现代的 Windows 本地主题，以获得原生 √ 效果和更好的交互
        available_themes = style.theme_names()
        if 'vista' in available_themes:
            style.theme_use('vista')
        elif 'xpnative' in available_themes:
            style.theme_use('xpnative')
        else:
            style.theme_use('winnative')
        
        # 主框架样式
        style.configure("TFrame", background=self.theme["bg_dark"])
        style.configure("Card.TFrame", background=self.theme["bg_card"])
        
        # 标签样式
        style.configure("TLabel", 
                       background=self.theme["bg_dark"], 
                       foreground=self.theme["text"],
                       font=self.fonts["body"])
        style.configure("Title.TLabel", 
                       font=self.fonts["title"],
                       foreground=self.theme["text"])
        style.configure("Subtitle.TLabel", 
                       font=self.fonts["subtitle"],
                       foreground=self.theme["text_dim"])
        style.configure("Card.TLabel",
                       background=self.theme["bg_card"],
                       foreground=self.theme["text"])
        style.configure("Dim.TLabel",
                       foreground=self.theme["text_dim"],
                       font=self.fonts["small"])
        
        # LabelFrame样式
        style.configure("TLabelframe", 
                       background=self.theme["bg_card"],
                       foreground=self.theme["text"])
        style.configure("TLabelframe.Label", 
                       background=self.theme["bg_card"],
                       foreground=self.theme["accent"],
                       font=self.fonts["subtitle"])
        
        # 按钮样式优化：增强对比度
        style.configure("TButton",
                       foreground=self.theme["text"],
                       padding=(15, 8),
                       font=self.fonts["body"])
        
        # 针对本地主题，只在必要时映射前景色，避免覆盖系统悬停效果
        style.map("TButton",
                 foreground=[("active", "#000000"), ("pressed", self.theme["accent"])])
        
        # 强调按钮
        style.configure("Accent.TButton",
                       foreground=self.theme["accent"],
                       padding=(20, 10),
                       font=self.fonts["subtitle"])
        style.map("Accent.TButton",
                 foreground=[("active", self.theme["success"]), ("pressed", "#000000")])
        
        # 输入框样式
        style.configure("TEntry",
                       fieldbackground=self.theme["bg_input"],
                       foreground=self.theme["text"],
                       insertcolor=self.theme["accent"],
                       padding=8)
        
        # Combobox样式
        style.configure("TCombobox",
                       fieldbackground=self.theme["bg_input"],
                       background=self.theme["bg_input"],
                       foreground=self.theme["text"],
                       arrowcolor=self.theme["text"],
                       padding=5)
        style.map("TCombobox",
                 fieldbackground=[("readonly", self.theme["bg_input"])],
                 background=[("readonly", self.theme["bg_input"])])
        
        # Checkbutton样式（winnative主题已有√样式）
        style.configure("TCheckbutton",
                       background=self.theme["bg_card"],
                       foreground=self.theme["text"],
                       font=self.fonts["body"])
        
        # Spinbox样式
        style.configure("TSpinbox",
                       fieldbackground=self.theme["bg_input"],
                       background=self.theme["bg_input"],
                       foreground=self.theme["text"],
                       arrowcolor=self.theme["text"],
                       padding=5)

    def run(self):
        """启动应用"""
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()
    
    def _on_close(self):
        """关闭窗口时保存配置"""
        self._save_config()
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
        self.root.destroy()

    # ============== UI 创建 ==============
    def create_interface(self):
        """创建现代风格界面"""
        # 主容器
        main = ttk.Frame(self.root, padding="15")
        main.grid(row=0, column=0, sticky="nsew")

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(2, weight=1)

        # 标题区域 - 简洁现代风格
        title_frame = ttk.Frame(main)
        title_frame.grid(row=0, column=0, columnspan=2, pady=(0, 20))
        
        ttk.Label(
            title_frame, 
            text=APP_DISPLAY_NAME, 
            style="Title.TLabel"
        ).pack()
        ttk.Label(
            title_frame,
            text="v3.0 | 支持多车次监控 · 候补订单 · 智能频率调节",
            style="Subtitle.TLabel"
        ).pack()

        # 步骤指示器 - 极简风格
        self._create_steps(main, row=1)
        
        # 主内容区
        self._create_main(main, row=2)
        
        # 控制按钮
        self._create_controls(main, row=3)

        # 初始日志 - 减少emoji使用
        self.log(f"{APP_DISPLAY_NAME} legacy UI started")
        self.log("流程: 环境检测 → 登录 → 配置 → 监控")
        self.log("提示: 验证码/支付需手动完成")
        self.log("—" * 40)

    def _create_steps(self, parent, row):
        """创建步骤指示器 - 极简风格"""
        frame = ttk.LabelFrame(parent, text="操作流程", padding="8")
        frame.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(0, 12))

        self.steps = ["1. 环境检测", "2. 打开登录页", "3. 页面分析", "4. 监控余票"]
        self.step_labels = []
        
        for i, step in enumerate(self.steps):
            label = ttk.Label(frame, text=step, foreground="gray")
            label.grid(row=0, column=i * 2, padx=10)
            self.step_labels.append(label)
            if i < len(self.steps) - 1:
                ttk.Label(frame, text="→", foreground="gray").grid(row=0, column=i * 2 + 1, padx=5)

    def _create_main(self, parent, row):
        """创建主内容区 - 现代风格"""
        # 左侧容器（带滚动条）
        left_container = ttk.LabelFrame(parent, padding="3")
        left_container.grid(row=row, column=0, sticky="nsew", padx=(0, 8))
        left_container.rowconfigure(0, weight=1)
        left_container.columnconfigure(0, weight=1)

        canvas = tk.Canvas(left_container, highlightthickness=0, bg=self.theme["bg_card"])
        scrollbar = ttk.Scrollbar(left_container, orient="vertical", command=canvas.yview)
        # 实际内容存放的 Frame
        left = ttk.Frame(canvas, padding="8", style="Card.TFrame")
        
        # 绑定滚动和自适应宽度
        canvas_window = canvas.create_window((0, 0), window=left, anchor="nw")
        
        def _configure_canvas(event):
            # 更新滚动区域
            canvas.configure(scrollregion=canvas.bbox("all"))
            # 使内部 frame 宽度跟随 canvas 宽度
            canvas.itemconfig(canvas_window, width=event.width)
            
        canvas.bind("<Configure>", _configure_canvas)
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # 鼠标滚轮支持
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        # --- 以下内容全部放在 left frame 中 ---

        # 环境检测
        env_frame = ttk.LabelFrame(left, text="环境检测", padding="8")
        env_frame.pack(fill="x", pady=(0, 8))

        self.env_status = ttk.Label(env_frame, text="点击检测环境", style="Card.TLabel")
        self.env_status.pack()
        self.btn_env = ttk.Button(env_frame, text="检测环境", command=self.check_environment)
        self.btn_env.pack(pady=5)

        # 登录
        login_frame = ttk.LabelFrame(left, text="登录管理", padding="8")
        login_frame.pack(fill="x", pady=(0, 8))

        self.btn_login = ttk.Button(
            login_frame, 
            text="打开 12306 登录页", 
            command=self.open_login, 
            state="disabled"
        )
        self.btn_login.pack(fill="x", pady=5)
        
        ttk.Label(
            login_frame,
            text="保存Cookie和设备指纹，短期内可免登录",
            style="Dim.TLabel"
        ).pack()

        # 查询配置
        cfg_frame = ttk.LabelFrame(left, text="行程配置", padding="10")
        cfg_frame.pack(fill="x", pady=(0, 8))

        # 出发站/到达站 (使用 Grid 布局确保宽度绝对一致)
        row1 = ttk.Frame(cfg_frame)
        row1.pack(fill="x", pady=3)
        row1.columnconfigure(1, weight=1)
        row1.columnconfigure(3, weight=1)
        
        ttk.Label(row1, text="出发站", width=8).grid(row=0, column=0, sticky="w")
        self.from_var = tk.StringVar(value="北京")
        from_entry = ttk.Entry(row1, textvariable=self.from_var)
        from_entry.grid(row=0, column=1, padx=5, sticky="ew")
        
        ttk.Label(row1, text="到达站", width=8).grid(row=0, column=2, sticky="w", padx=(10, 0))
        self.to_var = tk.StringVar(value="成都")
        to_entry = ttk.Entry(row1, textvariable=self.to_var)
        to_entry.grid(row=0, column=3, padx=5, sticky="ew")

        # 日期
        row2 = ttk.Frame(cfg_frame)
        row2.pack(fill="x", pady=3)
        ttk.Label(row2, text="出发日期", width=8).pack(side="left")
        self.date_var = tk.StringVar(value=time.strftime("%Y-%m-%d"))
        ttk.Entry(row2, textvariable=self.date_var, width=14).pack(side="left", padx=5)
        ttk.Label(row2, text="格式: YYYY-MM-DD", style="Dim.TLabel").pack(side="left")

        # 车次
        row3 = ttk.Frame(cfg_frame)
        row3.pack(fill="x", pady=3)
        ttk.Label(row3, text="目标车次", width=8).pack(side="left")
        self.train_var = tk.StringVar(value="D3382")
        ttk.Entry(row3, textvariable=self.train_var, width=20).pack(side="left", padx=5, fill="x", expand=True)
        
        row3_hint = ttk.Frame(cfg_frame)
        row3_hint.pack(fill="x")
        ttk.Label(
            row3_hint, 
            text="多车次用逗号分隔，如: G1587,D3382", 
            style="Dim.TLabel"
        ).pack(side="left")

        # 席别
        row4 = ttk.Frame(cfg_frame)
        row4.pack(fill="x", pady=3)
        ttk.Label(row4, text="目标席别", width=8).pack(side="left")
        self.seat_var = tk.StringVar(value="二等座")
        seat_combo = ttk.Combobox(
            row4, 
            textvariable=self.seat_var, 
            width=18,
            values=["二等座", "一等座", "商务座", "硬座", "软座", "硬卧", "软卧", "无座"]
        )
        seat_combo.pack(side="left", padx=5, fill="x", expand=True)
        
        row4_hint = ttk.Frame(cfg_frame)
        row4_hint.pack(fill="x")
        ttk.Label(
            row4_hint, 
            text="多席别用逗号分隔，如: 二等座,一等座", 
            style="Dim.TLabel"
        ).pack(side="left")

        # 刷新间隔
        row5 = ttk.Frame(cfg_frame)
        row5.pack(fill="x", pady=3)
        ttk.Label(row5, text="刷新间隔", width=8).pack(side="left")
        self.interval_var = tk.IntVar(value=5)  # 默认5秒，更合规
        ttk.Spinbox(row5, from_=3, to=30, textvariable=self.interval_var, width=6).pack(side="left", padx=5)
        ttk.Label(row5, text="秒", style="Card.TLabel").pack(side="left")
        
        # 智能频率调节
        self.smart_rate_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            row5, 
            text="智能调节",
            variable=self.smart_rate_var
        ).pack(side="left", padx=(15, 0))

        # 自动提交选项
        row6 = ttk.Frame(cfg_frame)
        row6.pack(fill="x", pady=3)
        self.auto_submit_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            row6, 
            text="命中后自动提交订单",
            variable=self.auto_submit_var
        ).pack(side="left")
        
        # 乘车人数量
        ttk.Label(row6, text="  乘车人数:", style="Card.TLabel").pack(side="left", padx=(10, 2))
        self.passenger_count_var = tk.IntVar(value=1)
        passenger_spin = ttk.Spinbox(row6, from_=1, to=5, textvariable=self.passenger_count_var, width=3)
        passenger_spin.pack(side="left")
        ttk.Label(row6, text="人", style="Card.TLabel").pack(side="left")
        
        # 乘车人配置
        row_psg = ttk.Frame(cfg_frame)
        row_psg.pack(fill="x", pady=3)
        ttk.Label(row_psg, text="乘车人", width=6, style="Card.TLabel").pack(side="left")
        self.passengers_var = tk.StringVar(value="")
        ttk.Entry(row_psg, textvariable=self.passengers_var).pack(side="left", padx=5, fill="x", expand=True)
        
        row_psg_hint = ttk.Frame(cfg_frame)
        row_psg_hint.pack(fill="x")
        ttk.Label(
            row_psg_hint,
            text="自动匹配12306账户中的乘车人，多个姓名用逗号分隔",
            style="Dim.TLabel"
        ).pack(side="left")

        # 座位偏好选项
        row6_seat = ttk.Frame(cfg_frame)
        row6_seat.pack(fill="x", pady=3)
        ttk.Label(row6_seat, text="座位偏好", width=8, style="Card.TLabel").pack(side="left")
        self.seat_prefer_var = tk.StringVar(value="无偏好")
        seat_prefer_combo = ttk.Combobox(
            row6_seat,
            textvariable=self.seat_prefer_var,
            width=10,
            values=["无偏好", "靠窗优先", "靠过道优先"],
            state="readonly"
        )
        seat_prefer_combo.pack(side="left", padx=5)
        
        # 候补订单选项
        row_alt = ttk.Frame(cfg_frame)
        row_alt.pack(fill="x", pady=3)
        self.auto_alternate_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            row_alt, 
            text="无票时自动提交候补",
            variable=self.auto_alternate_var
        ).pack(side="left")
        
        ttk.Label(row_alt, text="  截止时间:", style="Card.TLabel").pack(side="left", padx=(10, 2))
        self.alternate_deadline_var = tk.StringVar(value="18:00")
        ttk.Entry(row_alt, textvariable=self.alternate_deadline_var, width=8).pack(side="left")
        
        row_alt_hint = ttk.Frame(cfg_frame)
        row_alt_hint.pack(fill="x")
        ttk.Label(
            row_alt_hint,
            text="候补截止时间格式: HH:MM，过期自动取消候补",
            style="Dim.TLabel"
        ).pack(side="left")

        # 定时开抢配置
        timer_frame = ttk.LabelFrame(left, text="定时开抢", padding="8")
        timer_frame.pack(fill="x", pady=(0, 8))
        
        row7 = ttk.Frame(timer_frame)
        row7.pack(fill="x", pady=2)
        
        self.timer_enabled_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            row7, 
            text="启用定时",
            variable=self.timer_enabled_var,
            command=self._toggle_timer_inputs
        ).pack(side="left")
        
        ttk.Label(row7, text="时间:").pack(side="left", padx=(10, 5))
        
        # 时间输入
        self.hour_var = tk.StringVar(value="08")
        self.minute_var = tk.StringVar(value="30")
        self.second_var = tk.StringVar(value="00")
        
        self.hour_spin = ttk.Spinbox(row7, from_=0, to=23, textvariable=self.hour_var, width=3, format="%02.0f", state="disabled")
        self.hour_spin.pack(side="left")
        ttk.Label(row7, text=":").pack(side="left")
        self.minute_spin = ttk.Spinbox(row7, from_=0, to=59, textvariable=self.minute_var, width=3, format="%02.0f", state="disabled")
        self.minute_spin.pack(side="left")
        ttk.Label(row7, text=":").pack(side="left")
        self.second_spin = ttk.Spinbox(row7, from_=0, to=59, textvariable=self.second_var, width=3, format="%02.0f", state="disabled")
        self.second_spin.pack(side="left")
        
        # 倒计时显示（放在同一行）
        self.countdown_label = ttk.Label(row7, text="", foreground="blue", font=("微软雅黑", 9, "bold"))
        self.countdown_label.pack(side="left", padx=(15, 0))

        # 定时增强配置行
        row8 = ttk.Frame(timer_frame)
        row8.pack(fill="x", pady=2)
        
        ttk.Label(row8, text="提前量:", style="Card.TLabel").pack(side="left")
        self.prepare_time_var = tk.IntVar(value=2)
        self.prepare_spin = ttk.Spinbox(row8, from_=0, to=10, textvariable=self.prepare_time_var, width=3, state="disabled")
        self.prepare_spin.pack(side="left", padx=5)
        ttk.Label(row8, text="秒", style="Card.TLabel").pack(side="left")

        row9 = ttk.Frame(timer_frame)
        row9.pack(fill="x", pady=2)
        self.keep_alive_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            row9, 
            text="等待期间发送心跳保活",
            variable=self.keep_alive_var
        ).pack(side="left")

        # 查询/分析按钮（放在 left 面板最底部）
        self.btn_analyze = ttk.Button(
            left, 
            text="打开查询页并分析", 
            command=self.analyze, 
            state="disabled"
        )
        self.btn_analyze.pack(fill="x", pady=(8, 0))

        # 右侧日志面板
        right = ttk.LabelFrame(parent, text="运行日志", padding="10")
        right.grid(row=row, column=1, sticky="nsew", padx=(8, 0))
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)

        self.log_text = scrolledtext.ScrolledText(
            right, 
            height=20, 
            width=55, 
            font=self.fonts["mono"],
            bg="#1e1e1e",                    # 恢复深色背景
            fg="#d4d4d4",                    # 浅灰色文字
            insertbackground="white",         # 白色光标
            selectbackground=self.theme["accent2"],
            relief="solid",
            borderwidth=1,
            padx=10,
            pady=10
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        
        # 日志控制按钮
        log_btns = ttk.Frame(right)
        log_btns.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(log_btns, text="清空", command=self._clear_log, width=8).pack(side="left")
        ttk.Button(log_btns, text="保存", command=self._save_log, width=8).pack(side="left", padx=5)

    def _create_controls(self, parent, row):
        """创建控制按钮 - 现代风格"""
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=0, columnspan=2, pady=15)

        self.btn_start = ttk.Button(
            frame, 
            text="开始监控", 
            command=self.start_monitor, 
            state="disabled",
            style="Accent.TButton"
        )
        self.btn_start.pack(side="left", padx=8)

        self.btn_stop = ttk.Button(
            frame, 
            text="停止", 
            command=self.stop_monitor, 
            state="disabled"
        )
        self.btn_stop.pack(side="left", padx=8)
        
        # 状态指示器
        self.status_label = ttk.Label(frame, text="● 未运行", foreground=self.theme["text_dim"])
        self.status_label.pack(side="left", padx=25)

        ttk.Button(frame, text="退出", command=self._on_close).pack(side="right", padx=8)
        ttk.Button(frame, text="保存配置", command=self._save_config).pack(side="right", padx=8)

    # ============== 辅助方法 ==============
    def update_step(self, idx: int, status: str = "active"):
        """更新步骤状态"""
        colors = {
            "inactive": "gray", 
            "active": "blue", 
            "completed": "green", 
            "error": "red"
        }
        if 0 <= idx < len(self.step_labels):
            self.step_labels[idx].config(foreground=colors.get(status, "gray"))
            if status == "completed":
                self.step_labels[idx].config(text="✓ " + self.steps[idx])

    def log(self, msg: str):
        """记录日志"""
        if threading.current_thread() is not threading.main_thread():
            try:
                self.root.after(0, lambda m=msg: self.log(m))
            except Exception:
                pass
            return
        
        timestamp = time.strftime("%H:%M:%S")
        log_line = f"[{timestamp}] {msg}\n"
        self.log_text.insert(tk.END, log_line)
        self.log_text.see(tk.END)
        self.root.update_idletasks()
        
        # 同时写入文件
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now().isoformat()}] {msg}\n")
        except Exception:
            pass
    
    def _clear_log(self):
        """清空日志"""
        self.log_text.delete(1.0, tk.END)
    
    def _save_log(self):
        """保存日志到文件"""
        try:
            log_content = self.log_text.get(1.0, tk.END)
            filename = f"log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            filepath = os.path.join(DATA_DIR, filename)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(log_content)
            self.log(f"日志已保存到: {filename}")
        except Exception as e:
            self.log(f"[错误] 保存日志失败: {e}")

    def _load_saved_config(self):
        """加载保存的配置"""
        if not self.config_manager:
            return
        
        config = self.config_manager.load()
        if config:
            self.from_var.set(config.from_station_cn or "北京")
            self.to_var.set(config.to_station_cn or "成都")
            if config.date:
                self.date_var.set(config.date)
            if config.train_code:
                self.train_var.set(config.train_code)
            if config.seat_keyword:
                self.seat_var.set(config.seat_keyword)
            self.interval_var.set(config.interval or 3)
            self.auto_submit_var.set(config.auto_submit)
            if hasattr(config, 'seat_prefer') and config.seat_prefer:
                self.seat_prefer_var.set(config.seat_prefer)
            
            # 定时增强项
            if hasattr(config, 'prepare_time'):
                self.prepare_time_var.set(config.prepare_time)
            if hasattr(config, 'keep_alive'):
                self.keep_alive_var.set(config.keep_alive)
            if hasattr(config, 'passengers'):
                self.passengers_var.set(config.passengers)
            if hasattr(config, 'passenger_count'):
                self.passenger_count_var.set(config.passenger_count)
            
            # 候补订单配置
            if hasattr(config, 'auto_alternate'):
                self.auto_alternate_var.set(config.auto_alternate)
            if hasattr(config, 'alternate_deadline') and config.alternate_deadline:
                self.alternate_deadline_var.set(config.alternate_deadline)
                
            self.log("已加载上次保存的配置")
    
    def _save_config(self):
        """保存当前配置"""
        if not self.config_manager:
            return
        
        try:
            config = QueryConfig(
                from_station_cn=self.from_var.get().strip(),
                to_station_cn=self.to_var.get().strip(),
                date=self.date_var.get().strip(),
                train_code=self.train_var.get().strip(),
                seat_keyword=self.seat_var.get().strip(),
                interval=self.interval_var.get(),
                auto_submit=self.auto_submit_var.get(),
                seat_prefer=self.seat_prefer_var.get(),
                passenger_count=self.passenger_count_var.get(),
                prepare_time=self.prepare_time_var.get(),
                keep_alive=self.keep_alive_var.get(),
                passengers=self.passengers_var.get().strip(),
                auto_alternate=self.auto_alternate_var.get(),
                alternate_deadline=self.alternate_deadline_var.get().strip(),
            )
            if self.config_manager.save(config):
                self.log("配置已保存")
            else:
                self.log("[警告] 配置保存失败")
        except Exception as e:
            self.log(f"[警告] 保存配置时出错: {e}")
    
    def _toggle_timer_inputs(self):
        """切换定时输入框状态"""
        if self.timer_enabled_var.get():
            self.hour_spin.config(state="normal")
            self.minute_spin.config(state="normal")
            self.second_spin.config(state="normal")
            self.prepare_spin.config(state="normal")
        else:
            self.hour_spin.config(state="disabled")
            self.minute_spin.config(state="disabled")
            self.second_spin.config(state="disabled")
            self.prepare_spin.config(state="disabled")
            self.countdown_label.config(text="")
    
    def _get_target_time(self) -> datetime:
        """获取目标开抢时间"""
        now = datetime.now()
        hour = int(self.hour_var.get())
        minute = int(self.minute_var.get())
        second = int(self.second_var.get())
        
        target = now.replace(hour=hour, minute=minute, second=second, microsecond=0)
        
        # 如果目标时间已过，设置为明天
        if target <= now:
            target = target + timedelta(days=1)
        
        return target
    
    def _update_countdown(self):
        """更新倒计时显示"""
        if not self.timer_enabled_var.get() or not self.is_monitoring:
            self.countdown_label.config(text="")
            return
        
        target = self._get_target_time()
        now = datetime.now()
        diff = target - now
        
        if diff.total_seconds() <= 0:
            self.countdown_label.config(text="⏰ 开抢时间到！", foreground="red")
            return
        
        hours, remainder = divmod(int(diff.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        
        countdown_text = f"⏳ 距离开抢: {hours:02d}:{minutes:02d}:{seconds:02d}"
        self.countdown_label.config(text=countdown_text, foreground="blue")
        
        # 每秒更新
        if self.is_monitoring:
            self.root.after(1000, self._update_countdown)
    
    def _check_stealth(self) -> bool:
        """检查浏览器隐身效果"""
        try:
            driver = self._ensure_driver()
            # 1. 检查 webdriver 特征
            is_detected = driver.execute_script("return navigator.webdriver")
            if is_detected:
                self.log("⚠️ 警告：检测到自动化特征 (navigator.webdriver=true)")
                return False
                
            # 2. 检查 chrome 属性
            chrome_props = driver.execute_script("return window.chrome !== undefined")
            if not chrome_props:
                self.log("⚠️ 警告：检测到 window.chrome 缺失")
                # return False # 某些浏览器本身就没有，暂不作为强制失败项
                
            # 3. 检查 RAIL_DEVICEID
            cookies = driver.get_cookies()
            has_device_id = any(c['name'] == 'RAIL_DEVICEID' for c in cookies)
            if not has_device_id:
                self.log("ℹ️ RAIL_DEVICEID 尚未生成，将在查询后检查")
                
            return True
        except Exception as e:
            self.log(f"⚠️ 隐身自检异常: {e}")
            return False

    def _wait_for_target_time(self) -> bool:
        """等待到达目标时间，返回是否应该继续"""
        if not self.timer_enabled_var.get():
            return True
        
        target = self._get_target_time()
        now = datetime.now()
        
        if now >= target:
            return True
        
        diff = (target - now).total_seconds()
        prepare_offset = self.prepare_time_var.get()
        actual_wait = diff - prepare_offset
        
        self.log(f"⏰ 定时开抢已启用，目标时间: {target.strftime('%H:%M:%S')}，提前量: {prepare_offset}秒")
        if actual_wait > 0:
            self.log(f"⏳ 等待 {int(actual_wait)} 秒后开始准备...")
        
        last_keep_alive = time.time()
        
        # 分段等待，支持中途取消
        while (target - datetime.now()).total_seconds() > prepare_offset:
            if not self.is_monitoring:
                return False
            
            # 每次最多等待1秒
            time.sleep(1)
            
            # --- 会话保活逻辑 ---
            # 如果开启了保活，且距离上次超过 5 分钟 (300秒)
            if self.keep_alive_var.get() and (time.time() - last_keep_alive) > 300:
                self.root.after(0, lambda: self.log("💓 发送保活心跳，维持登录状态..."))
                try:
                    # 在浏览器中刷新一次查询或执行无害操作
                    self._ensure_driver().execute_script("document.getElementById('query_ticket').click();")
                    last_keep_alive = time.time()
                except Exception as e:
                    self.log(f"⚠️ 保活操作失败: {e}")
            
            # 重新计算剩余时间
            remaining = (target - datetime.now()).total_seconds()
            
            # 最后10秒预热提示
            if prepare_offset < remaining <= prepare_offset + 10:
                current_ready_wait = int(remaining - prepare_offset)
                if current_ready_wait > 0:
                    self.root.after(0, lambda d=current_ready_wait: self.log(f"🔥 {d} 秒后进入抢票状态..."))
        
        if prepare_offset > 0:
            self.log(f"🚀 已到达提前准备时间（-{prepare_offset}s），开始抢票操作！")
        else:
            self.log("🚀 开抢时间到！开始抢票！")
        return True

    # ============== 核心功能 ==============
    def check_environment(self):
        """检测环境"""
        self.update_step(0, "active")
        self.log("🔍 开始检测环境...")

        if not SELENIUM_AVAILABLE:
            self.env_status.config(text="Selenium 未安装", foreground="red")
            self.update_step(0, "error")
            messagebox.showerror("错误", "未安装 selenium：请执行 pip install selenium")
            return

        self.log(f"✅ Python: {sys.version.split()[0]}")
        self.log(f"✅ 操作系统: {sys.platform}")
        
        # 检查 chromedriver
        if not os.path.exists(CHROMEDRIVER_PATH):
            self.log(f"⚠️ 未找到 chromedriver: {CHROMEDRIVER_PATH}")
            self.log("💡 将尝试使用系统 PATH 中的 chromedriver")
        
        try:
            _ = self._ensure_driver(test_only=True)
            self.driver.quit()
            self.driver = None
            self.log("✅ ChromeDriver 可用（profile 模式）")
        except Exception as e:
            self.log(f"❌ ChromeDriver 检测失败: {e}")
            self.env_status.config(text="ChromeDriver 异常", foreground="red")
            self.update_step(0, "error")
            messagebox.showerror(
                "错误", 
                f"ChromeDriver 不可用：\n{e}\n\n"
                "建议：\n1. 安装 Chrome 浏览器\n2. 下载匹配版本的 chromedriver\n3. 放到程序目录或添加到 PATH"
            )
            return

        self.env_status.config(text="✅ 环境检测完成", foreground="green")
        self.update_step(0, "completed")

        self.btn_login.config(state="normal")
        self.btn_analyze.config(state="normal")

    def _ensure_driver(self, test_only: bool = False):
        """确保 WebDriver 可用（风控优化增强版）"""
        if self.driver and not test_only:
            return self.driver

        profile_dir = os.path.join(DATA_DIR, "chrome_profile_12306")
        os.makedirs(profile_dir, exist_ok=True)
        
        # 优先使用反检测模块
        if ANTI_DETECT_AVAILABLE:
            self.log("🛡️ 启用风控优化模式...")
            try:
                anti_detect = AntiDetect(DATA_DIR, log_callback=self.log, driver_path=CHROMEDRIVER_PATH)
                self.driver = anti_detect.create_driver(profile_dir)
                
                # 初始化行为模拟器和设备ID保护器
                self.behavior_simulator = BehaviorSimulator(self.driver, self.log)
                self.device_id_protector = RailDeviceIdProtector(self.driver, self.log)
                
                self.log("✅ 风控优化模式已启用")
                return self.driver
            except Exception as e:
                self.log(f"⚠️ 风控优化模式启动失败，回退到标准模式: {e}")
        
        # 回退到标准模式（保留原有逻辑作为兜底）
        self.log("ℹ️ 使用标准 Selenium 模式")
        options = webdriver.ChromeOptions()
        
        options.add_argument(f"--user-data-dir={profile_dir}")
        options.add_argument("--profile-directory=Default")

        # 基础反检测
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--start-maximized")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        
        try:
            if os.path.exists(CHROMEDRIVER_PATH):
                self.driver = webdriver.Chrome(options=options, service=service)
            else:
                self.driver = webdriver.Chrome(options=options)
        except Exception as e:
            self.driver = webdriver.Chrome(options=options)
        
        # 标准模式下也尝试初始化辅助组件
        if ANTI_DETECT_AVAILABLE:
            self.behavior_simulator = BehaviorSimulator(self.driver, self.log)
            self.device_id_protector = RailDeviceIdProtector(self.driver, self.log)
        else:
            self.behavior_simulator = None
            self.device_id_protector = None
        
        return self.driver

    def open_login(self):
        """打开登录页"""
        self.update_step(1, "active")
        self.log("🔐 打开 12306 登录页...")
        try:
            drv = self._ensure_driver()
            drv.get(LOGIN_URL)
            self.log("🌐 已打开登录页：请手动完成登录与验证码（通常只需一次）")
            self.update_step(1, "completed")
        except Exception as e:
            self.log(f"❌ 打开登录页失败: {e}")
            self.update_step(1, "error")

    def _collect_cfg(self) -> dict:
        """收集配置"""
        cfg = {
            "from_station_cn": self.from_var.get().strip(),
            "to_station_cn": self.to_var.get().strip(),
            "date": self.date_var.get().strip(),
            "train_code": self.train_var.get().strip(),
            "seat_keyword": self.seat_var.get().strip(),
            "interval": int(self.interval_var.get()),
            "auto_submit": self.auto_submit_var.get(),
            "passenger_count": int(self.passenger_count_var.get()),  # 乘车人数量
            "seat_prefer": self.seat_prefer_var.get(),  # 座位偏好：无偏好/靠窗优先/靠过道优先
            "prepare_time": self.prepare_time_var.get(),
            "keep_alive": self.keep_alive_var.get(),
            "passengers": self.passengers_var.get().strip(),
            "auto_alternate": self.auto_alternate_var.get(),
            "alternate_deadline": self.alternate_deadline_var.get().strip(),
            "smart_rate": self.smart_rate_var.get(),
        }
        
        if not cfg["from_station_cn"]:
            raise ValueError("出发站不能为空")
        if not cfg["to_station_cn"]:
            raise ValueError("到达站不能为空")
        if not cfg["date"]:
            raise ValueError("日期不能为空")
        
        # 验证日期格式
        try:
            datetime.strptime(cfg["date"], "%Y-%m-%d")
        except ValueError:
            raise ValueError("日期格式错误，请使用 YYYY-MM-DD 格式")
        
        if cfg["auto_alternate"] and cfg["alternate_deadline"]:
            try:
                datetime.strptime(cfg["alternate_deadline"], "%H:%M")
            except ValueError:
                raise ValueError("候补截止时间格式错误，请使用 HH:MM 格式")
        
        return cfg

    def analyze(self):
        """分析页面"""
        try:
            self.query_cfg = self._collect_cfg()
        except ValueError as e:
            messagebox.showwarning("配置错误", str(e))
            return

        self.update_step(2, "active")
        self.log("🔍 启动查询页分析（将自动填参并点击查询）...")
        threading.Thread(target=self._analyze_worker, daemon=True).start()

    def _analyze_worker(self):
        """分析工作线程"""
        try:
            from gui_12306_0 import PageAnalyzer

            drv = self._ensure_driver()
            analyzer = PageAnalyzer(
                drv, 
                log_callback=lambda m: self.root.after(0, lambda: self.log(m)),
                base_dir=DATA_DIR
            )

            rows = analyzer.open_fill_query_and_analyze(self.query_cfg)
            if not rows:
                self.root.after(0, lambda: self.update_step(2, "error"))
                return
            
            if getattr(self, "device_id_protector", None):
                self.device_id_protector.save_device_id()

            self.root.after(0, lambda: self.update_step(2, "completed"))
            self.root.after(0, lambda: self.btn_start.config(state="normal"))
            self.log("✅ 分析完成：你可以开始监控余票了")

        except Exception as e:
            msg = str(e)
            self.root.after(0, lambda m=msg: self.log(f"❌ 分析失败: {m}"))
            self.root.after(0, lambda: self.update_step(2, "error"))

    def start_monitor(self):
        """开始监控"""
        if not self.query_cfg:
            messagebox.showwarning("提示", "请先「打开查询页并自动填参&分析」")
            return

        self.is_monitoring = True
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        
        # 根据是否启用定时显示不同状态
        if self.timer_enabled_var.get():
            target_time = self._get_target_time()
            self.status_label.config(text=f"⏰ 等待 {target_time.strftime('%H:%M:%S')} 开抢", foreground="orange")
            self.log(f"⏰ 定时开抢模式，将在 {target_time.strftime('%H:%M:%S')} 开始抢票")
            # 启动倒计时更新
            self._update_countdown()
        else:
            self.status_label.config(text="🟢 监控中...", foreground="green")
            self.log("📡 开始监控余票...")
        
        self.update_step(3, "active")
        
        # 强制自检
        self.log("🛡️ 正在进行防封自检...")
        if not self._check_stealth():
            self.log("❌ 防封自检未通过：您的环境存在自动化印记，容易被封。建议关闭所有 Chrome 窗口后重试。")
        else:
            self.log("✅ 防封自检通过：当前环境模拟程度较高。")

        # 记录监控开始状态，用于行为模拟
        self.last_activity_time = time.time()
        
        threading.Thread(target=self._monitor_worker, daemon=True).start()

    def _monitor_worker(self):
        """监控工作线程"""
        try:
            # 如果启用了定时开抢，等待到目标时间
            if self.timer_enabled_var.get():
                self.root.after(0, lambda: self.status_label.config(text="⏰ 等待开抢中...", foreground="orange"))
                
                if not self._wait_for_target_time():
                    # 被用户取消
                    self.root.after(0, lambda: self.log("⏹ 定时任务已取消"))
                    return
                
                # 开抢时间到，更新状态
                self.root.after(0, lambda: self.status_label.config(text="🚀 抢票中...", foreground="red"))
                
                # 开始抢票前的小随机延迟，避免整点那一刻过于机械
                time.sleep(random.uniform(0.1, 0.4))
            
            from gui_12306_0 import TicketMonitor

            drv = self._ensure_driver()
            if getattr(self, "device_id_protector", None):
                if not self.device_id_protector.check_and_restore():
                    self.device_id_protector.save_device_id()
            monitor = TicketMonitor(
                drv,
                self.query_cfg,
                log_callback=lambda m: self.root.after(0, lambda: self.log(m)),
                stop_check=lambda: not self.is_monitoring,
                notify_callback=lambda title, text: self.root.after(
                    0, 
                    lambda: self._on_ticket_found(title, text)
                ),
            )
            monitor.run()

            self.root.after(0, lambda: self.update_step(3, "completed"))
            self.root.after(0, lambda: self.log("✅ 监控结束"))

        except Exception as e:
            msg = str(e)
            self.root.after(0, lambda m=msg: self.log(f"❌ 监控异常: {m}"))
            self.root.after(0, lambda: self.update_step(3, "error"))
        finally:
            self.is_monitoring = False
            self.root.after(0, lambda: self.btn_start.config(state="normal"))
            self.root.after(0, lambda: self.btn_stop.config(state="disabled"))
            self.root.after(0, lambda: self.status_label.config(text="⚪ 已停止", foreground="gray"))
            self.root.after(0, lambda: self.countdown_label.config(text=""))
    
    def _on_ticket_found(self, title: str, text: str):
        """发现票时的处理"""
        # 语音提醒
        NotificationManager.speak("老大，发现目标车票了，请立即下单支付！", self.log)
        
        # 弹窗提醒
        messagebox.showinfo(title, text)
        
        # 尝试将窗口置顶
        try:
            self.root.lift()
            self.root.focus_force()
        except Exception:
            pass

    def stop_monitor(self):
        """停止监控"""
        self.is_monitoring = False
        self.log("⏹ 正在停止监控...")
        self.btn_stop.config(state="disabled")
        self.btn_start.config(state="normal")
        self.status_label.config(text="⚪ 已停止", foreground="gray")


class PasswordDialog:
    """启动密码验证对话框"""
    def __init__(self, password_hash: str):
        self.password_hash = password_hash
        self.success = False
        
        self.root = tk.Tk()
        self.root.title("安全验证")
        self.root.geometry("300x150")
        self.root.resizable(False, False)
        
        # 居中显示
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = (screen_width - 300) // 2
        y = (screen_height - 150) // 2
        self.root.geometry(f"+{x}+{y}")

        ttk.Label(self.root, text="请输入程序启动密码：").pack(pady=(20, 5))
        
        self.password_var = tk.StringVar()
        self.entry = ttk.Entry(self.root, textvariable=self.password_var, show="*", width=25)
        self.entry.pack(pady=5)
        self.entry.bind("<Return>", lambda e: self.verify())
        self.entry.focus_set()

        btn_frame = ttk.Frame(self.root)
        btn_frame.pack(pady=10)
        
        ttk.Button(btn_frame, text="确定", command=self.verify).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="取消", command=self.root.destroy).pack(side="left", padx=5)

    def verify(self):
        candidate_hash = hashlib.sha256(self.password_var.get().encode("utf-8")).hexdigest()
        if candidate_hash.lower() == self.password_hash.lower():
            self.success = True
            self.root.destroy()
        else:
            messagebox.showerror("错误", "密码错误，请重新输入！")
            self.password_var.set("")

    def run(self):
        self.root.mainloop()
        return self.success


def get_startup_password_hash() -> str:
    """读取启动密码 SHA-256；未配置时不启用启动密码框"""
    env_hash = os.environ.get("T12306_STARTUP_PASSWORD_SHA256", "").strip()
    if env_hash:
        return env_hash
    
    hash_file = get_data_path("startup_password.sha256")
    try:
        if os.path.exists(hash_file):
            with open(hash_file, "r", encoding="utf-8") as f:
                return f.read().strip()
    except Exception:
        pass
    return ""


def main():
    """主入口"""
    # 检查是否为打包后的 EXE 运行
    if getattr(sys, 'frozen', False):
        password_hash = get_startup_password_hash()
        if password_hash:
            dialog = PasswordDialog(password_hash)
            if not dialog.run():
                sys.exit(0)  # 验证失败或取消，直接退出

    try:
        from railwatch_ui import main as railwatch_main
        railwatch_main()
        return
    except RuntimeError as exc:
        if "PySide6 is required" not in str(exc):
            raise
        print(f"{APP_DISPLAY_NAME}: PySide6 unavailable, falling back to legacy Tkinter UI. {exc}")

    app = T12306GUI()
    app.run()


if __name__ == "__main__":
    main()
