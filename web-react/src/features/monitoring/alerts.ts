// 声音告警：Web Audio 合成提示音 + 浏览器语音合成，均为零依赖。
// 所有函数都静默失败，不影响识别主流程。

let audioContext: AudioContext | null = null;

function getAudioContext(): AudioContext | null {
  try {
    if (!audioContext) audioContext = new AudioContext();
    if (audioContext.state === 'suspended') void audioContext.resume();
    return audioContext;
  } catch {
    return null;
  }
}

// 在用户手势（如点击「开始识别」）内调用，提前创建并激活 AudioContext。
// 浏览器自动播放策略要求音频上下文必须由用户手势解锁，否则后续告警音会被静音。
export function primeAudio(): void {
  getAudioContext();
}

// 按同样时间间隔依次播放一组音高，形成琶音或连续脉冲。
function scheduleTones(frequencies: number[], type: OscillatorType, step: number, peak: number): void {
  const context = getAudioContext();
  if (!context) return;
  const now = context.currentTime;
  frequencies.forEach((frequency, index) => {
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    oscillator.type = type;
    oscillator.frequency.value = frequency;
    const start = now + index * step;
    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(peak, start + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + step);
    oscillator.connect(gain).connect(context.destination);
    oscillator.start(start);
    oscillator.stop(start + step);
  });
}

// 短促上升琶音，用于轻度/中度提醒。
export function playChime(): void {
  scheduleTones([660, 784, 988], 'sine', 0.18, 0.3);
}

// 低沉连续脉冲，比提示音更抢耳，用于重度疲劳。
export function playAlarm(): void {
  scheduleTones([440, 440, 440], 'square', 0.3, 0.22);
}

// 语音播报：合成不了或未授权时静默失败。
export function speak(text: string): void {
  try {
    if (!('speechSynthesis' in window)) return;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = 'zh-CN';
    utterance.rate = 1.05;
    window.speechSynthesis.speak(utterance);
  } catch {
    // 忽略语音合成失败。
  }
}