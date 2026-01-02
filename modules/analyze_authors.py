import requests
import logging
from collections import defaultdict
import scholarly

logger = logging.getLogger(__name__)

def get_author_from_google_scholar(author_name):
    """
    从 Google Scholar 获取作者信息
    """
    try:
        # 搜索作者
        search_query = scholarly.search_author(author_name)
        author_result = next(search_query, None)
        
        if not author_result:
            return create_fallback_author(author_name, "Google Scholar 未找到")
        
        # 获取详细信息
        author_data = scholarly.fill(author_result, sections=['basics', 'indices', 'publications'])
        
        # 提取机构信息
        affiliation = author_data.get('affiliation', '')
        affiliations = [affiliation] if affiliation else []
        
        # 提取近期论文
        publications = author_data.get('publications', [])[:5]
        recent_papers = []
        for pub in publications:
            paper_info = {
                'title': pub.get('bib', {}).get('title', ''),
                'year': pub.get('bib', {}).get('pub_year', ''),
                'citationCount': pub.get('num_citations', 0),
                'venue': pub.get('bib', {}).get('venue', '') or pub.get('bib', {}).get('journal', ''),
                'url': pub.get('pub_url', '') or pub.get('eprint_url', '')
            }
            recent_papers.append(paper_info)
        
        # 构建 Google Scholar 主页链接
        scholar_id = author_data.get('scholar_id', '')
        homepage = f"https://scholar.google.com/citations?user={scholar_id}" if scholar_id else ''
        
        return {
            "name": author_data.get('name', author_name),
            "affiliations": affiliations,
            "affiliation": affiliation,  # 单独保存完整机构名
            "paperCount": len(author_data.get('publications', [])),
            "citationCount": author_data.get('citedby', 0),
            "hIndex": author_data.get('hindex', 0),
            "i10Index": author_data.get('i10index', 0),
            "homepage": author_data.get('homepage', '') or homepage,
            "url": homepage,
            "email": author_data.get('email_domain', ''),
            "interests": author_data.get('interests', []),  # 研究兴趣
            "recentPapers": recent_papers,
            "searchSuccess": True,
            "source": "Google Scholar"
        }
        
    except StopIteration:
        return create_fallback_author(author_name, "未找到匹配作者")
    except Exception as e:
        logger.error(f"Google Scholar 错误 {author_name}: {str(e)}")
        return create_fallback_author(author_name, str(e))


def get_orcid_details(orcid_url):
    """
    从 ORCID 获取详细的机构信息和研究兴趣
    """
    try:
        if not orcid_url:
            return None, None
        
        # 提取 ORCID ID
        orcid_id = orcid_url.replace('https://orcid.org/', '').strip('/')
        
        # ORCID API 请求
        api_url = f"https://pub.orcid.org/v3.0/{orcid_id}"
        headers = {
            'Accept': 'application/json',
            'User-Agent': 'PaperLens/1.0'
        }
        
        response = requests.get(api_url, headers=headers, timeout=10)
        
        if response.status_code != 200:
            return None, None
        
        data = response.json()
        
        # 提取机构信息
        affiliations = []
        
        # 从 employments 获取工作机构
        employments = data.get('activities-summary', {}).get('employments', {}).get('affiliation-group', [])
        for emp_group in employments:
            summaries = emp_group.get('summaries', [])
            for summary in summaries:
                emp = summary.get('employment-summary', {})
                org = emp.get('organization', {})
                org_name = org.get('name', '')
                if org_name and org_name not in affiliations:
                    # 检查是否是当前职位（没有结束日期）
                    end_date = emp.get('end-date')
                    if end_date is None:  # 当前职位优先
                        affiliations.insert(0, org_name)
                    else:
                        affiliations.append(org_name)
        
        # 从 educations 获取教育机构（作为备选）
        if not affiliations:
            educations = data.get('activities-summary', {}).get('educations', {}).get('affiliation-group', [])
            for edu_group in educations:
                summaries = edu_group.get('summaries', [])
                for summary in summaries:
                    edu = summary.get('education-summary', {})
                    org = edu.get('organization', {})
                    org_name = org.get('name', '')
                    if org_name and org_name not in affiliations:
                        affiliations.append(org_name)
        
        # 提取研究兴趣/关键词
        interests = []
        
        # 从 keywords 获取
        keywords = data.get('person', {}).get('keywords', {}).get('keyword', [])
        for kw in keywords:
            content = kw.get('content', '')
            if content:
                # 可能包含多个关键词，用逗号或分号分隔
                for term in content.replace(';', ',').split(','):
                    term = term.strip()
                    if term and term not in interests:
                        interests.append(term)
        
        # 从 researcher-urls 中也可能获取研究领域信息
        # 从 biography 中提取（可选，需要NLP处理，这里简化处理）
        
        return affiliations[:5], interests[:10]  # 限制数量
        
    except Exception as e:
        logger.error(f"ORCID 获取详情失败: {e}")
        return None, None


def get_author_from_openalex(author_name):
    """
    从 OpenAlex 获取作者信息（备选方案）
    """
    try:
        headers = {'User-Agent': 'PaperLens/1.0 (mailto:jyiii058278@gmail.com)'}
        
        # 搜索作者
        search_url = "https://api.openalex.org/authors"
        params = {
            'search': author_name,
            'per_page': 1
        }
        
        response = requests.get(search_url, params=params, headers=headers, timeout=10)
        
        if response.status_code != 200:
            return create_fallback_author(author_name, f"OpenAlex 错误: {response.status_code}")
        
        data = response.json()
        results = data.get('results', [])
        
        if not results:
            return create_fallback_author(author_name, "OpenAlex 未找到")
        
        author = results[0]
        
        # 获取统计数据
        works_count = author.get('works_count', 0)
        cited_by_count = author.get('cited_by_count', 0)
        summary_stats = author.get('summary_stats', {})
        h_index = summary_stats.get('h_index', 0)
        i10_index = summary_stats.get('i10_index', 0)
        
        logger.info(f"OpenAlex 作者统计: {author_name} - 论文:{works_count}, 引用:{cited_by_count}, H:{h_index}")
        
        # 获取 ORCID
        orcid = author.get('orcid', '')
        
        # 从 ORCID 获取机构和研究兴趣
        orcid_affiliations, orcid_interests = get_orcid_details(orcid)
        
        # 使用 ORCID 的机构信息，如果没有则回退到 OpenAlex
        if orcid_affiliations:
            affiliations = orcid_affiliations
        else:
            # 回退到 OpenAlex 的机构信息
            affiliations = []
            last_institutions = author.get('last_known_institutions', [])
            for inst in last_institutions:
                inst_name = inst.get('display_name', '')
                if inst_name and inst_name not in affiliations:
                    affiliations.append(inst_name)
        
        # 使用 ORCID 的研究兴趣，如果没有则回退到 OpenAlex
        if orcid_interests:
            interests = orcid_interests
        else:
            # 回退到 OpenAlex 的 concepts
            interests = [c.get('display_name', '') for c in author.get('x_concepts', [])[:5] if c.get('display_name')]
        
        # 获取作者论文
        author_id = author.get('id', '').replace('https://openalex.org/', '')
        papers = get_author_papers_from_openalex(author_id, headers)
        
        # 构建 Google Scholar 搜索链接作为主页
        author_display_name = author.get('display_name', author_name)
        google_scholar_url = f"https://scholar.google.com/scholar?q=author:{author_display_name.replace(' ', '+')}"
        
        # 保留 OpenAlex URL 作为备用
        openalex_url = author.get('id', '')
        
        return {
            "name": author_display_name,
            "affiliations": affiliations,
            "affiliation": affiliations[0] if affiliations else '',
            "paperCount": works_count,
            "citationCount": cited_by_count,
            "hIndex": h_index,
            "i10Index": i10_index,
            "homepage": google_scholar_url,
            "url": google_scholar_url,
            "openalex_url": openalex_url,
            "orcid": orcid,
            "interests": interests,
            "recentPapers": papers,
            "searchSuccess": True,
            "source": "OpenAlex"
        }
        
    except Exception as e:
        logger.error(f"OpenAlex 错误 {author_name}: {str(e)}")
        import traceback
        traceback.print_exc()
        return create_fallback_author(author_name, str(e))


def get_author_papers_from_openalex(author_id, headers):
    """获取作者的论文列表"""
    try:
        papers_url = "https://api.openalex.org/works"
        params = {
            'filter': f'author.id:{author_id}',
            'per_page': 5,
            'sort': 'publication_date:desc'
        }
        
        response = requests.get(papers_url, params=params, headers=headers, timeout=10)
        
        if response.status_code != 200:
            return []
        
        data = response.json()
        papers = []
        
        for work in data.get('results', []):
            # 提取 DOI URL
            doi = work.get('doi', '')
            url = doi if doi else work.get('id', '')
            
            papers.append({
                'title': work.get('title', ''),
                'year': work.get('publication_year', ''),
                'citationCount': work.get('cited_by_count', 0),
                'venue': work.get('primary_location', {}).get('source', {}).get('display_name', ''),
                'url': url
            })
        
        return papers
        
    except Exception as e:
        logger.error(f"获取论文失败: {e}")
        return []

def get_author_from_openalex_by_paper(author_name, paper_title):
    """
    通过论文标题和作者名联合搜索，确保找到正确的作者
    """
    try:
        headers = {'User-Agent': 'PaperLens/1.0 (mailto:jyiii058278@gmail.com)'}
        
        # 先搜索论文，从论文作者中找到匹配的作者
        if paper_title:
            author_info = find_author_from_paper(author_name, paper_title, headers)
            if author_info and author_info.get('searchSuccess'):
                return author_info
        
        # 如果论文搜索失败，回退到作者搜索
        logger.info(f"论文联合搜索失败，回退到作者名搜索: {author_name}")
        return get_author_from_openalex(author_name)
        
    except Exception as e:
        logger.error(f"联合搜索错误 {author_name}: {str(e)}")
        return create_fallback_author(author_name, str(e))


def find_author_from_paper(author_name, paper_title, headers):
    """
    通过论文标题搜索，然后从论文作者中找到匹配的作者
    """
    try:
        # 搜索论文
        works_url = "https://api.openalex.org/works"
        params = {
            'search': paper_title,
            'per_page': 5  # 获取多个结果以提高匹配几率
        }
        
        response = requests.get(works_url, params=params, headers=headers, timeout=15)
        
        if response.status_code != 200:
            logger.warning(f"论文搜索失败: {response.status_code}")
            return None
        
        data = response.json()
        works = data.get('results', [])
        
        if not works:
            logger.warning(f"未找到论文: {paper_title[:50]}...")
            return None
        
        # 在搜索结果中找到标题最匹配的论文
        best_work = find_best_matching_work(works, paper_title)
        
        if not best_work:
            return None
        
        logger.info(f"找到匹配论文: {best_work.get('title', '')[:50]}...")
        
        # 从论文作者中找到匹配的作者
        authorships = best_work.get('authorships', [])
        matched_author = find_matching_author(authorships, author_name)
        
        if not matched_author:
            logger.warning(f"在论文作者中未找到: {author_name}")
            return None
        
        # 获取完整的作者详情
        author_id = matched_author.get('author', {}).get('id', '')
        if author_id:
            return get_author_details_by_id(author_id, author_name, matched_author, headers)
        
        return None
        
    except Exception as e:
        logger.error(f"论文作者搜索错误: {e}")
        return None


def find_best_matching_work(works, target_title):
    """
    在搜索结果中找到标题最匹配的论文
    """
    from difflib import SequenceMatcher
    
    target_title_lower = target_title.lower().strip()
    best_match = None
    best_ratio = 0
    
    for work in works:
        work_title = work.get('title', '') or ''
        work_title_lower = work_title.lower().strip()
        
        # 计算相似度
        ratio = SequenceMatcher(None, target_title_lower, work_title_lower).ratio()
        
        if ratio > best_ratio:
            best_ratio = ratio
            best_match = work
    
    # 相似度阈值
    if best_ratio >= 0.7:
        logger.info(f"论文匹配度: {best_ratio:.2%}")
        return best_match
    
    logger.warning(f"最佳匹配度过低: {best_ratio:.2%}")
    return None


def find_matching_author(authorships, target_name):
    """
    在论文作者列表中找到匹配的作者
    """
    from difflib import SequenceMatcher
    
    target_name_lower = target_name.lower().strip()
    target_parts = set(target_name_lower.split())
    
    best_match = None
    best_score = 0
    
    for authorship in authorships:
        author = authorship.get('author', {})
        author_name = author.get('display_name', '') or ''
        author_name_lower = author_name.lower().strip()
        author_parts = set(author_name_lower.split())
        
        # 方法1: 完整名字相似度
        ratio = SequenceMatcher(None, target_name_lower, author_name_lower).ratio()
        
        # 方法2: 名字部分重叠（处理名字顺序不同的情况）
        overlap = len(target_parts & author_parts) / max(len(target_parts), len(author_parts), 1)
        
        # 方法3: 检查姓氏匹配（通常最后一个词是姓氏）
        target_last = target_name_lower.split()[-1] if target_name_lower.split() else ''
        author_last = author_name_lower.split()[-1] if author_name_lower.split() else ''
        last_name_match = 1.0 if target_last == author_last else 0.0
        
        # 综合评分
        score = ratio * 0.4 + overlap * 0.3 + last_name_match * 0.3
        
        if score > best_score:
            best_score = score
            best_match = authorship
    
    # 设置阈值
    if best_score >= 0.5:
        matched_name = best_match.get('author', {}).get('display_name', '')
        logger.info(f"作者匹配: {target_name} -> {matched_name} (score: {best_score:.2f})")
        return best_match
    
    return None


def get_author_details_by_id(author_id, original_name, authorship_info, headers):
    """
    通过作者 ID 获取完整的作者详情
    """
    try:
        # 从 authorship 中提取基本信息
        author_basic = authorship_info.get('author', {})
        institutions = authorship_info.get('institutions', [])
        
        # 修正：正确处理 OpenAlex author ID URL
        # OpenAlex ID 格式: https://openalex.org/A1234567890
        # API URL 格式: https://api.openalex.org/authors/A1234567890
        if author_id.startswith('https://openalex.org/'):
            author_id_clean = author_id.replace('https://openalex.org/', '')
            author_url = f"https://api.openalex.org/authors/{author_id_clean}"
        elif author_id.startswith('https://api.openalex.org/'):
            author_url = author_id
        else:
            author_url = f"https://api.openalex.org/authors/{author_id}"
        
        logger.info(f"请求作者 API: {author_url}")
        
        response = requests.get(author_url, headers=headers, timeout=10)
        
        if response.status_code != 200:
            logger.warning(f"作者详情请求失败: {response.status_code}")
            # 如果获取详情失败，使用 authorship 中的信息，但尝试单独获取统计数据
            return build_author_from_authorship(original_name, authorship_info, headers)
        
        author = response.json()
        
        # 获取 ORCID
        orcid = author.get('orcid', '')
        
        # 从 ORCID 获取机构和研究兴趣
        orcid_affiliations, orcid_interests = get_orcid_details(orcid)
        
        # 机构信息：优先使用论文中的机构 -> ORCID -> OpenAlex
        affiliations = []
        
        # 首先使用论文中的机构（最准确，代表发表该论文时的机构）
        for inst in institutions:
            inst_name = inst.get('display_name', '')
            if inst_name and inst_name not in affiliations:
                affiliations.append(inst_name)
        
        # 补充 ORCID 机构
        if orcid_affiliations:
            for aff in orcid_affiliations:
                if aff not in affiliations:
                    affiliations.append(aff)
        
        # 补充 OpenAlex 最新机构
        if not affiliations:
            last_institutions = author.get('last_known_institutions', [])
            for inst in last_institutions:
                inst_name = inst.get('display_name', '')
                if inst_name and inst_name not in affiliations:
                    affiliations.append(inst_name)
        
        # 研究兴趣
        if orcid_interests:
            interests = orcid_interests
        else:
            interests = [c.get('display_name', '') for c in author.get('x_concepts', [])[:5] if c.get('display_name')]
        
        # 获取统计数据
        works_count = author.get('works_count', 0)
        cited_by_count = author.get('cited_by_count', 0)
        summary_stats = author.get('summary_stats', {})
        h_index = summary_stats.get('h_index', 0)
        i10_index = summary_stats.get('i10_index', 0)
        
        logger.info(f"作者统计: {original_name} - 论文:{works_count}, 引用:{cited_by_count}, H:{h_index}, i10:{i10_index}")
        
        # 获取作者论文
        author_id_for_papers = author.get('id', '').replace('https://openalex.org/', '')
        papers = get_author_papers_from_openalex(author_id_for_papers, headers)
        
        author_display_name = author.get('display_name', original_name)
        google_scholar_url = f"https://scholar.google.com/scholar?q=author:{author_display_name.replace(' ', '+')}"
        
        return {
            "name": author_display_name,
            "affiliations": affiliations[:5],
            "affiliation": affiliations[0] if affiliations else '',
            "paperCount": works_count,
            "citationCount": cited_by_count,
            "hIndex": h_index,
            "i10Index": i10_index,
            "homepage": google_scholar_url,
            "url": google_scholar_url,
            "openalex_url": author.get('id', ''),
            "orcid": orcid,
            "interests": interests[:10],
            "recentPapers": papers,
            "searchSuccess": True,
            "source": "OpenAlex (论文联合搜索)",
            "matchMethod": "paper_title"
        }
        
    except Exception as e:
        logger.error(f"获取作者详情失败: {e}")
        import traceback
        traceback.print_exc()
        return build_author_from_authorship(original_name, authorship_info, headers)


def build_author_from_authorship(author_name, authorship_info, headers=None):
    """
    从 authorship 信息构建基本作者信息
    如果可能，尝试通过作者 ID 获取统计数据
    """
    author_basic = authorship_info.get('author', {})
    institutions = authorship_info.get('institutions', [])
    
    affiliations = [inst.get('display_name', '') for inst in institutions if inst.get('display_name')]
    
    display_name = author_basic.get('display_name', author_name)
    google_scholar_url = f"https://scholar.google.com/scholar?q=author:{display_name.replace(' ', '+')}"
    
    # 尝试从作者 ID 获取基本统计
    author_id = author_basic.get('id', '')
    works_count = 0
    cited_by_count = 0
    h_index = 0
    i10_index = 0
    orcid = author_basic.get('orcid', '')
    papers = []
    
    if author_id and headers:
        try:
            # 尝试获取作者统计数据
            if author_id.startswith('https://openalex.org/'):
                author_id_clean = author_id.replace('https://openalex.org/', '')
                author_url = f"https://api.openalex.org/authors/{author_id_clean}"
            else:
                author_url = f"https://api.openalex.org/authors/{author_id}"
            
            response = requests.get(author_url, headers=headers, timeout=5)
            if response.status_code == 200:
                author_data = response.json()
                works_count = author_data.get('works_count', 0)
                cited_by_count = author_data.get('cited_by_count', 0)
                summary_stats = author_data.get('summary_stats', {})
                h_index = summary_stats.get('h_index', 0)
                i10_index = summary_stats.get('i10_index', 0)
                orcid = author_data.get('orcid', '') or orcid
                
                # 获取论文
                author_id_for_papers = author_data.get('id', '').replace('https://openalex.org/', '')
                papers = get_author_papers_from_openalex(author_id_for_papers, headers)
                
                logger.info(f"备选方式获取统计成功: {display_name}")
        except Exception as e:
            logger.warning(f"备选统计获取失败: {e}")
    
    return {
        "name": display_name,
        "affiliations": affiliations,
        "affiliation": affiliations[0] if affiliations else '',
        "paperCount": works_count,
        "citationCount": cited_by_count,
        "hIndex": h_index,
        "i10Index": i10_index,
        "homepage": google_scholar_url,
        "url": google_scholar_url,
        "openalex_url": author_id,
        "orcid": orcid,
        "interests": [],
        "recentPapers": papers,
        "searchSuccess": True if works_count > 0 else False,
        "source": "OpenAlex (论文作者)",
        "matchMethod": "paper_authorship"
    }


def generate_team_analysis(authors):
    """
    生成团队分析数据
    """
    total_papers = 0
    total_citations = 0
    total_h_index = 0
    h_index_count = 0
    institution_distribution = {}
    research_interests = {}
    
    for author in authors:
        # 统计论文和引用
        total_papers += author.get('paperCount', 0) or 0
        total_citations += author.get('citationCount', 0) or 0
        
        # 统计 H 指数
        h_index = author.get('hIndex', 0)
        if h_index and h_index > 0:
            total_h_index += h_index
            h_index_count += 1
        
        # 机构分布
        affiliation = author.get('affiliation', '') or ''
        if affiliation:
            # 简化机构名称（去掉过长的部分）
            simplified_name = affiliation.split(',')[0].strip()
            institution_distribution[simplified_name] = institution_distribution.get(simplified_name, 0) + 1
        
        # 研究兴趣
        interests = author.get('interests', []) or []
        for interest in interests[:5]:  # 每个作者最多取5个
            if interest:
                research_interests[interest] = research_interests.get(interest, 0) + 1
    
    # 计算平均 H 指数
    avg_h_index = round(total_h_index / h_index_count, 1) if h_index_count > 0 else 0
    
    # 排序研究兴趣
    sorted_interests = dict(sorted(research_interests.items(), key=lambda x: x[1], reverse=True)[:15])
    
    return {
        "totalPapers": total_papers,
        "totalCitations": total_citations,
        "avgHIndex": avg_h_index,
        "institutionDistribution": institution_distribution,
        "researchInterests": sorted_interests
    }

def create_fallback_author(author_name, error_msg):
    """创建备选作者信息"""
    return {
        "name": author_name,
        "affiliations": [],
        "affiliation": "",
        "paperCount": 0,
        "citationCount": 0,
        "hIndex": 0,
        "homepage": "",
        "url": f"https://scholar.google.com/scholar?q=author:{author_name.replace(' ', '+')}",
        "interests": [],
        "recentPapers": [],
        "searchSuccess": False,
        "source": "未找到",
        "error": error_msg
    }



def get_fallback_author_analysis():
    """
    返回示例作者分析数据，包含链接
    """
    return {
        "authors_count": 3,
        "authors": [
            {
                "name": "王小明",
                "affiliations": ["清华大学计算机科学与技术系"],
                "paperCount": 25,
                "citationCount": 1200,
                "hIndex": 15,
                "url": "https://www.semanticscholar.org/author/王小明/12345678",
                "recentPapers": [
                    {
                        "title": "基于深度学习的自然语言处理研究", 
                        "year": 2023, 
                        "citationCount": 45,
                        "url": "https://www.semanticscholar.org/paper/12345678"
                    },
                    {
                        "title": "神经网络在机器翻译中的应用", 
                        "year": 2022, 
                        "citationCount": 78,
                        "url": "https://www.semanticscholar.org/paper/87654321"
                    }
                ]
            },
            {
                "name": "李华", 
                "affiliations": ["北京大学人工智能研究院"],
                "paperCount": 18,
                "citationCount": 890,
                "hIndex": 12,
                "url": "https://www.semanticscholar.org/author/李华/87654321",
                "recentPapers": [
                    {
                        "title": "多模态学习的最新进展", 
                        "year": 2023, 
                        "citationCount": 32,
                        "url": "https://www.semanticscholar.org/paper/11223344"
                    },
                    {
                        "title": "计算机视觉技术综述", 
                        "year": 2022, 
                        "citationCount": 56,
                        "url": "https://www.semanticscholar.org/paper/44332211"
                    }
                ]
            }
        ],
        "analysis": {
            "institutionDistribution": {"清华大学": 1, "北京大学": 1},
            "teamSize": 2,
            "productiveAuthors": 2,
            "highlyCitedAuthors": 2,
            "totalPapers": 43,
            "totalCitations": 2090,
            "collaborationNetwork": True
        }
    }


