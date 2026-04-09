import logging
import requests
from config import DMS_BASE_URL, DMS_API_KEY

logger = logging.getLogger(__name__)


class DMSClient:
    """
    对接学校文档管理系统（OA/DMS）的 REST 客户端。

    如果 DMS_BASE_URL 为空（config.py 默认），所有方法会直接
    返回成功占位值，不发任何网络请求，方便没有 DMS 的演示环境使用。
    """

    def __init__(self):
        self.enabled = bool(DMS_BASE_URL)
        self.base_url = DMS_BASE_URL.rstrip('/')
        self.headers = {
            'Authorization': f'Bearer {DMS_API_KEY}',
            'Accept': 'application/json',
        }

    def upload_stamped_doc(self, image_path: str, metadata: dict) -> str | None:
        """
        上传盖章后的文件图片到 DMS。
        返回 DMS 分配的文档 ID，失败返回 None。
        """
        if not self.enabled:
            logger.info('[DMS] 未配置，跳过上传')
            return None

        try:
            with open(image_path, 'rb') as f:
                resp = requests.post(
                    f'{self.base_url}/api/documents/upload',
                    headers=self.headers,
                    files={'file': ('stamped.jpg', f, 'image/jpeg')},
                    data={'metadata': str(metadata)},
                    timeout=10,
                )
            resp.raise_for_status()
            doc_id = resp.json().get('doc_id')
            logger.info(f'[DMS] 上传成功，doc_id={doc_id}')
            return doc_id
        except Exception as e:
            logger.warning(f'[DMS] 上传失败（不影响本地流程）：{e}')
            return None

    def query_personnel(self, id_number: str) -> dict | None:
        """
        从 DMS 查询人员信息（备用：本地 DB 中没有时用）。
        返回 {'name': ..., 'dept': ...} 或 None。
        """
        if not self.enabled:
            return None

        try:
            resp = requests.get(
                f'{self.base_url}/api/personnel/{id_number}',
                headers=self.headers,
                timeout=5,
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.warning(f'[DMS] 人员查询失败：{e}')
        return None
