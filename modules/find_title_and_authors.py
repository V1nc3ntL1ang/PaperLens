import re
import logging
import requests 


logger = logging.getLogger(__name__)


def extract_title_authors_with_ai(text, api_key):
    """
    使用DeepSeek API提取论文标题和作者
    """
    if not api_key:
        return "111", ["1","2","3"]
        
    try:
        prompt = f"""请从以下学术论文的开头内容中提取标题和作者信息。

论文内容：
{text[:2000]} 

请严格按照以下JSON格式输出:
{{
    "title": "论文标题",
    "authors": ["作者1", "作者2", "作者3"]
}}

要求：
1. 标题：提取论文的完整标题
2. 作者：提取所有作者姓名，按论文中出现的顺序
3. 如果无法确定作者，可以返回空数组
4. 只输出JSON格式,不要有其他文字"""

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": "你是一个专业的学术助手，擅长从论文中提取结构化信息。"},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 800,
            "temperature": 0.1
        }

        response = requests.post("https://api.deepseek.com/v1/chat/completions", 
                               headers=headers, json=payload, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            content = result['choices'][0]['message']['content']
            logger.info(f"AI响应内容: {content}")
            
            # 提取JSON部分
            import json
            try:
                json_match = re.search(r'\{.*\}', content, re.DOTALL)
                if json_match:
                    data = json.loads(json_match.group())
                    title = data.get('title', '').strip()
                    authors = data.get('authors', [])
                    
                    # 验证和清理数据
                    if title and authors:
                        cleaned_authors = []
                        for author in authors:
                            if author and isinstance(author, str) and len(author.strip()) > 1:
                                cleaned_authors.append(author.strip())
                        
                        return title, cleaned_authors
            except Exception as e:
                logger.warning(f"AI提取JSON解析失败: {e}")
        
        # 如果AI提取失败，返回空值
        return "", []
        
    except Exception as e:
        logger.error(f"AI提取标题作者错误: {e}")
        return "", []
        

def get_fallback_papers():
    """
    返回高质量的示例论文数据
    """
    return [
        {
            "paperId": "fallback1",
            "title": "Attention Is All You Need",
            "authors": [
                {"authorId": "1", "name": "Ashish Vaswani"},
                {"authorId": "2", "name": "Noam Shazeer"},
                {"authorId": "3", "name": "Niki Parmar"}
            ],
            "year": 2017,
            "url": "https://arxiv.org/abs/1706.03762",
            "abstract": "The dominant sequence transduction models are based on complex recurrent or convolutional neural networks that include an encoder and a decoder. The best performing models also connect the encoder and decoder through an attention mechanism. We propose a new simple network architecture, the Transformer, based solely on attention mechanisms, dispensing with recurrence and convolutions entirely.",
            "citationCount": 45000,
            "venue": "NeurIPS"
        },
        {
            "paperId": "fallback2", 
            "title": "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding",
            "authors": [
                {"authorId": "4", "name": "Jacob Devlin"},
                {"authorId": "5", "name": "Ming-Wei Chang"},
                {"authorId": "6", "name": "Kenton Lee"}
            ],
            "year": 2018,
            "url": "https://arxiv.org/abs/1810.04805",
            "abstract": "We introduce a new language representation model called BERT, which stands for Bidirectional Encoder Representations from Transformers. Unlike recent language representation models, BERT is designed to pre-train deep bidirectional representations from unlabeled text by jointly conditioning on both left and right context in all layers.",
            "citationCount": 35000,
            "venue": "NAACL"
        },
        {
            "paperId": "fallback3",
            "title": "Deep Residual Learning for Image Recognition",
            "authors": [
                {"authorId": "7", "name": "Kaiming He"},
                {"authorId": "8", "name": "Xiangyu Zhang"},
                {"authorId": "9", "name": "Shaoqing Ren"}
            ],
            "year": 2016,
            "url": "https://arxiv.org/abs/1512.03385",
            "abstract": "Deeper neural networks are more difficult to train. We present a residual learning framework to ease the training of networks that are substantially deeper than those used previously. We explicitly reformulate the layers as learning residual functions with reference to the layer inputs, instead of learning unreferenced functions.",
            "citationCount": 120000,
            "venue": "CVPR"
        }
    ]


