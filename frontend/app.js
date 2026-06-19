// pywebview JS bridge
const downloadList = document.getElementById('download-list');
const emptyState = document.getElementById('empty-state');
const settingsOverlay = document.getElementById('settings-overlay');

function api() { return window.pywebview.api; }

// -- Download List --
function renderDownloads(downloads) {
    if (!downloads || downloads.length === 0) {
        downloadList.classList.add('hidden');
        emptyState.classList.remove('hidden');
        return;
    }
    downloadList.classList.remove('hidden');
    emptyState.classList.add('hidden');

    downloadList.innerHTML = downloads.map(dl => `
        <div class="dl-item" data-id="${dl.id}">
            <div class="row-top">
                <span class="filename" title="${dl.fileName}">${dl.fileName}</span>
                <span class="meta">${dl.size}</span>
            </div>
            <div class="progress-bar"><div class="fill" style="width:${dl.percent}%"></div></div>
            <div class="row-bottom">
                <span class="status ${dl.status.toLowerCase()}">${dl.status}${dl.status === 'Downloading' ? ' \u00b7 ' + dl.speed + ' \u00b7 ' + dl.percent + '%' : ''}${dl.error ? ' \u00b7 ' + dl.error : ''}</span>
                <div class="actions">
                    ${dl.status === 'Downloading' ? '<button onclick="onPause(\'' + dl.id + '\')">Pause</button>' : ''}
                    ${dl.status === 'Paused' ? '<button onclick="onResume(\'' + dl.id + '\')">Resume</button>' : ''}
                    ${dl.status === 'Downloading' || dl.status === 'Paused' ? '<button onclick="onCancel(\'' + dl.id + '\')">Cancel</button>' : ''}
                    ${dl.status === 'Done' || dl.status === 'Error' || dl.status === 'Cancelled' ? '<button onclick="onRemove(\'' + dl.id + '\')">Remove</button>' : ''}
                </div>
            </div>
        </div>
    `).join('');
}

window.onPause = (id) => api().pause(id);
window.onResume = (id) => api().resume(id);
window.onCancel = (id) => api().cancel(id);
window.onRemove = (id) => api().remove(id);

// -- Backend push handlers --
window.onDownloadsUpdated = renderDownloads;
window.onError = (msg) => alert(msg);

// -- Context Menu --
let ctxMenu = null;
function hideContextMenu() { if (ctxMenu) { ctxMenu.remove(); ctxMenu = null; } }
document.addEventListener('click', hideContextMenu);

downloadList.addEventListener('contextmenu', (e) => {
    e.preventDefault();
    hideContextMenu();
    const item = e.target.closest('.dl-item');
    if (!item) return;
    const id = item.dataset.id;
    const status = item.querySelector('.status').classList[1];

    ctxMenu = document.createElement('div');
    ctxMenu.className = 'context-menu';
    ctxMenu.style.left = e.pageX + 'px';
    ctxMenu.style.top = e.pageY + 'px';

    const removeBtn = document.createElement('div');
    removeBtn.textContent = 'Remove';
    removeBtn.onclick = () => { api().remove(id); hideContextMenu(); };
    ctxMenu.appendChild(removeBtn);

    if (status === 'error' || status === 'cancelled' || status === 'paused') {
        const deleteBtn = document.createElement('div');
        deleteBtn.textContent = 'Delete';
        deleteBtn.onclick = () => { api().delete(id); hideContextMenu(); };
        ctxMenu.appendChild(deleteBtn);
    }

    const clearBtn = document.createElement('div');
    clearBtn.textContent = 'Clear All Completed';
    clearBtn.onclick = () => { api().clear_completed(); hideContextMenu(); };
    ctxMenu.appendChild(clearBtn);

    document.body.appendChild(ctxMenu);
});

// Initial load once pywebview is ready
window.addEventListener('pywebviewready', () => {
    api().get_downloads().then(renderDownloads);
    api().is_first_run().then(first => { if (first) openSettings(); });
});

// -- Settings --
document.getElementById('btn-settings').addEventListener('click', openSettings);
document.getElementById('btn-cancel').addEventListener('click', closeSettings);
document.getElementById('btn-save').addEventListener('click', saveSettings);
document.getElementById('btn-validate').addEventListener('click', validateKey);
document.getElementById('btn-browse').addEventListener('click', browseFolder);
document.getElementById('btn-browse-7z').addEventListener('click', browse7z);
document.getElementById('btn-register').addEventListener('click', async () => {
    try { await api().register(); document.getElementById('reg-status').textContent = '\u2713 Registered'; } catch(e) { document.getElementById('reg-status').textContent = '\u2717 ' + e; }
});
document.getElementById('btn-deregister').addEventListener('click', async () => {
    try { await api().deregister(); document.getElementById('reg-status').textContent = '\u2713 Removed'; } catch(e) { document.getElementById('reg-status').textContent = '\u2717 ' + e; }
});
document.getElementById('btn-register-modl').addEventListener('click', async () => {
    try { await api().register_modl(); document.getElementById('reg-modl-status').textContent = '\u2713 Registered'; } catch(e) { document.getElementById('reg-modl-status').textContent = '\u2717 ' + e; }
});
document.getElementById('btn-deregister-modl').addEventListener('click', async () => {
    try { await api().deregister_modl(); document.getElementById('reg-modl-status').textContent = '\u2713 Removed'; } catch(e) { document.getElementById('reg-modl-status').textContent = '\u2717 ' + e; }
});
document.getElementById('btn-getkey').addEventListener('click', () => api().open_api_key_page());

async function openSettings() {
    const cfg = await api().get_config();
    document.getElementById('cfg-apikey').value = cfg.api_key || '';
    document.getElementById('cfg-downloaddir').value = cfg.download_dir || '';
    document.getElementById('cfg-sevenzippath').value = cfg.seven_zip_path || '';
    document.getElementById('cfg-tray').checked = cfg.minimize_to_tray;
    document.getElementById('cfg-appendmodid').checked = cfg.append_mod_id;
    document.getElementById('cfg-appendversion').checked = cfg.append_version;
    document.getElementById('validate-status').textContent = '';

    const registered = await api().is_registered();
    document.getElementById('reg-status').textContent = registered ? '(currently registered)' : '(not registered)';

    const modlRegistered = await api().is_modl_registered();
    document.getElementById('reg-modl-status').textContent = modlRegistered ? '(currently registered)' : '(not registered)';

    settingsOverlay.classList.remove('hidden');
}

function closeSettings() {
    settingsOverlay.classList.add('hidden');
}

async function saveSettings() {
    const apiKey = document.getElementById('cfg-apikey').value;
    const downloadDir = document.getElementById('cfg-downloaddir').value;
    const sevenZipPath = document.getElementById('cfg-sevenzippath').value;
    const tray = document.getElementById('cfg-tray').checked;
    const appendModID = document.getElementById('cfg-appendmodid').checked;
    const appendVersion = document.getElementById('cfg-appendversion').checked;
    try {
        await api().save_config(apiKey, downloadDir, tray, appendModID, appendVersion, sevenZipPath);
        closeSettings();
    } catch(e) {
        alert('Failed to save: ' + e);
    }
}

async function validateKey() {
    const key = document.getElementById('cfg-apikey').value;
    const status = document.getElementById('validate-status');
    if (!key) { status.textContent = 'Enter a key first.'; status.className = 'error'; return; }
    status.textContent = 'Validating...';
    status.className = '';
    try {
        const name = await api().validate_api_key(key);
        status.textContent = 'Connected as: ' + name;
        status.className = 'success';
    } catch(e) {
        status.textContent = 'Error: ' + e;
        status.className = 'error';
    }
}

async function browseFolder() {
    const current = document.getElementById('cfg-downloaddir').value;
    try {
        const path = await api().browse_folder(current);
        if (path) document.getElementById('cfg-downloaddir').value = path;
    } catch(e) {}
}

async function browse7z() {
    try {
        const path = await api().browse_7z();
        if (path) document.getElementById('cfg-sevenzippath').value = path;
    } catch(e) {}
}
