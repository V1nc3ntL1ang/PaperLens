import requests
import logging
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity


logger = logging.getLogger(__name__)

# 全局加载模型（避免重复加载）
_embedding_model = None

def get_embedding_model():
    """懒加载嵌入模型"""
    global _embedding_model
    if _embedding_model is None:
        # 使用学术论文专用模型，或者通用模型
        try:
            _embedding_model = SentenceTransformer('allenai/specter2')
            logger.info("加载 SPECTER2 模型成功")
        except:
            # 备选：更轻量的模型
            _embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
            logger.info("加载 MiniLM 模型成功")
    return _embedding_model


def extract_paper_keywords(text, max_keywords=10):
    """
    从论文文本中提取关键词用于初步搜索
    """
    import re
    from collections import Counter
    
    # 学术停用词
    stop_words = {
        'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
        'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'been',
        'be', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
        'could', 'should', 'may', 'might', 'must', 'shall', 'can', 'need',
        'this', 'that', 'these', 'those', 'it', 'its', 'they', 'them', 'their',
        'we', 'our', 'you', 'your', 'he', 'she', 'his', 'her', 'which', 'who',
        'whom', 'what', 'where', 'when', 'why', 'how', 'all', 'each', 'every',
        'both', 'few', 'more', 'most', 'other', 'some', 'such', 'no', 'not',
        'only', 'same', 'so', 'than', 'too', 'very', 'just', 'also', 'now',
        'paper', 'study', 'research', 'method', 'results', 'conclusion',
        'introduction', 'abstract', 'figure', 'table', 'section', 'chapter',
        'however', 'therefore', 'thus', 'hence', 'moreover', 'furthermore',
        'although', 'though', 'while', 'whereas', 'because', 'since', 'unless',
        'proposed', 'propose', 'show', 'shows', 'shown', 'based', 'using', 'used'
    }
    
    # 提取单词
    words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
    
    # 过滤停用词
    filtered_words = [w for w in words if w not in stop_words]
    
    # 统计词频
    word_counts = Counter(filtered_words)
    
    # 提取最常见的关键词
    keywords = [word for word, count in word_counts.most_common(max_keywords)]
    
    return keywords


def search_candidate_papers_openalex(query_text, keywords, max_candidates=50):
    """
    使用 OpenAlex 搜索候选论文
    """
    headers = {'User-Agent': 'PaperLens/1.0 (mailto:contact@example.com)'}
    all_papers = []
    seen_ids = set()
    
    try:
        # 策略1：使用标题/摘要直接搜索
        url = "https://api.openalex.org/works"
        
        # 构建搜索查询（使用前几个关键词）
        search_query = ' '.join(keywords[:5])
        
        params = {
            'search': search_query,
            'per_page': 25,
            'sort': 'relevance_score:desc',
            'filter': 'type:article,has_abstract:true',
            'select': 'id,doi,title,publication_year,cited_by_count,authorships,primary_location,abstract_inverted_index'
        }
        
        response = requests.get(url, params=params, headers=headers, timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            for work in data.get('results', []):
                paper_id = work.get('id', '')
                if paper_id and paper_id not in seen_ids:
                    seen_ids.add(paper_id)
                    paper = parse_openalex_work(work)
                    if paper and paper.get('abstract'):  # 只保留有摘要的
                        all_papers.append(paper)
        
        # 策略2：基于概念搜索补充
        if len(all_papers) < max_candidates:
            # 先获取相关概念
            concepts = get_concepts_for_query(search_query, headers)
            
            if concepts:
                concept_filter = '|'.join([c.replace('https://openalex.org/', '') for c in concepts[:3]])
                params = {
                    'filter': f'concepts.id:{concept_filter},type:article,has_abstract:true',
                    'per_page': 25,
                    'sort': 'cited_by_count:desc',
                    'select': 'id,doi,title,publication_year,cited_by_count,authorships,primary_location,abstract_inverted_index'
                }
                
                response = requests.get(url, params=params, headers=headers, timeout=15)
                
                if response.status_code == 200:
                    data = response.json()
                    for work in data.get('results', []):
                        paper_id = work.get('id', '')
                        if paper_id and paper_id not in seen_ids:
                            seen_ids.add(paper_id)
                            paper = parse_openalex_work(work)
                            if paper and paper.get('abstract'):
                                all_papers.append(paper)
        
        logger.info(f"OpenAlex 搜索到 {len(all_papers)} 篇候选论文")
        return all_papers[:max_candidates]
        
    except Exception as e:
        logger.error(f"OpenAlex 搜索失败: {e}")
        return []


def get_concepts_for_query(query, headers):
    """
    根据查询获取相关的 OpenAlex concepts
    """
    try:
        url = "https://api.openalex.org/concepts"
        params = {
            'search': query,
            'per_page': 5
        }
        
        response = requests.get(url, params=params, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            return [c.get('id', '') for c in data.get('results', [])]
        return []
        
    except:
        return []


def parse_openalex_work(work):
    """
    解析 OpenAlex 论文数据
    """
    try:
        # 还原摘要（OpenAlex 使用倒排索引存储）
        abstract = reconstruct_abstract(work.get('abstract_inverted_index', {}))
        
        # 提取作者
        authors = []
        for authorship in work.get('authorships', [])[:5]:
            author = authorship.get('author', {})
            author_name = author.get('display_name', '')
            if author_name:
                authors.append({'name': author_name})
        
        # 提取期刊/会议
        venue = ''
        primary_location = work.get('primary_location', {})
        if primary_location:
            source = primary_location.get('source', {})
            if source:
                venue = source.get('display_name', '')
        
        # 构建 URL
        doi = work.get('doi', '')
        url = doi if doi else work.get('id', '')
        
        return {
            'id': work.get('id', ''),
            'title': work.get('title', ''),
            'abstract': abstract,
            'year': work.get('publication_year', ''),
            'citationCount': work.get('cited_by_count', 0),
            'authors': authors,
            'venue': venue,
            'url': url
        }
        
    except Exception as e:
        logger.error(f"解析论文数据失败: {e}")
        return None


def reconstruct_abstract(inverted_index):
    """
    从 OpenAlex 的倒排索引还原摘要文本
    """
    if not inverted_index:
        return ''
    
    try:
        # 创建位置到单词的映射
        position_word = {}
        for word, positions in inverted_index.items():
            for pos in positions:
                position_word[pos] = word
        
        # 按位置排序并拼接
        if position_word:
            max_pos = max(position_word.keys())
            words = [position_word.get(i, '') for i in range(max_pos + 1)]
            return ' '.join(words)
        
        return ''
        
    except Exception as e:
        logger.error(f"还原摘要失败: {e}")
        return ''


def rank_papers_by_similarity(query_text, candidate_papers, top_k=10):
    """
    使用语义相似度对候选论文进行排序
    """
    if not candidate_papers:
        return []
    
    try:
        model = get_embedding_model()
        
        # 编码查询文本
        query_embedding = model.encode(query_text, convert_to_numpy=True)
        
        # 编码候选论文（使用标题+摘要）
        candidate_texts = []
        for paper in candidate_papers:
            text = paper.get('title', '')
            abstract = paper.get('abstract', '')
            if abstract:
                text += ' ' + abstract[:500]  # 限制摘要长度
            candidate_texts.append(text)
        
        candidate_embeddings = model.encode(candidate_texts, convert_to_numpy=True)
        
        # 计算余弦相似度
        similarities = cosine_similarity([query_embedding], candidate_embeddings)[0]
        
        # 综合评分：相似度 + 引用数归一化
        max_citations = max(p.get('citationCount', 0) for p in candidate_papers) or 1
        
        scored_papers = []
        for i, paper in enumerate(candidate_papers):
            similarity_score = similarities[i]
            citation_score = paper.get('citationCount', 0) / max_citations * 0.2  # 引用权重20%
            
            # 时间衰减：更近的论文略微加分
            year = paper.get('year', 2020) or 2020
            recency_score = max(0, (year - 2015) / 10) * 0.1  # 时间权重10%
            
            total_score = similarity_score * 0.7 + citation_score + recency_score
            
            scored_papers.append({
                **paper,
                'similarity_score': round(float(similarity_score), 4),
                'total_score': round(float(total_score), 4)
            })
        
        # 按总分排序
        scored_papers.sort(key=lambda x: x['total_score'], reverse=True)
        
        return scored_papers[:top_k]
        
    except Exception as e:
        logger.error(f"相似度计算失败: {e}")
        # 降级：按引用数排序
        return sorted(candidate_papers, key=lambda x: x.get('citationCount', 0), reverse=True)[:top_k]