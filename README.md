# 🤖 LLM 项目重构助手

一个基于大语言模型（LLM）自动分析和重构项目结构的智能工具。  
它能扫描你的项目文件，理解代码功能，然后重新组织目录、重命名文件、修正导入路径，并生成新的项目结构，让你的代码库更加清晰、模块化，并自动推送至您的 Github 远程仓库（可选）。

## ✨ 特性

- **智能分析**：将代码分批发送给 LLM，让模型理解每个文件的功能。
- **自动重构**：
  - 重命名文件（英文小写 + 下划线/连字符，保留编号）
  - 重新组织目录（按功能模块分组，如 `utils/`、`models/`、`api/`）
  - 自动修正代码中的导入/引用路径
  - 可选删除无用文件，生成 `README.md`、`requirements.txt` 等新文件
- **分批处理**：避免上下文过长，自动切分文件，支持大项目。
- **灵活配置**：支持自定义 API 端点、模型、文件类型、大小限制等。
- **安全重建**：将重构结果输出到新目录，不破坏原项目。

## 🛠️ 安装

1. 克隆本仓库：
   ```bash
   git clone https://github.com/SchrodingerJia/LLM-Project-Reorganizer.git
   cd LLM-Project-Reorganizer
   ```

2. 安装依赖：
   ```bash
   pip install -r requirements.txt
   ```
   依赖包括：
   - `openai`（LLM 接口）
   - `python-dotenv`（环境变量管理）

## ⚙️ 配置

### 1. 创建 `.env` 文件
在项目根目录下创建 `.env` 文件，填入你的 API 信息（以 DeepSeek 为例）：
```
OPENAI_API_KEY=your_api_key_here
BASE_URL=https://api.deepseek.com/v1
```
如果你使用其他兼容 OpenAI 的 API，请修改 `BASE_URL` 为对应地址。

### 2. 修改 `main.py` 中的用户配置
打开 `main.py`，找到以下部分并填写：
```python
config = Config(
    source_dir=r"YOUR_SOURCE_PROJECT_PATH",  # 待重构的项目路径
    target_dir=r"YOUR_TARGET_PROJECT_PATH",  # 重构后输出的路径
    base_url=os.getenv("BASE_URL"),          # 从 .env 读取
    api_key=os.getenv("OPENAI_API_KEY"),     # 从 .env 读取
    model="deepseek-chat",                   # 可更换模型
    github_url=''   # 填写则直接推送到 GitHub, 否则请留空
)
```
然后在 `your_requirement` 变量中描述你的项目背景和重构需求（参考已有注释）。

若您需要同步到 GitHub，请确保：
- 已安装 `git`，并配置好用户名和邮箱。
- 在 `main.py` 中填写 `github_url`，如 `https://github.com/YOUR_NAME/YOUR_REPO.git` （最好为空仓库，创建时不添加任何文件如 `README.md`、`.gitignore`、`LICENSE`）。
- 确保本地有 `git` 权限，或使用 SSH Key 推送。

**请谨慎选择直接推送，LLM有概率犯傻，建议推送前先人工复核**

### 3. 可选参数调整
在 `recognizer.py` 的 `Config` 类中可以调整以下高级参数：
- `max_context_files`：每批最多提交的文件数（必须为偶数）
- `max_chat_chars`：每批提交的字符数上限
- `max_file_size`：单个文件允许的最大大小（过大则截断）
- `code_extensions` / `aux_extensions`：识别代码文件和辅助文件的扩展名
- `skip_extensions`：跳过的文件/文件夹（如 `.pyc`, `__pycache__`）

## 🚀 使用方法

1. 确保配置正确，且原项目路径存在。
2. 在终端运行：
   ```bash
   python main.py
   ```
3. 程序会：
   - 扫描源项目，分类文件
   - 分批调用 LLM，分析并生成重构方案
   - 将重构结果保存到 `reorg_result.json`
   - 根据结果在目标目录重建新项目
   - （可选）将您的项目推送至指定 Github 仓库

4. 查看输出目录，检查重构后的项目。

## 🔍 工作原理

1. **文件扫描**  
   `FileManager` 遍历源目录，根据扩展名将文件分为 `code`、`aux`、`other` 三类。

2. **分批调用 LLM**  
   `LLMReorganizer` 将文件按大小排序，并分批提交给 LLM。每批包含前后各半的文件，以保持上下文均衡。  
   提示词要求 LLM 输出严格的 JSON 格式，包含：
   - `new_structure`：文件重命名映射
   - `modifications`：需要修改的行内容
   - `new_files`：新增的文件（如 README.md）

3. **合并结果**  
   多批返回的结果被合并到最终的重构方案中。

4. **项目重建**  
   `ProjectBuilder` 根据方案：
   - 复制未修改的文件
   - 创建新结构的文件（修改或仅重命名）
   - 生成新文件（如 README）

## ⚠️ 注意事项

- **API 费用**：调用 LLM 会产生费用，请根据项目大小评估。
- **分批策略**：若项目极大，可能需要调整 `max_context_files` 和 `max_chat_chars` 以避免超出模型上下文窗口。文件较大时，LLM响应较慢，程序配置有流式输出，请耐心等待。
- **文件安全**：工具默认不会删除原项目文件，重建输出到新目录。但 `deleted_files` 仅在重建时**不复制**原文件，不会真正删除原文件。
- **代码修改**：LLM 可能无法完美修正所有导入路径，建议重建后人工检查。
- **隐私保护**：确保你的 API 密钥安全，不要在公开仓库中提交 `.env` 文件。

## 📄 许可证

MIT License

---

欢迎提交 Issue 和 PR，一起改进这个智能重构工具！

## 📝 优化方向

- **文件上传**：优化文件内容筛选。
- **提示词优化**：少部分情况下LLM尝试输出完整代码块，待解决。