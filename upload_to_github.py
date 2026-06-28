"""
自动化上传脚本：将黄金仪表盘代码上传到 GitHub
使用方法：
1. 在 GitHub 生成 Personal Access Token (https://github.com/settings/tokens)
2. 运行本脚本：python upload_to_github.py
3. 按提示输入用户名、邮箱和 token
4. 脚本会自动创建仓库并推送代码
"""
import os
import sys
import subprocess
import json
import requests

# ================== 配置 ==================
LOCAL_REPO_DIR = r"D:\1编程测试\gold_dashboard"
GITHUB_REPO_NAME = "gold-dashboard"
GITHUB_REPO_DESC = "黄金核心驱动因素监控仪表盘 - 基于Streamlit的黄金宏观指标可视化工具"
GITHUB_REPO_PUBLIC = True  # True=公开, False=私有

# ================== 颜色输出 ==================
class Color:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    END = '\033[0m'

def print_success(msg):
    print(f"{Color.GREEN}✅ {msg}{Color.END}")

def print_warning(msg):
    print(f"{Color.YELLOW}⚠️  {msg}{Color.END}")

def print_error(msg):
    print(f"{Color.RED}❌ {msg}{Color.END}")

def print_info(msg):
    print(f"{Color.BLUE}ℹ️  {msg}{Color.END}")

def print_step(step, msg):
    print(f"\n{Color.BLUE}=== 第{step}步：{msg} ==={Color.END}")

# ================== 主流程 ==================
def main():
    print("\n" + "="*60)
    print("🚀 黄金仪表盘 - GitHub 自动上传工具")
    print("="*60 + "\n")

    # ---------- 第1步：获取用户信息 ----------
    print_step(1, "输入 GitHub 账号信息")
    
    github_username = input("📝 请输入你的 GitHub 用户名: ").strip()
    github_email = input("📧 请输入你的 GitHub 邮箱: ").strip()
    github_token = input("🔑 请输入你的 GitHub Personal Access Token (ghp_xxx...): ").strip()
    
    if not github_username or not github_email or not github_token:
        print_error("所有字段都必须填写！")
        sys.exit(1)
    
    print_info(f"GitHub 用户名: {github_username}")
    print_info(f"GitHub 邮箱: {github_email}")
    print_info(f"Token 长度: {len(github_token)} 字符")
    
    # ---------- 第2步：配置 Git ----------
    print_step(2, "配置 Git 用户信息")
    
    try:
        subprocess.run(["git", "config", "--global", "user.name", github_username], check=True)
        subprocess.run(["git", "config", "--global", "user.email", github_email], check=True)
        print_success("Git 用户信息配置完成")
    except subprocess.CalledProcessError as e:
        print_error(f"Git 配置失败: {e}")
        sys.exit(1)
    
    # ---------- 第3步：创建 GitHub 仓库 ----------
    print_step(3, f"创建 GitHub 仓库: {GITHUB_REPO_NAME}")
    
    api_url = "https://api.github.com/user/repos"
    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github.v3+json"
    }
    payload = {
        "name": GITHUB_REPO_NAME,
        "description": GITHUB_REPO_DESC,
        "private": not GITHUB_REPO_PUBLIC,
        "auto_init": True  # 自动创建 README
    }
    
    print_info(f"正在创建仓库: {GITHUB_REPO_NAME}...")
    
    try:
        response = requests.post(api_url, headers=headers, json=payload, timeout=30)
        
        if response.status_code == 201:
            repo_data = response.json()
            repo_url = repo_data["html_url"]
            print_success(f"仓库创建成功！")
            print_info(f"仓库地址: <ADDRESS_REMOVED>")
        elif response.status_code == 422:
            # 仓库已存在
            print_warning(f"仓库 '{GITHUB_REPO_NAME}' 已存在，将直接使用")
            repo_url = f"https://github.com/{github_username}/{GITHUB_REPO_NAME}"
        else:
            print_error(f"创建仓库失败 (HTTP {response.status_code}): {response.text}")
            sys.exit(1)
    except Exception as e:
        print_error(f"创建仓库时发生错误: {e}")
        sys.exit(1)
    
    # ---------- 第4步：初始化本地仓库并提交 ----------
    print_step(4, "初始化本地 Git 仓库")
    
    os.chdir(LOCAL_REPO_DIR)
    print_info(f"当前目录: {os.getcwd()}")
    
    # 检查是否已经是 git 仓库
    if not os.path.exists(".git"):
        try:
            subprocess.run(["git", "init"], check=True)
            print_success("Git 仓库初始化完成")
        except subprocess.CalledProcessError as e:
            print_error(f"Git 初始化失败: {e}")
            sys.exit(1)
    else:
        print_warning("当前目录已经是 Git 仓库，跳过初始化")
    
    # 添加远程仓库
    remote_url = f"https://{github_username}:{github_token}@github.com/{github_username}/{GITHUB_REPO_NAME}.git"
    
    try:
        # 检查是否已经有 origin 远程
        result = subprocess.run(["git", "remote"], capture_output=True, text=True)
        if "origin" in result.stdout:
            subprocess.run(["git", "remote", "remove", "origin"], check=True)
            print_info("已移除旧的 origin 远程")
        
        subprocess.run(["git", "remote", "add", "origin", remote_url], check=True)
        print_success("远程仓库配置完成")
    except subprocess.CalledProcessError as e:
        print_error(f"配置远程仓库失败: {e}")
        sys.exit(1)
    
    # 拉取远程 README（如果仓库已存在）
    try:
        subprocess.run(["git", "pull", "origin", "main", "--allow-unrelated-histories"], 
                      capture_output=True, text=True)
        print_info("已拉取远程 README")
    except:
        try:
            subprocess.run(["git", "pull", "origin", "master", "--allow-unrelated-histories"], 
                          capture_output=True, text=True)
            print_info("已拉取远程 README (master 分支)")
        except:
            print_warning("无需拉取远程文件（可能是新仓库）")
    
    # 添加文件
    print_info("正在添加文件...")
    files_to_add = ["gold_app.py", "requirements.txt"]
    
    for file in files_to_add:
        if os.path.exists(file):
            subprocess.run(["git", "add", file], check=True)
            print_success(f"已添加: {file}")
        else:
            print_warning(f"文件不存在: {file}")
    
    # 提交
    print_info("正在提交代码...")
    try:
        result = subprocess.run(
            ["git", "commit", "-m", "Initial commit: 黄金仪表盘代码"],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            print_success("代码提交完成")
        else:
            if "nothing to commit" in result.stdout or "nothing to commit" in result.stderr:
                print_warning("没有需要提交的更改")
            else:
                print_error(f"提交失败: {result.stderr}")
                sys.exit(1)
    except subprocess.CalledProcessError as e:
        print_warning(f"提交步骤跳过: {e}")
    
    # ---------- 第5步：推送到 GitHub ----------
    print_step(5, "推送代码到 GitHub")
    
    # 确定分支名
    branch_name = "main"
    try:
        result = subprocess.run(["git", "branch", "--show-current"], 
                              capture_output=True, text=True, check=True)
        current_branch = result.stdout.strip()
        if current_branch:
            branch_name = current_branch
    except:
        branch_name = "main"
    
    print_info(f"当前分支: {branch_name}")
    print_info("正在推送代码（可能需要输入密码）...")
    
    try:
        # 尝试推送到 main 分支
        push_result = subprocess.run(
            ["git", "push", "-u", "origin", branch_name],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if push_result.returncode == 0:
            print_success("代码推送成功！")
        else:
            # 如果 main 失败，尝试 master
            print_warning("推送到 main 失败，尝试 master...")
            subprocess.run(["git", "branch", "-M", "master"], check=True)
            push_result = subprocess.run(
                ["git", "push", "-u", "origin", "master"],
                capture_output=True,
                text=True,
                timeout=60
            )
            if push_result.returncode == 0:
                print_success("代码推送成功（master 分支）！")
            else:
                print_error(f"推送失败: {push_result.stderr}")
                sys.exit(1)
    except subprocess.TimeoutExpired:
        print_error("推送超时，请检查网络连接")
        sys.exit(1)
    except Exception as e:
        print_error(f"推送时发生错误: {e}")
        sys.exit(1)
    
    # ---------- 完成 ----------
    print("\n" + "="*60)
    print_success("🎉 代码已成功上传到 GitHub！")
    print("="*60)
    print()
    print_info(f"仓库地址: {repo_url}")
    print_info(f"黄金仪表盘页面: {repo_url}/blob/main/gold_app.py")
    print()
    print_step("下一步", "部署到 Streamlit Community Cloud")
    print_info("1. 访问 https://share.streamlit.io")
    print_info("2. 使用 GitHub 账号登录")
    print_info(f"3. 选择仓库: {github_username}/{GITHUB_REPO_NAME}")
    print_info("4. 分支: main, 主文件: gold_app.py")
    print_info("5. 点击 Deploy 按钮")
    print()
    print_success("部署完成后，你会得到一个公网地址，可以分享给朋友！")
    print()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n操作已取消")
        sys.exit(0)
    except Exception as e:
        print_error(f"发生未知错误: {e}")
        sys.exit(1)
