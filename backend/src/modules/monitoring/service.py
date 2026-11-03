"""识别会话：调用共享情绪与眨眼算法。"""
from __future__ import annotations

import contextlib
import io
import threading
import time
from dataclasses import asdict

import cv2
import numpy as np

from backend.src.config.model_assets import resolve_face_predictor
from backend.src.config.paths import DEFAULT_EMOTION_MODEL
from backend.src.mind_wandering.fusion import AttentionEngine, FrameSample

# 情绪 -> 疲劳 的映射规则参数（与 BodyRecognitionConfig 相互独立的融合参数）。
# 情绪：FER-2013 七类中没有"困倦"，为每种情绪设定对疲劳的贡献权重，用加权分
# 近似困倦程度——低落/呆滞类权重高，警觉/兴奋类权重低。
EMOTION_FATIGUE_WEIGHTS = {
    "angry": 0.1,
    "disgust": 0.1,
    "fear": 0.0,
    "happy": 0.0,
    "sad": 1.0,
    "surprise": 0.0,
    "neutral": 0.25,
}
EMOTION_DROWSY_SCORE_THRESHOLD = 0.5
EMOTION_DROWSY_SECONDS = 3.0


class AnalysisSession:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.blink_detector = None
        self.emotion_recognizer = None
        self.fatigue_detector = None
        self.face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        self.started_at = time.monotonic()
        self.frames = 0
        self.face_frames = 0
        self._emotion_drowsy_start = None
        # 走神/专注融合引擎：持有窗口缓冲、个体基线与状态机，必须按会话重置。
        self.attention = AttentionEngine()

    @property
    def ready(self) -> bool:
        return (
            self.blink_detector is not None
            and self.emotion_recognizer is not None
            and self.fatigue_detector is not None
        )

    def start(self) -> None:
        with self.lock:
            if self.ready:
                return
            from backend.src.algorithms.blink_detection.blink_detector import BlinkDetector
            from backend.src.algorithms.blink_detection.config import BlinkConfig
            from backend.src.algorithms.emotion.use_model import EmotionRecognizer
            from backend.src.algorithms.bodyrecognition.fatigue_detector import FatigueDetector
            from backend.src.algorithms.bodyrecognition.config import BodyRecognitionConfig

            model = DEFAULT_EMOTION_MODEL
            if not model.is_file():
                raise FileNotFoundError(f"情绪模型不存在：{model}")
            # dlib 关键点模型（OpenFace 疲劳检测依赖）不在版本库中，缺失时这里会自动
            # 下载并解压到 backend/models/dlib/，网络不可用则抛出带修复指引的错误。
            predictor_path = resolve_face_predictor()
            # 两个模型都成功后再更新会话，加载失败时释放已经创建的资源。
            detector = BlinkDetector(BlinkConfig(mode="robust"))
            try:
                # 旧模块的 Unicode 输出在部分 Windows 控制台会报编码错误。
                with contextlib.redirect_stdout(io.StringIO()):
                    recognizer = EmotionRecognizer(str(model))
                fatigue = FatigueDetector(BodyRecognitionConfig(predictor_path=str(predictor_path)))
            except Exception:
                detector.close()
                raise
            self.blink_detector = detector
            self.emotion_recognizer = recognizer
            self.fatigue_detector = fatigue
            self.started_at = time.monotonic()

    def close(self) -> None:
        """服务退出时释放 MediaPipe 模型资源。"""
        with self.lock:
            if self.blink_detector is not None:
                self.blink_detector.close()
            self.blink_detector = None
            self.emotion_recognizer = None
            if self.fatigue_detector is not None:
                self.fatigue_detector.close()
            self.fatigue_detector = None

    def reset(self) -> None:
        with self.lock:
            if self.blink_detector is not None:
                self.blink_detector.reset()
            if self.emotion_recognizer is not None and hasattr(self.emotion_recognizer, "history"):
                self.emotion_recognizer.history.clear()
            if self.fatigue_detector is not None:
                self.fatigue_detector.reset()
            self.started_at = time.monotonic()
            self.frames = 0
            self.face_frames = 0
            self._emotion_drowsy_start = None
            self.attention.reset()

    def analyze(self, frame: np.ndarray) -> dict:
        with self.lock:
            if not self.ready:
                raise RuntimeError("识别模型尚未加载")
            self.frames += 1
            blink = self.blink_detector.process_frame(frame)
            fatigue = self.fatigue_detector.process_frame(frame)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = self.face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))
            face_box = None
            emotion = None
            confidence = None
            probabilities = {}
            if len(faces):
                x, y, w, h = max(faces, key=lambda item: int(item[2]) * int(item[3]))
                face_box = [int(x), int(y), int(w), int(h)]
                roi = frame[y:y + h, x:x + w]
                emotion, confidence, probabilities = self.emotion_recognizer.predict(roi)
            if blink.face_detected:
                self.face_frames += 1
            elapsed = max(time.monotonic() - self.started_at, 1.0)
            fatigue_flags = self._combine_fatigue(blink, fatigue, probabilities)
            # 三路信号以同一时间戳进入融合层，保证窗口对齐不依赖帧序号。
            now = time.monotonic()
            self.attention.feed(FrameSample(
                t=now,
                face=bool(blink.face_detected),
                ear=blink.ear,
                threshold=blink.threshold,
                eye_closed=blink.state == "CLOSED",
                blink=bool(blink.blink_detected),
                emotion=emotion,
                confidence=confidence,
                probs=dict(probabilities) if probabilities else {},
            ))
            attention = self.attention.latest
            return {
                "frame_width": int(frame.shape[1]),
                "frame_height": int(frame.shape[0]),
                "face_detected": bool(blink.face_detected),
                "face_box": face_box,
                "ear": blink.ear,
                "threshold": blink.threshold,
                "eye_state": blink.state,
                "blink_detected": bool(blink.blink_detected),
                "blink_count": int(self.blink_detector.blink_count),
                "blink_rate_per_min": float(self.blink_detector.blink_count * 60.0 / elapsed),
                "valid_face_ratio": float(self.face_frames / self.frames),
                "emotion": emotion,
                "emotion_confidence": confidence,
                "emotion_probabilities": probabilities,
                "mar": fatigue.mar,
                "pitch": fatigue.pitch,
                "yaw": fatigue.yaw,
                "roll": fatigue.roll,
                "is_yawning": fatigue.is_yawning,
                "yawn_duration": fatigue.yawn_duration,
                "is_drowsy": fatigue.is_drowsy,
                "pose_drowsy": fatigue.pose_drowsy,
                "pose_lean_duration": fatigue.pose_lean_duration,
                "is_fatigued": fatigue_flags["is_fatigued"],
                "eye_drowsy": fatigue_flags["eye_drowsy"],
                "emotion_drowsy": fatigue_flags["emotion_drowsy"],
                "gaze_drowsy": fatigue_flags["gaze_drowsy"],
                "pose": asdict(fatigue.pose) if fatigue.pose is not None else None,
                # ---- 融合层新增，不改变以上既有字段的语义 ----
                "attention": attention.as_dict() if attention is not None else None,
                "attention_calibration": self.attention.calibration_progress(now),
            }

    def _combine_fatigue(self, blink, fatigue, emotion_probabilities) -> dict:
        """汇总各信号源，得到最终疲劳判定。

        眨眼、打哈欠/肢体动作、情绪三个信号任一满足即判定为疲劳；情绪采用
        "加权分 + 持续时长"判定（每种情绪对疲劳的贡献权重见顶部常量），
        视线疲劳由前端"屏幕中央注视区"判定，后端只保留字段占位。
        """
        # 眨眼：眼睛持续闭合（状态机 CLOSED 需连续多帧低 EAR，非单帧抖动）。
        eye_drowsy = bool(
            blink is not None and blink.face_detected and blink.state == "CLOSED"
        )
        # 打哈欠 + 肢体动作：FatigueDetector 内部已完成时长判定后置位。
        yawn_pose_drowsy = bool(fatigue is not None and fatigue.is_drowsy)

        now = time.monotonic()

        # 情绪 -> 疲劳：七类情绪概率按权重加权，加权分达到阈值且持续达时长后置位。
        emotion_score = (
            sum(
                emotion_probabilities.get(label, 0.0) * weight
                for label, weight in EMOTION_FATIGUE_WEIGHTS.items()
            )
            if emotion_probabilities
            else 0.0
        )
        if emotion_score >= EMOTION_DROWSY_SCORE_THRESHOLD:
            if self._emotion_drowsy_start is None:
                self._emotion_drowsy_start = now
            emotion_duration = now - self._emotion_drowsy_start
        else:
            self._emotion_drowsy_start = None
            emotion_duration = 0.0
        emotion_drowsy = emotion_duration >= EMOTION_DROWSY_SECONDS

        # 视线 -> 疲劳：由前端真实视线（MediaPipe 落点）相对"屏幕中央注视区"判定，
        # 后端无实时视线数据，此处仅保留接口字段，前端会把结果并入最终判定。
        gaze_drowsy = False

        is_fatigued = eye_drowsy or yawn_pose_drowsy or emotion_drowsy or gaze_drowsy
        return {
            "is_fatigued": is_fatigued,
            "eye_drowsy": eye_drowsy,
            "emotion_drowsy": emotion_drowsy,
            "gaze_drowsy": gaze_drowsy,
        }

