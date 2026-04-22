import re
import json
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

        # 从模板数据库加载字段定义
        template = self._load_template(doc_type)

        self._check_required_fields(fields, doc_type, result, template)
        self._check_forbidden_fields(fields, doc_type, result, template)
        self._check_field_rules(fields, result, template)
        self._check_date(fields, result)
        self._check_signature(full_text, result)
        self._check_id(fields, result)

        return result

    def _load_template(self, doc_type: str) -> dict | None:
        """从数据库加载模板，失败时返回 None"""
        try:
            from database.template import get_template_by_code
            return get_template_by_code(doc_type)
        except Exception:
            return None

    # ── 规则1：必填字段完整性 ─────────────────────────────────────────────────
    def _check_required_fields(self, fields, doc_type, result, template):
        required_names = []
        if template:
            required_names = [
                f['field_name'] for f in template.get('fields', [])
                if f.get('field_category') == 'required'
            ]
        # fallback 到配置
        if not required_names:
            required_names = REQUIRED_FIELDS.get(doc_type, REQUIRED_FIELDS['general'])

        for field in required_names:
            if field not in fields or not fields[field]:
                result.hard_errors.append(f'缺少必填项：{field}')

    # ── 规则1.5：非法字段检查 ─────────────────────────────────────────────────
    def _check_forbidden_fields(self, fields, doc_type, result, template):
        if not template:
            return
        forbidden_names = [
            f['field_name'] for f in template.get('fields', [])
            if f.get('field_category') == 'forbidden'
        ]
        for field in forbidden_names:
            if field in fields and fields[field]:
                result.hard_errors.append(f'文件中不应包含字段：{field}')

    # ── 规则1.6：字段值规则校验 ───────────────────────────────────────────────
    def _check_field_rules(self, fields, result, template):
        if not template:
            return
        for fdef in template.get('fields', []):
            fname = fdef['field_name']
            rule_str = fdef.get('validation_rule', '')
            if not rule_str or fname not in fields or not fields[fname]:
                continue
            try:
                rule = json.loads(rule_str)
            except (json.JSONDecodeError, TypeError):
                continue
            value = str(fields[fname])
            errors = self._apply_field_rules(fname, value, rule)
            result.hard_errors.extend(errors)

    def _apply_field_rules(self, field_name: str, value: str, rule: dict) -> list:
        errors = []
        # regex
        if 'regex' in rule:
            pattern = rule['regex']
            try:
                if not re.search(pattern, value):
                    errors.append(f'字段 {field_name} 的值 "{value}" 不符合格式要求')
            except re.error:
                pass
        # min_length
        if 'min_length' in rule and len(value) < rule['min_length']:
            errors.append(f'字段 {field_name} 的值长度不能少于 {rule["min_length"]} 个字符')
        # max_length
        if 'max_length' in rule and len(value) > rule['max_length']:
            errors.append(f'字段 {field_name} 的值长度不能超过 {rule["max_length"]} 个字符')
        # min_value (numeric)
        if 'min_value' in rule:
            try:
                if float(value) < rule['min_value']:
                    errors.append(f'字段 {field_name} 的值不能小于 {rule["min_value"]}')
            except (ValueError, TypeError):
                pass
        # max_value (numeric)
        if 'max_value' in rule:
            try:
                if float(value) > rule['max_value']:
                    errors.append(f'字段 {field_name} 的值不能大于 {rule["max_value"]}')
            except (ValueError, TypeError):
                pass
        # allowed_values
        if 'allowed_values' in rule:
            allowed = rule['allowed_values']
            if value not in allowed:
                errors.append(
                    f'字段 {field_name} 的值 "{value}" 不在允许范围：{", ".join(allowed)}'
                )
        # date_format
        if 'date_format' in rule:
            fmt = rule['date_format']
            try:
                datetime.strptime(value, fmt)
            except ValueError:
                errors.append(f'字段 {field_name} 的日期格式不正确，应为 {fmt}')
        return errors

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
