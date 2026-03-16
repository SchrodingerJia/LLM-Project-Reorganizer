import os
import re
import shutil
import json
import logging
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
import openai
from dotenv import load_dotenv

# ============================
# 🛠️ 配置模块
# ============================
load_dotenv()

@dataclass
class Config:
    source_dir: str
    target_dir: str
    base_url: str
    api_key: str
    model: str
    github_url: str = ''
    max_context_files: int = 6  # 每次最多提交给LLM的文件数，必须为偶数
    max_chat_chars: int = 8000  # 每轮提交给LLM的代码文件字符数上限
    max_file_size: int = 100 * 1024  # 100KB，避免过大文件
    code_extensions: Tuple = ('.py', '.c', '.java', '.ipynb', '.js', '.cpp', '.h', '.cs', '.v', '.xdc', '.m')
    aux_extensions: Tuple = ('.json', '.csv', '.xlsx', '.txt', '.yaml', '.yml', '.md', '.xls')
    skip_extensions: Tuple = ('.pyc', '.log', '.tmp', '.DS_Store', '.git', '__pycache__', '.o', '.exe')
    source_extensions: Tuple = ('.docx', '.doc', '.pdf', '.zip', '.rar', '.pptx', '.ppt', '.png', '.jpg')
    skip_extensions = (*skip_extensions, *source_extensions)

    def __post_init__(self):
        if not self.api_key:
            raise ValueError("API key is required. Set OPENAI_API_KEY in .env or pass directly.")
        openai.api_key = self.api_key
        openai.base_url = self.base_url

# ============================
# 📁 文件系统工具
# ============================
class FileManager:
    ENCODINGS = ['utf-8', 'gbk', 'gb2312', 'gb18030', 'big5', 'latin-1']    # 支持的编码格式
    def __init__(self, config: Config):
        self.config = config
        self.logger = logging.getLogger(__name__)

    def scan_files(self) -> Dict[str, List[Path]]:
        """扫描源目录，按类型分类文件"""
        files = {
            'code': [],
            'aux': [],
            'other': []
        }
        for root, dirs, filenames in os.walk(self.config.source_dir):
            # 跳过隐藏/系统文件夹
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in self.config.skip_extensions]
            for filename in filenames:
                if any(filename.endswith(ext) for ext in self.config.skip_extensions):
                    continue
                filepath = Path(root) / filename
                if filename.endswith(self.config.code_extensions):
                    files['code'].append(filepath)
                elif filename.endswith(self.config.aux_extensions):
                    files['aux'].append(filepath)
                else:
                    files['other'].append(filepath)
        self.logger.info(f"Found {len(files['code'])} code files, {len(files['aux'])} aux files, {len(files['other'])} other files")
        return files
    
    def read_file_content(self, filepath: Path, nu: bool = False) -> Optional[str]:
        """安全读取文件内容，对大文件截断，并添加注释提示
        如果文件超过 max_file_size，则仅读取前 max_file_chars 字符，
        并在末尾添加注释：(large file: <size> bytes)
        nu: 是否标注行号
        """
        for encoding in self.ENCODINGS:
            try:
                with open(filepath, 'r', encoding=encoding) as f:
                    if filepath.suffix in ('.ipynb'):
                        lines = self._ipynb_lines(filepath)
                    else:
                        lines = f.readlines()

                    stripped_lines = []
                    file_size = 0
                    i = 0
                    for line in lines:
                        if line.strip():
                            content = f'line {i}:'+ line.rstrip() if nu else line.rstrip()
                            stripped_lines.append(content)
                            file_size += len(content.encode('utf-8'))
                            i += 1
                    if file_size > self.config.max_file_size:
                        self._truncate_large_files(stripped_lines, filepath.name)
                    return '\n'.join(stripped_lines)
            except UnicodeDecodeError:
                continue
        self.logger.warning(f"Error reading {filepath}: Unsupported encoding.")
        return None
        
    def write_file(self, filepath: Path, content: str):
        """安全写入文件，确保目录存在"""
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)

    def copy_file(self, src: Path, dst: Path):
        """复制文件，确保父目录存在"""
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    def _ipynb_lines(self, notebook_file: Path) -> List[str]:
        """Jupyter Notebook 文件提取内容"""
        with open(notebook_file, 'r', encoding='utf-8') as f:
            notebook = json.load(f)

        content = ''
        for cell in notebook['cells']:
            if cell['cell_type'] == 'code':
                source = cell['source']
                if not source:
                    continue
                # source 可能是字符串列表，也可能是单一字符串
                if isinstance(source, list):
                    source = ''.join(source)
                content += '```python\n'+source+'\n```\n'
            elif cell['cell_type'] == 'markdown':
                source = cell['source']
                if not source:
                    continue
                if isinstance(source, list):
                    source = ''.join(source)
                content += '```markdown\n'+source+'\n```\n'
        return content.split('\n')
    
    def _truncate_large_files(self, lines: List[str], filename: str) -> None:
        """大文件处理：截断"""
        total_size = 0
        i = 0
        while total_size < self.config.max_file_size:
            total_size += len(lines[i].encode('utf-8'))
            i += 1
        lines = lines[:i]
        hidden_size = len('\n'.join(lines[i:]).encode('utf-8'))
        lines.append(f"\n\n<!-- {hidden_size} bytes more -->")
        self.logger.info(f"Truncated {filename} to {len(lines)} lines")

# ============================
# 🧠 LLM 交互模块
# ============================
class LLMReorganizer:
    def __init__(self, config: Config):
        self.config = config
        self.client = openai.OpenAI(base_url=config.base_url, api_key=config.api_key)
        self.logger = logging.getLogger(__name__)

    def _build_prompt(self, project_structure: str, user_request: str, 
                      code_files: Dict[str, str], aux_files: Dict[str, str], 
                      results: Dict, final_flag: bool = False) -> str:
        """构建清晰的LLM提示词"""
        prompt = f"""
### 用户需求：
{user_request}

"""
        prompt += """
### 你的任务：
1. 重新命名提供了内容的文件，使其名称清晰表达功能，**禁止使用中文和空格**，使用英文小写+连字符/下划线且长度不宜过长（如：`data_loader.py`）。
2. 如果文件有编号（如 `1`, `v2`, `001`），请**保留编号**，并在编号后加 `-` 之后再添加功能简述，功能简述部分则必须使用下划线而不是连字符。
3. 重新组织项目目录结构，按功能模块分组（如 `utils/`, `models/`, `data/`, `api/` 等）。
4. 代码文件中若因路径更改导致导入/引用错误，请**同步修改代码中对应行的路径引用**（如 import, include, open() 路径等）`，但若没有，不要做修改。
5. 对于辅助文件（如 .json/.csv），若对理解项目至关重要，请保留并重命名；否则可建议删除或忽略。
6. 输出格式严格遵循如下要求：
(1) 使用Markdown代码块，以<```json>开头，以<```>结尾.
(2) 若文件**只需修改名称，内容无需修改**，只需填写new_structure字段，格式为：{"旧文件路径": "新文件路径"}，一对一，一对多时，额外文件放入新建文件中。对于需要删除或忽略的文件，可以通过避免在此处输出实现。
(3) (**尽量少输出这一项，禁止在此处输出完整代码**) 若文件内容需要局部修改，请按格式将内容输出到modifications字段中为：{"旧文件路径": [{"修改处的行号(从0开始)": "修改后的新行"}]}。
(4) (**所有完整代码在此输出**) 若有新建的文件，请将文件内容输出在new_files字段中，格式为：{"文件路径": "文件内容"}。

以下是一个输出示例：
```json
{
  "new_structure": {
    "src/utils/helper.py": "utils/data_processor.py"},
    "data/raw.csv": "data/input.csv"}
  },
  "modifications": {
    "src/utils/helper.py": [{"line 3": "modified_content_of_line_3"}]
  },
  "new_files": {"README.md": "README的内容"},
  "deleted_files": ["data/old_config.json"]
}
```
"""
        prompt += f"""
请确保 JSON 格式正确，路径是相对项目根目录 {os.path.basename(self.config.source_dir)} 的(不包含根本身)。不要输出任何其他内容。

### 项目结构（相对路径）：
{project_structure}

### 代码文件内容（请分析每个文件的功能）：
{self._format_files(code_files)}

### 可选辅助文件（仅在必要时参考）：
{self._format_files(aux_files, title="辅助文件")}
"""
        if results["new_structure"]:
            prompt += f'''\n当前处理结果如下，参考已处理的部分，给出原有基础上修改或新增的部分，保持一致的部分不要输出：\n{results}'''
        if final_flag:
            prompt += "\n\n**注意：** 这是最后一批文件，请完成所有修改并给出最终版README.md文件(最好使用中文完成，用于介绍这一项目，包括项目结构、功能、使用方法等)。必要时给出requirements.txt等文件。"
        else:
            prompt += "\n\n若你没有收到你是**最后一批文件**的提示，不要添加README。"
        return prompt

    def _format_files(self, files: Dict[str, str], title="代码文件") -> str:
        """格式化文件列表为字符串"""
        if not files:
            return "无"
        result = []
        for path, content in files.items():
            if title == "代码文件":
                result.append(f"## {path}\n{content}\n")
            else:
                content = content[:200] + "..." if len(content) > 200 else content
                result.append(f"## {path}\n{content}")
        return "\n".join(result)

    def _extract_json_response(self, response_text: str) -> Dict:
        """从LLM响应中提取JSON"""
        match = re.search(r'```json\s*({.*?})\s*```', response_text, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        else:
            # 尝试直接解析（若无代码块）
            try:
                return json.loads(response_text[response_text.index("{"):response_text.rindex("}")+1])
            except:
                raise ValueError(f"无法解析LLM响应为有效JSON: {response_text}...")

    def reorganize_project(self, user_request: str, files: Dict[str, List[Path]], fm: FileManager) -> Dict:
        """分批处理文件，调用LLM重构项目"""
        self.logger.info("开始分批处理文件以避免上下文过长...")

        # 分组：先处理代码文件，再处理辅助文件（按需）
        code_files = {str(f.relative_to(self.config.source_dir)): fm.read_file_content(f,nu=True) for f in files['code']}
        aux_files = {str(f.relative_to(self.config.source_dir)): fm.read_file_content(f,nu=True) for f in files['aux']}

        # 总文件大小
        total_code_chars = sum(len(v) for v in code_files.values())
        total_aux_chars = sum(len(v) for v in aux_files.values())
        max_files_nums = self.config.max_chat_chars//int((total_code_chars+total_aux_chars)/(len(code_files)+len(aux_files)))//2*2
        max_files_nums = max_files_nums if max_files_nums > 0 else 2
        max_files_nums = min(max_files_nums, self.config.max_context_files)

        # 按文件大小排序
        code_items = sorted(code_files.items(), key=lambda x: len(x[1]), reverse=True)
        aux_items = list(aux_files.items())

        # 切分为前后两部分
        code_items_front = code_items[:len(code_items)//2]
        code_items_back = code_items[len(code_items)//2:]
        code_items_back.reverse()

        # 构建项目结构
        project_structure = self._build_project_structure(files)

        all_results = {
            "new_structure": {},
            "modifications": {},
            "deleted_files": [],
            "new_files": {}
        }

        # 分批，每次处理 max_files_nums 个文件，为平衡考虑，前一半和后一半分别取 max_files_nums//2 个
        i_aux = 0
        batch_num = len(code_items_front)//(max_files_nums//2) + 1
        for i in range(0, max(len(code_items_front),1), max_files_nums//2):
            final_flag = i + max_files_nums//2 >= len(code_items_front)
            if final_flag:
                batch_code = code_items_front[i:] + code_items_back[i:]
                batch_aux = aux_items[i_aux:]
            else:
                batch_code = code_items_front[i:i+max_files_nums//2] + code_items_back[i:i+max_files_nums//2]
                batch_aux = aux_items[i_aux:i_aux+len(aux_items)//(len(code_items_front)//(max_files_nums//2)+1)]
            
            batch_code = {path: content for path, content in batch_code}
            batch_aux = {path: content for path, content in batch_aux}
            prompt = self._build_prompt(project_structure, user_request, batch_code, batch_aux, all_results, final_flag)

            self.logger.info(f"发送第 {i//(max_files_nums//2)+1}/{batch_num} 批 {len(batch_code)+len(batch_aux)} 个文件到LLM，长度{len(prompt)}")

            try:
                stream = self.client.chat.completions.create(
                    model=self.config.model,
                    messages=[
                        {"role": "system", "content": "你将完成一个项目重构任务，请严格按照要求输出JSON。"},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.2,
                    timeout=(len(prompt)//10000*10+10)*60,
                    stream=True
                )

                raw_response = ""
                for chunk in stream:
                    content = chunk.choices[0].delta.content
                    if content is not None:
                        raw_response += content
                        print(content, end="", flush=True)
                        
                result = self._extract_json_response(raw_response)

                # 合并结果
                all_results["new_structure"].update(result.get("new_structure", {}))
                all_results["modifications"].update(result.get("modifications", {}))
                all_results["new_files"].update(result.get("new_files", {}))
                all_results["deleted_files"] = list(set(all_results["deleted_files"] + result.get("deleted_files", [])))
                
            except Exception as e:
                self.logger.error(f"LLM处理批次失败: {e}")
                raise

        return all_results

    def _build_project_structure(self, files: Dict[str, List[Path]]) -> str:
        """构建项目树状结构字符串"""
        # 根目录名称（取最后一级）
        root_name = os.path.basename(self.config.source_dir)
        lines = [root_name + "\\"]
        valid_files = files['code'] + files['aux'] + files['other']

        def _build(current_path, prefix):
            """递归构建子项"""
            try:
                entries = os.listdir(current_path)
            except PermissionError:
                lines.append(prefix + "[权限不足]")
                return

            # 分离目录和文件，分别排序
            dirs = []
            files = []
            for entry in entries:
                full = os.path.join(current_path, entry)
                if os.path.isdir(full):
                    dirs.append(entry)
                elif Path(full) in valid_files:
                    files.append(entry)
            dirs.sort()
            files.sort()
            sorted_entries = dirs + files  # 目录在前，文件在后

            for entry in sorted_entries:
                full = os.path.join(current_path, entry)
                is_dir = os.path.isdir(full)
                lines.append(prefix + entry + ("\\" if is_dir else ""))
                if is_dir:
                    _build(full, prefix + "  ")  # 递归子目录，缩进增加两个空格

        _build(self.config.source_dir, "  ")
        return "项目结构:\n"+"\n".join(lines)

# ============================
# 🔄 项目重建模块
# ============================
class ProjectBuilder:
    def __init__(self, config: Config, fm: FileManager):
        self.config = config
        self.fm = fm
        self.logger = logging.getLogger(__name__)

    def load_results(self, result_path: str) -> Dict:
        """加载重构结果"""
        with open(result_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def build_project(self, reorganization_result: Dict):
        """根据LLM输出重建项目"""
        final_results = {
            "new_structure": {},
            "modifications": {},
            "deleted_files": [],
            "new_files": {}
        }
        for old_path, new_path in reorganization_result["new_structure"].items():
            if old_path.startswith(os.path.basename(self.config.source_dir)):
                old_path = old_path[len(os.path.basename(self.config.source_dir)) + 1:]
            final_results["new_structure"][Path(old_path)] = Path(new_path)
        for old_path, modification in reorganization_result["modifications"].items():
            if old_path.startswith(os.path.basename(self.config.source_dir)):
                old_path = old_path[len(os.path.basename(self.config.source_dir)) + 1:]
            final_results["modifications"][Path(old_path)] = modification
        final_results["deleted_files"] = [Path(f) for f in reorganization_result["deleted_files"]]
        final_results["new_files"] = {Path(new_path): content for new_path, content in reorganization_result["new_files"].items()}
        reorganization_result = final_results

        source_root = Path(self.config.source_dir)
        target_root = Path(self.config.target_dir)
        target_root.mkdir(parents=True, exist_ok=True)

        # 1. 删除目标文件夹中旧文件（可选，谨慎）
        # shutil.rmtree(target_root, ignore_errors=True)
        # target_root.mkdir()

        # 2. 复制未修改的文件（other）
        files_to_skip = set()
        for old_path in reorganization_result["new_structure"].keys():
            files_to_skip.add(old_path)
        for file in reorganization_result["deleted_files"]:
            files_to_skip.add(file)

        # 复制未参与重构的文件
        for f in Path(self.config.source_dir).rglob("*"):
            if f.is_file():
                rel_path = f.relative_to(source_root)
                if rel_path not in files_to_skip and f.suffix not in self.config.skip_extensions:
                    dst = target_root / rel_path
                    self.fm.copy_file(f, dst)
                    self.logger.info(f"Copied untouched file: {rel_path}")

        # 3. 创建新结构的文件
        for old_path, new_path in reorganization_result["new_structure"].items():
            old_full = source_root / old_path
            new_full = target_root / new_path

            old_flag = old_path in reorganization_result["modifications"]
            new_flag = new_path in reorganization_result["modifications"]
            if old_flag or new_flag:
                # 修改内容
                content = self.fm.read_file_content(old_full).splitlines()
                for modification in reorganization_result["modifications"][old_path if old_flag else new_path]:
                    for line_num, new_content in modification.items():
                        try:
                            line = int(line_num.replace('line', '')) if type(line_num) == str else line_num
                            content[line] = new_content
                        except ValueError:
                            self.logger.error(f"Invalid line number in {old_path}: {line_num}. Modification skipped.")
                self.fm.write_file(new_full, '\n'.join(content))
                self.logger.info(f"Updated: {new_path}")
            else:
                # 仅重命名，内容不变
                if old_full.exists():
                    self.fm.copy_file(old_full, new_full)
                    self.logger.info(f"Renamed file: {old_path} -> {new_path}")

        # 4. 删除文件（可选，根据需求）
        # for del_file in reorganization_result["deleted_files"]:
            # 删除原文件（如果存在）
            # del_path = target_root / Path(del_file)
            # if del_path.exists():
                # del_path.unlink()
                # self.logger.info(f"Deleted: {del_file}")

        # 5. 创建新文件（如 README.md, requirements.txt）
        for file_path, content in reorganization_result["new_files"].items():
            new_full = target_root / file_path
            self.fm.write_file(new_full, content)
            self.logger.info(f"Created new file: {file_path}")

        self.logger.info(f"✅ 项目已成功重建到: {target_root}")