/**
 * Scientech-IMS — UI Utilities
 *
 * Shared UI helper functions: toasts, modals, loading states, formatting.
 */

// =========================================================================
// Toast Notifications
// =========================================================================

/**
 * Show a toast notification.
 * @param {string} message - Notification text
 * @param {'success'|'error'|'warning'|'info'} type - Toast type
 * @param {number} duration - Auto-dismiss in ms (default 4000)
 */
export function showToast(message, type = 'info', duration = 4000) {
    const container = document.getElementById('toast-container')
        || createToastContainer();

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;

    const icons = {
        success: 'fa-check-circle',
        error: 'fa-exclamation-circle',
        warning: 'fa-exclamation-triangle',
        info: 'fa-info-circle',
    };

    toast.innerHTML = `
        <i class="fas ${icons[type] || icons.info}"></i>
        <span class="toast-message">${escapeHtml(message)}</span>
        <button class="toast-close" onclick="this.parentElement.remove()">&times;</button>
    `;

    container.appendChild(toast);

    // Animate in
    requestAnimationFrame(() => toast.classList.add('toast-visible'));

    // Auto-dismiss
    if (duration > 0) {
        setTimeout(() => {
            toast.classList.remove('toast-visible');
            toast.addEventListener('transitionend', () => toast.remove());
        }, duration);
    }
}

function createToastContainer() {
    const container = document.createElement('div');
    container.id = 'toast-container';
    document.body.appendChild(container);
    return container;
}

// =========================================================================
// Modal Dialogs
// =========================================================================

/**
 * Show a confirmation dialog.
 * @param {string} title - Dialog title
 * @param {string} message - Dialog message
 * @param {Object} options - { confirmText, cancelText, danger }
 * @returns {Promise<boolean>}
 */
export function showConfirm(title, message, options = {}) {
    const {
        confirmText = 'Confirm',
        cancelText = 'Cancel',
        danger = false,
    } = options;

    return new Promise((resolve) => {
        const overlay = document.createElement('div');
        overlay.className = 'modal-overlay modal-active';

        overlay.innerHTML = `
            <div class="modal-content" style="max-width:420px">
                <div class="modal-header">
                    <h3>${escapeHtml(title)}</h3>
                </div>
                <div class="modal-body">
                    <p>${escapeHtml(message)}</p>
                </div>
                <div class="modal-footer">
                    <button class="btn btn-secondary" id="modal-cancel">${escapeHtml(cancelText)}</button>
                    <button class="btn ${danger ? 'btn-danger' : 'btn-primary'}" id="modal-confirm">
                        ${escapeHtml(confirmText)}
                    </button>
                </div>
            </div>
        `;

        document.body.appendChild(overlay);

        overlay.querySelector('#modal-confirm').addEventListener('click', () => {
            overlay.remove();
            resolve(true);
        });

        overlay.querySelector('#modal-cancel').addEventListener('click', () => {
            overlay.remove();
            resolve(false);
        });

        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) {
                overlay.remove();
                resolve(false);
            }
        });
    });
}

// =========================================================================
// Loading States
// =========================================================================

/**
 * Show a loading spinner inside a container.
 * @param {HTMLElement|string} container - DOM element or selector
 */
export function showLoading(container) {
    const el = typeof container === 'string'
        ? document.querySelector(container)
        : container;
    if (!el) return;

    el.innerHTML = `
        <div class="loading-container">
            <div class="loading-spinner"></div>
            <p class="text-muted">Loading...</p>
        </div>
    `;
}

/**
 * Show an empty state placeholder.
 * @param {HTMLElement|string} container - DOM element or selector
 * @param {string} message - Message to display
 * @param {string} icon - FontAwesome icon class
 */
export function showEmptyState(container, message = 'No data found', icon = 'fa-inbox') {
    const el = typeof container === 'string'
        ? document.querySelector(container)
        : container;
    if (!el) return;

    el.innerHTML = `
        <div class="empty-state">
            <i class="fas ${icon}"></i>
            <p>${escapeHtml(message)}</p>
        </div>
    `;
}

// =========================================================================
// Formatting Helpers
// =========================================================================

/**
 * Format a number with locale separators.
 */
export function formatNumber(value, decimals = 0) {
    if (value == null) return '—';
    return Number(value).toLocaleString('en-IN', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
    });
}

/**
 * Format a date string to locale display.
 */
export function formatDate(dateStr) {
    if (!dateStr) return '—';
    const d = new Date(dateStr);
    return d.toLocaleDateString('en-IN', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
    });
}

/**
 * Format a date with time.
 */
export function formatDateTime(dateStr) {
    if (!dateStr) return '—';
    const d = new Date(dateStr);
    return d.toLocaleDateString('en-IN', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
    });
}

/**
 * Get relative time string (e.g., "2 hours ago").
 */
export function timeAgo(dateStr) {
    if (!dateStr) return '—';
    const d = new Date(dateStr);
    const now = new Date();
    const seconds = Math.floor((now - d) / 1000);

    const intervals = [
        { label: 'year', seconds: 31536000 },
        { label: 'month', seconds: 2592000 },
        { label: 'week', seconds: 604800 },
        { label: 'day', seconds: 86400 },
        { label: 'hour', seconds: 3600 },
        { label: 'minute', seconds: 60 },
    ];

    for (const interval of intervals) {
        const count = Math.floor(seconds / interval.seconds);
        if (count >= 1) {
            return `${count} ${interval.label}${count > 1 ? 's' : ''} ago`;
        }
    }
    return 'Just now';
}

/**
 * Escape HTML to prevent XSS.
 */
export function escapeHtml(str) {
    if (str == null) return '';
    const div = document.createElement('div');
    div.textContent = String(str);
    return div.innerHTML;
}

/**
 * Debounce a function call.
 */
export function debounce(fn, delay = 300) {
    let timer;
    return (...args) => {
        clearTimeout(timer);
        timer = setTimeout(() => fn(...args), delay);
    };
}

/**
 * Generate a status badge HTML.
 */
export function statusBadge(status, text) {
    const colorMap = {
        active: 'success',
        completed: 'success',
        approved: 'success',
        received: 'success',
        in_transit: 'info',
        in_progress: 'info',
        pending: 'warning',
        requested: 'warning',
        overdue: 'danger',
        cancelled: 'danger',
        inactive: 'danger',
        rejected: 'danger',
    };
    const color = colorMap[status?.toLowerCase()] || 'secondary';
    const label = text || status || 'unknown';
    return `<span class="badge badge-${color}">${escapeHtml(label)}</span>`;
}

/**
 * Build pagination controls HTML.
 */
export function renderPagination(currentPage, totalPages, onPageChange) {
    if (totalPages <= 1) return '';

    const pages = [];
    const maxVisible = 5;
    let start = Math.max(1, currentPage - Math.floor(maxVisible / 2));
    let end = Math.min(totalPages, start + maxVisible - 1);
    if (end - start < maxVisible - 1) {
        start = Math.max(1, end - maxVisible + 1);
    }

    let html = '<div class="pagination">';

    html += `<button class="pagination-btn" ${currentPage <= 1 ? 'disabled' : ''}
        onclick="(${onPageChange})(${currentPage - 1})">
        <i class="fas fa-chevron-left"></i>
    </button>`;

    for (let i = start; i <= end; i++) {
        html += `<button class="pagination-btn ${i === currentPage ? 'active' : ''}"
            onclick="(${onPageChange})(${i})">${i}</button>`;
    }

    html += `<button class="pagination-btn" ${currentPage >= totalPages ? 'disabled' : ''}
        onclick="(${onPageChange})(${currentPage + 1})">
        <i class="fas fa-chevron-right"></i>
    </button>`;

    html += '</div>';
    return html;
}
