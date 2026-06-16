const micBtn = document.getElementById('mic-btn');
const statusText = document.getElementById('status-text');
const orb = document.querySelector('.orb');

let isRecording = false;
let socket = null;
let audioContext = null;
let mediaStream = null;
let processor = null;

// Audio playback queue
let audioQueue = [];
let isPlaying = false;
let playContext = null;

function initWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    socket = new WebSocket(`${protocol}//${window.location.host}/ws`);

    socket.onopen = () => {
        console.log('WebSocket connected');
    };

    socket.onmessage = async (event) => {
        // Handle incoming audio from the server
        if (event.data instanceof Blob) {
            const arrayBuffer = await event.data.arrayBuffer();
            playAudioData(arrayBuffer);
        } else {
            // Text messages (e.g. status updates)
            try {
                const data = JSON.parse(event.data);
                if (data.type === 'status') {
                    setStatus(data.message, data.state);
                }
            } catch (e) {
                console.error("Failed to parse message", e);
            }
        }
    };

    socket.onclose = () => {
        console.log('WebSocket disconnected. Reconnecting in 2s...');
        setTimeout(initWebSocket, 2000);
    };
}

function setStatus(text, state = 'idle') {
    statusText.textContent = text;
    orb.className = 'orb'; // reset
    if (state !== 'idle') {
        orb.classList.add(state);
    }
}

async function startRecording() {
    try {
        mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
        
        const source = audioContext.createMediaStreamSource(mediaStream);
        processor = audioContext.createScriptProcessor(4096, 1, 1);
        
        source.connect(processor);
        processor.connect(audioContext.destination);

        processor.onaudioprocess = (e) => {
            if (!isRecording) return;
            const inputData = e.inputBuffer.getChannelData(0);
            
            // Convert Float32 to Int16
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
        setStatus('Listening...', 'listening');
        
        // Tell server we started
        if (socket && socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({ type: 'start_recording' }));
        }
    } catch (err) {
        console.error('Error accessing microphone:', err);
        setStatus('Microphone access denied');
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

    setStatus('Processing...', 'idle');
    
    // Tell server we stopped
    if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'stop_recording' }));
    }
}

micBtn.addEventListener('click', () => {
    if (!socket || socket.readyState !== WebSocket.OPEN) {
        alert("WebSocket not connected. Please wait.");
        return;
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
    
    // Convert incoming 16-bit PCM to Float32
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

function playNextInQueue() {
    if (audioQueue.length === 0) {
        isPlaying = false;
        setStatus('Click the microphone to start', 'idle');
        return;
    }

    isPlaying = true;
    setStatus('Speaking...', 'speaking');
    
    const buffer = audioQueue.shift();
    const source = playContext.createBufferSource();
    source.buffer = buffer;
    source.connect(playContext.destination);
    
    source.onended = () => {
        playNextInQueue();
    };
    
    source.start();
}

// Initialize
window.addEventListener('load', initWebSocket);
