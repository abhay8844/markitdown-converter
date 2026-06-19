// UI Element Selectors
const dropzone = document.getElementById('dropzone');
const fileInput = document.getElementById('fileInput');
const dropzoneDefault = document.getElementById('dropzone-default');
const dropzoneUploading = document.getElementById('dropzone-uploading');
const dropzoneConverting = document.getElementById('dropzone-converting');
const controlPanel = document.querySelector('.control-panel');

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

// Global state variables
let currentMarkdown = '';
let currentFilename = '';
let terminalInterval = null;
let activeTimeouts = [];
let isConvertingStateStarted = false;

// Allowed extensions matching python backend
const ALLOWED_EXTENSIONS = [
    'pdf', 'docx', 'xlsx', 'pptx', 'html', 'htm', 'csv', 'tsv', 'json', 'xml', 'txt', 'text', 'md', 'rst'
];

// Audio/Video blocked extensions explicitly checked for error messaging
const BLOCKED_EXTENSIONS = [
    'mp3', 'wav', 'aac', 'flac', 'ogg', 'wma', 'm4a', 
    'mp4', 'mkv', 'avi', 'mov', 'wmv', 'flv', 'webm', 'mpeg', '3gp'
];

// Setup Event Listeners
document.addEventListener('DOMContentLoaded', () => {
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
        // Only trigger click if click is on default state (not during progress)
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

    // Buttons
    resetBtn.addEventListener('click', resetAppState);
    errorResetBtn.addEventListener('click', resetAppState);
    copyBtn.addEventListener('click', copyToClipboard);
    downloadBtn.addEventListener('click', downloadMarkdownFile);
});

// File Selection & Validation
function handleFileSelection(file) {
    errorContainer.classList.add('hidden');
    
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
    const maxSize = 150 * 1024 * 1024; // 150MB
    if (file.size > maxSize) {
        showError("File Too Large", "Maximum supported file size is 150MB. Please choose a smaller file.");
        return;
    }
    
    currentFilename = file.name;
    uploadFile(file);
}

// Format byte sizes
function formatBytes(bytes, decimals = 2) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
}

// Upload File via AJAX to show progress
function uploadFile(file) {
    // Show Uploading View
    dropzoneDefault.classList.add('hidden');
    dropzoneUploading.classList.remove('hidden');
    
    // Reset progress visual
    updateProgressRing(0);
    uploadStatus.textContent = `Preparing upload: 0B / ${formatBytes(file.size)}`;
    isConvertingStateStarted = false;

    const formData = new FormData();
    formData.append('file', file);

    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/convert', true);

    // Track upload progress
    xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) {
            const percentComplete = Math.round((e.loaded / e.total) * 100);
            updateProgressRing(percentComplete);
            uploadStatus.textContent = `Uploading: ${formatBytes(e.loaded)} / ${formatBytes(e.total)}`;
            if (percentComplete >= 100) {
                showConvertingLogs(file.name, file.size);
            }
        }
    };

    // Upload complete & server processing
    xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
            try {
                const response = JSON.parse(xhr.responseText);
                if (response.success) {
                    showCompletionLogs(response, file.size);
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
    };

    xhr.send(formData);
}

// Update progress ring visuals
function updateProgressRing(percent) {
    uploadPercentage.textContent = `${percent}%`;
    const radius = 50;
    const circumference = 2 * Math.PI * radius;
    const offset = circumference - (percent / 100) * circumference;
    progressBarFill.style.strokeDashoffset = offset;
}

// Show converting logs immediately when file finishes uploading to Render
function showConvertingLogs(filename, size) {
    if (isConvertingStateStarted) return;
    isConvertingStateStarted = true;
    
    dropzoneUploading.classList.add('hidden');
    dropzoneConverting.classList.remove('hidden');
    terminalLog.innerHTML = '';
    
    // Clear any active timeouts
    activeTimeouts.forEach(clearTimeout);
    activeTimeouts = [];
    
    const logs = [
        { text: '✔ Connection established.', class: 'text-success', delay: 50 },
        { text: `🗂 File received: ${filename} (${formatBytes(size)})`, class: 'text-normal', delay: 200 },
        { text: '⚙ Spawning Microsoft MarkItDown parser on server...', class: 'text-info', delay: 400 },
        { text: '⚡ Running document structure analysis...', class: 'text-warning', delay: 700 },
        { text: '⏳ Waiting for Gemini API layout refinement...', class: 'text-warning', delay: 1100 }
    ];
    
    logs.forEach(log => {
        const t = setTimeout(() => {
            const line = document.createElement('div');
            line.className = `log-line ${log.class}`;
            line.textContent = log.text;
            terminalLog.appendChild(line);
            terminalLog.scrollTop = terminalLog.scrollHeight;
        }, log.delay);
        activeTimeouts.push(t);
    });
}

// Show completion sequence as soon as the server response returns
function showCompletionLogs(data, originalSize) {
    activeTimeouts.forEach(clearTimeout);
    activeTimeouts = [];
    
    terminalLog.innerHTML = '';
    
    const completionLogs = [
        { text: '✔ Connection established.', class: 'text-success' },
        { text: `🗂 File received: ${data.filename} (${formatBytes(originalSize)})`, class: 'text-normal' },
        { text: '⚙ Spawning Microsoft MarkItDown parser on server...', class: 'text-info' },
        { text: '✔ Document structure parsed successfully.', class: 'text-success' },
        { text: '✔ Gemini layout refinement complete.', class: 'text-success' },
        { text: '✔ Token savings analysis complete.', class: 'text-success' },
        { text: '✍ Formatting final Markdown content...', class: 'text-info' },
        { text: '🎉 Process completed successfully!', class: 'text-success' }
    ];
    
    completionLogs.forEach((log, index) => {
        const t = setTimeout(() => {
            const line = document.createElement('div');
            line.className = `log-line ${log.class}`;
            line.textContent = log.text;
            terminalLog.appendChild(line);
            terminalLog.scrollTop = terminalLog.scrollHeight;
        }, index * 60);
        activeTimeouts.push(t);
    });

    const finalT = setTimeout(() => {
        displayResults(data);
    }, completionLogs.length * 60 + 150);
    activeTimeouts.push(finalT);
}

// Display converted Markdown & stats
function displayResults(data) {
    dropzoneConverting.classList.add('hidden');
    resultsPanel.classList.remove('hidden');
    
    // Hide the upload card completely so the results occupy the entire page width
    controlPanel.classList.add('hidden');
    
    currentMarkdown = data.markdown;
    
    // Render file properties
    resultFilename.textContent = data.filename;
    const ext = data.filename.split('.').pop().toUpperCase();
    resultFiletype.textContent = `${ext} Document`;
    
    // Render stats
    statOrigSize.textContent = formatBytes(data.original_size);
    statMdSize.textContent = formatBytes(data.markdown_size);
    
    // Calculate token savings
    // A standard rule is characters count reduced correlates to token count saved.
    // If markdown is smaller, savings are positive.
    const rawSavings = ((data.original_size - data.markdown_size) / data.original_size) * 100;
    const savingsPercent = Math.max(0, rawSavings).toFixed(1);
    statSavings.textContent = `${savingsPercent}%`;
    
    // Render Markdown preview
    if (!data.markdown || data.markdown.trim() === "") {
        tabContentPreview.innerHTML = `
            <div class="empty-markdown-warning">
                <svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="#fbbf24" stroke-width="1.5">
                    <circle cx="12" cy="12" r="10"/>
                    <line x1="12" y1="8" x2="12" y2="12"/>
                    <line x1="12" y1="16" x2="12.01" y2="16"/>
                </svg>
                <h3>No Text Extracted</h3>
                <p>The document was successfully parsed, but no text content was found. This typically happens if the file is a scanned document, image-only PDF, or contains only graphics.</p>
            </div>
        `;
        rawMarkdownCode.textContent = "/* No text content could be extracted from this document. */";
    } else {
        tabContentPreview.innerHTML = marked.parse(data.markdown);
        rawMarkdownCode.textContent = data.markdown;
    }
    
    // Switch to preview tab by default
    switchTab('preview');
}

// Switch between preview and raw code tabs
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

// Error handling panel display
function showError(title, msg) {
    activeTimeouts.forEach(clearTimeout);
    activeTimeouts = [];
    isConvertingStateStarted = false;

    // Hide all states
    dropzoneDefault.classList.add('hidden');
    dropzoneUploading.classList.add('hidden');
    dropzoneConverting.classList.add('hidden');
    controlPanel.classList.remove('hidden');
    
    // Display error card
    errorContainer.classList.remove('hidden');
    errorText.textContent = msg;
    
    // Reset file input value
    fileInput.value = '';
}

// Reset app back to default upload state
function resetAppState() {
    activeTimeouts.forEach(clearTimeout);
    activeTimeouts = [];
    isConvertingStateStarted = false;

    errorContainer.classList.add('hidden');
    resultsPanel.classList.add('hidden');
    dropzoneUploading.classList.add('hidden');
    dropzoneConverting.classList.add('hidden');
    
    controlPanel.classList.remove('hidden');
    
    dropzoneDefault.classList.remove('hidden');
    
    // Reset inputs
    fileInput.value = '';
    currentMarkdown = '';
    currentFilename = '';
}

// Copy to clipboard action
function copyToClipboard() {
    if (!currentMarkdown) return;
    
    navigator.clipboard.writeText(currentMarkdown).then(() => {
        showToast("Copied to clipboard!");
    }).catch(err => {
        // Fallback for non-secure contexts
        const textarea = document.createElement('textarea');
        textarea.value = currentMarkdown;
        document.body.appendChild(textarea);
        textarea.select();
        try {
            document.execCommand('copy');
            showToast("Copied to clipboard!");
        } catch (e) {
            alert("Failed to copy. Please select text and copy manually.");
        }
        document.body.removeChild(textarea);
    });
}

// Download md file action
function downloadMarkdownFile() {
    if (!currentMarkdown) return;
    
    const blob = new Blob([currentMarkdown], { type: 'text/markdown;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    
    // Change file extension to .md
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

// Toast notification display
function showToast(msg) {
    toast.textContent = msg;
    toast.classList.remove('hidden');
    
    setTimeout(() => {
        toast.classList.add('hidden');
    }, 2500);
}
