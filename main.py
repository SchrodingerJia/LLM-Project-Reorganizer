import logging
import os
import json
from recognizer import Config, FileManager, LLMReorganizer, ProjectBuilder
from uploader import GitHubPusher

def main():
    # ============================
    # 🛠️ 用户配置（请按需修改）
    # ============================
    config = Config(
        source_dir=r"YOUR_SOURCE_PROJECT_PATH", # 源项目路径
        target_dir=r"YOUR_TARGET_PROJECT_PATH", # 目标项目路径
        base_url=os.getenv("BASE_URL"),         # 从 .env 读取
        api_key=os.getenv("OPENAI_API_KEY"),    # 从 .env 读取
        model="deepseek-chat",                  # LLM 模型
        github_url=''   # 填写则直接推送到 GitHub, 否则请留空（谨慎选择，LLM有概率犯傻，建议先人工复核）
    )
    # 简述您的项目及更多需求，便于 LLM 重构项目，以下是参考提示。
    your_requirement = """
这是一个XXX项目，请按照以下要求重构项目：
1. 【项目背景】；
2. 【匿名化提示】；
3. 【临时文件删除】；
4. 【其他需求】。
    """
    # ============================
    # 设置日志
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    # ============================
    # 🚀 执行流程
    # ============================
    fm = FileManager(config)
    llm = LLMReorganizer(config)
    builder = ProjectBuilder(config, fm)
    # 1. 扫描文件
    files = fm.scan_files()
    # 2. 用户需求（可替换为输入）
    user_request = your_requirement
    # 3. LLM 重构
    reorg_result = llm.reorganize_project(user_request, files, fm)
    # 4. 保存重构结果
    with open("reorg_result.json", "w", encoding="utf-8") as f:
        json.dump(reorg_result, f, indent=4, ensure_ascii=False)
    # 5. 构建新项目
    builder.build_project(reorg_result)
    print("\n🎉 项目重构完成！")
    print(f"新项目位于: {config.target_dir}")
    # 6. 推送到 GitHub
    # 注意：请确保您已创建好一个 GitHub 仓库，并配置好 SSH Key
    if config.github_url:
        print("开始推送至 GitHub...")
        pusher = GitHubPusher(config.github_url, config.target_dir)
        pusher.push()
    
if __name__ == "__main__":
    main()