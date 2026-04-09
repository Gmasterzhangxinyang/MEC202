from datetime import datetime
from config import REQUIRED_FIELDS, SIGNATURE_KEYWORDS
from validator.id_checker import verify_id


class ValidationResult:
    """验证结果容器，区分硬错误（直接拒绝）和软警告（推入人工复审）"""
    def __init__(self):
        self.hard_errors  = []   # 明确错误 → 直接拒绝
        self.soft_warnings = []  # 疑问项   → 人工复审

    @property
    def passed(self):
        return len(self.hard_errors) == 0

    @property
    def needs_review(self):
        return self.passed and len(self.soft_warnings) > 0

    def all_messages(self):
        return self.hard_errors + self.soft_warnings


class DocumentValidator:

    def validate(self, fields: dict, full_text: str, doc_type: str) -> ValidationResult:
        result = ValidationResult()

        self._check_required_fields(fields, doc_type, result)
        self._check_date(fields, result)
        self._check_signature(full_text, result)
        self._check_id(fields, result)

        return result

    # ── 规则1：必填字段完整性 ─────────────────────────────────────────────────
    def _check_required_fields(self, fields, doc_type, result):
        required = REQUIRED_FIELDS.get(doc_type, REQUIRED_FIELDS['general'])
        for field in required:
            if field not in fields or not fields[field]:
                result.hard_errors.append(f'缺少必填项：{field}')

    # ── 规则2：日期合法性 ─────────────────────────────────────────────────────
    def _check_date(self, fields, result):
        date_str = fields.get('日期')
        if not date_str:
            return  # 已由必填字段规则处理

        try:
            doc_date = datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            result.hard_errors.append(f'日期格式无法识别：{date_str}')
            return

        now = datetime.now()

        if doc_date.year < 2000:
            result.hard_errors.append(f'日期异常：{date_str} 年份过早')
            return

        if doc_date > now:
            result.hard_errors.append(f'日期异常：{date_str} 是未来日期')
            return

        # 软警告：日期超过90天
        delta_days = (now - doc_date).days
        if delta_days > 90:
            result.soft_warnings.append(
                f'注意：文件日期 {date_str} 距今已超过 {delta_days} 天，请人工确认是否有效'
            )

    # ── 规则3：签名/审批栏检测 ────────────────────────────────────────────────
    def _check_signature(self, full_text, result):
        found = any(kw in full_text for kw in SIGNATURE_KEYWORDS)
        if not found:
            result.hard_errors.append('未在文件中检测到签名/审批栏，请确认文件已被授权人签署')

    # ── 规则4：ID号对库验证 ───────────────────────────────────────────────────
    def _check_id(self, fields, result):
        id_number = fields.get('学号')
        name      = fields.get('姓名', '')

        if not id_number:
            # 没有学号字段，跳过（由必填字段规则处理）
            return

        passed, msg = verify_id(id_number, name)
        if not passed:
            result.hard_errors.append(msg)
