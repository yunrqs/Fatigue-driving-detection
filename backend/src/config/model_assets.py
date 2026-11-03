"""第三方模型资产的定位与自动获取。

``backend/models/`` 在 ``.gitignore`` 中被忽略（权重体积太大，不适合进版本库），
因此新克隆仓库或换一台机器后，``backend/models/dlib/shape_predictor_68_face_landmarks.dat``
通常并不存在，点击“开始识别”会直接抛 ``FileNotFoundError``。

本模块把“找模型”这件事从业务代码里抽出来，按三步处理：

1. **查找**：依次检查环境变量 ``FOCUSLENS_FACE_PREDICTOR``、显式传入的路径、
   仓库默认位置、以及用户级缓存目录，命中任何一处就直接使用；
2. **补全**：全部缺失时，从官方镜像下载 ``.bz2`` 压缩包，流式解压到临时文件，
   校验体积后再原子改名，避免中断留下半个模型；
3. **报错**：网络不可用等情况下抛出可操作的错误信息（列出搜索过的路径、
   手动下载地址与放置位置）。

如此设计的原因：dlib 的 68 点模型是 OpenFace 疲劳检测（打哈欠 / 头部姿态）的
硬依赖，但它不是本项目产物，不能要求使用者手动去 dlib.net 找。
"""

from __future__ import annotations

import bz2
import logging
import os
import shutil
import urllib.request
from pathlib import Path
from typing import Iterable, Optional, Sequence, Union

from backend.src.config.paths import DEFAULT_FACE_PREDICTOR, DLIB_MODELS, PROJECT_ROOT

logger = logging.getLogger(__name__)

PathLike = Union[str, "os.PathLike[str]"]

FACE_PREDICTOR_NAME = "shape_predictor_68_face_landmarks.dat"

# 官方 dlib-models 仓库与 dlib 官网提供同一份权重；前者在部分网络环境下更快，
# 因此按其可用性依次尝试，任一成功即停止。
FACE_PREDICTOR_URLS: Sequence[str] = (
    "https://raw.githubusercontent.com/davisking/dlib-models/master/"
    "shape_predictor_68_face_landmarks.dat.bz2",
    "https://dlib.net/files/shape_predictor_68_face_landmarks.dat.bz2",
)

# 官方模型解压后约 95 MiB。用体积下限识别“下载/解压被截断”的残file——
# 这种文件 dlib 读取时会抛 deserialize 错误，比体积检查更难定位。
FACE_PREDICTOR_MIN_BYTES = 90 * 1024 * 1024

# 允许用户指定任意位置的自有副本，便于离线环境或已有模型复用。
ENV_FACE_PREDICTOR = "FOCUSLENS_FACE_PREDICTOR"

# 下载分块大小：64 KiB 兼顾进度回报与内存占用。
_CHUNK_BYTES = 64 * 1024
_NETWORK_TIMEOUT_SEC = 30


def candidate_face_predictor_paths(
    explicit: Optional[PathLike] = None,
) -> tuple[Path, ...]:
    """返回按优先级排序的候选路径（去重，保持顺序）。"""
    raw: list[Path] = []

    env_value = os.environ.get(ENV_FACE_PREDICTOR)
    if env_value:
        raw.append(Path(env_value).expanduser())

    if explicit:
        raw.append(Path(explicit).expanduser())

    raw.append(Path(DEFAULT_FACE_PREDICTOR))
    # 仓库内 OpenFace 参考实现自带的模型目录：历史上是手动拷贝的来源。
    raw.append(
        PROJECT_ROOT
        / "pytorch-openpose-master"
        / "openface-master"
        / "models"
        / "dlib"
        / FACE_PREDICTOR_NAME
    )
    # 用户级缓存，与 blink_detection 的 face_landmarker.task 采用同一约定。
    raw.append(Path.home() / ".cache" / "focuslens" / FACE_PREDICTOR_NAME)

    seen: set[Path] = set()
    ordered: list[Path] = []
    for path in raw:
        try:
            resolved = path.resolve()
        except OSError:  # 非法路径直接跳过，不影响其它候选
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        ordered.append(path)
    return tuple(ordered)


def is_valid_face_predictor(path: PathLike) -> bool:
    """文件存在且体积达到下限才算可用。"""
    try:
        candidate = Path(path)
        return candidate.is_file() and candidate.stat().st_size >= FACE_PREDICTOR_MIN_BYTES
    except OSError:
        return False


def find_face_predictor(explicit: Optional[PathLike] = None) -> Optional[Path]:
    """在候选路径中查找可用模型，找不到返回 ``None``。"""
    for path in _iter_candidates(explicit):
        if is_valid_face_predictor(path):
            return path
    return None


def resolve_face_predictor(
    explicit: Optional[PathLike] = None,
    *,
    download: bool = True,
) -> Path:
    """返回可直接交给 ``dlib.shape_predictor`` 的模型路径。

    本地已有时零成本返回；缺失时默认自动下载（``download=False`` 可禁用，
    用于离线自检或单元测试）。
    """
    found = find_face_predictor(explicit)
    if found is not None:
        return found
    if not download:
        raise FileNotFoundError(missing_model_message(explicit))
    return download_face_predictor()


def download_face_predictor(dest: Optional[PathLike] = None) -> Path:
    """下载并解压模型，返回最终 ``.dat`` 路径。

    ``dest`` 可以是目标文件或目标目录；默认写入 ``backend/models/dlib/``，
    该目录不可写时退回用户缓存目录。
    """
    targets = _destination_candidates(dest)
    last_error: Optional[BaseException] = None

    for target in targets:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            part_bz2 = target.with_suffix(target.suffix + ".part")
            part_dat = target.with_suffix(target.suffix + ".extracting")

            _download_archive(part_bz2)
            logger.info("正在解压 dlib 关键点模型 -> %s", target)
            _extract_bz2(part_bz2, part_dat)
            part_bz2.unlink(missing_ok=True)
            if not is_valid_face_predictor(part_dat):
                size = part_dat.stat().st_size if part_dat.exists() else 0
                part_dat.unlink(missing_ok=True)
                raise RuntimeError(
                    f"解压后的模型体积异常（{size} 字节，期望 >= {FACE_PREDICTOR_MIN_BYTES}）"
                )
            os.replace(part_dat, target)  # 原子改名：不会出现“看见但读不了”的半成品
            logger.info("dlib 关键点模型已就绪：%s", target)
            return target
        except Exception as exc:  # noqa: BLE001 - 逐个目录降级重试
            last_error = exc
            logger.warning("写入 %s 失败：%s", target, exc)

    raise RuntimeError(
        f"无法获取 dlib 关键点模型（{FACE_PREDICTOR_NAME}）：{last_error}\n"
        f"请手动下载 {FACE_PREDICTOR_URLS[1]}，解压后放到 "
        f"{Path(DEFAULT_FACE_PREDICTOR)}，或设置环境变量 "
        f"{ENV_FACE_PREDICTOR} 指向已有副本。"
    ) from last_error


def missing_model_message(explicit: Optional[PathLike] = None) -> str:
    """构造“找不到模型”的可操作提示，便于直接展示给使用者。"""
    searched = "\n".join(f"  - {path}" for path in _iter_candidates(explicit))
    return (
        f"dlib 关键点模型不存在：{FACE_PREDICTOR_NAME}\n"
        f"已搜索以下位置：\n{searched}\n"
        f"修复方式任选其一：\n"
        f"  1. 直接点击“开始识别”由程序自动下载（默认写入 {Path(DLIB_MODELS)}）；\n"
        f"  2. 手动下载 {FACE_PREDICTOR_URLS[1]}，解压后放到 "
        f"{Path(DEFAULT_FACE_PREDICTOR)}；\n"
        f"  3. 设置环境变量 {ENV_FACE_PREDICTOR} 指向已有的 .dat 文件。"
    )


# --------------------------------------------------------------------------- #
# 内部实现
# --------------------------------------------------------------------------- #
def _iter_candidates(explicit: Optional[PathLike]) -> Iterable[Path]:
    return candidate_face_predictor_paths(explicit)


def _destination_candidates(dest: Optional[PathLike]) -> list[Path]:
    """决定落盘位置：显式指定的位置优先，其次仓库目录，最后用户缓存。"""
    if dest is not None:
        raw = Path(dest).expanduser()
        # 以 .dat 结尾视为文件路径，其余一律当作目录（目录可能尚不存在）。
        return [raw] if raw.suffix == ".dat" else [raw / FACE_PREDICTOR_NAME]
    return [
        Path(DLIB_MODELS) / FACE_PREDICTOR_NAME,
        Path.home() / ".cache" / "focuslens" / FACE_PREDICTOR_NAME,
    ]


def _download_archive(part_path: Path) -> None:
    """把压缩包下载到 ``part_path``，多个镜像依次尝试。"""
    errors: list[str] = []
    for url in FACE_PREDICTOR_URLS:
        try:
            logger.info("正在下载 dlib 关键点模型：%s", url)
            request = urllib.request.Request(
                url, headers={"User-Agent": "focuslens-setup/1.0"}
            )
            with urllib.request.urlopen(request, timeout=_NETWORK_TIMEOUT_SEC) as response:
                expected = int(response.headers.get("Content-Length") or 0)
                received = 0
                with open(part_path, "wb") as handle:
                    while True:
                        chunk = response.read(_CHUNK_BYTES)
                        if not chunk:
                            break
                        handle.write(chunk)
                        received += len(chunk)
            if expected and received != expected:
                raise RuntimeError(f"下载不完整：{received}/{expected} 字节")
            return
        except Exception as exc:  # noqa: BLE001 - 换下一个镜像
            errors.append(f"{url} -> {exc}")
            part_path.unlink(missing_ok=True)
    raise RuntimeError("所有下载源均失败：" + "；".join(errors))


def _extract_bz2(src: Path, dst: Path) -> None:
    """流式解压，避免把 100 MiB 模型整体读进内存。"""
    with bz2.BZ2File(src, "rb") as archive, open(dst, "wb") as out:
        shutil.copyfileobj(archive, out, _CHUNK_BYTES)
