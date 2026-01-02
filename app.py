import fitz
import logging
import requests
import time
import json
import os
from datetime import datetime
from flask import Flask, request, jsonify, send_file, Response, stream_with_context
from modules.find_references import extract_references
from modules.verify_references import (
    find_best_match,
    get_fallback_reference_verification,
    smart_extract_search_query,
    search_openalex,
)
from modules.find_github_urls import extract_github_urls
from modules.find_candidate_papers import (
    extract_paper_keywords,
    search_candidate_papers_openalex,
    rank_papers_by_similarity,
)
from modules.find_title_and_authors import extract_title_authors_with_ai
from modules.analyze_authors import (
    get_author_from_google_scholar,
    get_author_from_openalex,
    get_author_from_openalex_by_paper,
    generate_team_analysis,
    get_fallback_author_analysis,
)

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder=".", static_url_path="")

# 允许跨域 (方便开发时前后端分离调试)
from flask_cors import CORS

CORS(app)


@app.route("/")
def index():
    return send_file("index.html")


@app.route("/api/upload", methods=["POST"])
def upload_pdf():
    if "file" not in request.files:
        return jsonify({"error": "没有上传文件"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "文件名为空"}), 400

    try:
        file_content = file.read()
        doc = fitz.open(stream=file_content, filetype="pdf")

        text = ""
        for page in doc:
            page_text = page.get_text()
            text += page_text + "\n"

        logger.info(f"提取到文本长度: {len(text)} 字符")

        page_count = len(doc)

        lines = text.split("\n")
        first_50_lines = "\n".join(lines[:50])

        api_key = request.headers.get("X-API-Key")
        title, authors = extract_title_authors_with_ai(first_50_lines, api_key)

        references = extract_references(text)

        # 提取 GitHub 链接
        github_urls = extract_github_urls(text)
        logger.info(f"提取到 GitHub 链接: {github_urls}")

        return jsonify(
            {
                "text": text if text else "",
                "page_count": page_count if page_count else 0,
                "references": references if references else [],
                "title": title,
                "authors": authors,
                "github_urls": github_urls,
            }
        )

    except Exception as e:
        logger.error(f"PDF处理错误: {str(e)}")
        return jsonify({"error": f"无法处理PDF文件: {str(e)}"}), 500
    finally:
        if "doc" in locals():
            doc.close()

@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.json
    messages = data.get('messages', [])
    api_key = request.headers.get('X-API-Key')
    print(f"=== DEBUG: API Key 值 ===")
    print(f"API Key 是否存在: {'X-API-Key' in request.headers}")
    print(f"API Key 值: '{api_key}'")
    print(f"API Key 长度: {len(api_key) if api_key else 0}")
    print(f"API Key 是否为空: {not api_key}")
    print(f"API Key 是否为None: {api_key is None}")
    print(f"=== DEBUG 结束 ===")
    model = data.get('model', 'deepseek-chat')
    api_base = data.get('api_base', 'https://api.deepseek.com/v1')

    if not api_key:
        return jsonify({"error": "未提供 API Key"}), 401

    try:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": 3000,
            "temperature": 0.2,
            "stream": False
        }

        response = requests.post(f"{api_base}/chat/completions", headers=headers, json=payload)
        
        if response.status_code != 200:
            return jsonify({"error": f"DeepSeek API Error: {response.text}"}), response.status_code

        return jsonify(response.json())

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route('/api/chat/stream', methods=['POST'])
def chat_stream():
    """流式聊天接口"""
    data = request.json
    api_key = request.headers.get('X-API-Key')
    
    if not api_key:
        return jsonify({'error': '缺少 API Key'}), 401
    
    api_base = data.get('api_base', 'https://api.deepseek.com/v1')
    
    def generate():
        try:
            response = requests.post(
                f"{api_base}/chat/completions",
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {api_key}'
                },
                json={
                    'model': data.get('model', 'deepseek-chat'),
                    'messages': data.get('messages', []),
                    'stream': True
                },
                stream=True,
                timeout=60
            )
            
            if response.status_code != 200:
                yield f"data: {json.dumps({'error': f'API错误: {response.status_code}'})}\n\n"
                return
            
            for line in response.iter_lines():
                if line:
                    decoded_line = line.decode('utf-8')
                    yield f"{decoded_line}\n\n"
                    
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
    
    return Response(
        stream_with_context(generate()),
        content_type='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no'  # 禁用 Nginx 缓冲
        }
    )

@app.route("/api/recommend_papers", methods=["POST"])
def recommend_papers():
    """
    根据论文内容推荐相关论文 - 基于语义相似度 + OpenAlex
    """
    data = request.get_json()
    paper_text = data.get("text", "") if data else ""
    paper_title = data.get("title", "") if data else ""
    max_results = data.get("max_results", 10) if data else 10

    if not paper_text and not paper_title:
        return jsonify({"error": "论文内容为空"}), 400

    try:
        # 构建查询文本
        query_text = (
            paper_title + " " + paper_text[:1000] if paper_title else paper_text[:1000]
        )

        logger.info(f"开始语义搜索相关论文，文本长度: {len(query_text)}")

        # 1. 提取关键词
        keywords = extract_paper_keywords(query_text)
        logger.info(f"提取关键词: {keywords[:5]}")

        # 2. 搜索候选论文
        candidate_papers = search_candidate_papers_openalex(
            query_text, keywords, max_candidates=50
        )

        logger.info(f"候选论文数量: {len(candidate_papers)}")  # 调试日志

        if not candidate_papers:
            return jsonify(
                {
                    "success": True,
                    "error": None,
                    "keywords_used": keywords[:5],
                    "candidates_found": 0,
                    "papers": [],
                    "source": "openalex",
                    "method": "semantic_similarity",
                }
            )

        # 3. 使用语义相似度排序
        ranked_papers = rank_papers_by_similarity(
            query_text, candidate_papers, top_k=max_results
        )

        logger.info(f"排序后论文数量: {len(ranked_papers)}")  # 调试日志

        # 4. 清理输出数据
        output_papers = []
        for paper in ranked_papers:
            paper_data = {
                "title": paper.get("title", ""),
                "authors": paper.get("authors", []),
                "year": paper.get("year", ""),
                "citationCount": paper.get("citationCount", 0),
                "venue": paper.get("venue", ""),
                "url": paper.get("url", ""),
                "abstract": (
                    paper.get("abstract", "")[:300] + "..."
                    if len(paper.get("abstract", "")) > 300
                    else paper.get("abstract", "")
                ),
                "similarity": paper.get("similarity_score", 0),
                "relevance": paper.get("total_score", 0),
            }
            output_papers.append(paper_data)

        logger.info(f"输出论文数量: {len(output_papers)}")  # 调试日志

        # 打印完整响应用于调试
        response_data = {
            "success": True,
            "keywords_used": keywords[:5],
            "candidates_found": len(candidate_papers),
            "papers": output_papers,
            "source": "openalex",
            "method": "semantic_similarity",
        }

        logger.info(
            f"返回响应: success={response_data['success']}, papers_count={len(response_data['papers'])}"
        )

        return jsonify(response_data)

    except Exception as e:
        logger.error(f"论文推荐错误: {str(e)}")
        import traceback

        traceback.print_exc()

        return (
            jsonify(
                {
                    "success": False,
                    "error": f"推荐服务异常: {str(e)}",
                    "papers": [],
                    "keywords_used": [],
                    "candidates_found": 0,
                }
            ),
            500,
        )


# 修改 analyze_authors 接口
@app.route("/api/analyze_authors", methods=["POST"])
def analyze_authors():
    """
    使用论文标题+作者名联合搜索，提高作者匹配准确性
    """
    data = request.get_json()
    authors = data.get("authors", []) if data else []
    paper_title = data.get("title", "")  # 新增：接收论文标题

    if not authors:
        return jsonify({"error": "作者信息为空"}), 400

    logger.info(f"开始分析作者信息: {authors}")
    logger.info(f"论文标题: {paper_title[:50]}..." if paper_title else "无论文标题")

    detailed_authors = []

    for i, author_name in enumerate(authors):
        logger.info(f"获取作者详情 {i+1}/{len(authors)}: {author_name}")

        # 优先使用 Google Scholar
        author_details = get_author_from_google_scholar(author_name)

        # 如果 Google Scholar 失败，使用论文标题联合搜索 OpenAlex
        if not author_details.get("searchSuccess"):
            logger.info(f"Google Scholar 未找到，尝试论文联合搜索: {author_name}")
            author_details = get_author_from_openalex_by_paper(author_name, paper_title)

        detailed_authors.append(author_details)
        time.sleep(1)  # 避免请求过快

    return jsonify(
        {
            "success": True,
            "authors_count": len(detailed_authors),
            "authors": detailed_authors,
            "analysis": generate_team_analysis(detailed_authors),
        }
    )


@app.route("/api/update_authors", methods=["POST"])
def update_authors():
    """
    手动更新作者信息
    """
    data = request.get_json()
    original_authors = data.get("original_authors", [])
    updated_authors = data.get("updated_authors", [])

    if not original_authors or not updated_authors:
        return jsonify({"error": "作者数据不能为空"}), 400

    try:
        # 为更新后的作者获取详细信息
        detailed_authors = []
        for i, author in enumerate(updated_authors):
            logger.info(f"获取更新作者详情 {i+1}/{len(updated_authors)}: {author}")
            author_details = get_author_from_google_scholar(author)

            # 如果 Google Scholar 失败，尝试 OpenAlex
            if not author_details.get("searchSuccess"):
                logger.info(f"Google Scholar 未找到，尝试 OpenAlex: {author}")
            author_details = get_author_from_openalex(author)
            if author_details:
                detailed_authors.append(author_details)
            time.sleep(0.5)

        return jsonify(
            {
                "success": True,
                "authors_count": len(detailed_authors),
                "authors": detailed_authors,
                "analysis": generate_team_analysis(detailed_authors),
                "original_authors": original_authors,
                "updated_authors": updated_authors,
            }
        )

    except Exception as e:
        logger.error(f"作者更新错误: {str(e)}")
        return (
            jsonify(
                {
                    "error": f"作者更新失败: {str(e)}",
                    "fallback_data": get_fallback_author_analysis(),
                }
            ),
            200,
        )


@app.route("/api/get_citations", methods=["POST"])
def get_citations():
    """
    使用 OpenAlex API 获取引用论文（完全免费，无需 Key）
    """
    data = request.get_json()
    paper_title = data.get("title", "")

    if not paper_title:
        return jsonify({"error": "论文标题不能为空"}), 400

    logger.info(f"搜索引用论文，标题: {paper_title}")

    try:
        headers = {"User-Agent": "PaperLens/1.0 (mailto:contact@example.com)"}

        # 1. 搜索论文
        search_url = "https://api.openalex.org/works"
        search_params = {"search": paper_title, "per_page": 1}

        search_response = requests.get(
            search_url, params=search_params, headers=headers, timeout=15
        )

        if search_response.status_code != 200:
            raise Exception(f"搜索失败: {search_response.status_code}")

        search_data = search_response.json()
        results = search_data.get("results", [])

        if not results:
            return jsonify(
                {
                    "success": False,
                    "error": "未找到该论文",
                    "fallback_used": True,
                    "citations": (),
                }
            )

        paper = results[0]
        paper_id = paper.get("id", "").replace("https://openalex.org/", "")

        # 2. 获取引用该论文的文献
        citations_url = "https://api.openalex.org/works"
        citations_params = {
            "filter": f"cites:{paper_id}",
            "per_page": 20,
            "sort": "cited_by_count:desc",
        }

        citations_response = requests.get(
            citations_url, params=citations_params, headers=headers, timeout=15
        )

        if citations_response.status_code != 200:
            raise Exception(f"获取引用失败: {citations_response.status_code}")

        citations_data = citations_response.json()
        citing_works = citations_data.get("results", [])

        # 3. 格式化结果
        formatted_citations = []
        for work in citing_works:
            # 提取作者（最多3个）
            authors = []
            for authorship in work.get("authorships", [])[:3]:
                author = authorship.get("author", {})
                if author.get("display_name"):
                    authors.append({"name": author["display_name"]})

            # 提取摘要
            abstract = ""
            if work.get("abstract_inverted_index"):
                # OpenAlex 的摘要是倒排索引格式，需要还原
                try:
                    inverted = work["abstract_inverted_index"]
                    word_positions = []
                    for word, positions in inverted.items():
                        for pos in positions:
                            word_positions.append((pos, word))
                    word_positions.sort()
                    abstract = " ".join([w for _, w in word_positions])[:300] + "..."
                except:
                    abstract = ""

            # 提取期刊/会议名称
            venue = ""
            primary_location = work.get("primary_location", {})
            if primary_location:
                source = primary_location.get("source", {})
                if source:
                    venue = source.get("display_name", "")

            # 提取 URL
            url = work.get("doi", "")
            if url and not url.startswith("http"):
                url = f"https://doi.org/{url}"
            if not url:
                url = work.get("id", "")

            formatted_citations.append(
                {
                    "title": work.get("title", "未知标题"),
                    "authors": authors,
                    "year": work.get("publication_year"),
                    "venue": venue,
                    "url": url,
                    "citationCount": work.get("cited_by_count", 0),
                    "abstract": abstract,
                }
            )

        return jsonify(
            {
                "success": True,
                "source": "OpenAlex",
                "original_paper": {
                    "title": paper.get("title", paper_title),
                    "citationCount": paper.get("cited_by_count", 0),
                    "year": paper.get("publication_year"),
                    "doi": paper.get("doi", ""),
                },
                "citations_count": len(formatted_citations),
                "citations": formatted_citations,
            }
        )

    except Exception as e:
        logger.error(f"OpenAlex API 错误: {e}")
        return jsonify(
            {
                "success": False,
                "error": str(e),
                "fallback_used": True,
                "original_paper": {"title": paper_title, "citationCount": 0},
                "citations_count": len(get_fallback_citations()),
                "citations": get_fallback_citations(),
            }
        )


def get_fallback_citations():
    """
    返回示例引用数据
    """
    return [
        {
            "title": "深度学习在自然语言处理中的最新进展",
            "authors": [{"name": "张伟"}, {"name": "李静"}],
            "year": 2023,
            "venue": "人工智能学报",
            "citationCount": 45,
            "abstract": "本文综述了深度学习在自然语言处理领域的最新研究成果和应用前景...",
            "url": "https://example.com/paper1",
        },
        {
            "title": "基于Transformer的文本表示学习研究",
            "authors": [{"name": "王明"}, {"name": "赵雪"}],
            "year": 2022,
            "venue": "计算机研究",
            "citationCount": 32,
            "abstract": "探讨了Transformer架构在文本表示学习中的应用和优化方法...",
            "url": "https://example.com/paper2",
        },
        {
            "title": "预训练语言模型的效率优化策略",
            "authors": [{"name": "刘强"}, {"name": "陈云"}],
            "year": 2023,
            "venue": "软件学报",
            "citationCount": 28,
            "abstract": "研究了大规模预训练语言模型的效率优化和部署策略...",
            "url": "https://example.com/paper3",
        },
    ]


@app.route("/api/verify_reference", methods=["POST"])
def verify_reference():
    """
    智能引用验证 - 使用AI提取搜索关键词
    """
    data = request.json
    ref_text = data.get("reference", "")

    if not ref_text:
        return jsonify({"error": "引用文本为空"}), 400

    try:
        logger.info(f"开始智能验证引用: {ref_text[:100]}...")

        # 使用AI提取搜索查询
        search_query = smart_extract_search_query(
            ref_text,
            request.headers.get("X-API-Key"),  # 从header获取API Key
            data.get("api_base", "https://api.deepseek.com/v1"),
        )

        logger.info(f"AI提取的搜索词: {search_query}")

        # 搜索OpenAlex
        papers = search_openalex(search_query, max_results=3)

        if papers:
            # 找到最佳匹配
            best_match = find_best_match(ref_text, papers)

            if best_match["score"] > 0.3:  # 匹配度阈值
                return jsonify(
                    {
                        "found": True,
                        "match_score": best_match["score"],
                        "data": best_match["paper"],
                        "search_query_used": search_query,
                        "ai_extraction_used": True,
                        "candidates": len(papers),
                    }
                )
            else:
                return jsonify(
                    {
                        "found": False,
                        "match_score": best_match["score"],
                        "message": f"找到相关论文但匹配度较低 ({(best_match['score']):.2f})",
                        "best_candidate": {
                            "title": best_match["paper"].get("title"),
                            "year": best_match["paper"].get("year"),
                            "authors": [
                                a.get("name")
                                for a in best_match["paper"].get("authors", [])
                            ][:3],
                        },
                        "search_query_used": search_query,
                        "ai_extraction_used": True,
                    }
                )
        else:
            return jsonify(
                {
                    "found": False,
                    "message": "未找到相关论文",
                    "search_query_used": search_query,
                    "ai_extraction_used": True,
                }
            )

    except Exception as e:
        logger.error(f"智能引用验证错误: {str(e)}")
        # 出错时使用备选方案
        return (
            jsonify(
                {
                    "error": f"验证服务异常: {str(e)}",
                    "fallback_data": get_fallback_reference_verification(ref_text),
                }
            ),
            200,
        )


# 笔记存储功能
NOTES_DIR = "user_notes"  # 笔记存储目录
os.makedirs(NOTES_DIR, exist_ok=True)


def get_note_filename(pdf_hash, user_id="default"):
    """生成笔记文件名"""
    return f"{NOTES_DIR}/{user_id}_{pdf_hash}.json"


def calculate_pdf_hash(file_content):
    """计算PDF文件的哈希值作为唯一标识"""
    import hashlib

    return hashlib.md5(file_content).hexdigest()


@app.route("/api/save_note", methods=["POST"])
def save_note():
    """
    保存论文笔记
    """
    try:
        data = request.get_json()
        pdf_content = data.get("pdf_content", "")
        notes = data.get("notes", {})
        user_id = data.get("user_id", "default")  # 可以扩展为多用户

        if not pdf_content:
            return jsonify({"error": "PDF内容不能为空"}), 400

        # 计算PDF哈希作为唯一标识
        pdf_hash = calculate_pdf_hash(pdf_content.encode("utf-8"))

        note_data = {
            "pdf_hash": pdf_hash,
            "notes": notes,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "page_count": len(notes),  # 有笔记的页数
        }

        # 保存到文件
        filename = get_note_filename(pdf_hash, user_id)
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(note_data, f, ensure_ascii=False, indent=2)

        return jsonify(
            {
                "success": True,
                "message": "笔记保存成功",
                "pdf_hash": pdf_hash,
                "saved_pages": len(notes),
            }
        )

    except Exception as e:
        logger.error(f"保存笔记错误: {str(e)}")
        return jsonify({"error": f"保存失败: {str(e)}"}), 500


@app.route("/api/load_note", methods=["POST"])
def load_note():
    """
    加载论文笔记
    """
    try:
        data = request.get_json()
        pdf_content = data.get("pdf_content", "")
        user_id = data.get("user_id", "default")

        if not pdf_content:
            return jsonify({"error": "PDF内容不能为空"}), 400

        pdf_hash = calculate_pdf_hash(pdf_content.encode("utf-8"))
        filename = get_note_filename(pdf_hash, user_id)

        if os.path.exists(filename):
            with open(filename, "r", encoding="utf-8") as f:
                note_data = json.load(f)
            return jsonify(
                {
                    "success": True,
                    "notes": note_data.get("notes", {}),
                    "created_at": note_data.get("created_at"),
                    "updated_at": note_data.get("updated_at"),
                }
            )
        else:
            return jsonify({"success": True, "notes": {}, "message": "未找到现有笔记"})

    except Exception as e:
        logger.error(f"加载笔记错误: {str(e)}")
        return jsonify({"error": f"加载失败: {str(e)}"}), 500


@app.route("/api/export_notes", methods=["POST"])
def export_notes():
    """
    导出笔记为 Markdown 格式
    """
    try:
        data = request.get_json()
        notes = data.get("notes", {})
        paper_title = data.get("paper_title", "未命名论文")

        # 构建 Markdown 内容
        markdown = f"# 📚 论文笔记：{paper_title}\n\n"
        markdown += f"**导出时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        markdown += "---\n\n"

        # 全局笔记
        global_note = notes.get("global", "")
        if global_note:
            markdown += "## 📝 全局笔记\n\n"
            markdown += f"{global_note}\n\n"
            markdown += "---\n\n"

        # 页面笔记
        pages = notes.get("pages", {})
        if pages:
            markdown += "## 📄 页面笔记\n\n"

            # 按页码排序
            sorted_pages = sorted(pages.items(), key=lambda x: int(x[0]))

            for page_num, content in sorted_pages:
                if content:  # 只导出有内容的页面
                    markdown += f"### 第 {page_num} 页\n\n"
                    markdown += f"{content}\n\n"

            markdown += "---\n\n"

        # 统计信息
        page_count = len([p for p in pages.values() if p])
        markdown += "## 📊 统计\n\n"
        markdown += f"- 全局笔记字数: {len(global_note)} 字\n"
        markdown += f"- 页面笔记数量: {page_count} 页\n"
        markdown += f"- 总字数: {len(global_note) + sum(len(p) for p in pages.values() if p)} 字\n"

        return jsonify(
            {
                "success": True,
                "markdown": markdown,
                "filename": f"论文笔记_{paper_title}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md",
            }
        )

    except Exception as e:
        logger.error(f"导出笔记错误: {str(e)}")
        return jsonify({"error": f"导出失败: {str(e)}"}), 500


if __name__ == "__main__":
    print("启动 PaperLens 后端服务...")
    print("请访问: http://localhost:5000")
    app.run(debug=True, port=5000)
