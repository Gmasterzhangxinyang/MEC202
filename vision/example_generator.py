"""示例文档图片生成器：根据模板定义自动生成样例文档图片"""

import os
import json
import io
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont


def _get_font(size):
    """尝试加载中文字体，找不到就用默认字体"""
    font_candidates = [
        '/System/Library/Fonts/STHeiti Light.ttc',
        '/System/Library/Fonts/PingFang.ttc',
        '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
        '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
        '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        '/Windows/Fonts/msyh.ttc',
    ]
    for path in font_candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


# 字段样例值
_SAMPLE_VALUES = {
    '姓名': '张三',
    '学号': '20210001',
    '日期': datetime.now().strftime('%Y-%m-%d'),
    '金额': '258.00',
    '原因': '个人事务',
    '请假类型': '事假',
    '请假天数': '2天',
    '用途': '办公用品采购',
    '证明类型': '在读证明',
    '报销用途': '差旅费用',
}


def generate_example_for_template(template: dict) -> bytes:
    """
    根据模板定义生成一张示例文档图片。
    返回 JPEG 字节数据。
    """
    W, H = 600, 800
    img = Image.new('RGB', (W, H), '#FAFAFA')
    draw = ImageDraw.Draw(img)

    font_title = _get_font(22)
    font_label = _get_font(16)
    font_value = _get_font(16)
    font_small = _get_font(13)
    font_watermark = _get_font(40)

    # 边框
    draw.rectangle([20, 20, W - 20, H - 20], outline='#CCCCCC', width=1)

    # 标题
    title = template.get('name', '示例文件')
    draw.text((W // 2, 55), title, fill='#1A1A1A', font=font_title, anchor='mm')
    draw.line([60, 75, W - 60, 75], fill='#CCCCCC', width=1)

    # 字段渲染
    fields = template.get('fields', [])
    y = 100
    for field_def in fields:
        fname = field_def.get('field_name', '')
        flabel = field_def.get('field_label', fname)
        category = field_def.get('field_category', 'required')
        validation_rule = field_def.get('validation_rule', '')

        if category == 'forbidden':
            # 非法字段：红色删除线标注
            draw.text((60, y), f'{flabel}：', fill='#999999', font=font_label)
            forbidden_text = '【不应出现】'
            text_x = 200
            draw.text((text_x, y), forbidden_text, fill='#CC0000', font=font_value)
            # 删除线
            bbox = draw.textbbox((text_x, y), forbidden_text, font=font_value)
            draw.line([bbox[0], y + 9, bbox[2], y + 9], fill='#CC0000', width=2)
            draw.line([60, y + 26, W - 60, y + 26], fill='#FFE0E0', width=1)
        else:
            # 必填/选填字段：显示样例值
            sample = _get_sample_value(fname, validation_rule)
            draw.text((60, y), f'{flabel}：', fill='#555555', font=font_label)
            draw.text((200, y), sample, fill='#1A1A1A', font=font_value)
            draw.line([60, y + 26, W - 60, y + 26], fill='#EEEEEE', width=1)

            # 验证规则提示
            rule_hint = _get_rule_hint(validation_rule)
            if rule_hint:
                draw.text((200, y + 18), f'({rule_hint})', fill='#AAAAAA', font=font_small)

            y += 6  # 额外间距给提示文字

        y += 42

    # 签名栏
    y += 20
    draw.text((60, y), '审批人签名：', fill='#555555', font=font_label)
    draw.text((200, y), '李老师', fill='#1A1A1A', font=font_value)
    y += 42
    draw.text((60, y), '日期：', fill='#555555', font=font_label)
    draw.text((200, y), datetime.now().strftime('%Y-%m-%d'), fill='#1A1A1A', font=font_value)

    # 页码
    draw.text((W // 2, H - 35), '第 1 页 / 共 1 页', fill='#AAAAAA', font=font_small, anchor='mm')

    # 水印 "示例文档"
    watermark = '示例文档'
    bbox = draw.textbbox((0, 0), watermark, font=font_watermark)
    ww = bbox[2] - bbox[0]
    wh = bbox[3] - bbox[1]
    # 斜着画水印
    draw.text((W // 2 - ww // 2 + 40, H // 2 - wh // 2 - 30),
              watermark, fill='#E0E0E0', font=font_watermark)

    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=92)
    return buf.getvalue()


def _get_sample_value(field_name: str, validation_rule: str = '') -> str:
    """获取字段的样例值"""
    if field_name in _SAMPLE_VALUES:
        return _SAMPLE_VALUES[field_name]

    # 检查 allowed_values
    if validation_rule:
        try:
            rule = json.loads(validation_rule)
            if 'allowed_values' in rule and rule['allowed_values']:
                return rule['allowed_values'][0]
        except (json.JSONDecodeError, TypeError):
            pass

    return '（示例内容）'


def _get_rule_hint(validation_rule: str) -> str:
    """从验证规则生成人类可读的提示"""
    if not validation_rule:
        return ''
    try:
        rule = json.loads(validation_rule)
    except (json.JSONDecodeError, TypeError):
        return ''

    hints = []
    if 'allowed_values' in rule:
        hints.append('可选：' + '/'.join(rule['allowed_values']))
    if 'min_value' in rule or 'max_value' in rule:
        lo = rule.get('min_value', '0')
        hi = rule.get('max_value', '无上限')
        hints.append(f'范围：{lo}~{hi}')
    if 'min_length' in rule and 'max_length' in rule:
        hints.append(f'长度：{rule["min_length"]}~{rule["max_length"]}')

    return '；'.join(hints)
