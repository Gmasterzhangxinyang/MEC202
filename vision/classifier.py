import re
from database.template import get_all_classification_rules, get_template_by_code


def classify_document(full_text: str, extracted_fields: dict) -> tuple:
    """
    根据全文和提取字段自动分类文档类型。

    返回 (template_code, confidence_score)。
    如果无法分类，返回 (None, 0.0)。
    """
    rules = get_all_classification_rules()
    if not rules:
        return None, 0.0

    scores = []
    for rule in rules:
        score = _compute_score(rule, full_text, extracted_fields)
        scores.append((rule['code'], rule['name'], score))

    # 按分数降序排序
    scores.sort(key=lambda x: x[2], reverse=True)

    if not scores or scores[0][2] < 0.3:
        return None, 0.0

    # 检查是否有多个模板分数接近（歧义）
    if len(scores) >= 2 and (scores[0][2] - scores[1][2]) < 0.05:
        return None, 0.0  # 歧义，无法确定

    return scores[0][0], scores[0][2]


def _compute_score(rule: dict, full_text: str, extracted_fields: dict) -> float:
    """计算单个模板的匹配分数"""
    score = 0.0

    # 1. 关键词匹配 (权重 0.5)
    keywords = rule.get('keywords', [])
    if keywords:
        matched = sum(1 for kw in keywords if kw in full_text)
        keyword_score = (matched / len(keywords)) * 0.5
        score += keyword_score

    # 2. 正则匹配 (固定加分 0.3)
    regex = rule.get('regex', '')
    if regex:
        try:
            if re.search(regex, full_text):
                score += 0.3
        except re.error:
            pass

    # 3. 必填字段命中 (权重 0.5)
    template = get_template_by_code(rule['code'])
    if template:
        required_fields = [
            f['field_name'] for f in template.get('fields', [])
            if f.get('field_category') == 'required'
        ]
        if required_fields:
            matched = sum(1 for f in required_fields if f in extracted_fields and extracted_fields[f])
            field_score = (matched / len(required_fields)) * 0.5
            score += field_score

    return score
