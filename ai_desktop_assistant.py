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
                return f"❌ 此功能目前仅支持Windows系统"
                
        except Exception as e:
            return f"❌ 打开应用失败: {e}"
            
    @staticmethod
    def system_power_action(action: str) -> str:
        """执行系统电源相关操作"""
        try:
            if sys.platform == "win32":
                # Windows系统
                if action == "关机":
                    print(f"\n⚠️  即将执行关机操作")
                    print("📋 是否确认关机？系统将在60秒后关机。")
                    confirm = input("请输入 (y/n): ").strip().lower()
                    if confirm not in ['y', 'yes', '是', '确认']:
                        return "❌ 关机操作已取消"
                    subprocess.Popen("shutdown /s /t 60", shell=True)
                    return "✅ 系统将在60秒后关机，请保存您的工作。输入'取消关机'可取消。"
                elif action == "取消关机":
                    subprocess.Popen("shutdown /a", shell=True)
                    return "✅ 已取消关机操作。"
                elif action == "重启":
                    print(f"\n⚠️  即将执行重启操作")
                    print("📋 是否确认重启？系统将在60秒后重启。")
                    confirm = input("请输入 (y/n): ").strip().lower()
                    if confirm not in ['y', 'yes', '是', '确认']:
                        return "❌ 重启操作已取消"
                    subprocess.Popen("shutdown /r /t 60", shell=True)
                    return "✅ 系统将在60秒后重启，请保存您的工作。输入'取消重启'可取消。"
                elif action == "取消重启":
                    subprocess.Popen("shutdown /a", shell=True)
                    return "✅ 已取消重启操作。"
                elif action == "注销":
                    print(f"\n⚠️  即将执行注销操作")
                    print("📋 是否确认注销当前用户？")
                    confirm = input("请输入 (y/n): ").strip().lower()
                    if confirm not in ['y', 'yes', '是', '确认']:
                        return "❌ 注销操作已取消"
                    subprocess.Popen("shutdown /l", shell=True)
                    return "✅ 正在注销当前用户..."
                elif action == "休眠":
                    print(f"\n⚠️  即将执行休眠操作")
                    print("📋 是否确认让系统进入休眠状态？")
                    confirm = input("请输入 (y/n): ").strip().lower()
                    if confirm not in ['y', 'yes', '是', '确认']:
                        return "❌ 休眠操作已取消"
                    subprocess.Popen("rundll32.exe powrprof.dll,SetSuspendState 0,1,0", shell=True)
                    return "✅ 系统正在进入休眠状态..."
                elif action == "睡眠":
                    print(f"\n⚠️  即将执行睡眠操作")
                    print("📋 是否确认让系统进入睡眠状态？")
                    confirm = input("请输入 (y/n): ").strip().lower()
                    if confirm not in ['y', 'yes', '是', '确认']:
                        return "❌ 睡眠操作已取消"
                    subprocess.Popen("rundll32.exe powrprof.dll,SetSuspendState 0,1,0", shell=True)
                    return "✅ 系统正在进入睡眠状态..."
                elif action == "锁定":
                    # 锁定操作相对安全，不需要确认
                    subprocess.Popen("rundll32.exe user32.dll,LockWorkStation", shell=True)
                    return "✅ 已锁定计算机。"
                else:
                    return f"❌ 不支持的系统操作: {action}"
            else:
                return f"❌ 此功能目前仅支持Windows系统"
        except Exception as e:
            return f"❌ 执行系统操作失败: {e}"
    
    @staticmethod
    def clean_system_junk() -> str:
        """清理系统垃圾和缓存文件"""
        try:
            if sys.platform != "win32":
                return "❌ 此功能目前仅支持Windows系统"
            
            print(f"\n🧹 即将执行系统清理操作")
            print("📋 将清理以下内容:")
            print("   • 临时文件 (%TEMP%)")
            print("   • Windows临时文件 (C:\\Windows\\Temp)")
            print("   • 回收站")
            print("   • 浏览器缓存 (Chrome, Edge)")
            print("   • 系统缓存文件")
            print("   • 预读取文件")
            print("⚠️  注意: 此操作将删除临时文件，可能影响某些程序的运行状态")
            
            confirm = input("是否确认执行清理操作？(y/n): ").strip().lower()
            if confirm not in ['y', 'yes', '是', '确认']:
                return "❌ 清理操作已取消"
            
            results = []
            cleaned_size = 0
            
            # 1. 清理用户临时文件
            try:
                temp_path = os.environ.get('TEMP', '')
                if temp_path and os.path.exists(temp_path):
                    print("🔄 正在清理用户临时文件...")
                    size_before = TaskExecutor._get_folder_size(temp_path)
                    TaskExecutor._clean_folder(temp_path, keep_folder=True)
                    size_after = TaskExecutor._get_folder_size(temp_path)
                    cleaned = size_before - size_after
                    cleaned_size += cleaned
                    results.append(f"✅ 用户临时文件: 清理了 {TaskExecutor._format_size(cleaned)}")
            except Exception as e:
                results.append(f"⚠️ 用户临时文件清理失败: {e}")
            
            # 2. 清理Windows临时文件
            try:
                win_temp_path = "C:\\Windows\\Temp"
                if os.path.exists(win_temp_path):
                    print("🔄 正在清理Windows临时文件...")
                    size_before = TaskExecutor._get_folder_size(win_temp_path)
                    TaskExecutor._clean_folder(win_temp_path, keep_folder=True)
                    size_after = TaskExecutor._get_folder_size(win_temp_path)
                    cleaned = size_before - size_after
                    cleaned_size += cleaned
                    results.append(f"✅ Windows临时文件: 清理了 {TaskExecutor._format_size(cleaned)}")
            except Exception as e:
                results.append(f"⚠️ Windows临时文件清理失败: {e}")
            
            # 3. 清理回收站
            try:
                print("🔄 正在清理回收站...")
                subprocess.run("PowerShell.exe -Command Clear-RecycleBin -Force", 
                             shell=True, capture_output=True, text=True, timeout=30)
                results.append("✅ 回收站: 已清空")
            except Exception as e:
                results.append(f"⚠️ 回收站清理失败: {e}")
            
            # 4. 清理预读取文件
            try:
                prefetch_path = "C:\\Windows\\Prefetch"
                if os.path.exists(prefetch_path):
                    print("🔄 正在清理预读取文件...")
                    size_before = TaskExecutor._get_folder_size(prefetch_path)
                    TaskExecutor._clean_folder(prefetch_path, keep_folder=True, file_pattern="*.pf")
                    size_after = TaskExecutor._get_folder_size(prefetch_path)
                    cleaned = size_before - size_after
                    cleaned_size += cleaned
                    results.append(f"✅ 预读取文件: 清理了 {TaskExecutor._format_size(cleaned)}")
            except Exception as e:
                results.append(f"⚠️ 预读取文件清理失败: {e}")
            
            # 5. 清理浏览器缓存
            try:
                print("🔄 正在清理浏览器缓存...")
                browser_cleaned = TaskExecutor._clean_browser_cache()
                cleaned_size += browser_cleaned
                results.append(f"✅ 浏览器缓存: 清理了 {TaskExecutor._format_size(browser_cleaned)}")
            except Exception as e:
                results.append(f"⚠️ 浏览器缓存清理失败: {e}")
            
            # 6. 运行磁盘清理
            try:
                print("🔄 正在运行系统磁盘清理...")
                subprocess.Popen("cleanmgr /sagerun:1", shell=True)
                results.append("✅ 系统磁盘清理: 已启动（在后台运行）")
            except Exception as e:
                results.append(f"⚠️ 系统磁盘清理启动失败: {e}")
            
            # 生成总结
            summary = f"\n🎯 清理完成! 总共释放了约 {TaskExecutor._format_size(cleaned_size)} 的磁盘空间"
            return '\n'.join(results) + summary
            
        except Exception as e:
            return f"❌ 系统清理失败: {e}"
    
    @staticmethod
    def _get_folder_size(folder_path: str) -> int:
        """获取文件夹大小（字节）"""
        total_size = 0
        try:
            for dirpath, dirnames, filenames in os.walk(folder_path):
                for filename in filenames:
                    try:
                        file_path = os.path.join(dirpath, filename)
                        if os.path.exists(file_path):
                            total_size += os.path.getsize(file_path)
                    except (OSError, FileNotFoundError):
                        continue
        except Exception:
            pass
        return total_size
    
    @staticmethod
    def _clean_folder(folder_path: str, keep_folder: bool = True, file_pattern: str = "*"):
        """清理文件夹内容"""
        try:
            import glob
            if file_pattern == "*":
                # 删除所有文件和子文件夹
                for root, dirs, files in os.walk(folder_path, topdown=False):
                    # 删除文件
                    for file in files:
                        try:
                            file_path = os.path.join(root, file)
                            os.remove(file_path)
                        except (OSError, PermissionError):
                            continue
                    # 删除空文件夹
                    for dir_name in dirs:
                        try:
                            dir_path = os.path.join(root, dir_name)
                            if dir_path != folder_path:  # 不删除根文件夹
                                os.rmdir(dir_path)
                        except (OSError, PermissionError):
                            continue
            else:
                # 按模式删除特定文件
                pattern_path = os.path.join(folder_path, file_pattern)
                for file_path in glob.glob(pattern_path):
                    try:
                        if os.path.isfile(file_path):
                            os.remove(file_path)
                    except (OSError, PermissionError):
                        continue
        except Exception:
            pass
    
    @staticmethod
    def _clean_browser_cache() -> int:
        """清理浏览器缓存"""
        total_cleaned = 0
        try:
            user_profile = os.environ.get('USERPROFILE', '')
            if not user_profile:
                return 0
            
            # Chrome缓存路径
            chrome_cache_paths = [
                os.path.join(user_profile, "AppData", "Local", "Google", "Chrome", "User Data", "Default", "Cache"),
                os.path.join(user_profile, "AppData", "Local", "Google", "Chrome", "User Data", "Default", "Code Cache"),
            ]
            
            # Edge缓存路径
            edge_cache_paths = [
                os.path.join(user_profile, "AppData", "Local", "Microsoft", "Edge", "User Data", "Default", "Cache"),
                os.path.join(user_profile, "AppData", "Local", "Microsoft", "Edge", "User Data", "Default", "Code Cache"),
            ]
            
            all_cache_paths = chrome_cache_paths + edge_cache_paths
            
            for cache_path in all_cache_paths:
                if os.path.exists(cache_path):
                    try:
                        size_before = TaskExecutor._get_folder_size(cache_path)
                        TaskExecutor._clean_folder(cache_path, keep_folder=True)
                        size_after = TaskExecutor._get_folder_size(cache_path)
                        total_cleaned += (size_before - size_after)
                    except Exception:
                        continue
                        
        except Exception:
            pass
        
        return total_cleaned
    
    @staticmethod
    def _format_size(size_bytes: int) -> str:
        """格式化文件大小显示"""
        if size_bytes == 0:
            return "0 B"
        
        size_names = ["B", "KB", "MB", "GB", "TB"]
        import math
        i = int(math.floor(math.log(size_bytes, 1024)))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        return f"{s} {size_names[i]}"
    
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
    def system_control_action(action: str, params: str = "") -> str:
        """执行系统控制操作（需要用户确认）"""
        try:
            if sys.platform != "win32":
                return "❌ 此功能目前仅支持Windows系统"
            
            action_lower = action.lower()
            
            # WiFi控制
            if action_lower in ["关闭wifi", "禁用wifi", "断开wifi"]:
                print(f"\n⚠️  即将关闭WiFi连接")
                print("📋 是否确认关闭WiFi？这将断开所有无线网络连接。")
                confirm = input("请输入 (y/n): ").strip().lower()
                if confirm not in ['y', 'yes', '是', '确认']:
                    return "❌ WiFi关闭操作已取消"
                
                try:
                    # 使用netsh命令禁用WiFi
                    result = subprocess.run('netsh interface set interface "Wi-Fi" admin=disable', 
                                          shell=True, capture_output=True, text=True, timeout=10)
                    if result.returncode == 0:
                        return "✅ WiFi已关闭"
                    else:
                        # 尝试其他可能的WiFi接口名称
                        interfaces = ["WLAN", "无线网络连接", "Wireless Network Connection"]
                        for interface in interfaces:
                            try:
                                result = subprocess.run(f'netsh interface set interface "{interface}" admin=disable', 
                                                      shell=True, capture_output=True, text=True, timeout=10)
                                if result.returncode == 0:
                                    return f"✅ WiFi已关闭 (接口: {interface})"
                            except:
                                continue
                        return "❌ 无法找到WiFi网络接口，请手动关闭"
                except Exception as e:
                    return f"❌ 关闭WiFi失败: {e}"
            
            elif action_lower in ["开启wifi", "启用wifi", "连接wifi"]:
                print(f"\n🔄 即将开启WiFi连接")
                print("📋 是否确认开启WiFi？")
                confirm = input("请输入 (y/n): ").strip().lower()
                if confirm not in ['y', 'yes', '是', '确认']:
                    return "❌ WiFi开启操作已取消"
                
                try:
                    # 使用netsh命令启用WiFi
                    result = subprocess.run('netsh interface set interface "Wi-Fi" admin=enable', 
                                          shell=True, capture_output=True, text=True, timeout=10)
                    if result.returncode == 0:
                        return "✅ WiFi已开启"
                    else:
                        # 尝试其他可能的WiFi接口名称
                        interfaces = ["WLAN", "无线网络连接", "Wireless Network Connection"]
                        for interface in interfaces:
                            try:
                                result = subprocess.run(f'netsh interface set interface "{interface}" admin=enable', 
                                                      shell=True, capture_output=True, text=True, timeout=10)
                                if result.returncode == 0:
                                    return f"✅ WiFi已开启 (接口: {interface})"
                            except:
                                continue
                        return "❌ 无法找到WiFi网络接口，请手动开启"
                except Exception as e:
                    return f"❌ 开启WiFi失败: {e}"
            
            # 音量控制
            elif action_lower in ["调节音量", "设置音量", "音量"]:
                if not params:
                    return "❌ 请指定音量值，例如：调节音量 50（设置为50%）"
                
                try:
                    volume = int(params.strip().replace('%', ''))
                    if not 0 <= volume <= 100:
                        return "❌ 音量值必须在0-100之间"
                    
                    print(f"\n🔊 即将设置系统音量为 {volume}%")
                    print("📋 是否确认调节音量？")
                    confirm = input("请输入 (y/n): ").strip().lower()
                    if confirm not in ['y', 'yes', '是', '确认']:
                        return "❌ 音量调节操作已取消"
                    
                    # 使用PowerShell设置音量
                    ps_command = f"""
Add-Type -TypeDefinition @'
using System.Runtime.InteropServices;
[Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAudioEndpointVolume {{
    int f(); int g(); int h(); int i();
    int SetMasterVolumeLevelScalar(float fLevel, System.Guid pguidEventContext);
    int j(); int k(); int l(); int m(); int n();
    int GetMasterVolumeLevelScalar(out float pfLevel);
}}
[Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDevice {{
    int Activate(ref System.Guid id, int clsCtx, int activationParams, out IAudioEndpointVolume aev);
}}
[Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceEnumerator {{
    int f(); int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice endpoint);
}}
[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] class MMDeviceEnumeratorComObject {{ }}
public class Audio {{
    static IAudioEndpointVolume Vol() {{
        var enumerator = new MMDeviceEnumeratorComObject() as IMMDeviceEnumerator;
        IMMDevice dev = null;
        Marshal.ThrowExceptionForHR(enumerator.GetDefaultAudioEndpoint(0, 0, out dev));
        IAudioEndpointVolume epv = null;
        var epvid = typeof(IAudioEndpointVolume).GUID;
        Marshal.ThrowExceptionForHR(dev.Activate(ref epvid, 23, 0, out epv));
        return epv;
    }}
    public static float GetVolume() {{ float v = -1; Marshal.ThrowExceptionForHR(Vol().GetMasterVolumeLevelScalar(out v)); return v; }}
    public static void SetVolume(float v) {{ Marshal.ThrowExceptionForHR(Vol().SetMasterVolumeLevelScalar(v, System.Guid.Empty)); }}
}}
'@
[Audio]::SetVolume({volume / 100.0})
"""
                    result = subprocess.run(f'PowerShell.exe -Command "{ps_command}"', 
                                          shell=True, capture_output=True, text=True, timeout=15)
                    if result.returncode == 0:
                        return f"✅ 系统音量已设置为 {volume}%"
                    else:
                        return f"❌ 音量调节失败: {result.stderr}"
                        
                except ValueError:
                    return "❌ 音量值必须是数字"
                except Exception as e:
                    return f"❌ 音量调节失败: {e}"
            
            elif action_lower in ["静音", "关闭声音"]:
                print(f"\n🔇 即将设置系统静音")
                print("📋 是否确认静音？")
                confirm = input("请输入 (y/n): ").strip().lower()
                if confirm not in ['y', 'yes', '是', '确认']:
                    return "❌ 静音操作已取消"
                
                try:
                    # 使用nircmd设置静音（如果可用）或PowerShell
                    result = subprocess.run('PowerShell.exe -Command "(New-Object -comObject WScript.Shell).SendKeys([char]173)"', 
                                          shell=True, capture_output=True, text=True, timeout=10)
                    return "✅ 系统已静音"
                except Exception as e:
                    return f"❌ 静音操作失败: {e}"
            
            # 启动任务管理器
            elif action_lower in ["任务管理器", "打开任务管理器", "启动任务管理器"]:
                try:
                    subprocess.Popen("taskmgr", shell=True)
                    return "✅ 任务管理器已启动"
                except Exception as e:
                    return f"❌ 启动任务管理器失败: {e}"
            
            # 启动设备管理器
            elif action_lower in ["设备管理器", "打开设备管理器", "启动设备管理器"]:
                print(f"\n⚙️ 即将启动设备管理器")
                print("📋 是否确认启动设备管理器？")
                confirm = input("请输入 (y/n): ").strip().lower()
                if confirm not in ['y', 'yes', '是', '确认']:
                    return "❌ 设备管理器启动已取消"
                
                try:
                    subprocess.Popen("devmgmt.msc", shell=True)
                    return "✅ 设备管理器已启动"
                except Exception as e:
                    return f"❌ 启动设备管理器失败: {e}"
            
            # 启动服务管理器
            elif action_lower in ["服务管理器", "服务", "打开服务"]:
                print(f"\n⚙️ 即将启动服务管理器")
                print("📋 是否确认启动服务管理器？")
                confirm = input("请输入 (y/n): ").strip().lower()
                if confirm not in ['y', 'yes', '是', '确认']:
                    return "❌ 服务管理器启动已取消"
                
                try:
                    subprocess.Popen("services.msc", shell=True)
                    return "✅ 服务管理器已启动"
                except Exception as e:
                    return f"❌ 启动服务管理器失败: {e}"
            
            # 启动注册表编辑器
            elif action_lower in ["注册表编辑器", "注册表", "regedit"]:
                print(f"\n⚠️  即将启动注册表编辑器")
                print("📋 注册表编辑器是高级系统工具，错误操作可能导致系统问题")
                print("📋 是否确认启动注册表编辑器？")
                confirm = input("请输入 (y/n): ").strip().lower()
                if confirm not in ['y', 'yes', '是', '确认']:
                    return "❌ 注册表编辑器启动已取消"
                
                try:
                    subprocess.Popen("regedit", shell=True)
                    return "✅ 注册表编辑器已启动"
                except Exception as e:
                    return f"❌ 启动注册表编辑器失败: {e}"
            
            # 启动系统配置
            elif action_lower in ["系统配置", "msconfig"]:
                print(f"\n⚙️ 即将启动系统配置")
                print("📋 是否确认启动系统配置工具？")
                confirm = input("请输入 (y/n): ").strip().lower()
                if confirm not in ['y', 'yes', '是', '确认']:
                    return "❌ 系统配置启动已取消"
                
                try:
                    subprocess.Popen("msconfig", shell=True)
                    return "✅ 系统配置已启动"
                except Exception as e:
                    return f"❌ 启动系统配置失败: {e}"
            
            # 启动命令提示符
            elif action_lower in ["命令提示符", "cmd", "终端"]:
                try:
                    subprocess.Popen("cmd", shell=True)
                    return "✅ 命令提示符已启动"
                except Exception as e:
                    return f"❌ 启动命令提示符失败: {e}"
            
            # 启动PowerShell
            elif action_lower in ["powershell", "ps"]:
                try:
                    subprocess.Popen("powershell", shell=True)
                    return "✅ PowerShell已启动"
                except Exception as e:
                    return f"❌ 启动PowerShell失败: {e}"
            
            # 显示系统信息
            elif action_lower in ["系统信息", "系统属性"]:
                try:
                    subprocess.Popen("msinfo32", shell=True)
                    return "✅ 系统信息已启动"
                except Exception as e:
                    return f"❌ 启动系统信息失败: {e}"
            
            # 启动磁盘管理
            elif action_lower in ["磁盘管理", "磁盘"]:
                print(f"\n💽 即将启动磁盘管理")
                print("📋 是否确认启动磁盘管理？")
                confirm = input("请输入 (y/n): ").strip().lower()
                if confirm not in ['y', 'yes', '是', '确认']:
                    return "❌ 磁盘管理启动已取消"
                
                try:
                    subprocess.Popen("diskmgmt.msc", shell=True)
                    return "✅ 磁盘管理已启动"
                except Exception as e:
                    return f"❌ 启动磁盘管理失败: {e}"
            
            # 启动事件查看器
            elif action_lower in ["事件查看器", "事件日志"]:
                print(f"\n📋 即将启动事件查看器")
                print("📋 是否确认启动事件查看器？")
                confirm = input("请输入 (y/n): ").strip().lower()
                if confirm not in ['y', 'yes', '是', '确认']:
                    return "❌ 事件查看器启动已取消"
                
                try:
                    subprocess.Popen("eventvwr.msc", shell=True)
                    return "✅ 事件查看器已启动"
                except Exception as e:
                    return f"❌ 启动事件查看器失败: {e}"
            
            # 启动性能监视器
            elif action_lower in ["性能监视器", "性能监控"]:
                try:
                    subprocess.Popen("perfmon.msc", shell=True)
                    return "✅ 性能监视器已启动"
                except Exception as e:
                    return f"❌ 启动性能监视器失败: {e}"
            
            # 启动资源监视器
            elif action_lower in ["资源监视器", "资源监控"]:
                try:
                    subprocess.Popen("resmon", shell=True)
                    return "✅ 资源监视器已启动"
                except Exception as e:
                    return f"❌ 启动资源监视器失败: {e}"
            
            # 启动控制面板
            elif action_lower in ["控制面板"]:
                try:
                    subprocess.Popen("control", shell=True)
                    return "✅ 控制面板已启动"
                except Exception as e:
                    return f"❌ 启动控制面板失败: {e}"
            
            # 启动Windows设置
            elif action_lower in ["windows设置", "设置", "系统设置"]:
                try:
                    subprocess.Popen("ms-settings:", shell=True)
                    return "✅ Windows设置已启动"
                except Exception as e:
                    return f"❌ 启动Windows设置失败: {e}"
            
            else:
                return f"❌ 不支持的系统控制操作: {action}\n💡 支持的操作包括: WiFi控制、音量调节、启动系统工具等"
                
        except Exception as e:
            return f"❌ 执行系统控制操作失败: {e}"
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
                return f"❌ 此功能目前仅支持Windows系统"
                
        except Exception as e:
            return f"❌ 打开应用失败: {e}"
            
    @staticmethod
    def system_power_action(action: str) -> str:
        """执行系统电源相关操作"""
        try:
            if sys.platform == "win32":
                # Windows系统
                if action == "关机":
                    print(f"\n⚠️  即将执行关机操作")
                    print("📋 是否确认关机？系统将在60秒后关机。")
                    confirm = input("请输入 (y/n): ").strip().lower()
                    if confirm not in ['y', 'yes', '是', '确认']:
                        return "❌ 关机操作已取消"
                    subprocess.Popen("shutdown /s /t 60", shell=True)
                    return "✅ 系统将在60秒后关机，请保存您的工作。输入'取消关机'可取消。"
                elif action == "取消关机":
                    subprocess.Popen("shutdown /a", shell=True)
                    return "✅ 已取消关机操作。"
                elif action == "重启":
                    print(f"\n⚠️  即将执行重启操作")
                    print("📋 是否确认重启？系统将在60秒后重启。")
                    confirm = input("请输入 (y/n): ").strip().lower()
                    if confirm not in ['y', 'yes', '是', '确认']:
                        return "❌ 重启操作已取消"
                    subprocess.Popen("shutdown /r /t 60", shell=True)
                    return "✅ 系统将在60秒后重启，请保存您的工作。输入'取消重启'可取消。"
                elif action == "取消重启":
                    subprocess.Popen("shutdown /a", shell=True)
                    return "✅ 已取消重启操作。"
                elif action == "注销":
                    print(f"\n⚠️  即将执行注销操作")
                    print("📋 是否确认注销当前用户？")
                    confirm = input("请输入 (y/n): ").strip().lower()
                    if confirm not in ['y', 'yes', '是', '确认']:
                        return "❌ 注销操作已取消"
                    subprocess.Popen("shutdown /l", shell=True)
                    return "✅ 正在注销当前用户..."
                elif action == "休眠":
                    print(f"\n⚠️  即将执行休眠操作")
                    print("📋 是否确认让系统进入休眠状态？")
                    confirm = input("请输入 (y/n): ").strip().lower()
                    if confirm not in ['y', 'yes', '是', '确认']:
                        return "❌ 休眠操作已取消"
                    subprocess.Popen("rundll32.exe powrprof.dll,SetSuspendState 0,1,0", shell=True)
                    return "✅ 系统正在进入休眠状态..."
                elif action == "睡眠":
                    print(f"\n⚠️  即将执行睡眠操作")
                    print("📋 是否确认让系统进入睡眠状态？")
                    confirm = input("请输入 (y/n): ").strip().lower()
                    if confirm not in ['y', 'yes', '是', '确认']:
                        return "❌ 睡眠操作已取消"
                    subprocess.Popen("rundll32.exe powrprof.dll,SetSuspendState 0,1,0", shell=True)
                    return "✅ 系统正在进入睡眠状态..."
                elif action == "锁定":
                    # 锁定操作相对安全，不需要确认
                    subprocess.Popen("rundll32.exe user32.dll,LockWorkStation", shell=True)
                    return "✅ 已锁定计算机。"
                else:
                    return f"❌ 不支持的系统操作: {action}"
            else:
                return f"❌ 此功能目前仅支持Windows系统"
        except Exception as e:
            return f"❌ 执行系统操作失败: {e}"
    
    @staticmethod
    def clean_system_junk() -> str:
        """清理系统垃圾和缓存文件"""
        try:
            if sys.platform != "win32":
                return "❌ 此功能目前仅支持Windows系统"
            
            print(f"\n🧹 即将执行系统清理操作")
            print("📋 将清理以下内容:")
            print("   • 临时文件 (%TEMP%)")
            print("   • Windows临时文件 (C:\\Windows\\Temp)")
            print("   • 回收站")
            print("   • 浏览器缓存 (Chrome, Edge)")
            print("   • 系统缓存文件")
            print("   • 预读取文件")
            print("⚠️  注意: 此操作将删除临时文件，可能影响某些程序的运行状态")
            
            confirm = input("是否确认执行清理操作？(y/n): ").strip().lower()
            if confirm not in ['y', 'yes', '是', '确认']:
                return "❌ 清理操作已取消"
            
            results = []
            cleaned_size = 0
            
            # 1. 清理用户临时文件
            try:
                temp_path = os.environ.get('TEMP', '')
                if temp_path and os.path.exists(temp_path):
                    print("🔄 正在清理用户临时文件...")
                    size_before = TaskExecutor._get_folder_size(temp_path)
                    TaskExecutor._clean_folder(temp_path, keep_folder=True)
                    size_after = TaskExecutor._get_folder_size(temp_path)
                    cleaned = size_before - size_after
                    cleaned_size += cleaned
                    results.append(f"✅ 用户临时文件: 清理了 {TaskExecutor._format_size(cleaned)}")
            except Exception as e:
                results.append(f"⚠️ 用户临时文件清理失败: {e}")
            
            # 2. 清理Windows临时文件
            try:
                win_temp_path = "C:\\Windows\\Temp"
                if os.path.exists(win_temp_path):
                    print("🔄 正在清理Windows临时文件...")
                    size_before = TaskExecutor._get_folder_size(win_temp_path)
                    TaskExecutor._clean_folder(win_temp_path, keep_folder=True)
                    size_after = TaskExecutor._get_folder_size(win_temp_path)
                    cleaned = size_before - size_after
                    cleaned_size += cleaned
                    results.append(f"✅ Windows临时文件: 清理了 {TaskExecutor._format_size(cleaned)}")
            except Exception as e:
                results.append(f"⚠️ Windows临时文件清理失败: {e}")
            
            # 3. 清理回收站
            try:
                print("🔄 正在清理回收站...")
                subprocess.run("PowerShell.exe -Command Clear-RecycleBin -Force", 
                             shell=True, capture_output=True, text=True, timeout=30)
                results.append("✅ 回收站: 已清空")
            except Exception as e:
                results.append(f"⚠️ 回收站清理失败: {e}")
            
            # 4. 清理预读取文件
            try:
                prefetch_path = "C:\\Windows\\Prefetch"
                if os.path.exists(prefetch_path):
                    print("🔄 正在清理预读取文件...")
                    size_before = TaskExecutor._get_folder_size(prefetch_path)
                    TaskExecutor._clean_folder(prefetch_path, keep_folder=True, file_pattern="*.pf")
                    size_after = TaskExecutor._get_folder_size(prefetch_path)
                    cleaned = size_before - size_after
                    cleaned_size += cleaned
                    results.append(f"✅ 预读取文件: 清理了 {TaskExecutor._format_size(cleaned)}")
            except Exception as e:
                results.append(f"⚠️ 预读取文件清理失败: {e}")
            
            # 5. 清理浏览器缓存
            try:
                print("🔄 正在清理浏览器缓存...")
                browser_cleaned = TaskExecutor._clean_browser_cache()
                cleaned_size += browser_cleaned
                results.append(f"✅ 浏览器缓存: 清理了 {TaskExecutor._format_size(browser_cleaned)}")
            except Exception as e:
                results.append(f"⚠️ 浏览器缓存清理失败: {e}")
            
            # 6. 运行磁盘清理
            try:
                print("🔄 正在运行系统磁盘清理...")
                subprocess.Popen("cleanmgr /sagerun:1", shell=True)
                results.append("✅ 系统磁盘清理: 已启动（在后台运行）")
            except Exception as e:
                results.append(f"⚠️ 系统磁盘清理启动失败: {e}")
            
            # 生成总结
            summary = f"\n🎯 清理完成! 总共释放了约 {TaskExecutor._format_size(cleaned_size)} 的磁盘空间"
            return '\n'.join(results) + summary
            
        except Exception as e:
            return f"❌ 系统清理失败: {e}"
    
    @staticmethod
    def _get_folder_size(folder_path: str) -> int:
        """获取文件夹大小（字节）"""
        total_size = 0
        try:
            for dirpath, dirnames, filenames in os.walk(folder_path):
                for filename in filenames:
                    try:
                        file_path = os.path.join(dirpath, filename)
                        if os.path.exists(file_path):
                            total_size += os.path.getsize(file_path)
                    except (OSError, FileNotFoundError):
                        continue
        except Exception:
            pass
        return total_size
    
    @staticmethod
    def _clean_folder(folder_path: str, keep_folder: bool = True, file_pattern: str = "*"):
        """清理文件夹内容"""
        try:
            import glob
            if file_pattern == "*":
                # 删除所有文件和子文件夹
                for root, dirs, files in os.walk(folder_path, topdown=False):
                    # 删除文件
                    for file in files:
                        try:
                            file_path = os.path.join(root, file)
                            os.remove(file_path)
                        except (OSError, PermissionError):
                            continue
                    # 删除空文件夹
                    for dir_name in dirs:
                        try:
                            dir_path = os.path.join(root, dir_name)
                            if dir_path != folder_path:  # 不删除根文件夹
                                os.rmdir(dir_path)
                        except (OSError, PermissionError):
                            continue
            else:
                # 按模式删除特定文件
                pattern_path = os.path.join(folder_path, file_pattern)
                for file_path in glob.glob(pattern_path):
                    try:
                        if os.path.isfile(file_path):
                            os.remove(file_path)
                    except (OSError, PermissionError):
                        continue
        except Exception:
            pass
    
    @staticmethod
    def _clean_browser_cache() -> int:
        """清理浏览器缓存"""
        total_cleaned = 0
        try:
            user_profile = os.environ.get('USERPROFILE', '')
            if not user_profile:
                return 0
            
            # Chrome缓存路径
            chrome_cache_paths = [
                os.path.join(user_profile, "AppData", "Local", "Google", "Chrome", "User Data", "Default", "Cache"),
                os.path.join(user_profile, "AppData", "Local", "Google", "Chrome", "User Data", "Default", "Code Cache"),
            ]
            
            # Edge缓存路径
            edge_cache_paths = [
                os.path.join(user_profile, "AppData", "Local", "Microsoft", "Edge", "User Data", "Default", "Cache"),
                os.path.join(user_profile, "AppData", "Local", "Microsoft", "Edge", "User Data", "Default", "Code Cache"),
            ]
            
            all_cache_paths = chrome_cache_paths + edge_cache_paths
            
            for cache_path in all_cache_paths:
                if os.path.exists(cache_path):
                    try:
                        size_before = TaskExecutor._get_folder_size(cache_path)
                        TaskExecutor._clean_folder(cache_path, keep_folder=True)
                        size_after = TaskExecutor._get_folder_size(cache_path)
                        total_cleaned += (size_before - size_after)
                    except Exception:
                        continue
                        
        except Exception:
            pass
        
        return total_cleaned
    
    @staticmethod
    def _format_size(size_bytes: int) -> str:
        """格式化文件大小显示"""
        if size_bytes == 0:
            return "0 B"
        
        size_names = ["B", "KB", "MB", "GB", "TB"]
        import math
        i = int(math.floor(math.log(size_bytes, 1024)))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        return f"{s} {size_names[i]}"
    
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
                elif action == "写入文件" and len(parts) >= 3:
                    # 写入文件|文件路径|文件内容
                    file_path = parts[1].strip()
                    content = parts[2].strip()
                    
                    if file_path.startswith('~'):
                        file_path = os.path.expanduser(file_path)
                    elif not os.path.isabs(file_path):
                        file_path = os.path.abspath(file_path)
                    
                    operation_info.update({
                        "file_path": file_path,
                        "content": content
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
            
            # 显示所有操作的摘要并请求用户确认
            if len(operations) > 1:
                print(f"\n🔄 检测到多任务操作，共 {len(operations)} 个任务:")
            else:
                print(f"\n🔄 检测到单任务操作:")
            
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
                elif op["action"] == "写入文件":
                    file_path = op.get('file_path', '未知路径')
                    content_preview = op.get('content', '')[:20] + ('...' if len(op.get('content', '')) > 20 else '')
                    print(f"  {i}. 写入文件: {file_path} (内容: {content_preview})")
            
            # 对所有操作都请求用户确认
            if len(operations) > 1:
                print("\n📋 是否确认执行以上所有操作？")
            else:
                print("\n📋 是否确认执行此操作？")
            
            confirm = input("请输入 (y/n): ").strip().lower()
            if confirm not in ['y', 'yes', '是', '确认']:
                if len(operations) > 1:
                    return "❌ 批量操作已取消"
                else:
                    return "❌ 操作已取消"
            
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
                    
                    elif op["action"] == "写入文件":
                        file_path = op["file_path"]
                        content = op["content"]
                        
                        try:
                            # 确保目录存在
                            directory = os.path.dirname(file_path)
                            if directory and not os.path.exists(directory):
                                os.makedirs(directory, exist_ok=True)
                            
                            # 检查文件扩展名，确保支持的格式
                            file_ext = os.path.splitext(file_path)[1].lower()
                            supported_formats = ['.txt', '.md', '.markdown', '.text']
                            
                            if file_ext not in supported_formats:
                                results.append(f"❌ 任务{i}: 不支持的文件格式: {file_ext}，目前支持: {', '.join(supported_formats)}")
                                continue
                            
                            # 写入文件
                            with open(file_path, 'w', encoding='utf-8') as f:
                                f.write(content)
                            
                            file_size = os.path.getsize(file_path)
                            file_size_kb = file_size / 1024
                            
                            results.append(f"✅ 任务{i}: 内容已写入文件: {os.path.basename(file_path)} ({file_size_kb:.1f} KB)")
                            success_count += 1
                            
                        except Exception as write_error:
                            results.append(f"❌ 任务{i}: 写入文件失败: {write_error}")
                
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
    
    def __init__(self, quick_mode=False):
        self.ollama_client = OllamaClient()
        self.task_executor = TaskExecutor()
        self.current_model = None
        self.quick_mode = quick_mode
        self.system_prompt = self._get_system_prompt(quick_mode)
        self.conversation_history = []  # 存储对话历史
        self.max_history_length = 20  # 最大历史记录长度
        
    def _get_system_prompt(self, quick_mode=False) -> str:
        """获取系统提示词"""
        if quick_mode:
            # 简化的系统提示词，用于快速启动
            return """你是智能桌面助手。当用户需要执行任务时，用以下格式回复：

打开应用: [TASK:OPEN_APP]应用名[/TASK]
系统信息: [TASK:SYSTEM_INFO][/TASK]
电源操作: [TASK:POWER_ACTION]操作名[/TASK] (关机/重启/注销/休眠/睡眠/锁定)
文件操作: [TASK:FILE_OP]操作|路径|参数[/TASK] (新建文件/新建文件夹/删除/重命名/复制/剪切)
写入文件: [TASK:WRITE_FILE]路径|内容[/TASK]
清理系统: [TASK:CLEAN_SYSTEM][/TASK]
系统控制: [TASK:SYSTEM_CONTROL]操作|参数[/TASK]

用中文回答，保持友好专业。"""
        
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

9. 清理系统垃圾和缓存时，回复格式：
[TASK:CLEAN_SYSTEM][/TASK]
清理临时文件、缓存、回收站等系统垃圾

10. 系统控制操作时，回复格式：
[TASK:SYSTEM_CONTROL]操作名称|参数[/TASK]
支持的操作包括：
- WiFi控制：关闭wifi、开启wifi
- 音量控制：调节音量|音量值（0-100）、静音
- 启动系统工具：任务管理器、设备管理器、服务管理器、注册表编辑器、系统配置、命令提示符、PowerShell、系统信息、磁盘管理、事件查看器、性能监视器、资源监视器、控制面板、Windows设置

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

用户："清理系统垃圾"
回复："[TASK:CLEAN_SYSTEM][/TASK]好的，我来帮你清理系统垃圾和缓存文件，释放磁盘空间。"

用户："关闭WiFi"
回复："[TASK:SYSTEM_CONTROL]关闭wifi|[/TASK]好的，我来帮你关闭WiFi连接。"

用户："把音量调到50"
回复："[TASK:SYSTEM_CONTROL]调节音量|50[/TASK]好的，我来帮你把系统音量调节到50%。"

用户："打开任务管理器"
回复："[TASK:SYSTEM_CONTROL]任务管理器|[/TASK]好的，我来帮你启动任务管理器。"

用户："启动设备管理器"
回复："[TASK:SYSTEM_CONTROL]设备管理器|[/TASK]好的，我来帮你启动设备管理器。"

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
        
        # 统一处理文件操作和写入文件任务
        all_file_operations = []
        
        # 匹配文件操作任务
        file_op_pattern = r'\[TASK:FILE_OP\](.*?)\[/TASK\]'
        file_matches = re.findall(file_op_pattern, ai_response)
        all_file_operations.extend(file_matches)
        
        # 匹配写入文件任务，转换为文件操作格式
        write_file_pattern = r'\[TASK:WRITE_FILE\](.*?)\[/TASK\]'
        write_matches = re.findall(write_file_pattern, ai_response, re.DOTALL)
        for write_params in write_matches:
            parts = write_params.split('|', 1)  # 只分割第一个|，因为内容可能包含|
            if len(parts) >= 2:
                file_path = parts[0].strip()
                content = parts[1].strip()
                # 转换为文件操作格式：写入文件|文件路径|文件内容
                write_operation = f"写入文件|{file_path}|{content}"
                all_file_operations.append(write_operation)
        
        # 如果有文件相关操作，统一处理
        if all_file_operations:
            result = self.task_executor.batch_file_operations(all_file_operations)
            results.append(result)
        
        # 匹配清理系统任务
        if '[TASK:CLEAN_SYSTEM][/TASK]' in ai_response:
            result = self.task_executor.clean_system_junk()
            results.append(result)
        
        # 匹配系统控制任务
        system_control_pattern = r'\[TASK:SYSTEM_CONTROL\](.*?)\[/TASK\]'
        control_matches = re.findall(system_control_pattern, ai_response)
        for control_params in control_matches:
            parts = control_params.split('|', 1)
            action = parts[0].strip()
            params = parts[1].strip() if len(parts) > 1 else ""
            # 修复：调用正确的方法名
            result = TaskExecutor.system_control_action(action, params)
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

def get_system_specs():
    """获取系统规格信息"""
    try:
        import platform
        import psutil
        
        # CPU信息
        cpu_count = psutil.cpu_count(logical=True)
        cpu_freq = psutil.cpu_freq()
        cpu_freq_ghz = cpu_freq.current / 1000 if cpu_freq else 0
        
        # 内存信息
        memory = psutil.virtual_memory()
        memory_gb = memory.total / (1024**3)
        
        # 系统信息
        system_info = {
            'cpu_cores': cpu_count,
            'cpu_freq_ghz': cpu_freq_ghz,
            'memory_gb': memory_gb,
            'system': platform.system(),
            'processor': platform.processor()
        }
        
        return system_info
    except Exception as e:
        print(f"⚠️ 获取系统信息失败: {e}")
        return {
            'cpu_cores': 4,  # 默认值
            'cpu_freq_ghz': 2.5,
            'memory_gb': 8,
            'system': 'Windows',
            'processor': 'Unknown'
        }

def estimate_model_size(model_name):
    """根据模型名称估算模型大小（GB）"""
    model_name_lower = model_name.lower()
    
    # 常见模型大小映射
    size_patterns = {
        '7b': 4.0,      # 7B参数模型约4GB
        '8b': 4.5,      # 8B参数模型约4.5GB
        '13b': 7.0,     # 13B参数模型约7GB
        '14b': 8.0,     # 14B参数模型约8GB
        '30b': 16.0,    # 30B参数模型约16GB
        '34b': 18.0,    # 34B参数模型约18GB
        '70b': 35.0,    # 70B参数模型约35GB
        'gemma': 2.0,   # Gemma系列通常较小
        'phi': 1.5,     # Phi系列通常很小
        'qwen': 4.0,    # Qwen系列中等大小
        'llama': 4.0,   # Llama系列默认大小
        'mistral': 4.0, # Mistral系列默认大小
        'codellama': 4.0, # CodeLlama系列默认大小
    }
    
    # 检查模型名称中的大小标识
    for pattern, size in size_patterns.items():
        if pattern in model_name_lower:
            return size
    
    # 如果无法识别，返回默认大小
    return 4.0

def estimate_init_time(system_specs, model_size_gb, quick_mode=False):
    """根据系统配置和模型大小估算初始化时间"""
    try:
        # 基础固定时间：标准模式90秒，快速模式40秒
        base_time = 40.0 if quick_mode else 90.0
        
        # 根据模型大小进行微调
        if model_size_gb <= 2:
            size_adjustment = -10  # 小模型减少10秒
        elif model_size_gb <= 4:
            size_adjustment = 0    # 中等模型不调整
        elif model_size_gb <= 8:
            size_adjustment = 10   # 较大模型增加10秒
        elif model_size_gb <= 16:
            size_adjustment = 20   # 大模型增加20秒
        else:
            size_adjustment = 30   # 超大模型增加30秒
        
        # 应用调整，确保不低于最小时间
        adjusted_time = base_time + size_adjustment
        min_time = 20.0 if quick_mode else 60.0
        
        return max(min_time, adjusted_time)
    except Exception:
        return 40.0 if quick_mode else 90.0  # 默认预估时间

def main():
    """主函数"""
    print("🤖 AI桌面助手启动中...")
    print("=" * 50)
    
    # 询问是否使用快速启动模式
    print("🚀 启动模式选择:")
    print("  1. 标准模式 - 完整功能，初始化时间较长")
    print("  2. 快速模式 - 简化提示词，快速启动")
    
    quick_mode = False
    while True:
        try:
            mode_choice = input("请选择启动模式 (1-标准/2-快速) [默认:1]: ").strip()
            if not mode_choice or mode_choice == '1':
                quick_mode = False
                print("✅ 已选择标准模式")
                break
            elif mode_choice == '2':
                quick_mode = True
                print("✅ 已选择快速模式")
                break
            else:
                print("❌ 请输入 1 或 2")
        except KeyboardInterrupt:
            print("\n👋 再见！")
            return
    
    assistant = AIDesktopAssistant(quick_mode=quick_mode)
    
    # 获取系统规格
    print("🔍 正在检测系统配置...")
    system_specs = get_system_specs()
    print(f"💻 系统配置: {system_specs['cpu_cores']}核心 CPU @ {system_specs['cpu_freq_ghz']:.1f}GHz, {system_specs['memory_gb']:.1f}GB 内存")
    
    # 检查Ollama服务是否可用
    models = assistant.list_available_models()
    if not models:
        print("❌ 无法连接到Ollama服务或没有安装模型")
        print("请确保Ollama正在运行并已安装至少一个模型")
        return
    
    # 显示可用模型和预估初始化时间
    mode_text = "快速模式" if quick_mode else "标准模式"
    print(f"\n📋 可用的AI模型 ({mode_text}):")
    for i, model in enumerate(models, 1):
        model_size = estimate_model_size(model['name'])
        init_time = estimate_init_time(system_specs, model_size, quick_mode)
        print(f"  {i}. {model['name']} (约{model_size:.1f}GB, 预估初始化时间: {init_time:.1f}秒)")
    
    # 选择模型
    selected_model = None
    estimated_init_time = 8.0
    
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
    
    # 计算选中模型的预估初始化时间
    model_size = estimate_model_size(selected_model)
    estimated_init_time = estimate_init_time(system_specs, model_size, quick_mode)
    
    mode_text = "快速模式" if quick_mode else "标准模式"
    print(f"✅ 已选择模型: {selected_model} ({mode_text})")
    print(f"📊 模型信息: 约{model_size:.1f}GB, 预估初始化时间: {estimated_init_time:.1f}秒")
    
    # 初始化AI模型（预热）
    mode_text = "快速" if quick_mode else "标准"
    print(f"\n🔄 正在{mode_text}初始化AI模型，预计需要 {estimated_init_time:.1f} 秒...")
    import time
    import threading
    start_time = time.time()
    
    # 动画效果相关变量
    animation_running = True
    animation_chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    
    if quick_mode:
        animation_messages = [
            "⚡ 快速启动中",
            "🔧 简化配置加载",
            "🎯 优化响应速度",
            "✨ 准备智能助手"
        ]
    else:
        animation_messages = [
            "🧠 正在唤醒AI大脑",
            "📚 正在加载知识库",
            "🔧 正在配置系统功能",
            "🎯 正在优化响应速度",
            "✨ 正在准备智能助手"
        ]
    
    def show_loading_animation():
        """显示加载动画"""
        char_index = 0
        message_index = 0
        message_counter = 0
        
        while animation_running:
            # 每隔一定时间切换消息
            if message_counter % 15 == 0:  # 每1.5秒切换一次消息
                current_message = animation_messages[message_index % len(animation_messages)]
                message_index += 1
            
            # 显示动画字符和消息
            print(f"\r   {animation_chars[char_index]} {current_message}{'.' * (message_counter % 4)}", end="", flush=True)
            
            char_index = (char_index + 1) % len(animation_chars)
            message_counter += 1
            time.sleep(0.1)
    
    # 启动动画线程
    animation_thread = threading.Thread(target=show_loading_animation, daemon=True)
    animation_thread.start()
    
    try:
        # 发送一个包含系统提示词的初始化消息来真正预热模型
        init_message = "系统初始化测试，请简短回复确认你已准备好" if quick_mode else "系统初始化测试，请简短回复确认你已准备好协助用户"
        init_response = assistant.ollama_client.chat(
            model=selected_model,
            messages=[{"role": "user", "content": init_message}],
            system_prompt=assistant.system_prompt  # 使用对应模式的系统提示词
        )
        
        # 停止动画
        animation_running = False
        time.sleep(0.2)  # 等待动画线程结束
        print("\r" + " " * 60 + "\r", end="")  # 清除动画行
        
        end_time = time.time()
        init_duration = end_time - start_time
        
        # 确保收到了回复
        # 确保收到了回复
        if init_response:
            # 比较实际时间与预估时间 - 提高精度判断
            time_diff = init_duration - estimated_init_time
            if abs(time_diff) <= 1.5:
                time_status = "✅ 预估准确"
            elif time_diff > 1.5:
                time_status = f"⏰ 比预估慢 {time_diff:.1f}秒"
            else:
                time_status = f"⚡ 比预估快 {abs(time_diff):.1f}秒"
            
            mode_text = "快速模式" if quick_mode else "标准模式"
            print(f"✅ AI模型初始化完成！({mode_text}, 实际耗时: {init_duration:.1f}秒, {time_status})")
            if len(init_response) > 100:
                print(f"   模型回复: {init_response[:80]}...")
            else:
                print(f"   模型回复: {init_response}")
        else:
            print("⚠️ 模型初始化可能未完全成功，但仍可正常使用")
            
        # 清空初始化对话，避免影响后续对话
        assistant.conversation_history = []
            
    except Exception as e:
        # 停止动画
        animation_running = False
        time.sleep(0.2)  # 等待动画线程结束
        print("\r" + " " * 60 + "\r", end="")  # 清除动画行
        
        end_time = time.time()
        init_duration = end_time - start_time
        print(f"⚠️ 模型初始化失败(耗时: {init_duration:.1f}秒)，但仍可正常使用: {e}")
    
    print("\n🎯 AI桌面助手已就绪！")
    print("\n🎯 AI桌面助手已就绪！")
    if quick_mode:
        print("⚡ 快速模式: 启动速度优化，功能完整可用")
    else:
        print("🔧 标准模式: 完整功能，详细任务识别")
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
