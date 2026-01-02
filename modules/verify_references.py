import re
import logging
import requests

logger = logging.getLogger(__name__)

def extract_search_query_with_ai(ref_text, api_key, api_base):
    """
    使用DeepSeek API从引用文本中智能提取搜索查询
    """
    try:
        # 构建提示词，让AI提取最合适的搜索关键词
        prompt = f"""
        请从以下学术引用文本中提取最适合用于论文搜索的关键信息。只需要返回最相关的论文标题或核心关键词，不要解释。

        引用文本："{ref_text}"

        请提取：
        1. 论文标题（最重要的搜索关键词）
        2. 如果有明显的独特短语，也一并提取
        
        只需返回提取的内容，不要额外说明。
        """

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {
                    "role": "system", 
                    "content": "你是一个学术助手，专门从引用文本中提取论文搜索关键词。请直接返回最相关的搜索词，不要解释。"
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "max_tokens": 100,
            "temperature": 0.1
        }

        response = requests.post(f"{api_base}/chat/completions", headers=headers, json=payload, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            search_query = result['choices'][0]['message']['content'].strip()
            
            # 清理AI返回的内容，移除可能的引号等
            search_query = re.sub(r'^["\']|["\']$', '', search_query)
            
            logger.info(f"AI提取的搜索词: {search_query}")
            return search_query
        else:
            logger.error(f"DeepSeek API错误: {response.status_code}")
            return None
            
    except Exception as e:
        logger.error(f"AI提取搜索词错误: {str(e)}")
        return None

def smart_extract_search_query(ref_text, api_key, api_base):
    """
    智能提取搜索查询：优先使用AI，失败时使用规则备选
    """
    # 首先尝试AI提取
    ai_query = extract_search_query_with_ai(ref_text, api_key, api_base)
    
    if ai_query and len(ai_query) > 10:  # 确保查询有足够内容
        return ai_query
    
    # AI提取失败时使用规则备选
    return rule_based_fallback(ref_text)

def rule_based_fallback(ref_text):
    """
    规则备选方法（当AI不可用时使用）
    """
    try:
        # 方法1: 提取引号内的内容（通常是标题）
        quoted_content = re.findall(r'["「]([^"」]+)["」]', ref_text)
        if quoted_content:
            for content in quoted_content:
                if len(content) > 15:  # 确保是合理的标题长度
                    return content
        
        # 方法2: 提取明显的论文标题特征（首字母大写的连续单词）
        title_pattern = r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){2,})\b'
        title_matches = re.findall(title_pattern, ref_text)
        if title_matches:
            # 选择最长的匹配作为标题
            longest_title = max(title_matches, key=len)
            if len(longest_title) > 20:
                return longest_title
        
        # 方法3: 提取作者+年份
        author_year_match = re.search(r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*(?:\s+et al\.)?)[,\s]+(\d{4})', ref_text)
        if author_year_match:
            authors = author_year_match.group(1)
            year = author_year_match.group(2)
            return f"{authors} {year}"
        
        # 方法4: 提取关键词短语
        # 寻找包含重要学术词汇的短语
        academic_indicators = ['learning', 'network', 'model', 'algorithm', 'system', 'analysis', 'detection']
        words = re.findall(r'\b([A-Za-z]+\s+[A-Za-z]+\s+[A-Za-z]+)\b', ref_text)
        for phrase in words:
            phrase_lower = phrase.lower()
            if any(indicator in phrase_lower for indicator in academic_indicators):
                if len(phrase) > 15:
                    return phrase
        
        # 最后备选：返回前60个字符
        return ref_text[:60].replace('\n', ' ').strip()
        
    except Exception as e:
        logger.error(f"规则备选方法错误: {str(e)}")
        return ref_text[:50]

def search_openalex(query, max_results=3):
    """
    使用提取的查询词搜索OpenAlex
    """
    try:
        url = "https://api.openalex.org/works"
        params = {
            'search': query,
            'per_page': max_results,
            'select': 'id,doi,title,authorships,publication_year,primary_location,cited_by_count,abstract_inverted_index,biblio'
        }
        
        headers = {
            'User-Agent': 'PaperLens-Academic-Tool/1.0 (mailto:your-email@example.com)',
            'Accept': 'application/json'
        }
        
        response = requests.get(url, params=params, headers=headers, timeout=15)
        
        if response.status_code == 200:
            result = response.json()
            # 转换OpenAlex格式为统一格式
            papers = []
            for work in result.get('results', []):
                paper = convert_openalex_to_standard(work)
                papers.append(paper)
            return papers
        else:
            logger.error(f"OpenAlex搜索失败: {response.status_code}")
            return []
            
    except Exception as e:
        logger.error(f"搜索OpenAlex错误: {str(e)}")
        return []


def convert_openalex_to_standard(work):
    """
    将OpenAlex返回的数据格式转换为标准格式
    """
    # 提取作者信息
    authors = []
    for authorship in work.get('authorships', []):
        author_info = authorship.get('author', {})
        if author_info:
            authors.append({
                'name': author_info.get('display_name', ''),
                'authorId': author_info.get('id', '')
            })
    
    # 提取URL（优先使用DOI，其次使用OpenAlex链接）
    url = None
    doi = work.get('doi')
    if doi:
        url = doi  # DOI已经是完整URL格式
    else:
        # 使用OpenAlex ID构建URL
        openalex_id = work.get('id', '')
        if openalex_id:
            url = openalex_id.replace('https://openalex.org/', 'https://openalex.org/works/')
    
    # 提取venue信息
    venue = ''
    primary_location = work.get('primary_location', {})
    if primary_location:
        source = primary_location.get('source', {})
        if source:
            venue = source.get('display_name', '')
    
    # 还原abstract（OpenAlex使用倒排索引存储）
    abstract = reconstruct_abstract(work.get('abstract_inverted_index'))
    
    # 提取paperId（从OpenAlex ID中提取）
    openalex_id = work.get('id', '')
    paper_id = openalex_id.replace('https://openalex.org/', '') if openalex_id else ''
    
    return {
        'paperId': paper_id,
        'title': work.get('title', ''),
        'authors': authors,
        'year': work.get('publication_year'),
        'url': url,
        'abstract': abstract,
        'citationCount': work.get('cited_by_count', 0),
        'venue': venue,
        'doi': doi,
        'referenceCount': work.get('biblio', {}).get('reference_count') if work.get('biblio') else None
    }


def reconstruct_abstract(inverted_index):
    """
    从OpenAlex的倒排索引重建摘要文本
    """
    if not inverted_index:
        return ''
    
    try:
        # 创建位置到词的映射
        position_word_map = {}
        for word, positions in inverted_index.items():
            for pos in positions:
                position_word_map[pos] = word
        
        # 按位置排序并重建文本
        if position_word_map:
            max_pos = max(position_word_map.keys())
            words = [position_word_map.get(i, '') for i in range(max_pos + 1)]
            return ' '.join(words)
        return ''
    except Exception as e:
        logger.error(f"重建摘要错误: {str(e)}")
        return ''


def calculate_ai_enhanced_match_score(ref_text, paper):
    """
    使用AI增强的匹配度计算
    """
    try:
        # 基础匹配分数
        base_score = calculate_basic_match_score(ref_text, paper)
        
        # 如果基础分数足够高，直接返回
        if base_score > 0.7:
            return base_score
        
        # 对于边缘情况，可以进一步使用AI进行精细匹配
        # 这里先实现基础版本，后续可以增强
        
        return base_score
        
    except Exception as e:
        logger.error(f"计算匹配度错误: {str(e)}")
        return 0


def calculate_basic_match_score(ref_text, paper):
    """
    基础匹配度计算（基于规则）
    """
    score = 0
    paper_title = paper.get('title', '').lower()
    paper_authors = ' '.join([a.get('name', '').lower() for a in paper.get('authors', [])])
    paper_year = str(paper.get('year', ''))
    
    ref_text_lower = ref_text.lower()
    
    # 1. 标题关键词匹配
    if paper_title:
        title_words = set(re.findall(r'\b[a-z]{4,}\b', paper_title))
        ref_words = set(re.findall(r'\b[a-z]{4,}\b', ref_text_lower))
        
        common_words = title_words.intersection(ref_words)
        if title_words:
            title_score = len(common_words) / len(title_words)
            score += title_score * 0.5  # 提高标题权重
    
    # 2. 作者匹配
    if paper_authors:
        author_last_names = []
        for author in paper.get('authors', [])[:2]:
            name = author.get('name', '')
            if name:
                last_name = name.split()[-1].lower()
                author_last_names.append(last_name)
        
        author_match_count = 0
        for last_name in author_last_names:
            if last_name in ref_text_lower:
                author_match_count += 1
        
        if author_last_names:
            author_score = author_match_count / len(author_last_names)
            score += author_score * 0.3
    
    # 3. 年份匹配
    if paper_year and paper_year in ref_text:
        score += 0.2
    
    return min(score, 1.0)


def find_best_match(ref_text, papers):
    """
    在搜索结果中找到最佳匹配
    """
    if not papers:
        return {'paper': None, 'score': 0}
    
    best_score = 0
    best_paper = papers[0]
    
    for paper in papers:
        score = calculate_ai_enhanced_match_score(ref_text, paper)
        if score > best_score:
            best_score = score
            best_paper = paper
    
    # 确保论文有可访问的URL
    if best_paper and not best_paper.get('url'):
        # 如果没有URL，尝试构建一个
        if best_paper.get('paperId'):
            best_paper['url'] = f"https://openalex.org/{best_paper['paperId']}"
        else:
            # 使用OpenAlex搜索链接作为备选
            title_encoded = requests.utils.quote(best_paper.get('title', ''))
            best_paper['url'] = f"https://openalex.org/works?search={title_encoded}"
    
    return {'paper': best_paper, 'score': best_score}

def get_fallback_reference_verification(ref_text):
    """
    备用的引用验证数据
    """
    return {
        "found": False,
        "message": "验证服务暂时不可用",
        "fallback_used": True,
        "reference_preview": ref_text[:100] + "..." if len(ref_text) > 100 else ref_text,
        "suggestion": "请手动在学术数据库中验证此引用"
    }