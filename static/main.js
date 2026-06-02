/* ════════════════════════════════════════════════════════════
   SORA // NEXUS — main.js
   ════════════════════════════════════════════════════════════ */

// ── Core State ───────────────────────────────────────────────
let ws              = null;
let audioCtx        = null;
let audioQueue      = [];
let isPlayingAudio  = false;

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
const recognition = new SpeechRecognition();
recognition.lang            = 'ja-JP';
recognition.interimResults  = false;
recognition.continuous      = false;

const startBtn       = document.getElementById('start-btn');
const chatLog        = document.getElementById('chat-log');
const micIndicator   = document.getElementById('mic-indicator');
const optionsOverlay = document.getElementById('options-overlay');

let isRecognitionActive = false;
let isAiTurn            = false;
let isStarted           = false;
let isOptionsOpen       = false;
let idleTimer           = null;
let isVisualParamChanged    = false;
let isPendingSettingsSync   = false;
let waitingPromptEl         = null;
let cameraOptionsMeta       = [];
let currentEmotionTheme     = 'neutral';

// クイック設定状態
let qcOpen       = false;
let voiceMuted   = false;
let cameraHidden = false;

// ── Particle System State ─────────────────────────────────────
const PARTICLE_MAX  = 45;
let   particles     = [];
let   particleCanvas, particleCtx;

// ── Emotion Theme ─────────────────────────────────────────────
const EMOTION_LABELS = {
    neutral:   '◈ neutral',
    happy:     '◈ happy',
    sad:       '◈ sad',
    angry:     '◈ angry',
    surprised: '◈ surprised',
};

function setEmotionTheme(emotion) {
    if (emotion === currentEmotionTheme) return;
    currentEmotionTheme = emotion;

    // CSS class swap
    document.body.className = document.body.className
        .replace(/\bemo-\w+/g, '').trim();
    if (emotion !== 'neutral') document.body.classList.add('emo-' + emotion);

    // Status bar label
    const sbEmo = document.getElementById('sb-emotion');
    if (sbEmo) sbEmo.textContent = EMOTION_LABELS[emotion] || '◈ ' + emotion;

    // Emotion flash
    const flash = document.getElementById('emotion-flash');
    if (flash) {
        flash.classList.remove('flash');
        void flash.offsetWidth; // reflow
        flash.classList.add('flash');
    }
}

// ── Status HUD ────────────────────────────────────────────────
const STATUS_LABELS = {
    STANDBY:     'STANDBY',
    LISTENING:   'LISTENING...',
    THINKING:    'THINKING...',
    SPEAKING:    'SPEAKING',
    RECONNECTING:'RECONNECTING',
};

function updateStatusMode(mode) {
    const el = document.getElementById('sb-mode');
    if (el) el.textContent = STATUS_LABELS[mode] || mode;
}

// ── Game Badge ────────────────────────────────────────────────
function updateGameBadge(active) {
    const badge = document.getElementById('game-badge');
    if (badge) badge.style.display = active ? 'block' : 'none';
}

// ── Settings Persistence (localStorage) ──────────────────────
const LS_KEY = 'sora_settings_v1';

function saveSettings() {
    try {
        const d = {
            bright:    document.getElementById('param-bright')?.value,
            contrast:  document.getElementById('param-contrast')?.value,
            saturate:  document.getElementById('param-saturate')?.value,
            vrmX:      document.getElementById('param-vrm-x')?.value,
            vrmY:      document.getElementById('param-vrm-y')?.value,
            vrmScale:  document.getElementById('param-vrm-scale')?.value,
            rate:      document.getElementById('param-rate')?.value,
            pitch:     document.getElementById('param-pitch')?.value,
            voice:     document.getElementById('param-voice')?.value,
            mirror:    document.getElementById('param-mirror')?.value,
            camera:    document.getElementById('param-camera')?.value,
        };
        localStorage.setItem(LS_KEY, JSON.stringify(d));
    } catch(_) {}
}

function loadSettings() {
    try {
        const raw = localStorage.getItem(LS_KEY);
        if (!raw) return;
        const d = JSON.parse(raw);
        const set = (id, val) => { const el = document.getElementById(id); if (el && val != null) el.value = val; };
        set('param-bright',     d.bright);
        set('param-contrast',   d.contrast);
        set('param-saturate',   d.saturate);
        set('param-vrm-x',      d.vrmX);
        set('param-vrm-y',      d.vrmY);
        set('param-vrm-scale',  d.vrmScale);
        set('param-rate',       d.rate);
        set('param-pitch',      d.pitch);
        set('param-voice',      d.voice);
        set('param-mirror',     d.mirror);
        set('param-camera',     d.camera);
        // Refresh all displayed values
        updateCSSFilters();
        syncVrmParams();
        updateRatePitchLabels();
        applyMirrorValue(d.mirror);
    } catch(_) {}
}

// ── Quick Config Panel ────────────────────────────────────────
function initQuickConfig() {
    const btn   = document.getElementById('config-btn');
    const panel = document.getElementById('quick-config-panel');
    if (!btn || !panel) return;

    btn.addEventListener('click', e => {
        e.stopPropagation();
        qcOpen = !qcOpen;
        panel.classList.toggle('open', qcOpen);
        btn.classList.toggle('open', qcOpen);
    });

    document.addEventListener('click', e => {
        if (qcOpen && !panel.contains(e.target) && e.target !== btn) {
            qcOpen = false;
            panel.classList.remove('open');
            btn.classList.remove('open');
        }
    });

    document.getElementById('toggle-mirror')?.addEventListener('click', toggleMirror);
    document.getElementById('toggle-voice')?.addEventListener('click',  toggleVoice);
    document.getElementById('toggle-camera')?.addEventListener('click', toggleCamera);
}

function setToggleState(id, active) {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.toggle('active',   active);
    el.classList.toggle('inactive', !active);
    const stateEl = el.querySelector('.qc-state');
    if (stateEl) stateEl.textContent = active ? 'ACTIVE' : 'MUTED';
}

function toggleMirror() {
    const sel     = document.getElementById('param-mirror');
    const isOn    = sel.value !== 'true';
    sel.value     = isOn ? 'true' : 'false';
    applyMirrorValue(sel.value);
    setToggleState('toggle-mirror', isOn);
    sendSettingsToServer();
}

function toggleVoice() {
    voiceMuted = !voiceMuted;
    setToggleState('toggle-voice', !voiceMuted);

    // 音声出力ミュート
    if (window.audioGainNode) {
        window.audioGainNode.gain.value = voiceMuted ? 0.0 : 1.0;
    }

    if (voiceMuted) {
        // 音声認識を停止、マイクインジケーター消灯
        try { recognition.stop(); } catch(_) {}
        isRecognitionActive = false;
        micIndicator.style.display = 'none';
        updateStatusMode('STANDBY');
    } else {
        // 音声認識を再開
        if (isStarted && !isAiTurn && !window.isSpeaking && !isOptionsOpen) {
            startListening();
        }
    }
}

function toggleCamera() {
    cameraHidden = !cameraHidden;
    setToggleState('toggle-camera', !cameraHidden);
    const cvs      = document.getElementById('camera-preview-canvas');
    const noSignal = document.getElementById('camera-no-signal');
    if (cvs)      cvs.style.display      = cameraHidden ? 'none'  : 'block';
    if (noSignal) noSignal.style.display = cameraHidden ? 'block' : 'none';
}

// ── Camera Utils ──────────────────────────────────────────────
function guessCameraType(label = '') {
    const l = label.toLowerCase();
    if (l.includes('usb') || l.includes('webcam') || l.includes('external')) return 'usb';
    if (l.includes('integrated') || l.includes('internal') || l.includes('built-in') || l.includes('builtin')) return 'internal';
    return 'unknown';
}

async function refreshCameraOptions(requestPermission = false) {
    const cameraSelect = document.getElementById('param-camera');
    if (!cameraSelect || !navigator.mediaDevices?.enumerateDevices) return;
    let stream = null;
    try {
        if (requestPermission) stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
        const devices = await navigator.mediaDevices.enumerateDevices();
        const cameras = devices.filter(d => d.kind === 'videoinput');
        if (!cameras.length) return;
        const prev = cameraSelect.value;
        cameraOptionsMeta = cameras.map((cam, idx) => ({
            index: idx,
            label: cam.label || `Camera ${idx}`,
            type:  guessCameraType(cam.label || ''),
        }));
        cameraSelect.innerHTML = '';
        cameraOptionsMeta.forEach(cam => {
            const opt = document.createElement('option');
            opt.value = String(cam.index);
            const tl = cam.type === 'usb' ? 'USB' : (cam.type === 'internal' ? 'Internal' : 'Unknown');
            opt.textContent = `Camera ${cam.index} (${tl}: ${cam.label})`;
            cameraSelect.appendChild(opt);
        });
        if ([...cameraSelect.options].some(o => o.value === prev)) cameraSelect.value = prev;
        else cameraSelect.value = '0';
    } catch(e) {
        console.warn('camera list refresh failed:', e);
    } finally {
        if (stream) stream.getTracks().forEach(t => t.stop());
    }
}

// ── WebSocket ─────────────────────────────────────────────────
function connectWebSocket() {
    console.log('【通信管理】WebSocket 接続要求を開始します...');
    ws = new WebSocket('ws://localhost:8000/ws');

    ws.onopen = () => {
        console.log('【通信管理】FastAPI バックエンドとのパイプライン接続に成功しました。');
        updateStatusMode('STANDBY');
        if (isStarted) sendSettingsToServer();
    };

    ws.onmessage = async (event) => {
        if (!isStarted) return;
        const msg = JSON.parse(event.data);

        if (msg.type === 'visitor_status') {
            const todayEl = document.getElementById('sys-today-count');
            const nowEl   = document.getElementById('sys-now-count');
            if (todayEl) todayEl.textContent = `${msg.today} 人`;
            if (nowEl) {
                if (msg.current > 0) {
                    nowEl.textContent = `${msg.current} 人検知中`;
                    nowEl.style.color = '#00ff88';
                } else {
                    nowEl.textContent = '-- 人';
                    nowEl.style.color = '';
                }
            }
            return;
        }

        if (msg.type === 'system_error') {
            // エラー内容をチャットログに赤字で表示
            if (isStarted) {
                const div = document.createElement('div');
                div.className = 'msg-system-error';
                div.textContent = msg.text;
                chatLog.appendChild(div);
                chatLog.scrollTop = chatLog.scrollHeight;
            }
            return;
        }

        if (['register_step','register_captured','register_done','register_failed'].includes(msg.type)) {
            handleRegisterMessage(msg);
            return;
        }

        if (msg.type === 'camera_preview') {
            // <img>不使用。canvas に直接描画してブロークンアイコンを根絶
            if (!cameraHidden) {
                const cvs = document.getElementById('camera-preview-canvas');
                if (cvs) {
                    const img = new Image();
                    img.onload = () => {
                        cvs.width  = img.width;
                        cvs.height = img.height;
                        cvs.getContext('2d').drawImage(img, 0, 0);
                    };
                    img.src = 'data:image/jpeg;base64,' + msg.image;
                }
            }
            return;
        }

        if (msg.type === 'audio') {
            stopIdleTimer();
            let rawText = msg.text;
            let emotion = msg.emotion || 'neutral';
            const m = rawText.match(/\[emotion:(.*?)\]/);
            if (m) { emotion = m[1]; rawText = rawText.replace(/\[emotion:.*?\]/, ''); }
            if (msg.command) executeVoiceCommand(msg.command);
            audioQueue.push({ bufferArray: bytesToBuffer(msg.audio), text: rawText, emotion });
            if (!isPlayingAudio) playNextInQueue();
        }
    };

    ws.onclose = (e) => {
        console.warn('【通信管理】WebSocket 切断。3秒後に自動再接続します...', e.reason);
        updateStatusMode('RECONNECTING');
        stopIdleTimer();
        setTimeout(connectWebSocket, 3000);
    };

    ws.onerror = err => console.error('【通信管理】WebSocket エラー:', err);
}

connectWebSocket();

// ── Idle Timer ────────────────────────────────────────────────
function resetIdleTimer() {
    stopIdleTimer();
    if (!isStarted || isOptionsOpen || window.isSpeaking || isAiTurn) return;
    const ms = Math.floor(30000 + Math.random() * 60000);
    console.log(`【タイマー稼働】独り言まで: ${(ms/1000).toFixed(1)}s`);
    idleTimer = setTimeout(() => {
        if (!isStarted || window.isSpeaking || isAiTurn || isOptionsOpen) return;
        isAiTurn = true;
        updateStatusMode('THINKING');
        try { recognition.stop(); } catch(_) {}
        isRecognitionActive = false;
        micIndicator.style.display = 'none';
        if (ws?.readyState === WebSocket.OPEN)
            ws.send(JSON.stringify({ type: 'idle_soliloquy' }));
    }, ms);
}

function stopIdleTimer() {
    if (idleTimer) { clearTimeout(idleTimer); idleTimer = null; }
}

// ── System Activation ─────────────────────────────────────────
function activateSystem() {
    if (startBtn.disabled) return;
    startBtn.disabled = true;
    startBtn.style.display = 'none';
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    isStarted = true;
    chatLog.innerHTML = '';
    appendMessage('status', '話しかけるか、下のフォームから入力してください...');
    if (ws?.readyState === WebSocket.OPEN)
        ws.send(JSON.stringify({ type: 'start_system' }));
    loadSettings();
    sendSettingsToServer();
    refreshCameraOptions(true);
    isAiTurn = false;
    updateStatusMode('STANDBY');
    startListening();
    resetIdleTimer();
    initParticleSystem();
}

startBtn.addEventListener('click', activateSystem);

window.addEventListener('keydown', event => {
    if (event.code === 'Space' && !isStarted) { event.preventDefault(); activateSystem(); }
    if (event.code === 'Escape') { event.preventDefault(); toggleOptionsWindow(); }
});

// ── Options Window ────────────────────────────────────────────
function toggleOptionsWindow() {
    if (!isOptionsOpen) {
        isOptionsOpen = true;
        optionsOverlay.style.display = 'block';
        refreshCameraOptions(false);
        try { recognition.stop(); } catch(_) {}
        isRecognitionActive = false;
        micIndicator.style.display = 'none';
        stopIdleTimer();
        isVisualParamChanged = false;
    } else {
        isOptionsOpen = false;
        optionsOverlay.style.display = 'none';
        saveSettings();
        sendSettingsToServer();
        if (isStarted) {
            isAiTurn = true;
            updateStatusMode('THINKING');
            if (ws?.readyState === WebSocket.OPEN)
                ws.send(JSON.stringify({ type: 'settings_changed' }));
        } else {
            startListening();
        }
        resetIdleTimer();
    }
}

// ── Settings Sync ─────────────────────────────────────────────
function sendSettingsToServer() {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    if (isAiTurn || isPlayingAudio || window.isSpeaking) {
        isPendingSettingsSync = true;
        return;
    }
    const vRate   = (parseInt(document.getElementById('param-rate').value) >= 0 ? '+' : '') + document.getElementById('param-rate').value + '%';
    const vPitch  = (parseInt(document.getElementById('param-pitch').value) >= 0 ? '+' : '') + document.getElementById('param-pitch').value + 'Hz';
    const vVoice  = document.getElementById('param-voice').value;
    const vMirror = document.getElementById('param-mirror').value;
    const vCamera = parseInt(document.getElementById('param-camera').value);
    ws.send(JSON.stringify({ type: 'settings', voice: vVoice, rate: vRate, pitch: vPitch, mirror: vMirror, camera: vCamera, visual_changed: isVisualParamChanged }));
    isVisualParamChanged = false;
}

// ── Chat Log ──────────────────────────────────────────────────
function appendMessage(role, text) {
    if (!isStarted && role !== 'status') return null;

    if (role === 'status') {
        if (!waitingPromptEl || !waitingPromptEl.isConnected) {
            waitingPromptEl = document.createElement('div');
            waitingPromptEl.className = 'msg-status';
            chatLog.appendChild(waitingPromptEl);
        }
        waitingPromptEl.innerText = text;
        chatLog.appendChild(waitingPromptEl);
        chatLog.scrollTop = chatLog.scrollHeight;
        return waitingPromptEl;
    }

    if (waitingPromptEl?.isConnected) { waitingPromptEl.remove(); waitingPromptEl = null; }
    document.querySelectorAll('.msg-status').forEach(el => el.remove());

    const div = document.createElement('div');
    div.className = role === 'user' ? 'msg-user' : 'msg-ai';
    div.innerText = text;
    chatLog.appendChild(div);
    chatLog.scrollTop = chatLog.scrollHeight;
    return div;
}

// ── Recognition ───────────────────────────────────────────────
function startListening() {
    if (!isStarted || voiceMuted || window.isSpeaking || isRecognitionActive || isAiTurn || isOptionsOpen) return;
    setTimeout(() => {
        if (!isStarted || window.isSpeaking || isRecognitionActive || isAiTurn || isOptionsOpen) return;
        try { recognition.start(); } catch(_) {}
    }, 300);
}

recognition.onstart = () => {
    if (!isStarted || isOptionsOpen) { try { recognition.stop(); } catch(_) {} return; }
    isRecognitionActive = true;
    micIndicator.style.display = 'block';
    updateStatusMode('LISTENING');
};

recognition.onresult = event => {
    if (!isStarted || isOptionsOpen) return;
    const text = event.results[0][0].transcript;
    appendMessage('user', 'あなた：' + text);
    isAiTurn = true;
    updateStatusMode('THINKING');
    try { recognition.stop(); } catch(_) {}
    isRecognitionActive = false;
    micIndicator.style.display = 'none';
    stopIdleTimer();
    if (ws?.readyState === WebSocket.OPEN)
        ws.send(JSON.stringify({ type: 'text', text }));
};

recognition.onerror = () => {
    isRecognitionActive = false;
    micIndicator.style.display = 'none';
    if (!isAiTurn) updateStatusMode('STANDBY');
    resetIdleTimer();
};

recognition.onend = () => {
    isRecognitionActive = false;
    micIndicator.style.display = 'none';
    if (isStarted && !voiceMuted && !isAiTurn && !window.isSpeaking && !isOptionsOpen) {
        updateStatusMode('STANDBY');
        startListening();
    }
};

// ── Voice Command Executor ────────────────────────────────────
function executeVoiceCommand(cmd) {
    if (!cmd?.key) return;
    console.log(`【フロントコマンド】${cmd.key} → ${cmd.value}`);

    if (cmd.key === 'scale') {
        const inp = document.getElementById('param-vrm-scale');
        let v = parseFloat(inp.value);
        v = cmd.value === 'UP' ? Math.min(v + 0.15, 2.0) : Math.max(v - 0.15, 0.5);
        inp.value = v; inp.dispatchEvent(new Event('input'));

    } else if (cmd.key === 'mirror') {
        const sel = document.getElementById('param-mirror');
        sel.value = sel.value === 'true' ? 'false' : 'true';
        applyMirrorValue(sel.value);
        sendSettingsToServer();

    } else if (cmd.key === 'camera') {
        const sel = document.getElementById('param-camera');
        const v   = String(cmd.value || '').toUpperCase();
        if (v === 'TOGGLE') {
            const cur  = parseInt(sel.value || '0', 10);
            const next = cameraOptionsMeta.length > 1 ? (cur + 1) % cameraOptionsMeta.length : (cur === 0 ? 1 : 0);
            sel.value  = String(next);
        } else if (v === 'INTERNAL') {
            const t = cameraOptionsMeta.find(c => c.type === 'internal');
            if (t) sel.value = String(t.index);
        } else if (v === 'USB') {
            const t = cameraOptionsMeta.find(c => c.type === 'usb');
            if (t) sel.value = String(t.index);
        } else if (/^\d+$/.test(v)) {
            sel.value = v;
        }
        sel.dispatchEvent(new Event('change'));

    } else if (cmd.key === 'rate') {
        const inp = document.getElementById('param-rate');
        let v = parseInt(inp.value);
        v = cmd.value === 'FASTER' ? Math.min(v + 25, 100) : Math.max(v - 25, -50);
        inp.value = v;
        inp.dispatchEvent(new Event('input'));
        inp.dispatchEvent(new Event('change'));

    } else if (cmd.key === 'volume') {
        if (!window.audioGainNode) return;
        if (cmd.value === 'UP')   window.audioGainNode.gain.value = Math.min(window.audioGainNode.gain.value + 0.2, 2.0);
        if (cmd.value === 'DOWN') window.audioGainNode.gain.value = Math.max(window.audioGainNode.gain.value - 0.2, 0.1);

    } else if (cmd.key === 'color') {
        const map  = { WARM: 'sepia(0.3) hue-rotate(-10deg)', COOL: 'hue-rotate(30deg)', NORMAL: '' };
        const col  = map[cmd.value] ?? '';
        const base = `brightness(${pBright.value}) contrast(${pContrast.value}) saturate(${pSaturate.value})`;
        filterContainer.style.filter = col ? `${base} ${col}` : base;

    } else if (cmd.key === 'register' && cmd.value === 'FACE') {
        startFaceRegistration();

    } else if (cmd.key === 'game') {
        updateGameBadge(cmd.value === 'START');

    } else if (cmd.key === 'history') {
        if (cmd.value === 'RESET') {
            updateGameBadge(false);
            chatLog.innerHTML = '';
            appendMessage('status', '話しかけるか、下のフォームから入力してください...');
        }
    }
}

// ── Audio Playback ────────────────────────────────────────────
function bytesToBuffer(base64Str) {
    const bin = window.atob(base64Str);
    const buf = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
    return buf.buffer;
}

async function playNextInQueue() {
    if (!isStarted) return;
    if (!audioQueue.length) {
        isPlayingAudio = false;
        window.isSpeaking = false;
        isAiTurn = false;
        updateStatusMode('STANDBY');
        appendMessage('status', '話しかけるか、下のフォームから入力してください...');
        if (window.playMotion) window.playMotion('neutral');
        if (ws?.readyState === WebSocket.OPEN)
            ws.send(JSON.stringify({ type: 'end_interaction' }));
        if (isPendingSettingsSync) {
            isPendingSettingsSync = false;
            sendSettingsToServer();
        }
        startListening();
        resetIdleTimer();
        return;
    }

    isPlayingAudio = true;
    window.isSpeaking = true;
    updateStatusMode('SPEAKING');
    const item = audioQueue.shift();
    appendMessage('ai', item.text);
    setEmotionTheme(item.emotion);
    if (window.playMotion) window.playMotion(item.emotion);

    try {
        const buf = await audioCtx.decodeAudioData(item.bufferArray);
        const src = audioCtx.createBufferSource();
        src.buffer = buf;

        if (!window.audioAnalyser) {
            window.audioAnalyser = audioCtx.createAnalyser();
            window.audioAnalyser.fftSize = 32;
        }
        if (!window.audioGainNode) {
            window.audioGainNode = audioCtx.createGain();
            window.audioGainNode.gain.value = 1.0;
            window.audioGainNode.connect(audioCtx.destination);
        }

        src.connect(window.audioAnalyser);
        window.audioAnalyser.connect(window.audioGainNode);
        src.onended = () => playNextInQueue();
        src.start(0);
    } catch(_) { playNextInQueue(); }
}

// ── CSS Filter Controls ───────────────────────────────────────
const filterContainer = document.querySelector('.avatar-filter-target');
const pBright    = document.getElementById('param-bright');
const pContrast  = document.getElementById('param-contrast');
const pSaturate  = document.getElementById('param-saturate');

function updateCSSFilters() {
    document.getElementById('val-bright').innerText    = pBright.value;
    document.getElementById('val-contrast').innerText  = pContrast.value;
    document.getElementById('val-saturate').innerText  = pSaturate.value;
    filterContainer.style.filter = `brightness(${pBright.value}) contrast(${pContrast.value}) saturate(${pSaturate.value})`;
    isVisualParamChanged = true;
}
pBright.addEventListener('input', updateCSSFilters);
pContrast.addEventListener('input', updateCSSFilters);
pSaturate.addEventListener('input', updateCSSFilters);

// ── VRM Param Controls ────────────────────────────────────────
const pVrmX     = document.getElementById('param-vrm-x');
const pVrmY     = document.getElementById('param-vrm-y');
const pVrmScale = document.getElementById('param-vrm-scale');

function syncVrmParams() {
    if (window.currentVrm) {
        window.currentVrm.scene.position.x = parseFloat(pVrmX.value);
        window.currentVrm.scene.position.y = parseFloat(pVrmY.value);
        const s = parseFloat(pVrmScale.value);
        window.currentVrm.scene.scale.set(s, s, s);
    }
    document.getElementById('val-vrm-x').innerText     = parseFloat(pVrmX.value).toFixed(2);
    document.getElementById('val-vrm-y').innerText     = parseFloat(pVrmY.value).toFixed(2);
    document.getElementById('val-vrm-scale').innerText = parseFloat(pVrmScale.value).toFixed(2);
}

pVrmX.addEventListener('input', e => {
    if (window.currentVrm) window.currentVrm.scene.position.x = parseFloat(e.target.value);
    document.getElementById('val-vrm-x').innerText = parseFloat(e.target.value).toFixed(2);
    isVisualParamChanged = true;
});
pVrmY.addEventListener('input', e => {
    document.getElementById('val-vrm-y').innerText = parseFloat(e.target.value).toFixed(2);
    isVisualParamChanged = true;
});
pVrmScale.addEventListener('input', e => {
    const v = parseFloat(e.target.value);
    document.getElementById('val-vrm-scale').innerText = v.toFixed(2);
    if (window.currentVrm) window.currentVrm.scene.scale.set(v, v, v);
    isVisualParamChanged = true;
});

// ── Mirror ────────────────────────────────────────────────────
function applyMirrorValue(val) {
    document.body.style.transform = val === 'true' ? 'scaleX(-1)' : 'none';
}

document.getElementById('param-mirror').addEventListener('change', e => {
    applyMirrorValue(e.target.value);
    sendSettingsToServer();
});

// ── Rate / Pitch Labels ───────────────────────────────────────
function updateRatePitchLabels() {
    const r = document.getElementById('param-rate');
    const p = document.getElementById('param-pitch');
    if (r) document.getElementById('val-rate').innerText  = (parseInt(r.value) >= 0 ? '+' : '') + r.value + '%';
    if (p) document.getElementById('val-pitch').innerText = (parseInt(p.value) >= 0 ? '+' : '') + p.value + 'Hz';
}

document.getElementById('param-rate').addEventListener('input', e => {
    document.getElementById('val-rate').innerText = (parseInt(e.target.value) >= 0 ? '+' : '') + e.target.value + '%';
});
document.getElementById('param-pitch').addEventListener('input', e => {
    document.getElementById('val-pitch').innerText = (parseInt(e.target.value) >= 0 ? '+' : '') + e.target.value + 'Hz';
});
document.getElementById('param-camera').addEventListener('change', () => sendSettingsToServer());
document.getElementById('param-rate').addEventListener('change', () => sendSettingsToServer());
document.getElementById('param-pitch').addEventListener('change', () => sendSettingsToServer());
document.getElementById('param-voice').addEventListener('change', () => sendSettingsToServer());

// ── Text Input Form ───────────────────────────────────────────
function initTextInputForm() {
    const area = document.getElementById('text-input-area');
    if (!area) return;

    const wrapper = document.createElement('div');
    wrapper.style.cssText = 'display:flex; gap:8px; width:100%;';

    const input = document.createElement('input');
    input.type        = 'text';
    input.id          = 'param-text-input';
    input.placeholder = 'ソラへメッセージを入力...';

    const btn = document.createElement('button');
    btn.id        = 'send-txt-btn';
    btn.innerText = 'SEND';

    const handleSend = () => {
        if (!isStarted) { activateSystem(); return; }
        const val = input.value.trim();
        if (!val) return;
        appendMessage('user', 'あなた：' + val);
        isAiTurn = true;
        updateStatusMode('THINKING');
        try { recognition.stop(); } catch(_) {}
        isRecognitionActive = false;
        micIndicator.style.display = 'none';
        stopIdleTimer();
        if (ws?.readyState === WebSocket.OPEN)
            ws.send(JSON.stringify({ type: 'text', text: val }));
        input.value = '';
    };

    btn.addEventListener('click', handleSend);
    input.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); handleSend(); } });

    wrapper.appendChild(input);
    wrapper.appendChild(btn);
    area.appendChild(wrapper);
}

// ── Particle System ───────────────────────────────────────────
let _particleInitDone = false;
function initParticleSystem() {
    particleCanvas = document.getElementById('particle-canvas');
    if (!particleCanvas) return;
    // body直下・全画面サイズ
    particleCanvas.width  = window.innerWidth;
    particleCanvas.height = window.innerHeight;
    particleCtx = particleCanvas.getContext('2d');
    if (!_particleInitDone) {
        _particleInitDone = true;
        requestAnimationFrame(animateParticles);
    }
    window.addEventListener('resize', () => {
        if (!particleCanvas) return;
        particleCanvas.width  = window.innerWidth;
        particleCanvas.height = window.innerHeight;
    });
}

function spawnParticle() {
    if (!particleCanvas || particles.length >= PARTICLE_MAX) return;
    const x = particleCanvas.width  * (0.2 + Math.random() * 0.6);
    const y = particleCanvas.height * (0.5 + Math.random() * 0.4);
    const ec = getComputedStyle(document.documentElement).getPropertyValue('--ec').trim() || '#00ffcc';
    particles.push({
        x, y,
        vx:    (Math.random() - 0.5) * 0.8,
        vy:    -(0.6 + Math.random() * 1.2),
        life:  1.0,
        decay: 0.012 + Math.random() * 0.01,
        size:  1.5 + Math.random() * 2.5,
        color: ec,
    });
}

function animateParticles() {
    requestAnimationFrame(animateParticles);
    if (!particleCtx || !particleCanvas) return;
    particleCtx.clearRect(0, 0, particleCanvas.width, particleCanvas.height);

    // ── JARVIS リング・クロスヘア描画 ────────────────────────
    jAngle += 0.0025;
    const W = particleCanvas.width, H = particleCanvas.height;
    if (W > 0 && H > 0) {
        // 両パネル（メッセージ＋アバター）の画面全体中央
        const cx = W * 0.5;
        const cy = H * 0.52;
        // 各リング半径を元の 40%（2/5）に縮小
        const D  = Math.min(W, H);
        const rO = D * 0.185;  // 外リング（目盛り）
        const rS = D * 0.160;  // セグメントリング
        const rM = D * 0.128;  // 中間リング
        const rI = D * 0.072;  // 内リング

        const ec  = getComputedStyle(document.body).getPropertyValue('--ec').trim() || '#00d4ff';
        const rgb = ec.startsWith('#')
            ? `${parseInt(ec.slice(1,3),16)},${parseInt(ec.slice(3,5),16)},${parseInt(ec.slice(5,7),16)}`
            : '0,212,255';

        // ── 1. 外リング＋72目盛り（正回転）
        particleCtx.save();
        particleCtx.translate(cx, cy);
        particleCtx.rotate(jAngle * 0.8);
        jRing(particleCtx, 0, 0, rO, rgb, 2, 0.65);
        jTicks(particleCtx, 0, 0, rO, rgb);
        particleCtx.restore();

        // ── 2. セグメントリング（逆回転・6分割）
        jSegRing(particleCtx, cx, cy, rS, rgb, 5, 0.9, 6, -jAngle * 1.1);

        // ── 3. カーディナルマーカー（セグメントリングの外側）
        jCardinal(particleCtx, cx, cy, rS + 6, rgb);

        // ── 4. 中間リング（逆回転）
        particleCtx.save();
        particleCtx.translate(cx, cy);
        particleCtx.rotate(-jAngle * 0.6);
        jRing(particleCtx, 0, 0, rM, rgb, 2.5, 0.8);
        // 45°に小マーカー
        [45,135,225,315].forEach(deg => {
            const a = deg * Math.PI / 180;
            particleCtx.beginPath();
            particleCtx.arc(Math.cos(a)*rM, Math.sin(a)*rM, 4, 0, Math.PI*2);
            particleCtx.fillStyle = `rgba(${rgb},1)`;
            particleCtx.shadowColor = `rgba(${rgb},1)`; particleCtx.shadowBlur = 10;
            particleCtx.fill(); particleCtx.shadowBlur = 0;
        });
        particleCtx.restore();

        // ── 5. 内リング（強グロー）
        jRing(particleCtx, cx, cy, rI, rgb, 3.5, 1.0);
        jRing(particleCtx, cx, cy, rI * 0.68, rgb, 1.5, 0.45);

        // ── 6. 軌道ピップ（外リング上を一周）
        jOrbitalPip(particleCtx, cx, cy, rO, rgb, jAngle * 2.2);

        // ── 7. クロスヘア
        jCross(particleCtx, cx, cy, W, H, rgb);

        // ── 8. コーナーブラケット
        jCorners(particleCtx, W, H, rgb, 36);

        // ── 9. 発話パルス（同心円が外に広がる）
        if (window.isSpeaking) {
            const t = Date.now() / 1000;
            [0, 0.55, 1.1].forEach(off => {
                const prog = ((t + off) % 1.8) / 1.8;
                const pr   = rI + (rO - rI) * prog;
                particleCtx.beginPath();
                particleCtx.arc(cx, cy, rI + (rO - rI) * prog, 0, Math.PI*2);
                particleCtx.strokeStyle = `rgba(${rgb},${0.7*(1-prog)})`;
                particleCtx.lineWidth = 2.5;
                particleCtx.stroke();
            });
        }
    }

    // ── パーティクル ─────────────────────────────────────────
    if (window.isSpeaking && Math.random() < 0.6) spawnParticle();
    particles = particles.filter(p => p.life > 0);
    for (const p of particles) {
        p.x    += p.vx;
        p.y    += p.vy;
        p.life -= p.decay;
        particleCtx.save();
        particleCtx.globalAlpha = Math.max(0, p.life * 0.85);
        particleCtx.fillStyle   = p.color;
        particleCtx.shadowColor = p.color;
        particleCtx.shadowBlur  = 6;
        particleCtx.beginPath();
        particleCtx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
        particleCtx.fill();
        particleCtx.restore();
    }
}

// ── Face Registration Flow ────────────────────────────────────
function startFaceRegistration() {
    const overlay = document.getElementById('register-overlay');
    if (!overlay) return;
    overlay.classList.add('active');
    setRegStatus('カメラ起動中...');
    // カメラプレビューを登録UIにも流す
    _syncRegPreview();
    if (ws?.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'face_register_start' }));
    }
}

function endFaceRegistration(success = true) {
    const overlay = document.getElementById('register-overlay');
    if (overlay) {
        setTimeout(() => overlay.classList.remove('active'), 2000);
    }
    document.getElementById('register-scan')?.classList.remove('active');
    setRegStatus(success ? '✓ 登録完了' : '✗ 登録失敗');
}

function setRegStep(step, total) {
    for (let i = 1; i <= 3; i++) {
        const el = document.getElementById(`reg-step-${i}`);
        if (!el) continue;
        el.classList.remove('active', 'done');
        if (i < step)      el.classList.add('done');
        else if (i === step) el.classList.add('active');
    }
}

function setRegStatus(text) {
    const el = document.getElementById('register-status');
    if (el) el.textContent = text;
}

function setRegInstruction(text) {
    const el = document.getElementById('register-instruction-text');
    if (el) el.textContent = text;
}

function _syncRegPreview() {
    // camera-preview-canvas の内容を register-preview-canvas に複写
    const src = document.getElementById('camera-preview-canvas');
    const dst = document.getElementById('register-preview-canvas');
    if (!src || !dst || src.width === 0) { setTimeout(_syncRegPreview, 100); return; }
    dst.width  = src.width;
    dst.height = src.height;
    dst.getContext('2d').drawImage(src, 0, 0);
    setTimeout(_syncRegPreview, 100);
}

// ws.onmessage に register_step / register_captured / register_done を処理
function handleRegisterMessage(msg) {
    if (msg.type === 'register_step') {
        setRegStep(msg.step, msg.total);
        setRegInstruction(msg.instruction);
        setRegStatus(`STEP ${msg.step} / ${msg.total} — 3秒後に撮影`);
        document.getElementById('register-scan')?.classList.remove('active');
        if (msg.audio) {
            const buf = bytesToBuffer(msg.audio);
            audioCtx?.decodeAudioData(buf).then(decoded => {
                const src = audioCtx.createBufferSource();
                src.buffer = decoded;
                src.connect(audioCtx.destination);
                src.start(0);
            }).catch(() => {});
        }
    } else if (msg.type === 'register_captured') {
        document.getElementById('register-scan')?.classList.add('active');
        setRegStatus(`${msg.angle.toUpperCase()} — 撮影完了 ✓`);
    } else if (msg.type === 'register_done') {
        setRegInstruction('登録完了しました');
        endFaceRegistration(true);
        if (msg.audio) {
            const buf = bytesToBuffer(msg.audio);
            audioCtx?.decodeAudioData(buf).then(decoded => {
                const src = audioCtx.createBufferSource();
                src.buffer = decoded;
                if (window.audioGainNode) src.connect(window.audioGainNode);
                else src.connect(audioCtx.destination);
                src.start(0);
            }).catch(() => {});
        }
    } else if (msg.type === 'register_failed') {
        setRegInstruction('登録に失敗しました');
        endFaceRegistration(false);
    }
}

// ── JARVIS UI Initialisation ──────────────────────────────────

/** 時計の更新 */
function startSysClock() {
    function tick() {
        const now = new Date();
        const hh = String(now.getHours()).padStart(2,'0');
        const mm = String(now.getMinutes()).padStart(2,'0');
        const ss = String(now.getSeconds()).padStart(2,'0');
        const el = document.getElementById('sys-clock');
        if (el) el.textContent = `${hh}:${mm}:${ss}`;
    }
    tick();
    setInterval(tick, 1000);
}

/** ステータスバーと sys-strip のモード同期 */
const _origUpdateStatusMode = updateStatusMode;
updateStatusMode = function(mode) {
    _origUpdateStatusMode(mode);
    const sv = document.getElementById('sys-status-val');
    if (sv) sv.textContent = mode;
};

/** WS接続状態を sys-strip に反映 */
function setSysNet(online) {
    const el = document.getElementById('sys-net');
    if (el) { el.textContent = online ? 'ONLINE' : 'OFFLINE'; el.style.color = online ? '' : '#ff4433'; }
}

// ── JARVIS Drawing Helpers ────────────────────────────────────
let jAngle = 0;

/** 実線リング */
function jRing(ctx, x, y, r, color, lw, alpha) {
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.strokeStyle = `rgba(${color},${alpha})`;
    ctx.lineWidth = lw;
    ctx.shadowColor = `rgba(${color},1)`;
    ctx.shadowBlur = 22;
    ctx.stroke(); ctx.stroke(); // 二重でグロー強調
    ctx.shadowBlur = 0;
}

/** セグメント（分割）リング */
function jSegRing(ctx, x, y, r, color, lw, alpha, segs, rotation) {
    const gap = 0.18;
    const segArc = (Math.PI * 2 / segs) * (1 - gap);
    for (let i = 0; i < segs; i++) {
        const start = rotation + (Math.PI * 2 / segs) * i;
        ctx.beginPath();
        ctx.arc(x, y, r, start, start + segArc);
        ctx.strokeStyle = `rgba(${color},${alpha})`;
        ctx.lineWidth = lw;
        ctx.shadowColor = `rgba(${color},0.9)`;
        ctx.shadowBlur = 14;
        ctx.stroke();
        ctx.shadowBlur = 0;
    }
}

/** 目盛りリング */
function jTicks(ctx, x, y, r, color) {
    for (let i = 0; i < 72; i++) {
        const a   = (i * Math.PI * 2 / 72) - Math.PI / 2;
        const maj = i % 9 === 0, med = i % 3 === 0;
        const len = maj ? 18 : (med ? 10 : 5);
        const op  = maj ? 1.0 : (med ? 0.55 : 0.22);
        ctx.beginPath();
        ctx.moveTo(x + Math.cos(a) * r, y + Math.sin(a) * r);
        ctx.lineTo(x + Math.cos(a) * (r - len), y + Math.sin(a) * (r - len));
        ctx.strokeStyle = `rgba(${color},${op})`;
        ctx.lineWidth = maj ? 2.5 : 1;
        if (maj) { ctx.shadowColor = `rgba(${color},1)`; ctx.shadowBlur = 8; }
        ctx.stroke();
        ctx.shadowBlur = 0;
    }
}

/** カーディナルマーカー（三角形） */
function jCardinal(ctx, cx, cy, r, color) {
    [0, Math.PI/2, Math.PI, Math.PI*3/2].forEach((a, idx) => {
        const mx = cx + Math.cos(a) * r;
        const my = cy + Math.sin(a) * r;
        const s  = idx % 2 === 0 ? 9 : 7; // N/S: larger, E/W: smaller
        ctx.save();
        ctx.translate(mx, my);
        ctx.rotate(a + Math.PI/2);
        ctx.beginPath();
        ctx.moveTo(0, -s);
        ctx.lineTo(s*0.6, s*0.5);
        ctx.lineTo(-s*0.6, s*0.5);
        ctx.closePath();
        ctx.fillStyle = `rgba(${color},0.95)`;
        ctx.shadowColor = `rgba(${color},1)`;
        ctx.shadowBlur = 14;
        ctx.fill();
        ctx.restore();
        ctx.shadowBlur = 0;
    });
}

/** 軌道ピップ（1点が外リングを周回） */
function jOrbitalPip(ctx, cx, cy, r, color, angle) {
    const x = cx + Math.cos(angle) * r;
    const y = cy + Math.sin(angle) * r;
    ctx.beginPath(); ctx.arc(x, y, 5, 0, Math.PI*2);
    ctx.fillStyle = `rgba(${color},1)`;
    ctx.shadowColor = `rgba(${color},1)`; ctx.shadowBlur = 18;
    ctx.fill(); ctx.shadowBlur = 0;
    // テール（後尾に残光）
    for (let i = 1; i <= 6; i++) {
        const ta = angle - i * 0.07;
        const tx = cx + Math.cos(ta) * r;
        const ty = cy + Math.sin(ta) * r;
        ctx.beginPath(); ctx.arc(tx, ty, 4 - i*0.5, 0, Math.PI*2);
        ctx.fillStyle = `rgba(${color},${0.5 - i*0.08})`;
        ctx.fill();
    }
}

/** クロスヘア（十字＋斜め45°） */
function jCross(ctx, cx, cy, W, H, color) {
    // 十字
    [[0,cy,W,cy],[cx,0,cx,H]].forEach(([x0,y0,x1,y1]) => {
        const g = ctx.createLinearGradient(x0,y0,x1,y1);
        g.addColorStop(0,    `rgba(${color},0)`);
        g.addColorStop(0.3,  `rgba(${color},0.45)`);
        g.addColorStop(0.5,  `rgba(${color},0.85)`);
        g.addColorStop(0.7,  `rgba(${color},0.45)`);
        g.addColorStop(1,    `rgba(${color},0)`);
        ctx.beginPath(); ctx.moveTo(x0,y0); ctx.lineTo(x1,y1);
        ctx.strokeStyle = g; ctx.lineWidth = 1;
        ctx.shadowColor = `rgba(${color},0.5)`; ctx.shadowBlur = 4;
        ctx.stroke(); ctx.shadowBlur = 0;
    });
    // 中心ドット
    ctx.beginPath(); ctx.arc(cx, cy, 5, 0, Math.PI*2);
    ctx.fillStyle = `rgba(${color},1)`;
    ctx.shadowColor = `rgba(${color},1)`; ctx.shadowBlur = 16;
    ctx.fill(); ctx.shadowBlur = 0;
    // 内十字（短い実線）
    const cl = 14;
    [[cx-cl,cy,cx+cl,cy],[cx,cy-cl,cx,cy+cl]].forEach(([x0,y0,x1,y1]) => {
        ctx.beginPath(); ctx.moveTo(x0,y0); ctx.lineTo(x1,y1);
        ctx.strokeStyle = `rgba(${color},0.9)`;
        ctx.lineWidth = 1.5;
        ctx.stroke();
    });
}

/** コーナーブラケット */
function jCorners(ctx, W, H, color, s) {
    [[0,0,1,1],[W,0,-1,1],[0,H,1,-1],[W,H,-1,-1]].forEach(([x,y,sx,sy]) => {
        ctx.beginPath();
        ctx.moveTo(x+sx*s, y); ctx.lineTo(x,y); ctx.lineTo(x,y+sy*s);
        ctx.strokeStyle = `rgba(${color},0.9)`;
        ctx.lineWidth = 3;
        ctx.shadowColor = `rgba(${color},1)`; ctx.shadowBlur = 12;
        ctx.stroke(); ctx.shadowBlur = 0;
    });
}

/** 発話中パルスリングの ON/OFF */
function setPulseRings(on) {
    ['av-pulse-1','av-pulse-2'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.classList.toggle('speaking', on);
    });
}

// playNextInQueue の発話フラグに連動させる
const _origPlay = playNextInQueue;
// NOTE: playNextInQueue 内の isSpeaking 変化はそのまま使う。
// 代わりに setEmotionTheme を拡張してパルスリングを制御する。
const _origSetEmotion = setEmotionTheme;
setEmotionTheme = function(emotion) {
    _origSetEmotion(emotion);
};

// ── DOMContentLoaded ──────────────────────────────────────────
window.addEventListener('DOMContentLoaded', () => {
    initTextInputForm();
    initQuickConfig();
    refreshCameraOptions(false);
    updateRatePitchLabels();
    updateCSSFilters();
    startSysClock();
    setSysNet(false);
    // layout 計算完了後に particle/JARVIS 描画を開始
    // (DOMContentLoaded 直後は clientWidth=0 になる場合があるため遅延)
    setTimeout(initParticleSystem, 300); // 初期はオフライン表示

    // WS接続後にオンライン表示
    const _check = setInterval(() => {
        if (ws && ws.readyState === WebSocket.OPEN) {
            setSysNet(true); clearInterval(_check);
        }
    }, 500);
});

// 発話状態をパルスリングに反映（audioQueue の変化を監視）
setInterval(() => {
    setPulseRings(!!window.isSpeaking);
}, 200);
