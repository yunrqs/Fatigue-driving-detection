import { useEffect, useRef, useState } from 'react';
import * as api from '../../features/monitoring/api';
import { captureVideo, playCamera, toJpeg } from '../../features/monitoring/camera';
import Sidebar from '../../features/monitoring/components/Sidebar';
import ResultPanels from '../../features/monitoring/components/ResultPanels';
import DriverHud from '../../features/monitoring/components/DriverHud';
import TripSummaryModal from '../../features/monitoring/components/TripSummaryModal';
import Icon from '../../components/Icon';
import type {
  AnalysisResult, ChartPoint, DriverEvent, Emotion, FatigueAssessment, FatigueLevel,
  Sensitivity, TripSummary,
} from '../../features/monitoring/types';
import { assessFatigue, SENSITIVITY_CONFIG } from '../../features/monitoring/fatigueScoring';
import { playAlarm, playChime, primeAudio, speak } from '../../features/monitoring/alerts';
import GazePanel from '../../features/gaze/components/GazePanel';
import { useGazePrediction } from '../../features/gaze/hooks/useGazePrediction';
import type { BodyPoseStatus } from '../../features/bodyrecognition/types';
import type { GazePoint } from '../../features/gaze/types';

// 屏幕中央注视区：视线落点在该矩形内视为「注视前方/看屏」，落到区域外（含屏幕外）
// 并持续一段时间即视为视线疲劳。判定时长由灵敏度档位决定（见 SENSITIVITY_CONFIG）。
const GAZE_REGION = { xMin: 0.2, xMax: 0.8, yMin: 0.2, yMax: 0.8 };

// 情绪中文标签，供摄像头画面人脸框叠加显示（与 ResultPanels 的情绪映射一致）。
const EMOTION_LABEL: Record<Emotion, string> = {
  angry: '愤怒', disgust: '厌恶', fear: '恐惧', happy: '愉悦',
  sad: '悲伤', surprise: '惊讶', neutral: '中性',
};

function inGazeRegion(point: GazePoint | null): boolean {
  if (!point || !point.inViewport) return false;
  return point.normalizedX >= GAZE_REGION.xMin && point.normalizedX <= GAZE_REGION.xMax
    && point.normalizedY >= GAZE_REGION.yMin && point.normalizedY <= GAZE_REGION.yMax;
}

// 上传到后端的帧做了水平镜像（captureVideo 内 scale(-1,1)），OpenPose 返回的
// left/right 与用户真实左右相反；这里交换左右字段让面板数据与真实肢体一致。
// 坐标值本身不改动，因此画面上的骨架标注位置不受影响。
function alignPoseSides(pose: BodyPoseStatus | null): BodyPoseStatus | null {
  if (!pose) return pose;
  return {
    ...pose,
    left_shoulder: pose.right_shoulder,
    right_shoulder: pose.left_shoulder,
    left_elbow: pose.right_elbow,
    right_elbow: pose.left_elbow,
    left_wrist: pose.right_wrist,
    right_wrist: pose.left_wrist,
    left_hip: pose.right_hip,
    right_hip: pose.left_hip,
    left_elbow_angle: pose.right_elbow_angle,
    right_elbow_angle: pose.left_elbow_angle,
    left_wrist_raise: pose.right_wrist_raise,
    right_wrist_raise: pose.left_wrist_raise,
  };
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '操作失败，请重试';
}

// OpenPose 上半身关键点名称，与后端 BodyPoseResult 字段保持一致。
type PoseKey = 'nose' | 'neck' | 'left_shoulder' | 'right_shoulder'
  | 'left_elbow' | 'right_elbow' | 'left_wrist' | 'right_wrist'
  | 'left_hip' | 'right_hip';

// 连接顺序决定了骨架连线；相邻两点画一条线。
const POSE_BONES: ReadonlyArray<[PoseKey, PoseKey]> = [
  ['nose', 'neck'],
  ['neck', 'left_shoulder'], ['neck', 'right_shoulder'],
  ['left_shoulder', 'right_shoulder'],
  ['left_shoulder', 'left_elbow'], ['left_elbow', 'left_wrist'],
  ['right_shoulder', 'right_elbow'], ['right_elbow', 'right_wrist'],
  ['left_shoulder', 'left_hip'], ['right_shoulder', 'right_hip'],
  ['left_hip', 'right_hip'],
];

function drawPoseKeypoints(context: CanvasRenderingContext2D, pose: BodyPoseStatus) {
  const points: Record<PoseKey, [number, number] | null> = {
    nose: pose.nose, neck: pose.neck,
    left_shoulder: pose.left_shoulder, right_shoulder: pose.right_shoulder,
    left_elbow: pose.left_elbow, right_elbow: pose.right_elbow,
    left_wrist: pose.left_wrist, right_wrist: pose.right_wrist,
    left_hip: pose.left_hip, right_hip: pose.right_hip,
  };
  const color = '#b48cff';
  context.strokeStyle = color;
  context.fillStyle = color;
  context.lineWidth = 2;
  context.setLineDash([]);
  for (const [a, b] of POSE_BONES) {
    const start = points[a];
    const end = points[b];
    if (!start || !end) continue;
    context.beginPath();
    context.moveTo(start[0], start[1]);
    context.lineTo(end[0], end[1]);
    context.stroke();
  }
  for (const key of Object.keys(points) as PoseKey[]) {
    const point = points[key];
    if (!point) continue;
    context.beginPath();
    context.arc(point[0], point[1], 3, 0, Math.PI * 2);
    context.fill();
  }
}

const LEVEL_RANK: Record<FatigueLevel, number> = { none: 0, mild: 1, moderate: 2, severe: 3 };

export default function App() {
  // useState 保存需要显示到页面的数据；useRef 保存视频、媒体流和请求等对象。
  const [cameraOn, setCameraOn] = useState(false);
  const [cameraLoading, setCameraLoading] = useState(false);
  const [modelLoading, setModelLoading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [service, setService] = useState({ online: false, text: '服务检查中' });
  const [clock, setClock] = useState(new Date().toLocaleTimeString('zh-CN', { hour12: false }));
  const [resolution, setResolution] = useState('—');
  const [videoAspectRatio, setVideoAspectRatio] = useState(16 / 9);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [fps, setFps] = useState('0.0');
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [history, setHistory] = useState<ChartPoint[]>([]);
  const [toast, setToast] = useState({ message: '', error: false });
  const [showPoseKeypoints, setShowPoseKeypoints] = useState(false);
  // 视图切换：摄像头页放实时画面与控制，数据页放结果面板。视频元素始终挂载，切换不影响采集与分析。
  const [view, setView] = useState<'camera' | 'data'>('camera');

  // —— 驾驶辅助（真实驾驶场景）相关状态 ——
  const [muted, setMuted] = useState(false);
  const [nightMode, setNightMode] = useState(false);
  const [sensitivity, setSensitivity] = useState<Sensitivity>('standard');
  const [fatigueAssessment, setFatigueAssessment] = useState<FatigueAssessment | null>(null);
  const [driveSeconds, setDriveSeconds] = useState(0);
  const [events, setEvents] = useState<DriverEvent[]>([]);
  const [tripSummary, setTripSummary] = useState<TripSummary | null>(null);

  const videoRef = useRef<HTMLVideoElement>(null);
  const gaze = useGazePrediction(videoRef, cameraOn);
  const [gazeDrowsy, setGazeDrowsy] = useState(false);
  const gazeOutsideSinceRef = useRef<number | null>(null);
  const overlayRef = useRef<HTMLCanvasElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const mountedRef = useRef(true);
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const pendingFrameRef = useRef<Promise<void> | null>(null);
  // 每次停止时更新编号，旧请求返回后发现编号不同，就不再更新页面。
  const runIdRef = useRef(0);

  // 帧循环里读这些值用 ref（避免旧闭包读到过期的 state）：gazeDrowsy 由独立 effect 维护、
  // sensitivity / muted 由用户在侧栏切换，都不可能通过调整帧循环依赖来可靠同步。
  const gazeDrowsyRef = useRef(false);
  const mutedRef = useRef(false);
  const sensitivityRef = useRef<Sensitivity>('standard');
  const fatigueSinceRef = useRef<number | null>(null);
  const lastFatigueLevelRef = useRef<FatigueLevel>('none');
  const lastAttentionStateRef = useRef<'deliberate_mw' | 'spontaneous_mw' | null>(null);
  const tripStartedAtRef = useRef<number | null>(null);
  const eventIdRef = useRef(0);

  useEffect(() => { mutedRef.current = muted; }, [muted]);
  useEffect(() => { sensitivityRef.current = sensitivity; }, [sensitivity]);

  // 视线疲劳：视线落点持续位于「屏幕中央注视区」之外（含屏幕外）达到时长阈值后置位。
  useEffect(() => {
    const point = gaze.frame.point;
    const active = gaze.status === 'running' && gaze.calibrated;
    const thresholdSeconds = SENSITIVITY_CONFIG[sensitivity].gazeOutsideSeconds;
    if (!active || !point) {
      gazeOutsideSinceRef.current = null;
      gazeDrowsyRef.current = false;
      setGazeDrowsy(false);
      return;
    }
    if (!inGazeRegion(point)) {
      if (gazeOutsideSinceRef.current === null) gazeOutsideSinceRef.current = performance.now();
      const drowsy = performance.now() - gazeOutsideSinceRef.current >= thresholdSeconds * 1000;
      gazeDrowsyRef.current = drowsy;
      setGazeDrowsy(drowsy);
    } else {
      gazeOutsideSinceRef.current = null;
      gazeDrowsyRef.current = false;
      setGazeDrowsy(false);
    }
  }, [gaze.frame.point, gaze.calibrated, gaze.status, sensitivity]);

  // 连续驾驶时长：以一次行程开始时刻为起点每秒推进，结束监测或重置统计时清零。
  useEffect(() => {
    const timer = setInterval(() => {
      if (tripStartedAtRef.current != null) {
        setDriveSeconds(Math.floor((Date.now() - tripStartedAtRef.current) / 1000));
      }
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  function addEvent(kind: DriverEvent['kind'], label: string) {
    const entry: DriverEvent = {
      id: ++eventIdRef.current,
      time: new Date().toLocaleTimeString('zh-CN', { hour12: false }),
      kind,
      label,
    };
    setEvents((previous) => [entry, ...previous].slice(0, 100));
  }

  // 疲劳等级跃迁 / 走神触发时记录事件并声光提醒；用 ref 去重，避免每帧重复播报。
  useEffect(() => {
    const level = fatigueAssessment?.level ?? 'none';
    if (level !== lastFatigueLevelRef.current) {
      if (level !== 'none') {
        const label = level === 'severe' ? '重度疲劳' : level === 'moderate' ? '中度疲劳' : '轻度疲劳';
        addEvent(level as DriverEvent['kind'], label);
        if (!mutedRef.current) {
          if (level === 'severe') {
            playAlarm();
            speak('检测到疲劳驾驶，请立即靠边停车休息');
          } else if (level === 'moderate') {
            playChime();
            speak('请注意休息，保持专注');
          } else {
            playChime();
          }
        }
      }
      lastFatigueLevelRef.current = level;
    }
    const attention = result?.attention?.state;
    if (attention === 'deliberate_mw' || attention === 'spontaneous_mw') {
      if (lastAttentionStateRef.current !== attention) {
        addEvent('distract', '注意力分散');
        if (!mutedRef.current) playChime();
        lastAttentionStateRef.current = attention;
      }
    } else {
      lastAttentionStateRef.current = null;
    }
  }, [fatigueAssessment, result]);

  function notify(message: string, error = false) {
    if (!mountedRef.current) return;
    clearTimeout(toastTimerRef.current);
    setToast({ message, error });
    toastTimerRef.current = setTimeout(() => setToast({ message: '', error: false }), 3200);
  }

  useEffect(() => {
    mountedRef.current = true;
    let cancelled = false;
    async function refreshHealth() {
      try {
        const health = await api.checkHealth();
        if (!cancelled) setService({ online: true, text: health.ready ? '识别服务就绪' : '服务在线 · 模型待加载' });
      } catch {
        if (!cancelled) setService({ online: false, text: '识别服务离线' });
      }
    }
    void refreshHealth();
    const healthTimer = setInterval(refreshHealth, 10000);
    const clockTimer = setInterval(() => setClock(new Date().toLocaleTimeString('zh-CN', { hour12: false })), 1000);
    return () => {
      cancelled = true;
      mountedRef.current = false;
      runIdRef.current += 1;
      clearInterval(healthTimer);
      clearInterval(clockTimer);
      clearTimeout(toastTimerRef.current);
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    };
  }, []);

  function clearOverlay() {
    const canvas = overlayRef.current;
    if (canvas) canvas.getContext('2d')?.clearRect(0, 0, canvas.width, canvas.height);
  }

  function pauseAnalysis() {
    runIdRef.current += 1;
    setAnalyzing(false);
    setFps('0.0');
    clearOverlay();
  }

  async function toggleCamera() {
    if (streamRef.current) {
      pauseAnalysis();
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
      if (videoRef.current) videoRef.current.srcObject = null;
      setCameraOn(false);
      setResolution('—');
      return;
    }
    setCameraLoading(true);
    try {
      if (!navigator.mediaDevices) throw new Error('请通过 localhost、127.0.0.1 或 HTTPS 打开页面');
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: 'user' }, audio: false,
      });
      const video = videoRef.current;
      if (!mountedRef.current || !video) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      streamRef.current = stream;
      video.srcObject = stream;
      await playCamera(video);
      if (!mountedRef.current) return;
      setResolution(`${video.videoWidth}×${video.videoHeight}`);
      setCameraOn(true);
      notify('摄像头已开启，画面只在本机处理。');
    } catch (error) {
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
      if (videoRef.current) videoRef.current.srcObject = null;
      notify(`无法开启摄像头：${errorMessage(error)}`, true);
    } finally {
      if (mountedRef.current) setCameraLoading(false);
    }
  }

  async function startAnalysis() {
    if (!streamRef.current || analyzing || modelLoading || resetting) return;
    const runId = runIdRef.current;
    // 在用户手势内激活音频上下文，否则疲劳告警音会被浏览器静音策略拦截。
    primeAudio();
    setModelLoading(true);
    try {
      // 先等暂停前的请求结束，确保服务器不会同时处理两帧。
      await pendingFrameRef.current;
      await api.startSession();
      if (!mountedRef.current || runId !== runIdRef.current || !streamRef.current) return;
      setService({ online: true, text: '识别服务就绪' });
      setAnalyzing(true);
      // 首次开始识别视为一次行程的起点；暂停后继续不重置时长。
      if (tripStartedAtRef.current == null) tripStartedAtRef.current = Date.now();
      notify('情绪识别与眨眼检测已启动。');
    } catch (error) {
      if (runId === runIdRef.current) notify(errorMessage(error), true);
    } finally {
      if (mountedRef.current) setModelLoading(false);
    }
  }

  useEffect(() => {
    if (!analyzing) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const runId = runIdRef.current;
    const frameTimes: number[] = [];
    let lastCompleted = performance.now();

    async function sendFrame() {
      const video = videoRef.current;
      if (!video || cancelled || runId !== runIdRef.current) return;
      const started = performance.now();
      try {
        const blob = await toJpeg(captureVideo(video, 640));
        if (cancelled || runId !== runIdRef.current) return;
        const nextResult = await api.analyzeFrame(blob);
        if (cancelled || runId !== runIdRef.current) return;
        setResult({ ...nextResult, pose: alignPoseSides(nextResult.pose) });
        setHistory((previous) => [...previous, { ear: nextResult.ear, threshold: nextResult.threshold }].slice(-80));

        // 疲劳评估：结合视线判定与持续时长，得出评分与分级。
        const fatiguedNow = nextResult.is_fatigued || gazeDrowsyRef.current;
        const nowMs = performance.now();
        if (fatiguedNow) {
          if (fatigueSinceRef.current == null) fatigueSinceRef.current = nowMs;
        } else {
          fatigueSinceRef.current = null;
        }
        const fatigueSeconds = fatiguedNow && fatigueSinceRef.current != null
          ? (nowMs - fatigueSinceRef.current) / 1000
          : 0;
        setFatigueAssessment(assessFatigue(nextResult, gazeDrowsyRef.current, fatigueSeconds, SENSITIVITY_CONFIG[sensitivityRef.current]));

        const completed = performance.now();
        frameTimes.push(completed - lastCompleted);
        lastCompleted = completed;
        if (frameTimes.length > 20) frameTimes.shift();
        const average = frameTimes.reduce((sum, value) => sum + value, 0) / frameTimes.length;
        setFps((1000 / average).toFixed(1));
        // 请求完成后再安排下一帧，慢速模型不会造成请求堆积。
        timer = setTimeout(tick, Math.max(0, 220 - (completed - started)));
      } catch (error) {
        if (!cancelled && runId === runIdRef.current) {
          pauseAnalysis();
          notify(errorMessage(error), true);
        }
      }
    }

    function tick() { pendingFrameRef.current = sendFrame(); }
    tick();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [analyzing]);

  useEffect(() => {
    const canvas = overlayRef.current;
    if (!canvas) return;
    const context = canvas.getContext('2d');
    if (!context) return;
    context.clearRect(0, 0, canvas.width, canvas.height);
    if (!analyzing || !cameraOn || !result) return;
    canvas.width = result.frame_width;
    canvas.height = result.frame_height;
    if (result.face_box) {
      const [x, y, width, height] = result.face_box;
      const color = result.blink_detected ? '#ffbd68' : '#42e8d1';
      context.strokeStyle = color;
      context.lineWidth = 2;
      context.setLineDash([12, 7]);
      context.strokeRect(x, y, width, height);
      context.setLineDash([]);

      // 人脸框上方叠加情绪标签：情绪 + 置信度 + 睁/闭眼状态，与框绑定显示。
      const emotionText = result.emotion ? EMOTION_LABEL[result.emotion] : '—';
      const confText = result.emotion_confidence != null ? `${Math.round(result.emotion_confidence * 100)}%` : '';
      const stateText = result.blink_detected ? '闭眼' : '睁眼';
      const label = `${emotionText}${confText ? ` ${confText}` : ''} · ${stateText}`;

      context.font = '12px "Microsoft YaHei", system-ui, sans-serif';
      const textWidth = context.measureText(label).width;
      const padX = 8;
      const boxHeight = 21;
      const labelX = x;
      const labelY = Math.max(0, y - boxHeight - 4);
      context.fillStyle = 'rgba(7,16,29,.85)';
      context.fillRect(labelX, labelY, textWidth + padX * 2, boxHeight);
      context.fillStyle = color;
      context.textBaseline = 'middle';
      context.fillText(label, labelX + padX, labelY + boxHeight / 2 + 1);
      context.textBaseline = 'alphabetic';
    }
    if (showPoseKeypoints && result.pose?.person_detected) {
      drawPoseKeypoints(context, result.pose);
    }
  }, [result, analyzing, cameraOn, showPoseKeypoints]);

  function clearTripState() {
    fatigueSinceRef.current = null;
    lastFatigueLevelRef.current = 'none';
    lastAttentionStateRef.current = null;
    tripStartedAtRef.current = null;
    setFatigueAssessment(null);
    setDriveSeconds(0);
    setEvents([]);
  }

  async function resetStats() {
    if (resetting || modelLoading) return;
    setResetting(true);
    pauseAnalysis();
    try {
      // 旧帧完成后再重置后端，避免旧帧把计数重新加回来。
      await pendingFrameRef.current;
      await api.resetSession();
      if (!mountedRef.current) return;
      setResult(null);
      setHistory([]);
      clearTripState();
      notify('统计已重置，点击“开始识别”继续。');
    } catch (error) {
      notify(`重置失败：${errorMessage(error)}`, true);
    } finally {
      if (mountedRef.current) setResetting(false);
    }
  }

  function endTrip() {
    const fatigueEvents = events.filter((event) => event.kind === 'mild' || event.kind === 'moderate' || event.kind === 'severe');
    const maxLevel = fatigueEvents.reduce<FatigueLevel>((max, event) => {
      const kind = event.kind as FatigueLevel;
      return LEVEL_RANK[kind] > LEVEL_RANK[max] ? kind : max;
    }, 'none');
    const summary: TripSummary = {
      startedAt: tripStartedAtRef.current
        ? new Date(tripStartedAtRef.current).toLocaleTimeString('zh-CN', { hour12: false })
        : '—',
      endedAt: new Date().toLocaleTimeString('zh-CN', { hour12: false }),
      durationSeconds: driveSeconds,
      fatigueEventCount: fatigueEvents.length,
      maxLevel,
    };
    setTripSummary(summary);
    void resetStats();
  }

  function saveCapture() {
    if (!streamRef.current || !videoRef.current) return;
    try {
      const video = videoRef.current;
      const canvas = captureVideo(video, video.videoWidth);
      const link = document.createElement('a');
      link.download = `focuslens-${new Date().toISOString().replace(/[:.]/g, '-')}.jpg`;
      link.href = canvas.toDataURL('image/jpeg', 0.92);
      link.click();
      notify('当前画面已保存。');
    } catch (error) { notify(errorMessage(error), true); }
  }

  function updateVideoSize() {
    const video = videoRef.current;
    if (video?.videoWidth && video.videoHeight) {
      setVideoAspectRatio(video.videoWidth / video.videoHeight);
      setResolution(`${video.videoWidth}×${video.videoHeight}`);
    }
  }

  const fatigued = (result?.is_fatigued ?? false) || gazeDrowsy;
  const attentionState = result?.attention?.state;
  const distracted = attentionState === 'deliberate_mw' || attentionState === 'spontaneous_mw';
  const faceDetected = analyzing && (result?.face_detected ?? false);

  return <div className={`app-shell${sidebarCollapsed ? ' sidebar-collapsed' : ''}${view === 'data' ? ' view-data' : ''}${nightMode ? ' night-mode' : ''}`}>
    <Sidebar cameraOn={cameraOn} cameraLoading={cameraLoading} modelLoading={modelLoading}
      gaze={gaze} collapsed={sidebarCollapsed} onToggleCollapsed={() => setSidebarCollapsed(value => !value)}
      serviceOnline={service.online} serviceText={service.text}
      analyzing={analyzing} resetting={resetting} onCamera={toggleCamera} onStart={startAnalysis}
      onPause={pauseAnalysis} onReset={resetStats} onCapture={saveCapture}
      showPoseKeypoints={showPoseKeypoints} onTogglePoseKeypoints={setShowPoseKeypoints}
      muted={muted} onToggleMuted={() => setMuted(value => !value)}
      nightMode={nightMode} onToggleNightMode={() => setNightMode(value => !value)}
      sensitivity={sensitivity} onSensitivityChange={setSensitivity}
      onEndTrip={endTrip}
      view={view} onViewChange={setView} />
    <main className="workspace">
      <header className="topbar">
        <div><p className="eyebrow">FOCUSLENS / 视觉状态实验台</p><h1>情绪与眨眼监测</h1></div>
        <div className="top-status">
          <span className={`status-pill ${service.online ? 'online' : 'offline'}`}><i />{service.text}</span>
          <time id="clock">{clock}</time>
        </div>
      </header>
      <section className="dashboard">
        <article className="panel camera-panel">
          <div className="panel-heading">
            <h2>实时画面</h2>
            <span className={`fatigue-status${fatigued ? ' drowsy' : ''}`}>{result || gazeDrowsy ? (fatigued ? '疲劳' : '正常') : '—'}</span>
            <div className={`live-badge${analyzing ? ' live' : ''}`}><i /><span>{analyzing ? '实时分析' : cameraOn ? '已暂停' : '待机'}</span></div>
          </div>
          <div className="video-stage" style={{ aspectRatio: videoAspectRatio }}>
            <video ref={videoRef} id="camera" playsInline muted onLoadedMetadata={updateVideoSize} onResize={updateVideoSize} />
            <canvas ref={overlayRef} id="overlay" aria-hidden="true" />
            <div className={`video-placeholder${cameraOn ? ' hidden' : ''}`}>
              <div className="scan-symbol"><Icon name="camera" /></div><strong>摄像头尚未开启</strong>
              <p>点击左侧「开启摄像头」开始采集</p>
            </div>
            <div className="frame-corners" aria-hidden="true"><i /><i /><i /><i /></div>
            <DriverHud assessment={fatigueAssessment} distracted={distracted} faceDetected={faceDetected}
              driveSeconds={driveSeconds} analyzing={analyzing} />
          </div>
          <div className="camera-footer">
            <span>分辨率 <b>{resolution}</b></span><span>分析 FPS <b>{fps}</b></span>
            <span>人脸状态 <b style={{ color: analyzing && result?.face_detected ? 'var(--cyan)' : undefined }}>{!analyzing ? '未检测' : result?.face_detected ? '已锁定' : '未检测'}</b></span>
          </div>
        </article>
        <ResultPanels result={result} history={history} gazeDrowsy={gazeDrowsy}
          assessment={fatigueAssessment} events={events} driveSeconds={driveSeconds} />
        <GazePanel gaze={gaze} />
      </section>
      <p className={`toast${toast.message ? ' show' : ''}${toast.error ? ' error' : ''}`} role="status">{toast.message}</p>
      {tripSummary && <TripSummaryModal summary={tripSummary} onClose={() => setTripSummary(null)} />}
    </main>
  </div>;
}