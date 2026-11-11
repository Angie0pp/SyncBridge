
const serverStatus = document.getElementById("serverStatus");
const uploadForm = document.getElementById("uploadForm");
const fileInput = document.getElementById("fileInput");
const selectedFile = document.getElementById("selectedFile");
const uploadMessage = document.getElementById("uploadMessage");
const uploadButton = document.getElementById("uploadButton");
const filesList = document.getElementById("filesList");
const refreshButton = document.getElementById("refreshButton");
const clearFilesButton = document.getElementById("clearFilesButton");

// Read the CSRF token supplied by Flask
const csrfToken = document.querySelector(
    'meta[name="csrf-token"]'
).content;


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
            headers: {
                "X-CSRFToken": csrfToken
            },
            body: formData
        });

        const result = await response.json();

        if (response.status === 401) {
            window.location.href = "/login";
            return;
        }

        if (!response.ok) {
            throw new Error(result.message || "Upload failed.");
        }

        uploadMessage.textContent = "✅ " + result.message;

        fileInput.value = "";
        selectedFile.textContent = "No file selected";

        await loadFiles();

    } catch (error) {
        uploadMessage.textContent = "❌ " + error.message;

    } finally {
        uploadButton.disabled = false;
        uploadButton.textContent = "Upload File";
    }
});


// Load files belonging to the logged-in user
async function loadFiles() {
    filesList.textContent = "Loading your files...";

    try {
        const response = await fetch("/api/files");

        if (response.status === 401) {
            window.location.href = "/login";
            return;
        }

        if (!response.ok) {
            throw new Error("Could not load your files.");
        }

        const files = await response.json();

        filesList.innerHTML = "";

        // Enable Clear All only when files exist
        clearFilesButton.disabled = files.length === 0;

        if (files.length === 0) {
            filesList.innerHTML =
                '<p class="empty-message">You have not uploaded any files yet.</p>';
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

            // Download button
            const download = document.createElement("a");
            download.className = "download-button";
            download.href = "/api/download/" + file.id;
            download.textContent = "Download";

            // Individual Delete button
            const deleteButton = document.createElement("button");
            deleteButton.type = "button";
            deleteButton.className = "delete-button";
            deleteButton.textContent = "🗑 Delete";

            deleteButton.addEventListener("click", () => {
                deleteFile(file.id, file.filename, deleteButton);
            });

            info.appendChild(name);
            info.appendChild(details);

            item.appendChild(info);
            item.appendChild(download);
            item.appendChild(deleteButton);

            filesList.appendChild(item);
        });

    } catch (error) {
        filesList.textContent = error.message;
        clearFilesButton.disabled = true;
    }
}


// Delete one selected file
async function deleteFile(fileId, filename, button) {

    const confirmed = confirm(
        `Are you sure you want to delete "${filename}"?`
    );

    if (!confirmed) {
        return;
    }

    button.disabled = true;
    button.textContent = "Deleting...";

    try {
        const response = await fetch(`/api/files/${fileId}`, {
            method: "DELETE",
            headers: {
                "X-CSRFToken": csrfToken
            }
        });

        const result = await response.json();

        if (response.status === 401) {
            window.location.href = "/login";
            return;
        }

        if (!response.ok) {
            throw new Error(result.message || "Could not delete file.");
        }

        alert("✅ " + result.message);

        await loadFiles();

    } catch (error) {
        alert("❌ " + error.message);
        button.disabled = false;
        button.textContent = "🗑 Delete";
    }
}


// Delete all files belonging to the logged-in user
clearFilesButton.addEventListener("click", async () => {

    const confirmed = confirm(
        "Are you sure you want to delete ALL your uploaded files? This action cannot be undone."
    );

    if (!confirmed) {
        return;
    }

    clearFilesButton.disabled = true;
    clearFilesButton.textContent = "Clearing...";

    try {
        const response = await fetch("/api/files/clear", {
            method: "DELETE",
            headers: {
                "X-CSRFToken": csrfToken
            }
        });

        const result = await response.json();

        if (response.status === 401) {
            window.location.href = "/login";
            return;
        }

        if (!response.ok) {
            throw new Error(result.message || "Could not clear files.");
        }

        alert("✅ " + result.message);

        await loadFiles();

    } catch (error) {
        alert("❌ " + error.message);

    } finally {
        clearFilesButton.textContent = "🗑 Clear All Files";
    }
});


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
