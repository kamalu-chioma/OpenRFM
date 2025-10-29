const uploadForm = document.getElementById('upload-form');
const fileInput = document.getElementById('file');
const clusterSelect = document.getElementById('cluster-size');
const statusMessage = document.getElementById('status-message');
const progressFeed = document.getElementById('progress-feed');
const resultTable = document.getElementById('result-table');
const resultHeader = document.getElementById('result-header');
const resultBody = document.getElementById('result-body');
const downloadLink = document.getElementById('download-link');

function appendProgress(message) {
    const item = document.createElement('div');
    item.className = 'progress-feed__item';
    item.textContent = message;
    progressFeed.appendChild(item);
    progressFeed.scrollTop = progressFeed.scrollHeight;
}

function setStatus(message, tone = 'neutral') {
    statusMessage.textContent = message;
    statusMessage.className = tone;
}

function resetUI() {
    progressFeed.innerHTML = '';
    setStatus('');
    resultHeader.innerHTML = '';
    resultBody.innerHTML = '';
    resultTable.hidden = true;
    downloadLink.hidden = true;
    downloadLink.removeAttribute('href');
}

async function uploadFile() {
    const formData = new FormData();
    formData.append('file', fileInput.files[0]);

    const response = await fetch('/upload', {
        method: 'POST',
        body: formData,
    });

    if (!response.ok) {
        const error = await response.json().catch(() => ({ error: 'Upload failed.' }));
        throw new Error(error.error || 'Upload failed');
    }

    return response.json();
}

async function processRfm(filePath, clusterSize) {
    const response = await fetch('/process_rfm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file_path: filePath, cluster_size: clusterSize }),
    });

    if (!response.ok) {
        const error = await response.json().catch(() => ({ error: 'Processing failed.' }));
        throw new Error(error.error || 'Processing failed');
    }

    return response.json();
}

function buildTable(rows) {
    if (!rows.length) {
        appendProgress('No rows returned from processing.');
        return;
    }

    const headers = Object.keys(rows[0]);
    resultHeader.innerHTML = `<tr>${headers.map((header) => `<th>${header}</th>`).join('')}</tr>`;
    resultBody.innerHTML = rows
        .map(
            (row) =>
                `<tr>${headers
                    .map((header) => `<td>${row[header] ?? ''}</td>`)
                    .join('')}</tr>`
        )
        .join('');

    resultTable.hidden = false;
}

function enableForm(isEnabled) {
    uploadForm.querySelectorAll('input, select, button').forEach((element) => {
        element.disabled = !isEnabled;
    });
}

if (uploadForm) {
    const socket = io();
    socket.on('progress', (data) => {
        if (data?.message) {
            appendProgress(data.message);
        }
    });

    uploadForm.addEventListener('submit', async (event) => {
        event.preventDefault();

        if (!fileInput.files.length) {
            setStatus('Please choose a CSV or Excel file first.', 'error');
            return;
        }

        resetUI();
        enableForm(false);
        setStatus('Uploading…', 'info');

        try {
            const uploadResponse = await uploadFile();
            setStatus('File uploaded. Running inference…', 'info');
            appendProgress('Upload completed. Schema inference starting…');

            const rfmResponse = await processRfm(uploadResponse.file_path, clusterSelect.value);
            setStatus('Success! Your results are ready.', 'success');
            appendProgress('Processing complete. Previewing the first rows…');

            if (Array.isArray(rfmResponse.messages)) {
                rfmResponse.messages.forEach((message) => appendProgress(message));
            }

            if (Array.isArray(rfmResponse.data)) {
                const preview = rfmResponse.data.slice(0, 5);
                buildTable(preview);
            }

            if (rfmResponse.download_link) {
                downloadLink.href = rfmResponse.download_link;
                downloadLink.hidden = false;
            }
        } catch (error) {
            console.error(error);
            setStatus(error.message || 'Something went wrong.', 'error');
            appendProgress('The pipeline reported an error. Review the message above and try again.');
        } finally {
            enableForm(true);
        }
    });
}
