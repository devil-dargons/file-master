# === 文件路径: src/core/meta_extractor.py ===
"""L2 元数据提取：EXIF / 视频时长分辨率 / 音频时长 / PDF 页数。

- 纯 Python + threading，不感知 Qt（进度经回调上报）
- 依赖按需导入：缺少某个库时只跳过该类文件，不影响其他类型
- 幂等：DAO 只返回"没有元数据"或"文件 mtime 已变"的记录
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Callable, Optional

from src.core.models import FileRecord, MediaMeta
from src.db.dao import FileDAO

logger = logging.getLogger(__name__)

ProgressCallback = Optional[Callable[[int, int, str], None]]   # (current, total, path)
FinishedCallback = Optional[Callable[[int, int], None]]        # (succeeded, failed)


def _parse_exif_time(value) -> str | None:
    """EXIF 时间 'YYYY:MM:DD HH:MM:SS' → 'YYYY-MM-DD HH:MM:SS'。"""
    if not value:
        return None
    text = str(value).strip()
    if len(text) >= 19 and text[4] == ":" and text[7] == ":":
        return f"{text[0:4]}-{text[5:7]}-{text[8:10]} {text[11:19]}"
    return text or None


def _extract_image(path: str) -> MediaMeta | None:
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(path) as img:
            meta = MediaMeta(width=img.width, height=img.height)
            exif = img.getexif()
            if exif:
                try:
                    ifd = exif.get_ifd(0x8769)
                except Exception:
                    ifd = {}
                shot = ifd.get(36867) or ifd.get(36868) or exif.get(306)
                meta.shot_time = _parse_exif_time(shot)
                make = str(exif.get(271) or "").strip()
                model = str(exif.get(272) or "").strip()
                meta.camera = f"{make} {model}".strip() or None
            return meta
    except Exception as e:
        logger.debug("EXIF 提取失败 %s: %s", path, e)
        return None


def _extract_audio(path: str) -> MediaMeta | None:
    try:
        from mutagen import File as MutagenFile
    except ImportError:
        return None
    try:
        audio = MutagenFile(path)
        if audio is None or audio.info is None:
            return None
        return MediaMeta(duration_sec=float(audio.info.length))
    except Exception as e:
        logger.debug("音频元数据提取失败 %s: %s", path, e)
        return None


def _extract_video(path: str) -> MediaMeta | None:
    try:
        import cv2
    except ImportError:
        return None
    capture = None
    try:
        capture = cv2.VideoCapture(path)
        if not capture.isOpened():
            return None
        fps = capture.get(cv2.CAP_PROP_FPS) or 0
        frames = capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        meta = MediaMeta(
            width=int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)) or None,
            height=int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)) or None,
        )
        if fps > 0 and frames > 0:
            meta.duration_sec = round(frames / fps, 2)
        return meta
    except Exception as e:
        logger.debug("视频元数据提取失败 %s: %s", path, e)
        return None
    finally:
        if capture is not None:
            capture.release()


def _extract_pdf(path: str) -> MediaMeta | None:
    try:
        import pymupdf
    except ImportError:
        try:
            import fitz as pymupdf  # type: ignore[no-redef]
        except ImportError:
            return None
    try:
        with pymupdf.open(path) as doc:
            meta = MediaMeta(page_count=doc.page_count)
            if doc.page_count:
                first = doc[0]
                meta.width = int(first.rect.width)
                meta.height = int(first.rect.height)
            return meta
    except Exception as e:
        logger.debug("PDF 元数据提取失败 %s: %s", path, e)
        return None


_EXTRACTORS = {
    "image": _extract_image,
    "video": _extract_video,
    "audio": _extract_audio,
    "document": None,  # 文档按扩展名二次分派
}


def extract_meta(path: str, file_type: str) -> MediaMeta | None:
    """按大类提取元数据；不支持的类型返回 None。"""
    if file_type == "document":
        if path.lower().endswith(".pdf"):
            return _extract_pdf(path)
        return None
    extractor = _EXTRACTORS.get(file_type)
    return extractor(path) if extractor else None


class MetadataExtractor(threading.Thread):
    """后台低优先级元数据队列：逐条提取并入库。"""

    def __init__(
        self,
        file_dao: FileDAO,
        on_progress: ProgressCallback = None,
        on_finished: FinishedCallback = None,
    ):
        super().__init__(daemon=True, name="MetadataExtractor")
        self.file_dao = file_dao
        self.on_progress = on_progress
        self.on_finished = on_finished
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        records: list[FileRecord] = self.file_dao.get_files_pending_meta()
        total = len(records)
        succeeded = 0
        failed = 0

        for index, record in enumerate(records, start=1):
            if self._stop_event.is_set():
                break
            if not os.path.exists(record.path):
                failed += 1
                continue
            meta = extract_meta(record.path, record.file_type)
            if meta is None or not self.file_dao.upsert_file_meta(
                    record.id, meta, record.modified_time, record.file_type):
                failed += 1
            else:
                succeeded += 1
            if self.on_progress:
                try:
                    self.on_progress(index, total, record.path)
                except Exception:
                    logger.exception("meta on_progress callback failed")

        logger.info("元数据提取结束：成功 %d，失败 %d", succeeded, failed)
        if self.on_finished:
            try:
                self.on_finished(succeeded, failed)
            except Exception:
                logger.exception("meta on_finished callback failed")
