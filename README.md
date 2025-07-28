# AI桌面助手

基于Python和Ollama的本地AI桌面助手，可以与本地AI模型进行对话并执行特定任务。

## 功能特性

- 🤖 与本地Ollama模型进行自然语言对话
- 📱 自动识别用户指令并执行特定任务
- 🚀 支持打开各种应用程序
- 📊 获取系统信息
- 📁 浏览目录内容
- 🔧 可扩展的任务执行框架

## 系统要求

- Python 3.7+
- Ollama (需要预先安装并运行)
- Windows/Linux/macOS

## 安装步骤

### 1. 安装Ollama

首先需要安装Ollama并下载至少一个模型：

```bash
# 访问 https://ollama.ai 下载并安装Ollama

# 下载一个模型（例如llama2）
ollama pull llama2
```

### 2. 安装Python依赖

```bash
# 克隆或下载项目文件
# 安装依赖
pip install -r requirements.txt
```

### 3. 启动助手

#### Windows用户
双击运行 `start_assistant.bat`

#### Linux/Mac用户
```bash
python ai_desktop_assistant.py
```

## 使用方法

1. 启动程序后，选择要使用的AI模型
2. 开始与AI助手对话
3. AI会自动识别你的指令并执行相应任务

### 支持的指令示例

- **打开应用**: "帮我打开记事本" / "启动计算器"
- **系统信息**: "查看系统信息" / "显示电脑配置"
- **文件浏览**: "列出当前目录的文件" / "查看桌面文件"

### 任务标记格式

AI助手使用特殊标记来触发任务：

- `[TASK:OPEN_APP]应用名称[/TASK]` - 打开应用程序
- `[TASK:SYSTEM_INFO][/TASK]` - 获取系统信息
- `[TASK:LIST_DIR]目录路径[/TASK]` - 列出目录内容

## 配置文件

编辑 `config.json` 可以自定义：

- Ollama服务地址
- 常用应用程序映射
- 系统提示词模板

## 扩展功能

要添加新的任务类型，需要：

1. 在 `TaskExecutor` 类中添加新的静态方法
2. 在 `_parse_and_execute_tasks` 方法中添加相应的解析逻辑
3. 更新系统提示词以包含新的任务格式

## 故障排除

### 常见问题

1. **无法连接到Ollama服务**
   - 确保Ollama正在运行：`ollama serve`
   - 检查端口11434是否被占用

2. **没有可用模型**
   - 下载模型：`ollama pull llama2`
   - 查看已安装模型：`ollama list`

3. **应用程序无法打开**
   - 检查应用程序名称是否正确
   - 在config.json中添加自定义应用程序映射

## 开发计划

- [ ] 添加更多任务类型（文件操作、网络请求等）
- [ ] 支持语音输入输出
- [ ] 图形用户界面
- [ ] 插件系统
- [ ] 多模型并行对话

## 许可证

MIT License

## 贡献

欢迎提交Issue和Pull Request来改进这个项目！