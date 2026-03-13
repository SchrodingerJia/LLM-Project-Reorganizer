import subprocess
import os
import sys

class GitHubPusher:
    """将本地项目推送到GitHub仓库的类"""

    def __init__(self, github_url, local_path, token=None):
        """
        初始化推送器
        :param github_url: GitHub仓库URL（如 https://github.com/username/repo.git 或 git@github.com:username/repo.git）
        :param local_path: 本地项目路径（绝对或相对路径）
        :param token: GitHub Personal Access Token（仅对HTTPS URL有效，可选）
        """
        self.github_url = github_url
        self.local_path = os.path.abspath(local_path)  # 转换为绝对路径
        self.token = token

        # 检查本地路径是否存在
        if not os.path.isdir(self.local_path):
            raise ValueError(f"本地路径 '{self.local_path}' 不存在或不是一个目录。")

    def _run_git_command(self, cmd, check=True):
        """
        执行git命令，成功时返回输出，失败时根据check参数决定是否抛出异常
        :param cmd: 命令列表，如 ['git', 'status']
        :param check: 是否检查命令成功，True则失败时抛出异常并退出程序，False则返回None
        :return: 命令输出（去除首尾空白）或None
        """
        try:
            result = subprocess.run(
                cmd,
                cwd=self.local_path,
                capture_output=True,
                text=True,
                check=check,
                encoding='utf-8'
            )
            return result.stdout.strip() if result.stdout else None
        except subprocess.CalledProcessError as e:
            if check:
                print(f"❌ 命令执行失败: {' '.join(cmd)}")
                print(f"错误输出: {e.stderr}")
                sys.exit(1)
            else:
                return None
        except FileNotFoundError:
            print("❌ 未找到git命令，请确保git已安装并添加到系统PATH。")
            sys.exit(1)

    def _has_uncommitted_changes(self):
        """检查工作区是否有未提交的更改（包括未跟踪的文件）"""
        status = self._run_git_command(['git', 'status', '--porcelain'], check=False)
        return bool(status and status.strip())

    def _has_commits(self):
        """检查仓库是否有任何提交"""
        head = self._run_git_command(['git', 'rev-parse', 'HEAD'], check=False)
        return head is not None

    def _get_current_branch(self):
        """获取当前分支名"""
        branch = self._run_git_command(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], check=False)
        return branch if branch and branch != 'HEAD' else None

    def _has_remote_origin(self):
        """检查是否存在名为origin的远程仓库"""
        remote = self._run_git_command(['git', 'remote', 'get-url', 'origin'], check=False)
        return remote is not None

    def _add_remote_origin(self):
        """添加远程仓库origin，支持HTTPS Token嵌入"""
        url = self.github_url
        if self.token and url.startswith('https://'):
            parts = url.split('://')
            if len(parts) == 2:
                url = f"{parts[0]}://{self.token}@{parts[1]}"
                print("🔑 已使用Token嵌入URL进行认证。")
        self._run_git_command(['git', 'remote', 'add', 'origin', url])
        print("🔗 远程仓库origin已添加。")

    def push(self):
        """执行推送操作：根据仓库状态自动初始化、提交、拉取、推送"""
        # 检查是否已经是Git仓库
        is_repo = os.path.exists(os.path.join(self.local_path, '.git'))
        if is_repo:
            response = input("⚠️ 本地路径已经是一个Git仓库。是否继续？(y/n): ")
            if response.lower() != 'y':
                print("操作取消。")
                return

            # 已经是Git仓库的处理流程
            print("📂 检测到已存在的Git仓库，继续操作...")

            # 检查是否有未提交的更改
            if self._has_uncommitted_changes():
                print("❌ 工作区存在未提交的更改，请先提交或暂存后再运行脚本。")
                sys.exit(1)

            if self._has_remote_origin():
                print("🔗 检测到远程仓库origin，执行拉取和推送...")
                # 先拉取最新代码
                print("⬇️ 拉取远程变更...")
                pull_result = self._run_git_command(['git', 'pull', 'origin', 'HEAD'], check=False)
                if pull_result is None:
                    print("❌ git pull失败，请手动解决冲突后重试。")
                    sys.exit(1)
                # 推送到远程
                print("⬆️ 推送到远程仓库...")
                self._run_git_command(['git', 'push', 'origin', 'HEAD'])
            else:
                print("🔗 未检测到远程仓库origin，正在添加...")
                self._add_remote_origin()

                # 检查是否有任何提交（避免空仓库推送失败）
                if not self._has_commits():
                    print("📦 仓库暂无提交，正在添加并提交所有文件...")
                    self._run_git_command(['git', 'add', '.'])
                    self._run_git_command(['git', 'commit', '-m', 'Initial commit'])

                # 推送到远程
                print("⬆️ 推送到远程仓库...")
                self._run_git_command(['git', 'push', '-u', 'origin', 'HEAD'])
        else:
            # 非仓库：执行完整初始化流程
            print("🚀 初始化git仓库...")
            self._run_git_command(['git', 'init'])

            print("📦 添加所有文件...")
            self._run_git_command(['git', 'add', '.'])

            print("✍️ 提交初始版本...")
            self._run_git_command(['git', 'commit', '-m', 'Initial commit'])

            # 添加远程仓库
            self._add_remote_origin()

            # 推送到远程
            print("⬆️ 推送到远程仓库...")
            self._run_git_command(['git', 'push', '-u', 'origin', 'HEAD'])

        print("✅ 成功将本地项目推送到GitHub！")