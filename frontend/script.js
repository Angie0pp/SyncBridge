
const serverStatus = document.getElementById("serverStatus");
const uploadForm = document.getElementById("uploadForm");
const fileInput = document.getElementById("fileInput");
const selectedFile = document.getElementById("selectedFile");
const uploadMessage = document.getElementById("uploadMessage");
const uploadButton = document.getElementById("uploadButton");
const filesList = document.getElementById("filesList");
const refreshButton = document.getElementById("refreshButton");

// Check server connection
async function checkServer() {
    try {
        const response = await fetch("/api/status");
        const data = await response.json();

        serverStatus.textContent = data.message;
    } catch (error) {
        serverStatus.textContent = "Server connection unavailable.";
    }
}

// Display selected filename
fileInput.addEventListener("change", () => {
    if (fileInput.files.length > 0) {
        selectedFile.textContent = fileInput.files[0].name;
    } else {
        selectedFile.textContent = "No file selected";
    }
});

// Upload selected file
uploadForm.addEventListener("submit", async (event) => {
    event.preventDefault();

    const file = fileInput.files[0];

    if (!file) {
        uploadMessage.textContent = "Please select a file first.";
        return;
    }

    const formData = new FormData();
    formData.append("file", file);

    uploadButton.disabled = true;
    uploadButton.textContent = "Uploading...";
    uploadMessage.textContent = "Please wait...";

    try {
        const response = await fetch("/api/upload", {
            method: "POST",
            body: formData
        });

        const result = await response.json();

        if (!response.ok) {
            throw new Error(result.message || "Upload failed.");
        }

        uploadMessage.textContent = "✅ " + result.message;
        fileInput.value = "";
        selectedFile.textContent = "No file selected";

        loadFiles();

    } catch (error) {
        uploadMessage.textContent = "❌ " + error.message;
    } finally {
        uploadButton.disabled = false;
        uploadButton.textContent = "Upload File";
    }
});

// Load received files
async function loadFiles() {
    filesList.textContent = "Loading files...";

    try {
        const response = await fetch("/api/files");

        if (!response.ok) {
            throw new Error("Could not load files.");
        }

        const files = await response.json();

        filesList.innerHTML = "";

        if (files.length === 0) {
            filesList.innerHTML =
                '<p class="empty-message">No files received yet.</p>';
            return;
        }

        files.forEach((file) => {
            const item = document.createElement("div");
            item.className = "file-item";

            const info = document.createElement("div");
            info.className = "file-info";

            const name = document.createElement("strong");
            name.textContent = file.filename;

            const details = document.createElement("small");
            details.textContent =
                formatSize(file.file_size) +
                " • " +
                file.transfer_type +
                " • " +
                file.transferred_at;

            const download = document.createElement("a");
            download.className = "download-button";
            download.href = "/api/download/" + file.id;
            download.textContent = "Download";

            info.appendChild(name);
            info.appendChild(details);

            item.appendChild(info);
            item.appendChild(download);

            filesList.appendChild(item);
        });

    } catch (error) {
        filesList.textContent = error.message;
    }
}

// Format file sizes
function formatSize(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) {
        return (bytes / 1024).toFixed(1) + " KB";
    }

    return (bytes / (1024 * 1024)).toFixed(2) + " MB";
}

// Refresh file list
refreshButton.addEventListener("click", loadFiles);

// Initial page loading
checkServer();
loadFiles();
