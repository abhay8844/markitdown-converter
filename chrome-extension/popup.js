// API Configuration
const API_URL = 'https://convert-to-md.onrender.com';

// UI Element Selectors
const dropzone = document.getElementById('dropzone');
const fileInput = document.getElementById('fileInput');
const dropzoneDefault = document.getElementById('dropzone-default');
const dropzoneUploading = document.getElementById('dropzone-uploading');
const dropzoneConverting = document.getElementById('dropzone-converting');
const uploadPanel = document.getElementById('upload-panel');

const progressBarFill = document.getElementById('progress-bar-fill');
const uploadPercentage = document.getElementById('upload-percentage');
const uploadStatus = document.getElementById('upload-status');
const terminalLog = document.getElementById('terminal-log');

const errorContainer = document.getElementById('error-container');
const errorText = document.getElementById('error-text');
const errorResetBtn = document.getElementById('error-reset-btn');

const resultsPanel = document.getElementById('results-panel');
const resultFilename = document.getElementById('result-filename');
const resultFiletype = document.getElementById('result-filetype');

const statOrigSize = document.getElementById('stat-orig-size');
const statMdSize = document.getElementById('stat-md-size');
const statSavings = document.getElementById('stat-savings');

const tabBtnPreview = document.getElementById('tab-btn-preview');
const tabBtnRaw = document.getElementById('tab-btn-raw');
const tabContentPreview = document.getElementById('tab-content-preview');
const tabContentRaw = document.getElementById('tab-content-raw');
const rawMarkdownCode = document.getElementById('raw-markdown-code').firstElementChild;

const resetBtn = document.getElementById('reset-btn');
const copyBtn = document.getElementById('copy-btn');
const downloadBtn = document.getElementById('download-btn');
const toast = document.getElementById('toast');
const serverStatusDiv = document.getElementById('server-status');

// Global state variables
let currentMarkdown = '';
let currentFilename = '';
let isServerOnline = false;

// Allowed extensions matching python backend
const ALLOWED_EXTENSIONS = [
    'pdf', 'docx', 'xlsx', 'pptx', 'html', 'htm', 'csv', 'tsv', 'json', 'xml', 'txt', 'text', 'md', 'rst'
];

// Audio/Video blocked extensions
const BLOCKED_EXTENSIONS = [
    'mp3', 'wav', 'aac', 'flac', 'ogg', 'wma', 'm4a', 
    'mp4', 'mkv', 'avi', 'mov', 'wmv', 'flv', 'webm', 'mpeg', '3gp'
];

// Initialize Extension and Event Listeners
document.addEventListener('DOMContentLoaded', () => {
    // Check server status immediately on load
    checkServerStatus();

    // Dropzone drag events
    ['dragenter', 'dragover'].forEach(eventName => {
        dropzone.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropzone.classList.add('dragover');
        }, false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        dropzone.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropzone.classList.remove('dragover');
        }, false);
    });

    dropzone.addEventListener('drop', (e) => {
        const dt = e.dataTransfer;
        const file = dt.files[0];
        if (file) handleFileSelection(file);
    });

    dropzone.addEventListener('click', (e) => {
        if (!dropzoneDefault.classList.contains('hidden')) {
            if (e.target !== fileInput) {
                fileInput.click();
            }
        }
    });

    fileInput.addEventListener('change', (e) => {
        const file = e.target.files[0];
        if (file) handleFileSelection(file);
    });

    // Tab switcher events
    tabBtnPreview.addEventListener('click', () => switchTab('preview'));
    tabBtnRaw.addEventListener('click', () => switchTab('raw'));

    // Button actions
    resetBtn.addEventListener('click', resetAppState);
    errorResetBtn.addEventListener('click', resetAppState);
    copyBtn.addEventListener('click', copyToClipboard);
    downloadBtn.addEventListener('click', downloadMarkdownFile);
    
    // Clicking status badge re-checks
    serverStatusDiv.addEventListener('click', checkServerStatus);
});

// Ping the FastAPI backend server to check if it's running
async function checkServerStatus() {
    updateServerStatusUI('checking', 'Checking server...');
    try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 3000);
        
        const response = await fetch(API_URL + '/', { 
            method: 'GET',
            signal: controller.signal
        });
        
        clearTimeout(timeoutId);
        
        if (response.ok || response.status === 200 || response.status === 404) {
            isServerOnline = true;
            updateServerStatusUI('online', 'Server: Online');
        } else {
            isServerOnline = false;
            updateServerStatusUI('offline', 'Server: Offline');
        }
    } catch (err) {
        isServerOnline = false;
        updateServerStatusUI('offline', 'Server: Offline');
    }
}

function updateServerStatusUI(status, text) {
    serverStatusDiv.className = `server-status ${status}`;
    serverStatusDiv.querySelector('.status-text').textContent = text;
}

// File Selection & Validation
function handleFileSelection(file) {
    errorContainer.classList.add('hidden');
    
    // Check if server is online before attempting
    if (!isServerOnline) {
        showError(
            "Server is Offline", 
            "The local MarkItDown backend server is not running. Please start the server by running 'python main.py' in the terminal before uploading files."
        );
        return;
    }
    
    const ext = file.name.split('.').pop().toLowerCase();
    
    // Check audio/video blocks
    if (BLOCKED_EXTENSIONS.includes(ext) || file.type.startsWith('audio/') || file.type.startsWith('video/')) {
        showError("Blocked File Type", "Audio and video formats are explicitly blocked. Please upload document formats only (.pdf, .docx, .xlsx, .pptx, etc.)");
        return;
    }
    
    // Check whitelist extension
    if (!ALLOWED_EXTENSIONS.includes(ext)) {
        showError("Unsupported Document Type", `The format '.${ext}' is not supported. Please upload standard document formats.`);
        return;
    }
    
    // Limit file size to 150MB
    const maxSize = 150 * 1024 * 1024;
    if (file.size > maxSize) {
        showError("File Too Large", "Maximum supported file size is 150MB. Please choose a smaller file.");
        return;
    }
    
    currentFilename = file.name;
    uploadFile(file);
}

// Helper to format file sizes
function formatBytes(bytes, decimals = 2) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
}

// Upload File using standard XMLHttpRequest for progress reporting
function uploadFile(file) {
    dropzoneDefault.classList.add('hidden');
    dropzoneUploading.classList.remove('hidden');
    
    updateProgressRing(0);
    uploadStatus.textContent = `Preparing upload: 0B / ${formatBytes(file.size)}`;

    const formData = new FormData();
    formData.append('file', file);

    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${API_URL}/convert`, true);

    // Track upload progress
    xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) {
            const percentComplete = Math.round((e.loaded / e.total) * 100);
            updateProgressRing(percentComplete);
            uploadStatus.textContent = `Uploading: ${formatBytes(e.loaded)} / ${formatBytes(e.total)}`;
        }
    };

    // Upload complete, server converting document
    xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
            try {
                const response = JSON.parse(xhr.responseText);
                if (response.success) {
                    startConvertingAnimation(response);
                } else {
                    showError("Conversion Error", response.detail || "Server failed to parse the document.");
                }
            } catch (err) {
                showError("Parse Error", "Failed to handle server response data.");
            }
        } else {
            let errorMsg = "A network or server error occurred.";
            try {
                const response = JSON.parse(xhr.responseText);
                if (response.detail) errorMsg = response.detail;
            } catch(e) {}
            showError("Server Failure", `${errorMsg} (Status code: ${xhr.status})`);
        }
    };

    xhr.onerror = () => {
        showError("Connection Failed", "Failed to connect to the backend server. Please verify the server is running locally.");
        isServerOnline = false;
        updateServerStatusUI('offline', 'Server: Offline');
    };

    xhr.send(formData);
}

// Update circular progress bar in popup
function updateProgressRing(percent) {
    uploadPercentage.textContent = `${percent}%`;
    const radius = 42;
    const circumference = 2 * Math.PI * radius;
    const offset = circumference - (percent / 100) * circumference;
    progressBarFill.style.strokeDashoffset = offset;
}

// Simulated terminal-style logs showing conversion details
function startConvertingAnimation(data) {
    dropzoneUploading.classList.add('hidden');
    dropzoneConverting.classList.remove('hidden');
    
    terminalLog.innerHTML = '';
    
    const logStatements = [
        { text: '✔ Connection established.', class: 'text-success', delay: 50 },
        { text: `🗂 File read: ${data.filename} (${formatBytes(data.original_size)})`, class: 'text-normal', delay: 150 },
        { text: '⚙ Spawning Microsoft MarkItDown parser...', class: 'text-info', delay: 250 },
        { text: '⚡ [1/3] Parsing layout nodes and formatting sheets...', class: 'text-warning', delay: 350 },
        { text: '⚡ [2/3] Extracting inline tables and text structures...', class: 'text-warning', delay: 450 },
        { text: '⚡ [3/3] Constructing Markdown representations...', class: 'text-warning', delay: 550 },
        { text: '✔ Token reduction analysis complete.', class: 'text-success', delay: 650 },
        { text: '✍ Formatting final Markdown content...', class: 'text-info', delay: 750 },
        { text: '🎉 Process completed successfully!', class: 'text-success', delay: 850 }
    ];

    logStatements.forEach((log) => {
        setTimeout(() => {
            const line = document.createElement('div');
            line.className = `log-line ${log.class}`;
            line.textContent = log.text;
            terminalLog.appendChild(line);
            terminalLog.scrollTop = terminalLog.scrollHeight;
        }, log.delay);
    });

    setTimeout(() => {
        displayResults(data);
    }, 1050);
}

// Render converted Markdown and stats in Popup results screen
function displayResults(data) {
    dropzoneConverting.classList.add('hidden');
    uploadPanel.classList.add('hidden');
    resultsPanel.classList.remove('hidden');
    
    currentMarkdown = data.markdown;
    
    resultFilename.textContent = data.filename;
    const ext = data.filename.split('.').pop().toUpperCase();
    resultFiletype.textContent = `${ext} Document`;
    
    statOrigSize.textContent = formatBytes(data.original_size);
    statMdSize.textContent = formatBytes(data.markdown_size);
    
    const rawSavings = ((data.original_size - data.markdown_size) / data.original_size) * 100;
    const savingsPercent = Math.max(0, rawSavings).toFixed(1);
    statSavings.textContent = `${savingsPercent}%`;
    
    // Render Markdown preview using local marked.js
    if (!data.markdown || data.markdown.trim() === "") {
        tabContentPreview.innerHTML = `
            <div style="text-align: center; padding: 1.5rem; color: #fbbf24;">
                <h3>No Text Extracted</h3>
                <p style="font-size: 0.75rem; color: #94a3b8; margin-top: 0.25rem;">
                    The document was successfully parsed, but no text content was found.
                </p>
            </div>
        `;
        rawMarkdownCode.textContent = "/* No text content could be extracted from this document. */";
    } else {
        // marked comes from local marked.min.js loaded in popup.html
        tabContentPreview.innerHTML = marked.parse(data.markdown);
        rawMarkdownCode.textContent = data.markdown;
    }
    
    switchTab('preview');
}

// Switch between preview tabs
function switchTab(tab) {
    if (tab === 'preview') {
        tabBtnPreview.classList.add('active');
        tabBtnRaw.classList.remove('active');
        tabContentPreview.classList.remove('hidden');
        tabContentRaw.classList.add('hidden');
    } else {
        tabBtnPreview.classList.remove('active');
        tabBtnRaw.classList.add('active');
        tabContentPreview.classList.add('hidden');
        tabContentRaw.classList.remove('hidden');
    }
}

// Display error messages inside container
function showError(title, msg) {
    dropzoneDefault.classList.add('hidden');
    dropzoneUploading.classList.add('hidden');
    dropzoneConverting.classList.add('hidden');
    uploadPanel.classList.remove('hidden');
    
    errorContainer.classList.remove('hidden');
    errorText.textContent = msg;
    fileInput.value = '';
}

// Reset UI state to start over
function resetAppState() {
    errorContainer.classList.add('hidden');
    resultsPanel.classList.add('hidden');
    dropzoneUploading.classList.add('hidden');
    dropzoneConverting.classList.add('hidden');
    
    uploadPanel.classList.remove('hidden');
    dropzoneDefault.classList.remove('hidden');
    
    fileInput.value = '';
    currentMarkdown = '';
    currentFilename = '';
    
    // Check server status again
    checkServerStatus();
}

// Copy markdown result to clipboard
function copyToClipboard() {
    if (!currentMarkdown) return;
    
    navigator.clipboard.writeText(currentMarkdown).then(() => {
        showToast("Copied to clipboard!");
    }).catch(err => {
        // Fallback for copy
        const textarea = document.createElement('textarea');
        textarea.value = currentMarkdown;
        document.body.appendChild(textarea);
        textarea.select();
        try {
            document.execCommand('copy');
            showToast("Copied to clipboard!");
        } catch (e) {
            alert("Failed to copy. Please copy manually.");
        }
        document.body.removeChild(textarea);
    });
}

// Download markdown file from popup context
function downloadMarkdownFile() {
    if (!currentMarkdown) return;
    
    const blob = new Blob([currentMarkdown], { type: 'text/markdown;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    
    const originalNameWithoutExt = currentFilename.substring(0, currentFilename.lastIndexOf('.')) || currentFilename;
    const downloadName = `${originalNameWithoutExt}.md`;
    
    link.href = url;
    link.setAttribute('download', downloadName);
    link.style.visibility = 'hidden';
    
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
}

// Show popup toast
function showToast(msg) {
    toast.textContent = msg;
    toast.classList.remove('hidden');
    
    setTimeout(() => {
        toast.classList.add('hidden');
    }, 2000);
}
