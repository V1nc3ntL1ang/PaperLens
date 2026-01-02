import re

def extract_references(pdf_file):
    """
    正确识别方括号编号的参考文献
    """
    try:
        lines = pdf_file.split('\n')
        ref_lines = []
        in_references = False
        current_ref = ""
        empty_line_count = 0
        ref_section_ended = False
        
        for i, line in enumerate(lines):
            line_clean = line.strip()
            
            # 跳过页眉页脚和版权信息
            if is_header_footer_copyright(line_clean):
                continue
                
            # 检测参考文献章节开始
            if not in_references and not ref_section_ended:
                if is_reference_section_header(line_clean):
                    in_references = True
                    continue
                
                # 新增：如果没有明确标题，但检测到参考文献格式，也认为是参考文献章节
                elif re.match(r'^\[\d+\]', line_clean) and len(line_clean) > 20:
                    # 检查下8行内是否还有其他方括号开头的行
                    has_another_ref = False
                    for j in range(i+1, min(i+9, len(lines))):  # 检查下8行
                        next_line_clean = lines[j].strip()
                        if re.match(r'^\[\d+\]', next_line_clean):
                            has_another_ref = True
                            break
                    
                    if has_another_ref:
                        in_references = True
                        # 直接开始处理这一行
                        current_ref = line_clean
                        continue

                # 新增：检测数字加点格式（如1. ）
                elif re.match(r'^1\.', line_clean) and len(line_clean) > 20:
                    # 检查下50行内是否有按顺序的2. 3. ... 10.
                    has_sequential_numbering = False
                    expected_number = 2
                    max_number_to_check = 10
                    
                    for j in range(i+1, min(i+51, len(lines))):  # 检查下50行
                        next_line_clean = lines[j].strip()
                        # 跳过空行
                        if not next_line_clean:
                            continue
                        
                        # 检查是否是当前期望的数字格式
                        if re.match(r'^' + str(expected_number) + r'\.', next_line_clean):
                            expected_number += 1
                            # 如果找到了10.，说明是顺序编号的参考文献
                            if expected_number > max_number_to_check:
                                has_sequential_numbering = True
                                break
                        # 如果不是期望的数字，重置检查（允许跳过某些编号）
                        elif re.match(r'^\d+\.', next_line_clean):
                            # 如果是其他数字，重新开始检查顺序
                            current_num = int(re.match(r'^(\d+)\.', next_line_clean).group(1))
                            if current_num == expected_number:
                                expected_number += 1
                            elif current_num > expected_number:
                                expected_number = current_num + 1
                
                    if has_sequential_numbering:
                        in_references = True
                        current_ref = line_clean
                        continue

            if in_references and not ref_section_ended:
                if not line_clean:
                    empty_line_count += 1
                    if empty_line_count >= 3 and current_ref:
                        ref_section_ended = True
                        if current_ref:
                            ref_lines.append(current_ref)
                        break
                    elif empty_line_count >= 2 and current_ref:
                        ref_lines.append(current_ref)
                        current_ref = ""
                    continue
                else:
                    empty_line_count = 0
                
                # 跳过页眉页脚（在参考文献章节内也要检查）
                if is_header_footer_copyright(line_clean):
                    continue
                
                # 修复：改进正则表达式，匹配方括号格式
                if re.match(r'^(\[\d+\]|\d+\.|•|\-|\.\s*\d)', line_clean):
                    if current_ref:
                        ref_lines.append(current_ref)
                    current_ref = line_clean
                elif current_ref:
                    # 继续当前参考文献（合并多行）
                    current_ref += " " + line_clean
                else:
                    current_ref = line_clean
                
                # 检查是否到达参考文献章节的结束标志
                if is_end_of_references_section(line_clean, i, lines):
                    ref_section_ended = True
                    if current_ref:
                        ref_lines.append(current_ref)
                    break
        
        if current_ref and not ref_section_ended:
            ref_lines.append(current_ref)
        
        # 最终过滤 - 放宽条件
        filtered_refs = filter_real_references(ref_lines)
        
        return filtered_refs if filtered_refs else None
        
    except Exception as e:
        return None
    
def is_header_footer_copyright(line):
    """判断是否是页眉页脚或版权信息 - 放宽条件"""
    if not line.strip():
        return False
        
    line_lower = line.lower()
    
    # 减少过于严格的过滤条件
    strict_indicators = [
        'nature biomedical engineering',
        'vol 5 | june 2021',
        '613–623 | www.nature.com',
        'articles nature',
        'scientific reports',
        'reporting summary',
        'author contribution',
        'acknowledgement',
        'competing interest',
        'data availability',
        'correspondence',
        'reprints',
        'supplementary'
    ]
    
    # 只过滤明确的页眉页脚，不要过滤可能的内容
    for indicator in strict_indicators:
        if indicator in line_lower:
            return True
    
    # 检查明显的URL和版权信息
    if re.search(r'https?://[^\s]+', line_lower) or 'doi.org' in line_lower:
        return True
    
    # 检查明显的版权信息
    if re.search(r'©\s*\d{4}', line_lower) or 'copyright' in line_lower:
        return True
    
    return False

def is_reference_section_header(line):
    """判断是否是参考文献章节标题 - 放宽条件"""
    line_lower = line.lower().strip()
    
    # 参考文献标题的匹配
    reference_headers = [
        'references',
        'reference',
        'bibliography', 
        '参考文献',
        '参考书目',
    ]
    
    # 精确匹配或开头匹配
    if line_lower in reference_headers:
        return True
    
    for header in reference_headers:
        if line_lower.startswith(header):
            return True
    
    return False

def is_end_of_references_section(line, line_num, all_lines):
    """判断是否是参考文献章节的结束 - 更保守"""
    line_clean = line.strip().lower()
    
    # 只有在明确的新章节标题时才结束
    section_headers = [
        'acknowledg',
        'author contribution',
        'competing interest', 
        'data availability',
        'supplementary',
        'appendix'
    ]
    
    # 必须是独立的短行才认为是章节标题
    if len(line_clean) < 50:
        for header in section_headers:
            if line_clean.startswith(header):
                return True
    
    return False

def filter_real_references(ref_lines):
    """最终过滤 - 大幅放宽条件"""
    real_references = []
    
    for ref in ref_lines:
        # 基本长度检查
        if len(ref) < 10 or len(ref) > 300:
            continue
            
        # 必须包含参考文献的基本特征
        if not has_basic_reference_features(ref):
            continue
            
        real_references.append(ref)
    
    return real_references

def has_basic_reference_features(text):
    """检查是否具有参考文献的基本特征"""
    # 包含年份（4位数字）
    has_year = re.search(r'(19|20)\d{2}', text)
    
    # 包含常见的参考文献特征
    ref_indicators = [
        'et al.', 'vol.', 'pp.', 'journal', 'proc.', 'conf.',
        'nature', 'science', 'cell', 'adv.', 'front.', 
        'acs', 'chem.', 'biol.', 'phys.', 'proc.', 'int.'
    ]
    
    has_ref_features = any(indicator in text.lower() for indicator in ref_indicators)
    
    # 包含作者模式（大写字母开头+逗号）
    has_author_pattern = re.search(r'[A-Z][a-z]+,', text)
    
    # 包含期刊缩写特征（大写字母+点）
    has_journal_pattern = re.search(r'[A-Z][a-z]*\.\s*[A-Z]', text)
    
    # 满足任意一个主要特征即可
    return (has_year or has_ref_features or has_author_pattern or has_journal_pattern) and len(text) > 20

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
            "url": "https://example.com/paper1"
        },
        {
            "title": "基于Transformer的文本表示学习研究",
            "authors": [{"name": "王明"}, {"name": "赵雪"}],
            "year": 2022, 
            "venue": "计算机研究",
            "citationCount": 32,
            "abstract": "探讨了Transformer架构在文本表示学习中的应用和优化方法...",
            "url": "https://example.com/paper2"
        },
        {
            "title": "预训练语言模型的效率优化策略",
            "authors": [{"name": "刘强"}, {"name": "陈云"}],
            "year": 2023,
            "venue": "软件学报", 
            "citationCount": 28,
            "abstract": "研究了大规模预训练语言模型的效率优化和部署策略...",
            "url": "https://example.com/paper3"
        }
    ]
