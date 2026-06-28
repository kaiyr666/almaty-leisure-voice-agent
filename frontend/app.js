const micBtn = document.getElementById('mic-btn');
const statusText = document.getElementById('status-text');
const orb = document.getElementById('orb');
const statusPulse = document.getElementById('status-pulse');
const transcriptBox = document.getElementById('transcript-box');

let isRecording = false;
let socket = null;
let audioContext = null;
let mediaStream = null;
let processor = null;
let shouldReconnect = true;
let reconnectTimeout = null;

// Audio playback queue
let audioQueue = [];
let isPlaying = false;
let playContext = null;

function initWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const socketUrl = `${protocol}//${window.location.host}/ws`;
    console.log(`Connecting to WebSocket: ${socketUrl}`);
    
    socket = new WebSocket(socketUrl);

    socket.onopen = () => {
        console.log('WebSocket connected');
        setStatus('Подключено. Нажмите на микрофон', 'idle');
        micBtn.disabled = false;
    };

    socket.onmessage = async (event) => {
        if (event.data instanceof Blob) {
            // Audio bytes received (24kHz raw PCM from ElevenLabs)
            const arrayBuffer = await event.data.arrayBuffer();
            playAudioData(arrayBuffer);
        } else {
            // Text JSON message received (e.g. status changes or transcripts)
            try {
                const data = JSON.parse(event.data);
                if (data.type === 'status') {
                    setStatus(data.message, data.state);
                } else if (data.type === 'transcript') {
                    addMessageToBox(data.role, data.text);
                }
            } catch (e) {
                console.error("Failed to parse text message:", e);
            }
        }
    };

    socket.onclose = () => {
        console.log('WebSocket disconnected.');
        setStatus('Соединение разорвано. Переподключение...', 'idle');
        micBtn.disabled = true;
        if (isRecording) {
            stopRecording();
        }
        if (shouldReconnect) {
            reconnectTimeout = setTimeout(() => {
                initWebSocket();
            }, 3000);
        }
    };

    socket.onerror = (err) => {
        console.error('WebSocket error:', err);
    };
}

function setStatus(text, state = 'idle') {
    statusText.textContent = text;
    
    // Reset classes
    orb.className = 'orb';
    statusPulse.className = 'status-pulse';
    
    if (state !== 'idle') {
        orb.classList.add(state);
        statusPulse.classList.add(state);
    }
}

function addMessageToBox(role, text) {
    // Check if system message needs to be removed
    const systemMsg = transcriptBox.querySelector('.system-msg');
    if (systemMsg) {
        systemMsg.remove();
    }
    
    const p = document.createElement('p');
    p.className = role === 'user' ? 'user-msg' : 'bot-msg';
    
    const prefix = role === 'user' ? 'Вы: ' : 'Помощник: ';
    p.textContent = `${prefix}${text}`;
    
    transcriptBox.appendChild(p);
    transcriptBox.scrollTop = transcriptBox.scrollHeight;
}

async function startRecording() {
    try {
        mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        // Sample rate of 16000Hz is expected by Groq Whisper
        audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
        
        const source = audioContext.createMediaStreamSource(mediaStream);
        processor = audioContext.createScriptProcessor(4096, 1, 1);
        
        source.connect(processor);
        processor.connect(audioContext.destination);

        processor.onaudioprocess = (e) => {
            if (!isRecording) return;
            const inputData = e.inputBuffer.getChannelData(0);
            
            // Convert Float32 to Int16 (little-endian signed 16-bit PCM)
            const pcmData = new Int16Array(inputData.length);
            for (let i = 0; i < inputData.length; i++) {
                const s = Math.max(-1, Math.min(1, inputData[i]));
                pcmData[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
            }
            
            if (socket && socket.readyState === WebSocket.OPEN) {
                socket.send(pcmData.buffer);
            }
        };

        isRecording = true;
        micBtn.classList.add('active');
        setStatus('Слушаю...', 'listening');
        
        // Notify server that user started recording
        if (socket && socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({ type: 'start_recording' }));
        }
    } catch (err) {
        console.error('Error accessing microphone:', err);
        setStatus('Микрофон недоступен', 'idle');
    }
}

function stopRecording() {
    isRecording = false;
    micBtn.classList.remove('active');
    
    if (processor) {
        processor.disconnect();
        processor = null;
    }
    if (mediaStream) {
        mediaStream.getTracks().forEach(track => track.stop());
        mediaStream = null;
    }
    if (audioContext) {
        audioContext.close();
        audioContext = null;
    }

    setStatus('Обработка...', 'idle');
    
    // Notify server that user stopped recording
    if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'stop_recording' }));
    }
}

micBtn.addEventListener('click', () => {
    if (!socket || socket.readyState !== WebSocket.OPEN) {
        alert("WebSocket не подключен. Пожалуйста, подождите.");
        return;
    }

    // Unlock AudioContext for playback (autoplay policy)
    if (!playContext) {
        playContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 24000 });
        if (audioQueue.length > 0 && !isPlaying) {
            playNextInQueue();
        }
    } else if (playContext.state === 'suspended') {
        playContext.resume().then(() => {
            console.log('Playback context unlocked');
            isPlaying = false;
            if (audioQueue.length > 0) playNextInQueue();
        });
    }

    if (isRecording) {
        stopRecording();
    } else {
        startRecording();
    }
});

// Playback logic
async function playAudioData(arrayBuffer) {
    if (!playContext) {
        playContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 24000 });
    }

    // Convert 16-bit PCM (from ElevenLabs) to Float32
    const int16Data = new Int16Array(arrayBuffer);
    const float32Data = new Float32Array(int16Data.length);
    for (let i = 0; i < int16Data.length; i++) {
        float32Data[i] = int16Data[i] / 32768.0;
    }

    const audioBuffer = playContext.createBuffer(1, float32Data.length, 24000);
    audioBuffer.getChannelData(0).set(float32Data);

    audioQueue.push(audioBuffer);

    if (!isPlaying) {
        playNextInQueue();
    }
}

async function playNextInQueue() {
    if (audioQueue.length === 0) {
        isPlaying = false;
        setStatus('Нажмите на микрофон', 'idle');
        return;
    }

    if (!playContext) {
        isPlaying = false;
        return;
    }

    if (playContext.state !== 'running') {
        try {
            await playContext.resume();
        } catch (e) {
            console.warn('Could not resume playback context:', e);
        }
    }

    isPlaying = true;
    setStatus('Говорю...', 'speaking');

    const buffer = audioQueue.shift();
    const source = playContext.createBufferSource();
    source.buffer = buffer;
    source.connect(playContext.destination);
    source.onended = () => playNextInQueue();
    source.start();
}

// Unlock audio playback context on general user gestures
document.addEventListener('click', () => {
    if (!playContext) {
        playContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 24000 });
        isPlaying = false;
        if (audioQueue.length > 0) playNextInQueue();
    } else if (playContext.state === 'suspended') {
        playContext.resume().then(() => {
            isPlaying = false;
            if (audioQueue.length > 0) playNextInQueue();
        });
    }
}, { once: false });

window.addEventListener('load', initWebSocket);
window.addEventListener('beforeunload', () => {
    shouldReconnect = false;
    if (socket) socket.close();
});
