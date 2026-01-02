import re

def extract_github_urls(text):
    """
    从论文文本中提取 GitHub 网址
    """
    github_urls = []
    
    # 匹配各种 GitHub URL 格式
    patterns = [
        # 标准 GitHub 仓库链接
        r'https?://github\.com/[a-zA-Z0-9_-]+/[a-zA-Z0-9_.-]+',
        # GitHub Gist 链接
        r'https?://gist\.github\.com/[a-zA-Z0-9_-]+/[a-zA-Z0-9]+',
        # GitHub Pages 链接
        r'https?://[a-zA-Z0-9_-]+\.github\.io/[a-zA-Z0-9_.-]*',
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            # 清理链接：移除换行符和多余空格
            cleaned_url = re.sub(r'\s+', '', match)
            # 移除末尾的标点符号
            cleaned_url = re.sub(r'[。，；：、\)\]\}\.]+$', '', cleaned_url)
            if cleaned_url and cleaned_url not in github_urls:
                github_urls.append(cleaned_url)
    
    # 去重并返回
    return list(set(github_urls))