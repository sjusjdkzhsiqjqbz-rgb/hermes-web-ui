
// Voice Input Support
document.addEventListener('DOMContentLoaded', () => {
    const voiceBtn = document.getElementById('voice-btn');
    const messageInput = document.getElementById('message-input');
    
    if (!voiceBtn || !messageInput) return;
    
    // Enable the button when the app is ready
    const observer = new MutationObserver((mutations) => {
        mutations.forEach((mutation) => {
            if (mutation.attributeName === 'disabled') {
                if (!messageInput.disabled) {
                    voiceBtn.disabled = false;
                } else {
                    voiceBtn.disabled = true;
                }
            }
        });
    });
    
    observer.observe(messageInput, { attributes: true });
    
    // Check if SpeechRecognition is supported
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
        voiceBtn.style.display = 'none';
        return;
    }
    
    const recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = true;
    
    let isRecording = false;
    
    recognition.onstart = () => {
        isRecording = true;
        voiceBtn.classList.add('recording');
        messageInput.placeholder = "Listening...";
    };
    
    recognition.onresult = (event) => {
        let interimTranscript = '';
        let finalTranscript = '';
        
        for (let i = event.resultIndex; i < event.results.length; i++) {
            const transcript = event.results[i][0].transcript;
            if (event.results[i].isFinal) {
                finalTranscript += transcript;
            } else {
                interimTranscript += transcript;
            }
        }
        
        if (finalTranscript) {
            const currentVal = messageInput.value;
            messageInput.value = currentVal ? currentVal + ' ' + finalTranscript : finalTranscript;
            // Trigger input event to resize textarea
            messageInput.dispatchEvent(new Event('input', { bubbles: true }));
        }
    };
    
    recognition.onerror = (event) => {
        console.error('Speech recognition error', event.error);
        stopRecording();
    };
    
    recognition.onend = () => {
        stopRecording();
    };
    
    function stopRecording() {
        isRecording = false;
        voiceBtn.classList.remove('recording');
        messageInput.placeholder = "Type your message...";
    }
    
    voiceBtn.addEventListener('click', (e) => {
        e.preventDefault();
        if (isRecording) {
            recognition.stop();
        } else {
            recognition.start();
        }
    });
});
