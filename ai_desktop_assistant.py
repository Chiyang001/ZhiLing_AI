#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI桌面助手 - 基于Ollama的本地AI对话助手
支持与本地Ollama模型对话并执行特定任务
"""

import json
import subprocess
import sys
import os
import re
import shutil
from typing import List, Dict, Optional
import requests
from datetime import datetime

class OllamaClient:
    """Ollama客户端，用于与本地Ollama服务通信"""
    
    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url
        
    def list_models(self) -> List[Dict]:
        """获取已安装的模型列表"""
        try:
            response = requests.get(f"{self.base_url}/api/tags")
            if response.status_code == 200:
                return response.json().get('models', [])
            else:
                return []
        except Exception as e:
            print(f"获取模型列表失败: {e}")
            return []
    
    def chat(self, model: str, messages: List[Dict], system_prompt: str = "") -> str:
        """与指定模型进行对话（支持多轮对话）"""
        try:
            # 构建消息列表
            chat_messages = []
            if system_prompt:
                chat_messages.append({"role": "system", "content": system_prompt})
            chat_messages.extend(messages)
            
            payload = {
                "model": model,
                "messages": chat_messages,
                "stream": False
            }
            
            response = requests.post(f"{self.base_url}/api/chat", json=payload)
            if response.status_code == 200:
                return response.json()['message']['content']
            else:
                return f"请求失败: {response.status_code}"
        except Exception as e:
            return f"对话失败: {e}"
    
    def chat_stream(self, model: str, messages: List[Dict], system_prompt: str = ""):
        """与指定模型进行流式对话（支持多轮对话）"""
        try:
            # 构建消息列表
            chat_messages = []
            if system_prompt:
                chat_messages.append({"role": "system", "content": system_prompt})
            chat_messages.extend(messages)
            
            payload = {
                "model": model,
                "messages": chat_messages,
                "stream": True
            }
            
            response = requests.post(f"{self.base_url}/api/chat", json=payload, stream=True)
            if response.status_code == 200:
                full_response = ""
                for line in response.iter_lines():
                    if line:
                        try:
                            data = json.loads(line.decode('utf-8'))
                            if 'message' in data and 'content' in data['message']:
                                content = data['message']['content']
                                full_response += content
                                yield content
                            if data.get('done', False):
                                break
                        except json.JSONDecodeError:
                            continue
                return full_response
            else:
                yield f"请求失败: {response.status_code}"
                return f"请求失败: {response.status_code}"
        except Exception as e:
            yield f"对话失败: {e}"
            return f"对话失败: {e}"

class TaskExecutor:
    """任务执行器，用于执行AI识别出的特定任务"""
    
    @staticmethod
    def get_all_shortcuts() -> Dict[str, str]:
        """获取所有可用的快捷方式和文件夹"""
        shortcuts = {}
        if sys.platform == "win32":
            # 获取用户桌面路径
            user_desktop_paths = []
            home_dir = os.path.expanduser("~")
            
            # 尝试多种桌面路径
            possible_desktop_names = ["Desktop", "桌面", "desktop"]
            for desktop_name in possible_desktop_names:
                desktop_path = os.path.join(home_dir, desktop_name)
                if os.path.exists(desktop_path):
                    user_desktop_paths.append(desktop_path)
            
            # 公共桌面路径
            public_desktop_paths = []
            if os.environ.get("PUBLIC"):
                public_desktop_paths.append(os.path.join(os.environ.get("PUBLIC"), "Desktop"))
            if os.environ.get("ALLUSERSPROFILE"):
                public_desktop_paths.append(os.path.join(os.environ.get("ALLUSERSPROFILE"), "Desktop"))
            
            # 开始菜单路径
            start_menu_paths = []
            if os.environ.get("APPDATA"):
                start_menu_paths.append(os.path.join(os.environ.get("APPDATA"), "Microsoft", "Windows", "Start Menu", "Programs"))
            if os.environ.get("PROGRAMDATA"):
                start_menu_paths.append(os.path.join(os.environ.get("PROGRAMDATA"), "Microsoft", "Windows", "Start Menu", "Programs"))
            
            # 合并所有搜索路径
            search_paths = user_desktop_paths + public_desktop_paths + start_menu_paths
            
            for search_path in search_paths:
                if os.path.exists(search_path):
                    try:
                        # 如果是桌面路径，也包含文件夹
                        is_desktop = any(desktop_name in search_path for desktop_name in ["Desktop", "桌面", "desktop"])
                        
                        for root, dirs, files in os.walk(search_path):
                            # 处理文件（快捷方式）
                            for file in files:
                                if file.lower().endswith(('.lnk', '.url')):
                                    app_name = file.replace('.lnk', '').replace('.url', '')
                                    full_path = os.path.join(root, file)
                                    shortcuts[app_name.lower()] = full_path
                            
                            # 如果是桌面路径，也添加文件夹
                            if is_desktop and root == search_path:  # 只处理桌面根目录的文件夹
                                for dir_name in dirs:
                                    if not dir_name.startswith('.'):  # 忽略隐藏文件夹
                                        full_path = os.path.join(root, dir_name)
                                        shortcuts[dir_name.lower()] = full_path
                    except Exception as e:
                        print(f"扫描路径 {search_path} 时出错: {e}")
                        continue
        return shortcuts
    
    @staticmethod
    def find_best_match(app_name: str, shortcuts: Dict[str, str]) -> tuple:
        """找到最佳匹配的快捷方式或文件夹"""
        app_name_lower = app_name.lower().strip()
        
        # 1. 完全匹配
        if app_name_lower in shortcuts:
            return shortcuts[app_name_lower], "完全匹配"
        
        # 2. 双向包含匹配（应用名在快捷方式名中，或快捷方式名在应用名中）
        best_match = None
        best_score = 0
        best_type = ""
        
        for shortcut_name, path in shortcuts.items():
            score = 0
            match_type = ""
            
            # 应用名包含在快捷方式名中
            if app_name_lower in shortcut_name:
                score = len(app_name_lower) / len(shortcut_name)
                item_type = "文件夹" if os.path.isdir(path) else "应用"
                match_type = f"应用名匹配: {shortcut_name} ({item_type})"
            
            # 快捷方式名包含在应用名中（处理"豆包AI"匹配"豆包"的情况）
            elif shortcut_name in app_name_lower:
                score = len(shortcut_name) / len(app_name_lower)
                item_type = "文件夹" if os.path.isdir(path) else "应用"
                match_type = f"快捷方式匹配: {shortcut_name} ({item_type})"
            
            # 开头匹配
            elif shortcut_name.startswith(app_name_lower) or app_name_lower.startswith(shortcut_name):
                if shortcut_name.startswith(app_name_lower):
                    score = len(app_name_lower) / len(shortcut_name)
                else:
                    score = len(shortcut_name) / len(app_name_lower)
                item_type = "文件夹" if os.path.isdir(path) else "应用"
                match_type = f"开头匹配: {shortcut_name} ({item_type})"
            
            # 关键词匹配（去掉常见后缀如AI、软件等）
            else:
                # 提取核心关键词
                app_keywords = app_name_lower.replace('ai', '').replace('软件', '').replace('应用', '').replace('文件夹', '').replace('服务站', '').strip()
                shortcut_keywords = shortcut_name.replace('ai', '').replace('软件', '').replace('应用', '').replace('文件夹', '').replace('服务站', '').strip()
                
                if app_keywords and shortcut_keywords:
                    if app_keywords in shortcut_keywords or shortcut_keywords in app_keywords:
                        score = min(len(app_keywords), len(shortcut_keywords)) / max(len(app_keywords), len(shortcut_keywords))
                        item_type = "文件夹" if os.path.isdir(path) else "应用"
                        match_type = f"关键词匹配: {shortcut_name} ({item_type})"
            
            # 更新最佳匹配
            if score > best_score:
                best_score = score
                best_match = path
                best_type = match_type
        
        # 如果找到了匹配项且分数足够高
        if best_match and best_score >= 0.2:  # 进一步降低阈值到20%，提高匹配成功率
            return best_match, best_type
        
        # 3. 模糊匹配（字符级别匹配）
        for shortcut_name, path in shortcuts.items():
            # 计算共同字符数
            common_chars = set(app_name_lower) & set(shortcut_name)
            if common_chars:
                match_ratio = len(common_chars) / max(len(set(app_name_lower)), len(set(shortcut_name)))
                if match_ratio >= 0.4:  # 降低字符匹配阈值到40%
                    item_type = "文件夹" if os.path.isdir(path) else "应用"
                    return path, f"字符匹配: {shortcut_name} ({item_type})"
        
        # 4. 部分匹配（针对中文名称的特殊处理）
        for shortcut_name, path in shortcuts.items():
            # 检查是否有任何连续的字符匹配
            for i in range(len(app_name_lower)):
                for j in range(i + 2, len(app_name_lower) + 1):  # 至少2个字符
                    substring = app_name_lower[i:j]
                    if len(substring) >= 2 and substring in shortcut_name:
                        item_type = "文件夹" if os.path.isdir(path) else "应用"
                        return path, f"部分匹配: {shortcut_name} ({item_type})"
        
        return None, None
    
    @staticmethod
    def open_application(app_name: str) -> str:
        """打开指定应用程序或文件夹"""
        try:
            if sys.platform == "win32":
                # Windows系统
                common_apps = {
                    "记事本": "notepad",
                    "计算器": "calc",
                    "画图": "mspaint",
                    "浏览器": "start chrome",
                    "文件管理器": "explorer",
                    "资源管理器": "explorer",
                    "任务管理器": "taskmgr",
                    "控制面板": "control",
                    "命令提示符": "cmd",
                    "设置": "ms-settings:",
                    "系统设置": "ms-settings:",
                    "注册表编辑器": "regedit",
                    "服务管理器": "services.msc",
                    "设备管理器": "devmgmt.msc",
                    "磁盘管理": "diskmgmt.msc",
                    "事件查看器": "eventvwr.msc",
                    "组策略编辑器": "gpedit.msc",
                    "性能监视器": "perfmon.msc",
                    "远程桌面": "mstsc",
                    "PowerShell": "powershell",
                    "资源监视器": "resmon",
                    "防火墙": "firewall.cpl",
                    "网络连接": "ncpa.cpl",
                    "声音设置": "mmsys.cpl",
                    "电源选项": "powercfg.cpl",
                    "系统属性": "sysdm.cpl",
                    "时间和日期": "timedate.cpl",
                    "用户账户": "netplwiz",
                    # 添加系统特殊项目
                    "计算机": "explorer.exe ::{20D04FE0-3AEA-1069-A2D8-08002B30309D}",
                    "我的电脑": "explorer.exe ::{20D04FE0-3AEA-1069-A2D8-08002B30309D}",
                    "此电脑": "explorer.exe ::{20D04FE0-3AEA-1069-A2D8-08002B30309D}",
                    "回收站": "explorer.exe ::{645FF040-5081-101B-9F08-00AA002F954E}",
                    "网络": "explorer.exe ::{F02C1A0D-BE21-4350-88B0-7367FC96EF3C}",
                    "网上邻居": "explorer.exe ::{F02C1A0D-BE21-4350-88B0-7367FC96EF3C}",
                    "桌面": "explorer.exe shell:desktop",
                    "文档": "explorer.exe shell:personal",
                    "下载": "explorer.exe shell:downloads",
                    "图片": "explorer.exe shell:mypictures",
                    "音乐": "explorer.exe shell:mymusic",
                    "视频": "explorer.exe shell:myvideo"
                }
                
                # 首先检查是否为系统内置应用
                app_name_lower = app_name.lower()
                matched_key = None
                
                # 精确匹配
                for key in common_apps:
                    if app_name == key or app_name_lower == key.lower():
                        matched_key = key
                        break
                
                # 如果没有精确匹配，尝试模糊匹配
                if not matched_key:
                    for key in common_apps:
                        if app_name_lower in key.lower() or key.lower() in app_name_lower:
                            matched_key = key
                            break
                
                if matched_key:
                    try:
                        subprocess.Popen(common_apps[matched_key], shell=True)
                        return f"✅ 已打开系统项目: {matched_key}"
                    except Exception as e:
                        return f"❌ 打开系统项目失败: {e}"
                
                # 对于第三方应用和文件夹，先读取所有快捷方式和文件夹
                print(f"🔍 正在搜索 '{app_name}' 相关的快捷方式...")
                shortcuts = TaskExecutor.get_all_shortcuts()
                
                if not shortcuts:
                    return f"❌ 未找到任何快捷方式或文件夹，请检查桌面和开始菜单是否有应用程序"
                
                # 查找最佳匹配
                best_match_path, match_type = TaskExecutor.find_best_match(app_name, shortcuts)
                
                if best_match_path:
                    try:
                        # 判断是文件夹还是快捷方式
                        if os.path.isdir(best_match_path):
                            # 是文件夹，用资源管理器打开
                            subprocess.Popen(f'explorer "{best_match_path}"', shell=True)
                            folder_name = os.path.basename(best_match_path)
                            return f"✅ 已打开文件夹: {folder_name} ({match_type})"
                        else:
                            # 是快捷方式文件，直接启动
                            os.startfile(best_match_path)
                            shortcut_name = os.path.basename(best_match_path).replace('.lnk', '').replace('.url', '')
                            return f"✅ 已打开应用: {shortcut_name} ({match_type})"
                    except Exception as e:
                        # 如果os.startfile失败，尝试使用subprocess
                        try:
                            if os.path.isdir(best_match_path):
                                subprocess.Popen(f'explorer "{best_match_path}"', shell=True)
                                folder_name = os.path.basename(best_match_path)
                                return f"✅ 已打开文件夹: {folder_name} ({match_type})"
                            else:
                                subprocess.Popen(f'start "" "{best_match_path}"', shell=True)
                                shortcut_name = os.path.basename(best_match_path).replace('.lnk', '').replace('.url', '')
                                return f"✅ 已打开应用: {shortcut_name} ({match_type})"
                        except Exception as e2:
                            return f"❌ 找到匹配项但启动失败: {best_match_path}\n错误信息: {e2}"
                else:
                    # 显示可用的快捷方式和文件夹供用户参考
                    available_items = list(shortcuts.keys())[:10]  # 显示前10个
                    items_list = "、".join(available_items)
                    return f"❌ 未找到与 '{app_name}' 匹配的应用程序或文件夹\n💡 可用的项目包括: {items_list}{'...' if len(shortcuts) > 10 else ''}"
                    
            else:
                # Linux/Mac系统
                subprocess.Popen([app_name], shell=True)
                return f"✅ 已打开 {app_name}"
                
        except Exception as e:
            return f"❌ 打开应用失败: {e}"
            
    @staticmethod
    def system_power_action(action: str) -> str:
        """执行系统电源相关操作"""
        try:
            if sys.platform == "win32":
                # Windows系统
                if action == "关机":
                    subprocess.Popen("shutdown /s /t 60", shell=True)
                    return "✅ 系统将在60秒后关机，请保存您的工作。输入'取消关机'可取消。"
                elif action == "取消关机":
                    subprocess.Popen("shutdown /a", shell=True)
                    return "✅ 已取消关机操作。"
                elif action == "重启":
                    subprocess.Popen("shutdown /r /t 60", shell=True)
                    return "✅ 系统将在60秒后重启，请保存您的工作。输入'取消重启'可取消。"
                elif action == "取消重启":
                    subprocess.Popen("shutdown /a", shell=True)
                    return "✅ 已取消重启操作。"
                elif action == "注销":
                    subprocess.Popen("shutdown /l", shell=True)
                    return "✅ 正在注销当前用户..."
                elif action == "休眠":
                    subprocess.Popen("rundll32.exe powrprof.dll,SetSuspendState 0,1,0", shell=True)
                    return "✅ 系统正在进入休眠状态..."
                elif action == "睡眠":
                    subprocess.Popen("rundll32.exe powrprof.dll,SetSuspendState 0,1,0", shell=True)
                    return "✅ 系统正在进入睡眠状态..."
                elif action == "锁定":
                    subprocess.Popen("rundll32.exe user32.dll,LockWorkStation", shell=True)
                    return "✅ 已锁定计算机。"
                else:
                    return f"❌ 不支持的系统操作: {action}"
            elif sys.platform == "darwin":  # macOS
                if action == "关机":
                    subprocess.Popen("sudo shutdown -h +1", shell=True)
                    return "✅ 系统将在1分钟后关机，请保存您的工作。"
                elif action == "重启":
                    subprocess.Popen("sudo shutdown -r +1", shell=True)
                    return "✅ 系统将在1分钟后重启，请保存您的工作。"
                elif action == "注销":
                    subprocess.Popen("osascript -e 'tell application \"System Events\" to log out'", shell=True)
                    return "✅ 正在注销当前用户..."
                elif action == "睡眠":
                    subprocess.Popen("pmset sleepnow", shell=True)
                    return "✅ 系统正在进入睡眠状态..."
                else:
                    return f"❌ 不支持的系统操作: {action}"
            elif sys.platform.startswith("linux"):  # Linux
                if action == "关机":
                    subprocess.Popen("sudo shutdown -h +1", shell=True)
                    return "✅ 系统将在1分钟后关机，请保存您的工作。"
                elif action == "重启":
                    subprocess.Popen("sudo shutdown -r +1", shell=True)
                    return "✅ 系统将在1分钟后重启，请保存您的工作。"
                elif action == "注销":
                    # 尝试多种桌面环境的注销命令
                    try:
                        subprocess.Popen("gnome-session-quit --logout --no-prompt", shell=True)
                    except:
                        try:
                            subprocess.Popen("qdbus org.kde.ksmserver /KSMServer logout 0 0 0", shell=True)
                        except:
                            return "❌ 无法执行注销操作，请手动注销。"
                    return "✅ 正在注销当前用户..."
                else:
                    return f"❌ 不支持的系统操作: {action}"
            else:
                return f"❌ 不支持的操作系统: {sys.platform}"
        except Exception as e:
            return f"❌ 执行系统操作失败: {e}"
    
    @staticmethod
    def get_system_info() -> str:
        """获取系统信息"""
        try:
            import platform
            info = f"""
📊 系统信息:
- 操作系统: {platform.system()} {platform.release()}
- 处理器: {platform.processor()}
- Python版本: {platform.python_version()}
- 当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            """
            return info.strip()
        except Exception as e:
            return f"❌ 获取系统信息失败: {e}"
    
    @staticmethod
    def list_directory(path: str = ".") -> str:
        """列出目录内容"""
        try:
            files = os.listdir(path)
            result = f"📁 目录 {os.path.abspath(path)} 的内容:\n"
            for file in files[:20]:  # 限制显示前20个文件
                result += f"  - {file}\n"
            if len(files) > 20:
                result += f"  ... 还有 {len(files) - 20} 个文件"
            return result
        except Exception as e:
            return f"❌ 列出目录失败: {e}"
    
    @staticmethod
    def search_applications(keyword: str = "") -> str:
        """搜索可用的应用程序"""
        try:
            if sys.platform != "win32":
                return "❌ 此功能目前仅支持Windows系统"
            
            print("🔍 正在扫描系统中的所有应用程序...")
            shortcuts = TaskExecutor.get_all_shortcuts()
            
            if not shortcuts:
                return "❌ 未找到任何应用程序快捷方式"
            
            # 过滤应用程序
            if keyword:
                keyword_lower = keyword.lower()
                filtered_apps = {name: path for name, path in shortcuts.items() 
                               if keyword_lower in name}
            else:
                filtered_apps = shortcuts
            
            if filtered_apps:
                result = f"🔍 找到的应用程序 {'(包含关键词: ' + keyword + ')' if keyword else ''}:\n"
                
                # 按名称排序
                sorted_apps = sorted(filtered_apps.items(), key=lambda x: x[0])
                
                for i, (app_name, path) in enumerate(sorted_apps[:30], 1):  # 限制显示30个
                    # 获取位置信息
                    if "Desktop" in path or "桌面" in path:
                        location = "桌面"
                    elif "Start Menu" in path:
                        location = "开始菜单"
                    else:
                        location = "其他"
                    
                    # 显示原始名称（首字母大写）
                    display_name = app_name.title()
                    result += f"  {i:2d}. {display_name} ({location})\n"
                
                if len(sorted_apps) > 30:
                    result += f"  ... 还有 {len(sorted_apps) - 30} 个应用程序"
                
                return result
            else:
                return f"❌ 未找到包含关键词 '{keyword}' 的应用程序"
                
        except Exception as e:
            return f"❌ 搜索应用程序失败: {e}"
    
    @staticmethod
    def list_desktop_shortcuts() -> str:
        """列出桌面上的所有快捷方式和文件夹"""
        try:
            if sys.platform != "win32":
                return "❌ 此功能目前仅支持Windows系统"
            
            # 获取桌面路径
            home_dir = os.path.expanduser("~")
            desktop_paths = []
            
            # 尝试多种桌面路径
            possible_desktop_names = ["Desktop", "桌面", "desktop"]
            for desktop_name in possible_desktop_names:
                desktop_path = os.path.join(home_dir, desktop_name)
                if os.path.exists(desktop_path):
                    desktop_paths.append(desktop_path)
            
            # 添加公共桌面
            if os.environ.get("PUBLIC"):
                public_desktop = os.path.join(os.environ.get("PUBLIC"), "Desktop")
                if os.path.exists(public_desktop):
                    desktop_paths.append(public_desktop)
            
            shortcuts = []
            folders = []
            files = []
            
            for desktop_path in desktop_paths:
                if os.path.exists(desktop_path):
                    try:
                        for item in os.listdir(desktop_path):
                            item_path = os.path.join(desktop_path, item)
                            
                            if os.path.isdir(item_path) and not item.startswith('.'):
                                # 文件夹
                                folders.append(item)
                            elif item.lower().endswith(('.lnk', '.url')):
                                # 快捷方式
                                app_name = item.replace('.lnk', '').replace('.url', '')
                                shortcuts.append(app_name)
                            elif os.path.isfile(item_path) and not item.startswith('.'):
                                # 普通文件
                                files.append(item)
                    except Exception as e:
                        print(f"扫描桌面路径 {desktop_path} 时出错: {e}")
                        continue
            
            # 添加桌面系统项目
            desktop_system_items = [
                "计算机", "我的电脑", "此电脑", "回收站", "网络", 
                "控制面板", "用户文件夹", "库", "文档库", "音乐库", "图片库", "视频库"
            ]
            
            result = f"🖥️ 桌面内容:\n\n"
            
            # 显示系统项目
            result += "📁 系统项目:\n"
            for i, item in enumerate(desktop_system_items, 1):
                result += f"  {i:2d}. {item}\n"
            
            # 显示文件夹
            if folders:
                unique_folders = sorted(list(set(folders)), key=str.lower)
                result += f"\n📂 文件夹 (共{len(unique_folders)}个):\n"
                for i, folder in enumerate(unique_folders, 1):
                    result += f"  {i:2d}. {folder}\n"
            
            # 显示快捷方式
            if shortcuts:
                unique_shortcuts = sorted(list(set(shortcuts)), key=str.lower)
                result += f"\n🔗 快捷方式 (共{len(unique_shortcuts)}个):\n"
                for i, shortcut in enumerate(unique_shortcuts, 1):
                    result += f"  {i:2d}. {shortcut}\n"
            
            # 显示普通文件
            if files:
                unique_files = sorted(list(set(files)), key=str.lower)
                result += f"\n📄 文件 (共{len(unique_files)}个):\n"
                for i, file in enumerate(unique_files[:10], 1):  # 只显示前10个文件
                    result += f"  {i:2d}. {file}\n"
                if len(unique_files) > 10:
                    result += f"  ... 还有 {len(unique_files) - 10} 个文件\n"
            
            if not shortcuts and not folders and not files:
                result += "\n❌ 桌面上没有找到任何项目\n"
                result += f"💡 检查的桌面路径: {', '.join(desktop_paths)}\n"
                
            return result
                
        except Exception as e:
            return f"❌ 列出桌面项目失败: {e}"
    
    @staticmethod
    def list_system_items() -> str:
        """列出所有可用的系统项目和工具"""
        try:
            if sys.platform != "win32":
                return "❌ 此功能目前仅支持Windows系统"
            
            result = "🛠️ 系统工具和项目:\n\n"
            
            # 文件管理
            result += "📁 文件管理:\n"
            file_items = [
                "文件管理器", "我的电脑", "计算机", "此电脑", "回收站",
                "桌面", "文档", "下载", "图片", "音乐", "视频", "网络"
            ]
            for i, item in enumerate(file_items, 1):
                result += f"  {i:2d}. {item}\n"
            
            # 系统设置
            result += "\n⚙️ 系统设置:\n"
            settings_items = [
                "设置", "控制面板", "设备管理器", "注册表编辑器", 
                "服务管理器", "组策略编辑器", "系统信息", "系统配置"
            ]
            for i, item in enumerate(settings_items, 1):
                result += f"  {i:2d}. {item}\n"
            
            # 系统工具
            result += "\n🔧 系统工具:\n"
            tools_items = [
                "任务管理器", "性能监视器", "资源监视器", "事件查看器",
                "磁盘管理", "磁盘清理", "磁盘碎片整理", "截图工具"
            ]
            for i, item in enumerate(tools_items, 1):
                result += f"  {i:2d}. {item}\n"
            
            # 网络工具
            result += "\n🌐 网络工具:\n"
            network_items = [
                "网络连接", "网络和共享中心", "防火墙", "远程桌面"
            ]
            for i, item in enumerate(network_items, 1):
                result += f"  {i:2d}. {item}\n"
            
            return result
            
        except Exception as e:
            return f"❌ 列出系统项目失败: {e}"
    
    @staticmethod
    def list_directory_files(path: str) -> Dict[str, str]:
        """列出指定目录下的所有文件和文件夹，返回名称到完整路径的映射"""
        files_map = {}
        try:
            if path.startswith('~'):
                path = os.path.expanduser(path)
            elif not os.path.isabs(path):
                path = os.path.abspath(path)
            
            if not os.path.exists(path):
                return files_map
            
            for item in os.listdir(path):
                item_path = os.path.join(path, item)
                # 使用小写作为键，便于模糊匹配
                files_map[item.lower()] = item_path
                # 同时保存原始名称
                files_map[item] = item_path
            
        except Exception as e:
            print(f"❌ 读取目录失败: {e}")
        
        return files_map
    
    @staticmethod
    def find_file_in_directory(filename: str, directory_files: Dict[str, str]) -> tuple:
        """在目录文件映射中查找最匹配的文件，使用与应用程序匹配相同的算法"""
        filename_lower = filename.lower().strip()
        
        # 1. 完全匹配（区分大小写）
        if filename in directory_files:
            return directory_files[filename], "完全匹配"
        
        # 2. 完全匹配（不区分大小写）
        if filename_lower in directory_files:
            return directory_files[filename_lower], "完全匹配(忽略大小写)"
        
        # 3. 双向包含匹配（与应用程序匹配算法一致）
        best_match = None
        best_score = 0
        best_type = ""
        
        for file_key, file_path in directory_files.items():
            file_basename = os.path.basename(file_path).lower()
            score = 0
            match_type = ""
            
            # 搜索词包含在文件名中
            if filename_lower in file_basename:
                score = len(filename_lower) / len(file_basename)
                match_type = f"包含匹配: {os.path.basename(file_path)}"
            
            # 文件名包含在搜索词中
            elif file_basename in filename_lower:
                score = len(file_basename) / len(filename_lower)
                match_type = f"被包含匹配: {os.path.basename(file_path)}"
            
            # 开头匹配
            elif file_basename.startswith(filename_lower) or filename_lower.startswith(file_basename):
                if file_basename.startswith(filename_lower):
                    score = len(filename_lower) / len(file_basename)
                else:
                    score = len(file_basename) / len(filename_lower)
                match_type = f"开头匹配: {os.path.basename(file_path)}"
            
            # 关键词匹配（去掉常见后缀）
            else:
                # 提取核心关键词，去除扩展名和常见词汇
                filename_keywords = os.path.splitext(filename_lower)[0].replace('应用', '').replace('软件', '').replace('程序', '').replace('工具', '').strip()
                file_keywords = os.path.splitext(file_basename)[0].replace('应用', '').replace('软件', '').replace('程序', '').replace('工具', '').strip()
                
                if filename_keywords and file_keywords:
                    if filename_keywords in file_keywords or file_keywords in filename_keywords:
                        score = min(len(filename_keywords), len(file_keywords)) / max(len(filename_keywords), len(file_keywords))
                        match_type = f"关键词匹配: {os.path.basename(file_path)}"
            
            # 更新最佳匹配
            if score > best_score:
                best_score = score
                best_match = file_path
                best_type = match_type
        
        # 如果找到了匹配项且分数足够高
        if best_match and best_score >= 0.2:  # 降低阈值，提高匹配成功率
            return best_match, best_type
        
        # 4. 模糊匹配（字符级别匹配）
        for file_key, file_path in directory_files.items():
            file_basename = os.path.basename(file_path).lower()
            # 计算共同字符数
            common_chars = set(filename_lower) & set(file_basename)
            if common_chars:
                match_ratio = len(common_chars) / max(len(set(filename_lower)), len(set(file_basename)))
                if match_ratio >= 0.4:  # 字符匹配阈值
                    return file_path, f"字符匹配: {os.path.basename(file_path)}"
        
        # 5. 部分匹配（针对中文名称的特殊处理）
        for file_key, file_path in directory_files.items():
            file_basename = os.path.basename(file_path).lower()
            # 检查是否有任何连续的字符匹配
            for i in range(len(filename_lower)):
                for j in range(i + 2, len(filename_lower) + 1):  # 至少2个字符
                    substring = filename_lower[i:j]
                    if len(substring) >= 2 and substring in file_basename:
                        return file_path, f"部分匹配: {os.path.basename(file_path)}"
        
        return None, None
    
    @staticmethod
    def batch_file_operations(operation_list: List[str]) -> str:
        """批量执行文件操作，只需要一次确认"""
        try:
            if not operation_list:
                return "❌ 没有要执行的文件操作"
            
            # 解析所有操作
            operations = []
            for params in operation_list:
                parts = params.split('|')
                if len(parts) < 2:
                    continue
                
                action = parts[0].strip()
                operation_info = {"action": action, "params": parts}
                
                # 解析具体参数
                if action == "新建文件":
                    if len(parts) >= 3:
                        # 标准格式：新建文件|目录路径|文件名
                        path = parts[1].strip()
                        filename = parts[2].strip()
                    elif len(parts) == 2:
                        # 简化格式：新建文件|完整文件路径
                        full_file_path = parts[1].strip()
                        path, filename = os.path.split(full_file_path)
                    else:
                        continue  # 跳过格式错误的操作
                    
                    if path.startswith('~'):
                        path = os.path.expanduser(path)
                    elif not os.path.isabs(path):
                        path = os.path.abspath(path)
                    
                    operation_info.update({
                        "path": path,
                        "filename": filename,
                        "full_path": os.path.join(path, filename)
                    })
                elif action == "新建文件夹" and len(parts) >= 3:
                    path = parts[1].strip()
                    dirname = parts[2].strip()
                    if path.startswith('~'):
                        path = os.path.expanduser(path)
                    elif not os.path.isabs(path):
                        path = os.path.abspath(path)
                    operation_info.update({
                        "path": path,
                        "dirname": dirname,
                        "full_path": os.path.join(path, dirname)
                    })
                elif action == "删除":
                    path = parts[1].strip()
                    if path.startswith('~'):
                        path = os.path.expanduser(path)
                    elif not os.path.isabs(path):
                        path = os.path.abspath(path)
                    
                    # 如果路径不存在，尝试在父目录中查找匹配的文件
                    if not os.path.exists(path):
                        parent_dir = os.path.dirname(path)
                        filename = os.path.basename(path)
                        if os.path.exists(parent_dir):
                            print(f"🔍 在目录 {parent_dir} 中搜索文件: {filename}")
                            directory_files = TaskExecutor.list_directory_files(parent_dir)
                            matched_path, match_type = TaskExecutor.find_file_in_directory(filename, directory_files)
                            if matched_path:
                                print(f"✅ 找到匹配文件: {match_type}")
                                path = matched_path
                    
                    operation_info.update({"path": path})
                elif action in ["重命名", "复制", "剪切"] and len(parts) >= 3:
                    path = parts[1].strip()
                    target = parts[2].strip()
                    
                    # 处理源路径
                    if path.startswith('~'):
                        path = os.path.expanduser(path)
                    elif not os.path.isabs(path):
                        path = os.path.abspath(path)
                    
                    # 如果源路径不存在，尝试在父目录中查找匹配的文件
                    original_path = path
                    if not os.path.exists(path):
                        parent_dir = os.path.dirname(path)
                        filename = os.path.basename(path)
                        if os.path.exists(parent_dir):
                            print(f"🔍 在目录 {parent_dir} 中搜索文件: {filename}")
                            directory_files = TaskExecutor.list_directory_files(parent_dir)
                            matched_path, match_type = TaskExecutor.find_file_in_directory(filename, directory_files)
                            if matched_path:
                                print(f"✅ 找到匹配文件: {match_type}")
                                path = matched_path
                            else:
                                # 显示可用文件供参考
                                available_files = [os.path.basename(p) for p in directory_files.values()][:5]
                                if available_files:
                                    print(f"💡 目录中的文件包括: {', '.join(available_files)}{'...' if len(directory_files) > 5 else ''}")
                    
                    # 处理目标路径
                    if target.startswith('~'):
                        target = os.path.expanduser(target)
                    elif not os.path.isabs(target):
                        # 对于重命名操作，如果目标不是绝对路径，则在源文件的目录中重命名
                        if action == "重命名":
                            target = os.path.join(os.path.dirname(path), target)
                        else:
                            target = os.path.abspath(target)
                    
                    # 对于复制操作，如果目标路径只是一个文件名，则复制到同一目录
                    if action == "复制" and not os.path.dirname(target):
                        target = os.path.join(os.path.dirname(path), target)
                    
                    operation_info.update({
                        "path": path, 
                        "target": target,
                        "original_path": original_path  # 保存原始路径用于错误提示
                    })
                
                operations.append(operation_info)
            
            if not operations:
                return "❌ 没有有效的文件操作"
            
            # 显示所有操作的摘要
            if len(operations) > 1:
                print(f"\n🔄 检测到多任务操作，共 {len(operations)} 个任务:")
                for i, op in enumerate(operations, 1):
                    if op["action"] == "新建文件":
                        print(f"  {i}. 新建文件: {op.get('path', '未知路径')}/{op.get('filename', '未知文件')}")
                    elif op["action"] == "新建文件夹":
                        print(f"  {i}. 新建文件夹: {op.get('path', '未知路径')}/{op.get('dirname', '未知文件夹')}")
                    elif op["action"] == "删除":
                        print(f"  {i}. 删除: {op.get('path', '未知路径')}")
                    elif op["action"] == "重命名":
                        print(f"  {i}. 重命名: {op.get('path', '未知路径')} -> {op.get('target', '未知目标')}")
                    elif op["action"] == "复制":
                        print(f"  {i}. 复制: {op.get('path', '未知路径')} -> {op.get('target', '未知目标')}")
                    elif op["action"] == "剪切":
                        print(f"  {i}. 剪切: {op.get('path', '未知路径')} -> {op.get('target', '未知目标')}")
                
                print("\n📋 是否确认执行以上所有操作？")
                confirm = input("请输入 (y/n): ").strip().lower()
                if confirm not in ['y', 'yes', '是', '确认']:
                    return "❌ 批量操作已取消"
            
            # 执行所有操作
            results = []
            success_count = 0
            
            for i, op in enumerate(operations, 1):
                try:
                    if op["action"] == "新建文件":
                        path = op["path"]
                        filename = op["filename"]
                        full_path = op["full_path"]
                        
                        if not os.path.exists(path):
                            results.append(f"❌ 任务{i}: 目录不存在: {path}")
                            continue
                        if os.path.exists(full_path):
                            results.append(f"❌ 任务{i}: 文件已存在: {full_path}")
                            continue
                        
                        with open(full_path, 'w', encoding='utf-8') as f:
                            f.write("")
                        results.append(f"✅ 任务{i}: 已创建文件: {filename}")
                        success_count += 1
                    
                    elif op["action"] == "新建文件夹":
                        path = op["path"]
                        dirname = op["dirname"]
                        full_path = op["full_path"]
                        
                        if not os.path.exists(path):
                            results.append(f"❌ 任务{i}: 目录不存在: {path}")
                            continue
                        if os.path.exists(full_path):
                            results.append(f"❌ 任务{i}: 文件夹已存在: {full_path}")
                            continue
                        
                        os.makedirs(full_path)
                        results.append(f"✅ 任务{i}: 已创建文件夹: {dirname}")
                        success_count += 1
                    
                    elif op["action"] == "删除":
                        path = op["path"]
                        
                        if not os.path.exists(path):
                            results.append(f"❌ 任务{i}: 路径不存在: {path}")
                            continue
                        
                        if os.path.isfile(path):
                            os.remove(path)
                            results.append(f"✅ 任务{i}: 已删除文件: {os.path.basename(path)}")
                        elif os.path.isdir(path):
                            shutil.rmtree(path)
                            results.append(f"✅ 任务{i}: 已删除文件夹: {os.path.basename(path)}")
                        success_count += 1
                    
                    elif op["action"] == "重命名":
                        path = op["path"]
                        new_name = os.path.basename(op["target"])
                        parent_dir = os.path.dirname(path)
                        new_path = os.path.join(parent_dir, new_name)
                        
                        if not os.path.exists(path):
                            results.append(f"❌ 任务{i}: 路径不存在: {path}")
                            continue
                        if os.path.exists(new_path):
                            results.append(f"❌ 任务{i}: 目标路径已存在: {new_path}")
                            continue
                        
                        os.rename(path, new_path)
                        results.append(f"✅ 任务{i}: 已重命名: {os.path.basename(path)} -> {new_name}")
                        success_count += 1
                    
                    elif op["action"] == "复制":
                        path = op["path"]
                        dest_path = op["target"]
                        
                        if not os.path.exists(path):
                            original_path = op.get("original_path", path)
                            results.append(f"❌ 任务{i}: 源路径不存在: {original_path}")
                            continue
                        
                        # 如果目标文件已存在，自动生成新的文件名
                        # 如果目标文件已存在，自动生成新的文件名
                        if os.path.exists(dest_path):
                            base_name, ext = os.path.splitext(dest_path)
                            counter = 1
                            while os.path.exists(dest_path):
                                if ext:
                                    dest_path = f"{base_name}_副本{counter if counter > 1 else ''}{ext}"
                                else:
                                    dest_path = f"{base_name}_副本{counter if counter > 1 else ''}"
                                counter += 1
                        
                        # 特殊处理：如果目标路径看起来像是要创建副本（包含原文件名）
                        elif os.path.basename(dest_path).startswith(os.path.splitext(os.path.basename(path))[0]):
                            # 检查是否是类似 "test.txt副本" 这样的格式
                            dest_basename = os.path.basename(dest_path)
                            src_basename_no_ext = os.path.splitext(os.path.basename(path))[0]
                            src_ext = os.path.splitext(os.path.basename(path))[1]
                            
                            # 如果目标文件名是 "原文件名副本" 格式，修正为 "原文件名_副本.扩展名"
                            if dest_basename == f"{src_basename_no_ext}副本" or dest_basename.endswith("副本"):
                                if "副本" in dest_basename and not dest_basename.endswith(src_ext):
                                    # 重新构建正确的文件名
                                    dest_path = os.path.join(os.path.dirname(dest_path), f"{src_basename_no_ext}_副本{src_ext}")
                        
                        try:
                            if os.path.isfile(path):
                                # 如果目标是目录，则在目录中创建文件
                                if os.path.isdir(dest_path):
                                    dest_path = os.path.join(dest_path, os.path.basename(path))
                                shutil.copy2(path, dest_path)
                                results.append(f"✅ 任务{i}: 已复制文件: {os.path.basename(path)} -> {os.path.basename(dest_path)}")
                            elif os.path.isdir(path):
                                # 复制文件夹
                                if os.path.exists(dest_path):
                                    dest_path = os.path.join(dest_path, os.path.basename(path))
                                shutil.copytree(path, dest_path)
                                results.append(f"✅ 任务{i}: 已复制文件夹: {os.path.basename(path)} -> {os.path.basename(dest_path)}")
                            success_count += 1
                        except Exception as copy_error:
                            results.append(f"❌ 任务{i}: 复制失败: {copy_error}")
                    
                    elif op["action"] == "剪切":
                        path = op["path"]
                        dest_path = op["target"]
                        
                        if not os.path.exists(path):
                            results.append(f"❌ 任务{i}: 源路径不存在: {path}")
                            continue
                        
                        if os.path.isdir(dest_path):
                            dest_path = os.path.join(dest_path, os.path.basename(path))
                        
                        shutil.move(path, dest_path)
                        results.append(f"✅ 任务{i}: 已移动: {os.path.basename(path)}")
                        success_count += 1
                
                except Exception as e:
                    results.append(f"❌ 任务{i}: 操作失败: {e}")
            
            # 生成总结
            summary = f"\n📊 批量操作完成: 成功 {success_count}/{len(operations)} 个任务"
            return '\n'.join(results) + summary
            
        except Exception as e:
            return f"❌ 批量文件操作失败: {e}"
    
    @staticmethod
    def write_content_to_file(file_path: str, content: str, encoding: str = 'utf-8') -> str:
        """将内容写入到指定文件"""
        try:
            # 处理路径
            if file_path.startswith('~'):
                file_path = os.path.expanduser(file_path)
            elif not os.path.isabs(file_path):
                file_path = os.path.abspath(file_path)
            
            # 确保目录存在
            directory = os.path.dirname(file_path)
            if directory and not os.path.exists(directory):
                os.makedirs(directory, exist_ok=True)
            
            # 检查文件扩展名，确保支持的格式
            file_ext = os.path.splitext(file_path)[1].lower()
            supported_formats = ['.txt', '.md', '.markdown', '.text']
            
            if file_ext not in supported_formats:
                return f"❌ 不支持的文件格式: {file_ext}，目前支持: {', '.join(supported_formats)}"
            
            # 写入文件
            with open(file_path, 'w', encoding=encoding) as f:
                f.write(content)
            
            file_size = os.path.getsize(file_path)
            file_size_kb = file_size / 1024
            
            return f"✅ 内容已成功写入文件: {os.path.basename(file_path)}\n📄 文件大小: {file_size_kb:.1f} KB\n📍 文件路径: {file_path}"
            
        except Exception as e:
            return f"❌ 写入文件失败: {e}"
    
    @staticmethod
    def file_operation(operation: str, params: str) -> str:
        """执行单个文件和文件夹操作（保留兼容性）"""
        return TaskExecutor.batch_file_operations([params])

class AIDesktopAssistant:
    """AI桌面助手主类"""
    
    def __init__(self):
        self.ollama_client = OllamaClient()
        self.task_executor = TaskExecutor()
        self.current_model = None
        self.system_prompt = self._get_system_prompt()
        self.conversation_history = []  # 存储对话历史
        self.max_history_length = 20  # 最大历史记录长度
        
    def _get_system_prompt(self) -> str:
        """获取系统提示词"""
        return """你是一个智能桌面助手，可以帮助用户执行各种任务。

当用户需要执行特定任务时，请按照以下格式回复：

1. 打开应用程序或系统项目时，回复格式：
[TASK:OPEN_APP]应用程序名称[/TASK]
然后给出正常的回答。

2. 获取系统信息时，回复格式：
[TASK:SYSTEM_INFO][/TASK]
然后给出正常的回答。

3. 列出目录内容时，回复格式：
[TASK:LIST_DIR]目录路径[/TASK]
然后给出正常的回答。

4. 执行系统电源操作时，回复格式：
[TASK:POWER_ACTION]操作名称[/TASK]
操作名称只能是：关机、重启、注销、休眠、睡眠、锁定、取消关机、取消重启

5. 搜索应用程序时，回复格式：
[TASK:SEARCH_APPS]关键词[/TASK]
如果不指定关键词，则列出所有找到的应用程序。

6. 查看桌面快捷方式时，回复格式：
[TASK:LIST_SHORTCUTS][/TASK]
列出桌面上的所有快捷方式。

7. 文件和文件夹操作时，回复格式：
[TASK:FILE_OP]操作类型|路径|参数[/TASK]
支持的操作类型：新建文件、新建文件夹、删除、重命名、复制、剪切
参数格式：操作类型|目标路径|额外参数(如文件名、新名称、目标路径等)

8. 写入内容到文件时，回复格式：
[TASK:WRITE_FILE]文件路径|文件内容[/TASK]
支持的文件格式：.txt、.md、.markdown、.text
文件内容可以包含换行符和格式化文本

重要提示：
- "打开计算机"、"打开我的电脑"、"打开此电脑" 应该使用 [TASK:OPEN_APP]计算机[/TASK]
- "打开回收站" 应该使用 [TASK:OPEN_APP]回收站[/TASK]
- "打开文件管理器"、"打开资源管理器" 应该使用 [TASK:OPEN_APP]文件管理器[/TASK]
- 只有明确的电源操作（关机、重启等）才使用 POWER_ACTION
- 所有其他"打开"请求都应该使用 OPEN_APP

示例：
用户："帮我打开记事本"
回复："[TASK:OPEN_APP]记事本[/TASK]好的，我来帮你打开记事本。"

用户："打开计算机"
回复："[TASK:OPEN_APP]计算机[/TASK]好的，我来帮你打开计算机（我的电脑）。"

用户："打开回收站"
回复："[TASK:OPEN_APP]回收站[/TASK]好的，我来帮你打开回收站。"

用户："帮我关机"
回复："[TASK:POWER_ACTION]关机[/TASK]好的，我将为您执行关机操作。"

用户："在桌面新建一个文件夹叫做测试"
回复："[TASK:FILE_OP]新建文件夹|~/Desktop|测试[/TASK]好的，我来帮你在桌面创建一个名为'测试'的文件夹。"

用户："在桌面创建3个文件夹，分别叫做a，b，c"
回复："[TASK:FILE_OP]新建文件夹|~/Desktop|a[/TASK][TASK:FILE_OP]新建文件夹|~/Desktop|b[/TASK][TASK:FILE_OP]新建文件夹|~/Desktop|c[/TASK]好的，我来帮你在桌面创建三个文件夹：a、b、c。"

用户："在桌面创建5个文件夹，从1到5命名，再在其中分别创建一个文件text.txt"
回复："[TASK:FILE_OP]新建文件夹|~/Desktop|1[/TASK][TASK:FILE_OP]新建文件夹|~/Desktop|2[/TASK][TASK:FILE_OP]新建文件夹|~/Desktop|3[/TASK][TASK:FILE_OP]新建文件夹|~/Desktop|4[/TASK][TASK:FILE_OP]新建文件夹|~/Desktop|5[/TASK][TASK:FILE_OP]新建文件|~/Desktop/1|text.txt[/TASK][TASK:FILE_OP]新建文件|~/Desktop/2|text.txt[/TASK][TASK:FILE_OP]新建文件|~/Desktop/3|text.txt[/TASK][TASK:FILE_OP]新建文件|~/Desktop/4|text.txt[/TASK][TASK:FILE_OP]新建文件|~/Desktop/5|text.txt[/TASK]好的，我来帮你在桌面创建5个文件夹（1到5），并在每个文件夹中创建text.txt文件。"

用户："删除D盘的temp文件夹"
回复："[TASK:FILE_OP]删除|D:/temp|[/TASK]好的，我将删除D盘的temp文件夹，请注意这将删除文件夹及其所有内容。"

用户："把文档里的report.txt复制到桌面"
用户："把文档里的report.txt复制到桌面"
回复："[TASK:FILE_OP]复制|~/Documents/report.txt|~/Desktop[/TASK]好的，我来帮你把report.txt文件从文档文件夹复制到桌面。"

用户："复制桌面上的test.txt一个副本"
回复："[TASK:FILE_OP]复制|~/Desktop/test.txt|~/Desktop/test_副本.txt[/TASK]好的，我来帮你在桌面创建test.txt的一个副本。"

用户："复制桌面上的文档.docx到同一目录下创建副本"
回复："[TASK:FILE_OP]复制|~/Desktop/文档.docx|~/Desktop/文档_副本.docx[/TASK]好的，我来帮你在桌面同一目录下创建文档.docx的副本。"

用户："将这份报告写入到桌面的report.txt文件中"
回复："[TASK:WRITE_FILE]~/Desktop/report.txt|这里是报告的具体内容...[/TASK]好的，我来帮你将报告内容写入到桌面的report.txt文件中。"

用户："创建一个markdown文件，内容是项目说明"
回复："[TASK:WRITE_FILE]~/Desktop/项目说明.md|# 项目说明\n\n这里是项目的详细说明内容...[/TASK]好的，我来帮你创建一个包含项目说明的markdown文件。"

请用中文回答，保持友好和专业的语调。"""

    def list_available_models(self) -> List[Dict]:
        """列出可用的模型"""
        return self.ollama_client.list_models()
    
    def select_model(self, model_name: str) -> bool:
        """选择要使用的模型"""
        models = self.list_available_models()
        model_names = [model['name'] for model in models]
        
        if model_name in model_names:
            self.current_model = model_name
            return True
        return False
    
    def process_user_input(self, user_input: str) -> str:
        """处理用户输入并返回回复"""
        if not self.current_model:
            return "❌ 请先选择一个AI模型"
        
        # 添加用户输入到对话历史
        self.conversation_history.append({"role": "user", "content": user_input})
        
        # 获取AI回复
        ai_response = self.ollama_client.chat(
            model=self.current_model,
            messages=self.conversation_history,
            system_prompt=self.system_prompt
        )
        
        # 添加AI回复到对话历史
        self.conversation_history.append({"role": "assistant", "content": ai_response})
        
        # 限制历史记录长度
        self._trim_conversation_history()
        
        # 解析并执行任务
        task_result = self._parse_and_execute_tasks(ai_response)
        
        # 组合最终回复
        if task_result:
            return f"{ai_response}\n\n{task_result}"
        else:
            return ai_response
    
    def process_user_input_stream(self, user_input: str):
        """处理用户输入并返回流式回复"""
        if not self.current_model:
            yield "❌ 请先选择一个AI模型"
            return
        
        # 添加用户输入到对话历史
        self.conversation_history.append({"role": "user", "content": user_input})
        
        # 流式获取AI回复
        ai_response = ""
        for chunk in self.ollama_client.chat_stream(
            model=self.current_model,
            messages=self.conversation_history,
            system_prompt=self.system_prompt
        ):
            ai_response += chunk
            yield chunk
        
        # 添加AI回复到对话历史
        self.conversation_history.append({"role": "assistant", "content": ai_response})
        
        # 限制历史记录长度
        self._trim_conversation_history()
        
        # 解析并执行任务
        task_result = self._parse_and_execute_tasks(ai_response)
        
        # 如果有任务结果，输出任务结果
        if task_result:
            yield f"\n\n{task_result}"
    
    def _parse_and_execute_tasks(self, ai_response: str) -> str:
        """解析AI回复中的任务标记并执行"""
        results = []
        
        # 匹配打开应用任务
        open_app_pattern = r'\[TASK:OPEN_APP\](.*?)\[/TASK\]'
        matches = re.findall(open_app_pattern, ai_response)
        for app_name in matches:
            result = self.task_executor.open_application(app_name.strip())
            results.append(result)
        
        # 匹配系统信息任务
        if '[TASK:SYSTEM_INFO][/TASK]' in ai_response:
            result = self.task_executor.get_system_info()
            results.append(result)
        
        # 匹配列出目录任务
        list_dir_pattern = r'\[TASK:LIST_DIR\](.*?)\[/TASK\]'
        matches = re.findall(list_dir_pattern, ai_response)
        for dir_path in matches:
            result = self.task_executor.list_directory(dir_path.strip())
            results.append(result)
            
        # 匹配系统电源操作任务
        power_action_pattern = r'\[TASK:POWER_ACTION\](.*?)\[/TASK\]'
        matches = re.findall(power_action_pattern, ai_response)
        for action in matches:
            result = self.task_executor.system_power_action(action.strip())
            results.append(result)
        
        # 匹配搜索应用任务
        search_apps_pattern = r'\[TASK:SEARCH_APPS\](.*?)\[/TASK\]'
        matches = re.findall(search_apps_pattern, ai_response)
        for keyword in matches:
            result = self.task_executor.search_applications(keyword.strip())
            results.append(result)
        
        # 匹配无参数的搜索应用任务
        if '[TASK:SEARCH_APPS][/TASK]' in ai_response:
            result = self.task_executor.search_applications()
            results.append(result)
        
        # 匹配列出桌面快捷方式任务
        if '[TASK:LIST_SHORTCUTS][/TASK]' in ai_response:
            result = self.task_executor.list_desktop_shortcuts()
            results.append(result)
        
        # 匹配文件操作任务 - 批量处理
        # 匹配文件操作任务 - 批量处理
        file_op_pattern = r'\[TASK:FILE_OP\](.*?)\[/TASK\]'
        file_matches = re.findall(file_op_pattern, ai_response)
        if file_matches:
            result = self.task_executor.batch_file_operations(file_matches)
            results.append(result)
        
        # 匹配写入文件任务
        write_file_pattern = r'\[TASK:WRITE_FILE\](.*?)\[/TASK\]'
        write_matches = re.findall(write_file_pattern, ai_response, re.DOTALL)
        for write_params in write_matches:
            parts = write_params.split('|', 1)  # 只分割第一个|，因为内容可能包含|
            if len(parts) >= 2:
                file_path = parts[0].strip()
                content = parts[1].strip()
                result = self.task_executor.write_content_to_file(file_path, content)
                results.append(result)
        
        return '\n'.join(results) if results else ""
    
    def _trim_conversation_history(self):
        """限制对话历史长度，保持最近的对话"""
        if len(self.conversation_history) > self.max_history_length:
            # 保留最近的对话，但确保成对出现（用户-助手）
            excess = len(self.conversation_history) - self.max_history_length
            # 确保删除的是成对的对话
            if excess % 2 != 0:
                excess += 1
            self.conversation_history = self.conversation_history[excess:]
    
    def clear_conversation_history(self):
        """清空对话历史"""
        self.conversation_history = []
        return "✅ 对话历史已清空"
    
    def get_conversation_summary(self) -> str:
        """获取对话历史摘要"""
        if not self.conversation_history:
            return "📝 当前没有对话历史"
        
        user_count = sum(1 for msg in self.conversation_history if msg["role"] == "user")
        assistant_count = sum(1 for msg in self.conversation_history if msg["role"] == "assistant")
        
        return f"📝 对话历史摘要:\n- 用户消息: {user_count} 条\n- 助手回复: {assistant_count} 条\n- 总计: {len(self.conversation_history)} 条消息"

def main():
    """主函数"""
    print("🤖 AI桌面助手启动中...")
    print("=" * 50)
    
    assistant = AIDesktopAssistant()
    
    # 检查Ollama服务是否可用
    models = assistant.list_available_models()
    if not models:
        print("❌ 无法连接到Ollama服务或没有安装模型")
        print("请确保Ollama正在运行并已安装至少一个模型")
        return
    
    # 显示可用模型
    print("📋 可用的AI模型:")
    for i, model in enumerate(models, 1):
        print(f"  {i}. {model['name']}")
    
    # 选择模型
    while True:
        try:
            choice = input(f"\n请选择模型 (1-{len(models)}) 或输入模型名称: ").strip()
            
            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(models):
                    selected_model = models[idx]['name']
                    break
            else:
                if assistant.select_model(choice):
                    selected_model = choice
                    break
                else:
                    print("❌ 模型不存在，请重新选择")
                    continue
                    
        except (ValueError, KeyboardInterrupt):
            print("\n👋 再见！")
            return
    
    assistant.current_model = selected_model
    print(f"✅ 已选择模型: {selected_model}")
    
    # 初始化AI模型（预热）
    print("\n🔄 正在初始化AI模型，请稍候...")
    import time
    start_time = time.time()
    
    try:
        # 发送一个包含系统提示词的初始化消息来真正预热模型
        print("   正在加载系统提示词和模型...")
        
        # 使用完整的系统提示词进行初始化，确保模型完全加载
        init_response = assistant.ollama_client.chat(
            model=selected_model,
            messages=[{"role": "user", "content": "系统初始化测试，请简短回复确认你已准备好协助用户"}],
            system_prompt=assistant.system_prompt  # 使用完整的系统提示词
        )
        
        end_time = time.time()
        init_duration = end_time - start_time
        
        # 确保收到了回复
        if init_response:
            print(f"✅ AI模型初始化完成！(耗时: {init_duration:.1f}秒)")
            if len(init_response) > 100:
                print(f"   模型回复: {init_response[:80]}...")
            else:
                print(f"   模型回复: {init_response}")
        else:
            print("⚠️ 模型初始化可能未完全成功，但仍可正常使用")
            
        # 清空初始化对话，避免影响后续对话
        assistant.conversation_history = []
            
    except Exception as e:
        end_time = time.time()
        init_duration = end_time - start_time
        print(f"⚠️ 模型初始化失败(耗时: {init_duration:.1f}秒)，但仍可正常使用: {e}")
    
    print("\n🎯 AI桌面助手已就绪！")
    print("\n🎯 AI桌面助手已就绪！")
    print("💡 提示: 你可以要求我打开应用程序、查看系统信息、文件操作等")
    print("💡 支持上下文关联对话，AI会记住之前的对话内容")
    print("💡 支持将AI生成的内容写入txt、md等文本文件")
    print("💡 输入 'clear' 清空对话历史，'history' 查看对话摘要")
    print("💡 输入 'quit' 或 'exit' 退出程序")
    print("⚡ 注意: 模型运行速度与电脑性能和模型大小有关")
    print("=" * 50)
    
    # 主对话循环
    while True:
        try:
            user_input = input("\n👤 你: ").strip()
            
            if user_input.lower() in ['quit', 'exit', '退出', '再见']:
                print("👋 再见！")
                break
            
            if not user_input:
                continue
            
            # 处理特殊命令
            if user_input.lower() in ['clear', '清空', '清空历史']:
                result = assistant.clear_conversation_history()
                print(f"🤖 AI助手: {result}")
                continue
            
            if user_input.lower() in ['history', '历史', '对话历史']:
                result = assistant.get_conversation_summary()
                print(f"🤖 AI助手: {result}")
                continue
            
            print("🤖 AI助手: ", end="", flush=True)
            # 使用流式输出
            for chunk in assistant.process_user_input_stream(user_input):
                print(chunk, end="", flush=True)
            print()  # 换行
            
        except KeyboardInterrupt:
            print("\n👋 再见！")
            break
        except Exception as e:
            print(f"❌ 发生错误: {e}")

if __name__ == "__main__":
    main()
