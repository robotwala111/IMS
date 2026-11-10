/**
 * Scientech-IMS Main Application
 * Handles UI interactions and page management
 */

// Global state
let currentPage = 'dashboard';
let categories = [];
let locations = [];
let transferItemMetadata = {};
let allTransferItems = [];
let transferSourceAvailableItemIds = new Set();
let transferStockAvailabilityCache = new Map();
let transferComplianceBlockerCache = new Map();
let usersCache = [];
let personalManagementTab = 'personal_qualification';
let pendingStockItemFilter = null; // { itemId, itemName } - set when navigating from Products to Stock
let allLogs = [];
let allAssets = [];
let allTransfers = [];
let allEmployeeRecords = [];
let employeesCache = []; // Non-login employees (field technicians etc.)
let assetItems = { equipment: [], instruments: [], consumables: [], accessories: [] };
let assetCurrentTab = 'equipment';
let assetEquipSubTab = 'equipment';
let allJobs = [];
let currentProductTypeTab = 'equipment';
let currentStockTypeTab = 'consumable';

function normalizeTypeKey(value) {
    return (value || '').toString().trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
}

function canonicalInventoryTypeKey(value) {
    const key = normalizeTypeKey(value);
    const aliases = {
        equipments: 'equipment',
        instruments: 'instrument',
        consumables: 'consumable',
        accessories: 'accessory',
    };
    return aliases[key] || key;
}

function productTypeForCategory(category) {
    const candidates = [
        category?.category_type_key,
        category?.category_type_name,
        category?.name,
    ];
    for (const candidate of candidates) {
        const type = canonicalInventoryTypeKey(candidate);
        if (type === 'equipment' || type === 'instrument') return type;
    }
    return '';
}

function activeRecords(records) {
    return (records || []).filter(record => {
        const value = record?.is_active ?? record?.isActive ?? record?.active;
        if (value === undefined || value === null) return true;
        if (typeof value === 'string') {
            return !['false', '0', 'inactive', 'disabled', 'no'].includes(value.trim().toLowerCase());
        }
        return value !== false && value !== 0;
    });
}

function localDateInputValue(date = new Date()) {
    const localDate = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
    return localDate.toISOString().slice(0, 10);
}

function localDateTimeInputValue(date = new Date()) {
    const localDate = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
    return localDate.toISOString().slice(0, 16);
}

function isSerializedCategory(categoryId) {
    const category = categories.find(c => c.id === categoryId);
    return (category?.stock_behavior || '').toLowerCase() === 'serialized';
}

function isSerialTrackedRecord(record) {
    return (record?.stock_behavior || '').toLowerCase() === 'serialized' || record?.is_serialized === true;
}

function isQuantityTrackedRecord(record) {
    return !isSerialTrackedRecord(record);
}

function quantityTypeKeyForRecord(record) {
    const category = record?.category_id ? categories.find(c => c.id === record.category_id) : null;
    const key = canonicalInventoryTypeKey(
        record?.asset_type ||
        record?.category_type_key ||
        record?.category_type_name ||
        record?.category_name ||
        category?.category_type_key ||
        category?.name ||
        record?.name
    );
    return ['consumable', 'accessory'].includes(key) ? key : 'consumable';
}

function stockRegisterTypeOptions(items) {
    const allowed = new Map();
    items.forEach(item => {
        const key = quantityTypeKeyForRecord(item);
        if (['consumable', 'accessory'].includes(key)) {
            allowed.set(key, key === 'accessory' ? 'Accessories' : 'Consumables');
        }
    });
    return [...allowed.entries()]
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([key, label]) => `<option value="${key}">${label}</option>`)
        .join('');
}

function stockItemDescriptionLabel(item) {
    const description = (item?.description || '').trim();
    const name = (item?.name || '').trim();
    const idPrefix = item?.id_number ? `${item.id_number} - ` : '';
    const mainLabel = description || name || item?.sku || 'Unnamed item';
    const productSuffix = description && name && description !== name ? ` (${name})` : '';
    return `${idPrefix}${mainLabel}${productSuffix}`;
}

async function confirmProbableDuplicateProduct(data, excludeItemId = null) {
    if (!data?.name?.trim()) return true;
    try {
        const matches = await ItemsAPI.getDuplicateSuggestions({
            name: data.name,
            manufacturer: data.manufacturer,
            model: data.model,
            excludeItemId
        });
        if (!Array.isArray(matches) || matches.length === 0) return true;
        const labels = matches.slice(0, 3).map(item =>
            `${item.name}${item.manufacturer ? ` / ${item.manufacturer}` : ''}${item.model ? ` / ${item.model}` : ''}`
        );
        return confirm(`Possible duplicate product found:\n\n${labels.join('\n')}\n\nCreate or save this product anyway?`);
    } catch (error) {
        console.warn('Could not check probable product duplicates', error);
        return true;
    }
}

function isProductTypeKey(type) {
    return ['equipment', 'instrument'].includes(canonicalInventoryTypeKey(type));
}

function productCategoriesForType(type) {
    const key = canonicalInventoryTypeKey(type);
    return categories.filter(c =>
        (c.stock_behavior || '').toLowerCase() === 'serialized' &&
        canonicalInventoryTypeKey(c.name || c.category_type_key || c.category_type_name) === key
    );
}

function isSerializedTransferType(type) {
    return ['equipment', 'instrument'].includes(canonicalInventoryTypeKey(type));
}

function isQuantityTransferType(type) {
    return ['consumable', 'accessory'].includes(canonicalInventoryTypeKey(type));
}

function isReturnableTransferType(type) {
    return ['equipment', 'instrument', 'accessory'].includes(canonicalInventoryTypeKey(type));
}

function transferTypeLabel(type) {
    const labels = {
        equipment: 'Equipment',
        instrument: 'Instrument',
        consumable: 'Consumable',
        accessory: 'Accessory'
    };
    const key = canonicalInventoryTypeKey(type);
    return labels[key] || (type || 'Transfer');
}

function isDocumentedLocalIssueTransfer(transfer) {
    return transfer &&
        transfer.from_location_id &&
        transfer.from_location_id === transfer.to_location_id &&
        String(transfer.shipping_method || '').toLowerCase() === 'issue stock';
}

function canReceiveTransfer(transfer, statusKey) {
    return statusKey === 'in_transit' && !isDocumentedLocalIssueTransfer(transfer);
}

function itemMatchesTransferType(item, transferType) {
    const key = canonicalInventoryTypeKey(transferType);
    if (isQuantityTransferType(key)) {
        return isQuantityTrackedRecord(item) && quantityTypeKeyForRecord(item) === key;
    }

    if (isSerializedTransferType(key)) {
        if (!isSerialTrackedRecord(item)) return false;
        const itemType = canonicalInventoryTypeKey(item?.asset_type || item?.category_type_key || item?.category_name);
        return itemType === key;
    }

    return false;
}

function stockBehaviorLabel(value) {
    return value === 'serialized' ? 'Serialized' : 'Quantity Based';
}

function inventoryCategoryOptions(selected = '') {
    const options = [
        ['equipment', 'Equipment'],
        ['instrument', 'Instrument'],
        ['consumable', 'Consumable'],
        ['accessory', 'Accessory'],
    ];
    return options.map(([value, label]) =>
        `<option value="${value}" ${canonicalInventoryTypeKey(selected) === value ? 'selected' : ''}>${label}</option>`
    ).join('');
}

async function ensureCategoryTypeId(typeKey, stockBehavior) {
    const key = canonicalInventoryTypeKey(typeKey);
    if (!key) return null;

    const typeName = {
        equipment: 'Equipment',
        instrument: 'Instrument',
        consumable: 'Consumable',
        accessory: 'Accessory',
    }[key] || key;

    try {
        const existing = await CategoryTypesAPI.getAll({ active_only: false });
        const found = (Array.isArray(existing) ? existing : []).find(type =>
            canonicalInventoryTypeKey(type.key || type.name) === key
        );
        if (found?.id) {
            if (found.is_active === false || found.stock_behavior !== (stockBehavior || defaultStockBehaviorForCategoryName(key))) {
                await CategoryTypesAPI.update(found.id, {
                    stock_behavior: stockBehavior || defaultStockBehaviorForCategoryName(key),
                    is_active: true
                });
            }
            return found.id;
        }
    } catch (error) {
        console.warn('Could not load category types:', error);
    }

    const created = await CategoryTypesAPI.create({
        name: typeName,
        key,
        stock_behavior: stockBehavior || defaultStockBehaviorForCategoryName(key),
        is_active: true
    });
    return created?.id || null;
}

function defaultStockBehaviorForCategoryName(name) {
    const key = canonicalInventoryTypeKey(name);
    return ['equipment', 'instrument'].includes(key) ? 'serialized' : 'quantity';
}

function bindCategoryStockBehaviorHint(form) {
    const behaviorSelect = form.querySelector('[name="stock_behavior"]');
    const behaviorHint = form.querySelector('[data-stock-behavior-hint]');
    if (!behaviorSelect) return;

    const updateHint = () => {
        const behavior = behaviorSelect.value || 'quantity';
        if (behaviorHint) {
            behaviorHint.textContent = behavior === 'serialized'
                ? 'Serial-based categories are managed in Products. Quantity is always 1 per serial/ID.'
                : 'Quantity-based categories are managed in Stock Levels with receipt, transfer, adjustment, and reorder workflows.';
        }
    };

    behaviorSelect.addEventListener('change', updateHint);
    updateHint();
}

// Role labels and badge colors
const ROLE_LABELS = {
    admin: 'Admin',
    head_office_manager: 'General Manager',
    location_manager: 'Location Manager'
};
const ROLE_BADGES = {
    admin: 'badge-danger',
    head_office_manager: 'badge-primary',
    location_manager: 'badge-warning'
};

// HTML escape utility to prevent XSS
function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

/**
 * Prevents double-submission by disabling the submit button for the duration of `asyncFn`.
 * Usage: await withSubmitLock(form, asyncFn)
 *
 * @param {HTMLFormElement} form  - The form element
 * @param {Function}        asyncFn - Async function to run while locked
 */
async function withSubmitLock(form, asyncFn) {
    if (form._submitting) return;
    form._submitting = true;
    const btn = form.querySelector('[type="submit"]') || form.querySelector('button:not([type="button"])');
    const originalText = btn ? btn.textContent : '';
    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Processing…';
    }
    try {
        await asyncFn();
    } finally {
        form._submitting = false;
        if (btn) {
            btn.disabled = false;
            btn.textContent = originalText;
        }
    }
}

// Global double-submit guard (capture phase, runs before individual listeners).
// Blocks re-entry if a form is already being processed via withSubmitLock.
document.addEventListener('submit', (e) => {
    if (e.target._submitting) {
        e.preventDefault();
        e.stopImmediatePropagation();
    }
}, true);

function getUserPermissions() {
    const user = AuthAPI.getUser();
    if (!user) return { role: null, canManage: false, isAdmin: false, canViewAllLocations: false };
    const role = user.role;
    return {
        role,
        isAdmin: role === 'admin',
        isHOManager: role === 'head_office_manager',
        isLocationManager: role === 'location_manager',
        canManage: ['admin', 'head_office_manager', 'location_manager'].includes(role),
        canManageCategories: ['admin', 'head_office_manager'].includes(role),
        canViewAllLocations: ['admin', 'head_office_manager'].includes(role),
    };
}

// Initialize application
document.addEventListener('DOMContentLoaded', () => {
    initializeApp();
});

function initializeApp() {
    loadBranding();

    const resetToken = new URLSearchParams(window.location.search).get('reset_token');

    // Remove any credentials that may have leaked into the URL (e.g. browser autofill)
    if (window.location.search) {
        window.history.replaceState(null, '', window.location.pathname);
    }

    // Check if user is authenticated
    if (AuthAPI.isAuthenticated()) {
        showMainApp();
        // Proactively refresh the token if it's expired or near expiry
        // before firing parallel page-load API calls
        _ensureFreshToken().then(() => loadDashboard());
    } else if (TokenStorage.getRefreshToken()) {
        // No access token but have refresh token — try silent re-auth
        API._doRefresh().then(ok => {
            if (ok) { showMainApp(); loadDashboard(); }
            else { showLoginPage(); }
        });
    } else {
        showLoginPage();
    }
    
    // Setup event listeners
    setupEventListeners();
    
    // Restore remembered email on initial load
    restoreRememberedEmail();
    if (resetToken) showPasswordResetModal(resetToken);
}

async function loadBranding() {
    try {
        const branding = await BrandingAPI.get();
        const appName = branding.app_name || 'Scientech-IMS';
        const companyName = branding.company_name || 'Scientech Services';
        document.querySelector('.login-brand-name').innerHTML = escapeHtml(appName).replace(/IMS$/, '<span>IMS</span>');
        document.querySelector('.sidebar-header span').textContent = appName;
        const tagline = document.querySelector('.login-brand-tagline');
        if (tagline) tagline.textContent = companyName;
        if (branding.logo_data_url) {
            const loginLogo = document.getElementById('login-brand-logo');
            const sidebarLogo = document.getElementById('sidebar-brand-logo');
            [loginLogo, sidebarLogo].forEach(img => {
                if (!img) return;
                img.src = branding.logo_data_url;
                img.classList.remove('hidden');
            });
        }
    } catch (error) {
        console.warn('Branding could not be loaded:', error);
    }
}

function _parseJwtExpiry(token) {
    try {
        const payload = JSON.parse(atob(token.split('.')[1]));
        return payload.exp ? payload.exp * 1000 : null;
    } catch { return null; }
}

async function _ensureFreshToken() {
    const token = TokenStorage.getAccessToken();
    if (!token) return;
    const exp = _parseJwtExpiry(token);
    // Refresh if token expires within next 2 minutes
    if (exp && exp - Date.now() < 120_000) {
        await API._doRefresh();
    }
}

function setupEventListeners() {
    // Login form
    document.getElementById('login-form').addEventListener('submit', handleLogin);
    
    // Password visibility toggle
    document.getElementById('toggle-password').addEventListener('click', togglePasswordVisibility);
    
    // Forgot password flow
    document.getElementById('forgot-password-link').addEventListener('click', (e) => {
        e.preventDefault();
        document.getElementById('forgot-password-modal').classList.remove('hidden');
        document.getElementById('forgot-email').focus();
    });
    document.getElementById('forgot-modal-close').addEventListener('click', closeForgotModal);
    document.getElementById('forgot-back-link').addEventListener('click', (e) => { e.preventDefault(); closeForgotModal(); });
    document.getElementById('forgot-done-btn').addEventListener('click', closeForgotModal);
    document.getElementById('forgot-password-form').addEventListener('submit', handleForgotPassword);
    
    // Logout button
    document.getElementById('logout-btn').addEventListener('click', handleLogout);
    
    // Sidebar navigation
    document.querySelectorAll('.nav-item[data-page]').forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            navigateTo(item.dataset.page);
            if (window.innerWidth <= 768) {
                document.querySelector('.sidebar')?.classList.remove('open');
            }
        });
    });
    
    // Sidebar toggle
    document.getElementById('sidebar-toggle').addEventListener('click', () => {
        const sidebar = document.querySelector('.sidebar');
        if (window.innerWidth <= 768) {
            sidebar.classList.toggle('open');
        } else {
            sidebar.classList.toggle('collapsed');
        }
    });

    // Global search — navigate to matching module on Enter
    const globalSearch = document.getElementById('global-search');
    if (globalSearch) {
        globalSearch.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                const q = globalSearch.value.trim().toLowerCase();
                if (!q) return;
                const moduleMap = {
                    product: 'items', item: 'items', inventory: 'items',
                    stock: 'stock', level: 'stock',
                    location: 'locations', site: 'locations',
                    category: 'categories',
                    transfer: 'transfers',
                    compliance: 'compliance', calibration: 'compliance',
                    log: 'logs', audit: 'logs',
                    asset: 'assets', equipment: 'assets',
                    personal: 'personal', personnel: 'personal', employee: 'personal',
                    job: 'jobs',
                    user: 'users',
                };
                const match = Object.keys(moduleMap).find(k => q.includes(k));
                if (match) {
                    navigateTo(moduleMap[match]);
                    globalSearch.value = '';
                } else {
                    showToast('No matching module found', 'info');
                }
            }
        });
    }
}

// Authentication
let lockoutInterval = null;

async function handleLogin(e) {
    e.preventDefault();
    
    const email = document.getElementById('email').value.trim();
    const password = document.getElementById('password').value;
    const rememberMe = document.getElementById('remember-me').checked;
    const errorDiv = document.getElementById('login-error');
    const submitBtn = document.getElementById('login-submit-btn');
    const lockoutDiv = document.getElementById('login-lockout');
    const attemptsDiv = document.getElementById('login-attempts-warning');
    
    // Don't submit if lockout countdown is active
    if (lockoutDiv && !lockoutDiv.classList.contains('hidden')) return;
    
    try {
        errorDiv.textContent = '';
        errorDiv.classList.remove('visible');
        attemptsDiv.classList.add('hidden');
        submitBtn.classList.add('loading');
        submitBtn.disabled = true;
        
        const user = await AuthAPI.login(email, password);
        
        // Handle remember me
        if (rememberMe) {
            localStorage.setItem('sims_remembered_email', email);
        } else {
            localStorage.removeItem('sims_remembered_email');
        }
        
        // Show last login info in welcome toast
        let welcomeMsg = 'Welcome back, ' + escapeHtml(user.name) + '!';
        if (user.last_login_at) {
            const lastLogin = new Date(user.last_login_at);
            welcomeMsg += ' Last login: ' + lastLogin.toLocaleString();
        }
        
        showToast(welcomeMsg, 'success');
        showMainApp();
        updateUserInfo(user);
        loadDashboard();
    } catch (error) {
        let msg = 'An unexpected error occurred';
        let detail = error.detail || null;
        
        if (detail && typeof detail === 'object') {
            msg = detail.message || msg;
            const info = detail.details || {};
            
            // Handle lockout response
            if (info.lockout_remaining_seconds && info.lockout_remaining_seconds > 0) {
                startLockoutCountdown(info.lockout_remaining_seconds);
                errorDiv.textContent = '';
                errorDiv.classList.remove('visible');
                submitBtn.classList.remove('loading');
                submitBtn.disabled = true;
                return;
            }
            
            // Show remaining attempts warning
            if (info.remaining_attempts !== undefined && info.remaining_attempts !== null) {
                const remaining = info.remaining_attempts;
                const attemptsText = document.getElementById('attempts-remaining-text');
                if (remaining <= 3 && remaining > 0) {
                    attemptsText.textContent = remaining === 1
                        ? 'Last attempt before account lockout!'
                        : remaining + ' attempts remaining before account lockout';
                    attemptsDiv.classList.remove('hidden');
                } else if (remaining === 0) {
                    startLockoutCountdown(info.lockout_duration_seconds || 900);
                    errorDiv.textContent = '';
                    errorDiv.classList.remove('visible');
                    submitBtn.classList.remove('loading');
                    submitBtn.disabled = true;
                    return;
                }
            }
        } else if (error && typeof error.message === 'string') {
            msg = error.message;
        }
        
        errorDiv.innerHTML = '<i class="fas fa-exclamation-circle"></i> ' + escapeHtml(msg);
        errorDiv.classList.add('visible');
    } finally {
        submitBtn.classList.remove('loading');
        if (!document.getElementById('login-lockout').classList.contains('hidden')) {
            submitBtn.disabled = true;
        } else {
            submitBtn.disabled = false;
        }
    }
}

function startLockoutCountdown(seconds) {
    const lockoutDiv = document.getElementById('login-lockout');
    const timerSpan = document.getElementById('lockout-timer');
    const submitBtn = document.getElementById('login-submit-btn');
    const errorDiv = document.getElementById('login-error');
    
    errorDiv.textContent = '';
    errorDiv.classList.remove('visible');
    lockoutDiv.classList.remove('hidden');
    submitBtn.disabled = true;
    
    if (lockoutInterval) clearInterval(lockoutInterval);
    
    let remaining = seconds;
    
    function updateTimer() {
        const mins = Math.floor(remaining / 60);
        const secs = remaining % 60;
        timerSpan.textContent = 'Try again in ' + mins + ':' + String(secs).padStart(2, '0');
        
        if (remaining <= 0) {
            clearInterval(lockoutInterval);
            lockoutInterval = null;
            lockoutDiv.classList.add('hidden');
            submitBtn.disabled = false;
            document.getElementById('login-attempts-warning').classList.add('hidden');
        }
        remaining--;
    }
    
    updateTimer();
    lockoutInterval = setInterval(updateTimer, 1000);
}

function restoreRememberedEmail() {
    const saved = localStorage.getItem('sims_remembered_email');
    if (saved) {
        document.getElementById('email').value = saved;
        document.getElementById('remember-me').checked = true;
        // Focus password field since email is pre-filled
        document.getElementById('password').focus();
    }
}

function togglePasswordVisibility() {
    const passwordInput = document.getElementById('password');
    const toggleBtn = document.getElementById('toggle-password');
    const icon = toggleBtn.querySelector('i');
    
    if (passwordInput.type === 'password') {
        passwordInput.type = 'text';
        icon.classList.replace('fa-eye', 'fa-eye-slash');
        toggleBtn.setAttribute('aria-label', 'Hide password');
    } else {
        passwordInput.type = 'password';
        icon.classList.replace('fa-eye-slash', 'fa-eye');
        toggleBtn.setAttribute('aria-label', 'Show password');
    }
}

function closeForgotModal() {
    document.getElementById('forgot-password-modal').classList.add('hidden');
    document.getElementById('forgot-step-request').classList.remove('hidden');
    document.getElementById('forgot-step-sent').classList.add('hidden');
    document.getElementById('forgot-error').textContent = '';
    document.getElementById('forgot-error').classList.remove('visible');
    document.getElementById('forgot-password-form').reset();
}

async function handleForgotPassword(e) {
    e.preventDefault();
    const email = document.getElementById('forgot-email').value;
    const errorDiv = document.getElementById('forgot-error');
    
    try {
        errorDiv.textContent = '';
        errorDiv.classList.remove('visible');
        
        await API._fetch(`${API_BASE_URL}/auth/forgot-password`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email })
        });
        
        // Always show success (don't reveal if email exists)
        document.getElementById('forgot-sent-email').textContent = email;
        document.getElementById('forgot-step-request').classList.add('hidden');
        document.getElementById('forgot-step-sent').classList.remove('hidden');
    } catch (error) {
        errorDiv.textContent = 'Something went wrong. Please try again.';
        errorDiv.classList.add('visible');
    }
}

async function handleLogout(e) {
    e.preventDefault();
    await AuthAPI.logout();
    showLoginPage();
    showToast('You have been logged out', 'info');
}

function showPasswordResetModal(token) {
    const modalTitle = document.getElementById('modal-title');
    const modalBody = document.getElementById('modal-body');
    modalTitle.textContent = 'Reset Password';
    modalBody.innerHTML = `
        <form id="password-reset-form">
            <div class="form-group">
                <label>New Password *</label>
                <input type="password" name="new_password" minlength="8" required autocomplete="new-password">
                <small class="form-help">Use uppercase, lowercase, a number, and a special character.</small>
            </div>
            <div class="form-group">
                <label>Confirm New Password *</label>
                <input type="password" name="confirm_password" minlength="8" required autocomplete="new-password">
            </div>
            <div id="password-reset-error" class="form-error"></div>
            <div class="modal-actions">
                <button type="submit" class="btn btn-primary">Reset Password</button>
            </div>
        </form>`;
    document.getElementById('modal-overlay').classList.remove('hidden');
    document.getElementById('password-reset-form').addEventListener('submit', async event => {
        event.preventDefault();
        await withSubmitLock(event.target, async () => {
            const formData = new FormData(event.target);
            const password = formData.get('new_password');
            const confirmation = formData.get('confirm_password');
            const error = document.getElementById('password-reset-error');
            if (password !== confirmation) {
                error.textContent = 'Passwords do not match.';
                return;
            }
            try {
                await AuthAPI.resetPassword(token, password, confirmation);
                closeModal();
                showLoginPage();
                showToast('Password reset successfully. Please log in.', 'success');
            } catch (resetError) {
                error.textContent = resetError.message;
            }
        });
    });
}

// Page Navigation
function showLoginPage() {
    document.getElementById('login-page').classList.remove('hidden');
    document.getElementById('main-app').classList.add('hidden');
    // Reset login form state
    document.getElementById('login-form').reset();
    const errorDiv = document.getElementById('login-error');
    errorDiv.textContent = '';
    errorDiv.classList.remove('visible');
    // Reset password visibility
    const passwordInput = document.getElementById('password');
    if (passwordInput.type !== 'password') {
        passwordInput.type = 'password';
        const icon = document.querySelector('#toggle-password i');
        if (icon) { icon.classList.replace('fa-eye-slash', 'fa-eye'); }
    }
    // Clear lockout and attempts warnings
    document.getElementById('login-lockout').classList.add('hidden');
    document.getElementById('login-attempts-warning').classList.add('hidden');
    document.getElementById('login-submit-btn').disabled = false;
    if (lockoutInterval) { clearInterval(lockoutInterval); lockoutInterval = null; }
    // Restore remembered email
    restoreRememberedEmail();
}

function showMainApp() {
    // Always clean the URL when showing the main app (removes any leaked credentials)
    if (window.location.search || window.location.hash) {
        window.history.replaceState(null, '', window.location.pathname);
    }

    document.getElementById('login-page').classList.add('hidden');
    document.getElementById('main-app').classList.remove('hidden');
    
    const user = AuthAPI.getUser();
    if (user) {
        updateUserInfo(user);
        applyRoleRestrictions();
    }

    // Initialize premium features on first show
    if (typeof premiumInit === 'function') premiumInit();
}

function updateUserInfo(user) {
    document.getElementById('user-name').textContent = user.name;
    document.getElementById('user-role').textContent = ROLE_LABELS[user.role] || user.role;
    // Set avatar initials
    const avatarEl = document.getElementById('user-avatar');
    if (avatarEl && user.name) {
        const parts = user.name.trim().split(/\s+/);
        avatarEl.textContent = parts.length >= 2
            ? (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
            : user.name.substring(0, 2).toUpperCase();
    }
}

function applyRoleRestrictions() {
    const perms = getUserPermissions();
    if (!perms.role) return;

    // Sidebar visibility by role
    const pageAccess = {
        dashboard: true,
        items: true,
        stock: true,
        locations: perms.canManage,
        categories: perms.canManage,
        transfers: true,
        compliance: true,
        logs: perms.isAdmin || perms.isHOManager,
        personal: perms.canManage,
        users: perms.isAdmin || perms.isHOManager,
    };

    document.querySelectorAll('.nav-item[data-page]').forEach(item => {
        const page = item.dataset.page;
        item.style.display = pageAccess[page] === false ? 'none' : '';
    });

    // Hide "Add" buttons in section headers for restricted users
    document.querySelectorAll('.section-header .btn-primary').forEach(btn => {
        const section = btn.closest('.content-section');
        if (!section) return;
        const sectionId = section.id;
        if (sectionId === 'users-section' || sectionId === 'locations-section') {
            btn.style.display = (perms.isAdmin || perms.isHOManager) ? '' : 'none';
        } else if (sectionId === 'categories-section') {
            btn.style.display = perms.canManageCategories ? '' : 'none';
        } else {
            btn.style.display = perms.canManage ? '' : 'none';
        }
    });

    // Stock: Adjust Stock requires manager+; Receipt/Issue/Return allowed for all
    const adjustBtn = document.querySelector('button[onclick="showAdjustStockModal()"]');
    if (adjustBtn) adjustBtn.style.display = perms.canManage ? '' : 'none';
    const alertBtn = document.querySelector('button[onclick="sendLowStockAlert()"]');
    if (alertBtn) alertBtn.style.display = perms.canManage ? '' : 'none';
}

function navigateTo(page) {
    // Check permission before navigating
    const perms = getUserPermissions();
    if (perms.role) {
        const restricted = {
            users: perms.isAdmin || perms.isHOManager,
            locations: perms.canManage,
            categories: perms.canManage,
            logs: perms.isAdmin || perms.isHOManager,
            personal: perms.canManage,
        };
        if (restricted[page] === false) {
            showToast('You do not have permission to access this section', 'error');
            return;
        }
    }

    currentPage = page;
    
    // Update active nav item
    document.querySelectorAll('.nav-item').forEach(item => {
        item.classList.remove('active');
    });
    document.querySelector(`.nav-item[data-page="${page}"]`)?.classList.add('active');
    
    // Update page title
    const titles = {
        dashboard: 'Dashboard',
        items: 'Products',
        stock: 'Stock Levels',
        locations: 'Locations',
        categories: 'Categories',
        transfers: 'Transfers',
        compliance: 'Compliance',
        logs: 'Audit Logs',
        personal: 'Personnel',
        jobs: 'Jobs (Hold)',
        users: 'User Management'
    };
    document.getElementById('page-title').textContent = titles[page] || page;
    
    // Hide all sections
    document.querySelectorAll('.content-section').forEach(section => {
        section.classList.add('hidden');
    });
    
    // Show selected section
    document.getElementById(`${page}-section`)?.classList.remove('hidden');
    
    // Load section data
    loadPageData(page);
}

async function loadPageData(page) {
    switch (page) {
        case 'dashboard':
            await loadDashboard();
            break;
        case 'items':
            await loadItems();
            break;
        case 'stock':
            await loadStock();
            break;
        case 'locations':
            await loadLocations();
            break;
        case 'categories':
            await loadCategories();
            break;
        case 'transfers':
            setTransferModuleTab('consumables');
            await refreshTransfersSection();
            break;
        case 'compliance':
            await loadComplianceData();
            break;
        case 'logs':
            await loadLogs();
            break;
        case 'personal':
            await loadEmployeeRecords();
            break;
        case 'jobs':
            await loadJobs();
            break;
        case 'users':
            await loadUsers();
            break;
    }
}

function setPersonalManagementTab(tab) {
    // Kept for backwards compatibility - no-op now (tabs removed)
    loadEmployeeRecords().catch(error => console.error('Personal records load error:', error));
}

function setTransferModuleTab(tab) {
    const consumablesBtn = document.getElementById('transfer-module-consumables');
    const equipmentBtn = document.getElementById('transfer-module-equipment');
    const consumablesPanel = document.getElementById('transfer-consumables-panel');
    const equipmentPanel = document.getElementById('transfer-equipment-panel');

    if (!consumablesBtn || !equipmentBtn || !consumablesPanel || !equipmentPanel) {
        return;
    }

    if (tab === 'equipment') {
        equipmentBtn.classList.add('active');
        consumablesBtn.classList.remove('active');
        equipmentPanel.classList.remove('hidden');
        consumablesPanel.classList.add('hidden');
    } else {
        consumablesBtn.classList.add('active');
        equipmentBtn.classList.remove('active');
        consumablesPanel.classList.remove('hidden');
        equipmentPanel.classList.add('hidden');
    }

    loadTransfers().catch(error => console.error('Transfer list refresh error:', error));
}

// ===== Equipment Compliance =====
let allComplianceItems = [];
let allComplianceCalibration = [];
let allComplianceMaintenance = [];
let filteredComplianceAll = [];
let filteredComplianceCalibration = [];
let filteredComplianceMaintenance = [];
let complianceActiveTab = 'all';

const compliancePagination = {
    all:         { currentPage: 1, itemsPerPage: 10, totalItems: 0, totalPages: 0 },
    calibration: { currentPage: 1, itemsPerPage: 10, totalItems: 0, totalPages: 0 },
    maintenance: { currentPage: 1, itemsPerPage: 10, totalItems: 0, totalPages: 0 },
};

function renderCompliancePage(tab) {
    const dataMap   = { all: filteredComplianceAll, calibration: filteredComplianceCalibration, maintenance: filteredComplianceMaintenance };
    const renderMap = { all: renderAllEquipmentTable, calibration: renderCalibrationTable, maintenance: renderMaintenanceTable };
    const records = dataMap[tab] || [];
    const state = compliancePagination[tab];
    state.totalItems = records.length;
    state.totalPages = Math.max(1, Math.ceil(records.length / state.itemsPerPage));
    if (state.currentPage > state.totalPages) state.currentPage = state.totalPages;
    const start = (state.currentPage - 1) * state.itemsPerPage;
    const end = start + state.itemsPerPage;
    renderMap[tab](records.slice(start, end));
    const paginationDiv = document.getElementById('compliance-' + tab + '-pagination');
    if (paginationDiv) paginationDiv.style.display = records.length > 0 ? 'block' : 'none';
    const infoEl  = document.getElementById('compliance-' + tab + '-page-info');
    if (infoEl) infoEl.textContent = `Showing ${records.length ? start + 1 : 0} - ${Math.min(end, state.totalItems)} of ${state.totalItems}`;
    const inputEl = document.getElementById('compliance-' + tab + '-page-input');
    if (inputEl) inputEl.value = state.currentPage;
    const totalEl = document.getElementById('compliance-' + tab + '-total-pages');
    if (totalEl) totalEl.textContent = state.totalPages;
    const firstBtn = document.getElementById('compliance-' + tab + '-first-page');
    const prevBtn  = document.getElementById('compliance-' + tab + '-prev-page');
    const nextBtn  = document.getElementById('compliance-' + tab + '-next-page');
    const lastBtn  = document.getElementById('compliance-' + tab + '-last-page');
    if (firstBtn) firstBtn.disabled = state.currentPage === 1;
    if (prevBtn)  prevBtn.disabled  = state.currentPage === 1;
    if (nextBtn)  nextBtn.disabled  = state.currentPage === state.totalPages;
    if (lastBtn)  lastBtn.disabled  = state.currentPage === state.totalPages;
}

function goToCompliancePage(tab, pageNum) {
    const state = compliancePagination[tab];
    state.currentPage = Math.max(1, Math.min(parseInt(pageNum), state.totalPages));
    renderCompliancePage(tab);
}
function prevCompliancePage(tab) {
    const state = compliancePagination[tab];
    if (state.currentPage > 1) { state.currentPage--; renderCompliancePage(tab); }
}
function nextCompliancePage(tab) {
    const state = compliancePagination[tab];
    if (state.currentPage < state.totalPages) { state.currentPage++; renderCompliancePage(tab); }
}

function escapeSpreadsheetCSV(value) {
    let text = value == null ? '' : String(value);
    if (/^[=+\-@\t\r]/.test(text)) text = "'" + text;
    return '"' + text.replace(/"/g, '""') + '"';
}

function exportComplianceCSV() {
    const tab = complianceActiveTab || 'all';
    const dataMap = { all: filteredComplianceAll, calibration: filteredComplianceCalibration, maintenance: filteredComplianceMaintenance };
    const records = dataMap[tab] || [];
    if (!records.length) { showToast('No records to export', 'warning'); return; }
    const esc = escapeSpreadsheetCSV;
    let headers, rows;
    if (tab === 'calibration') {
        headers = ['Serial Number', 'ID No.', 'Equipment', 'Location', 'Calibration Due', 'Last Result', 'Due Soon', 'Status', 'Issues'];
        rows = records.map(r => [esc(r.serial_number), esc(r.id_number), esc(r.item_name), esc(r.location_name),
            esc(r.calibration_due_at ? new Date(r.calibration_due_at).toLocaleDateString() : '-'),
            esc(r.calibration_result || '-'), esc(r.calibration_due_soon ? 'Yes' : 'No'),
            esc(r.can_transfer ? 'Clear' : 'Blocked'), esc((r.blocked_reasons || []).join('; '))]);
    } else if (tab === 'maintenance') {
        headers = ['Serial Number', 'Equipment', 'Frequency (days)', 'Location', 'Last Completed', 'Next Due', 'Period Status', 'Status', 'Issues'];
        rows = records.map(r => [esc(r.serial_number), esc(r.item_name), esc(r.maintenance_interval_days || 30),
            esc(r.location_name),
            esc(r.maintenance_last_completed_at ? new Date(r.maintenance_last_completed_at).toLocaleDateString() : 'Never'),
            esc(r.maintenance_next_due_at ? new Date(r.maintenance_next_due_at).toLocaleDateString() : 'Overdue'),
            esc(r.maintenance_completed_this_period ? 'Done' : 'Pending'),
            esc(r.can_transfer ? 'Clear' : 'Blocked'), esc((r.blocked_reasons || []).join('; '))]);
    } else {
        headers = ['Serial Number', 'Equipment', 'Location', 'Calibration Due', 'Calibration Result', 'Equipment Status', 'Service Period', 'Status', 'Issues'];
        rows = records.map(r => [esc(r.serial_number), esc(r.item_name), esc(r.location_name),
            esc(r.calibration_due_at ? new Date(r.calibration_due_at).toLocaleDateString() : 'N/A'),
            esc(r.calibration_result || 'N/A'),
            esc(r.maintenance_next_due_at ? new Date(r.maintenance_next_due_at).toLocaleDateString() : 'Never Done'),
            esc(r.maintenance_completed_this_period ? 'Done' : 'Pending'),
            esc(r.can_transfer ? 'Clear' : 'Blocked'), esc((r.blocked_reasons || []).join('; '))]);
    }
    const csv = [headers.join(','), ...rows.map(r => r.join(','))].join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'compliance_' + tab + '_' + new Date().toISOString().slice(0, 10) + '.csv';
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

function setComplianceTab(tab) {
    complianceActiveTab = tab;
    const tabs = ['all', 'calibration', 'maintenance'];
    tabs.forEach(t => {
        const btn = document.getElementById('compliance-tab-' + t);
        const panel = document.getElementById('compliance-' + t + '-panel');
        if (btn) btn.classList.toggle('active', t === tab);
        if (panel) panel.classList.toggle('hidden', t !== tab);
    });
    filterComplianceData();
}

function filterComplianceData() {
    const search = (document.getElementById('compliance-search')?.value || '').toLowerCase().trim();
    const statusFilter = document.getElementById('compliance-status-filter')?.value || '';
    const locationFilter = document.getElementById('compliance-location-filter')?.value || '';

    const filterList = (items) => items.filter(item => {
        if (statusFilter === 'blocked' && item.can_transfer) return false;
        if (statusFilter === 'allowed' && !item.can_transfer) return false;
        if (locationFilter && item.location_id !== locationFilter) return false;
        if (search) {
            const haystack = [
                item.serial_number, item.id_number, item.item_sku, item.item_name, item.location_name
            ].filter(Boolean).join(' ').toLowerCase();
            if (!haystack.includes(search)) return false;
        }
        return true;
    });

    filteredComplianceAll = filterList(allComplianceItems);
    filteredComplianceCalibration = filterList(allComplianceCalibration);
    filteredComplianceMaintenance = filterList(allComplianceMaintenance);
    compliancePagination.all.currentPage = 1;
    compliancePagination.calibration.currentPage = 1;
    compliancePagination.maintenance.currentPage = 1;
    renderCompliancePage('all');
    renderCompliancePage('calibration');
    renderCompliancePage('maintenance');
}

function complianceStatFilter(card) {
    const filter = card.dataset.filter;
    const wasActive = card.classList.contains('active-filter');
    document.querySelectorAll('.compliance-stat-card').forEach(c => c.classList.remove('active-filter'));
    const statusEl = document.getElementById('compliance-status-filter');

    if (wasActive) {
        if (statusEl) statusEl.value = '';
        filterComplianceData();
        return;
    }

    card.classList.add('active-filter');
    if (filter === 'blocked') {
        if (statusEl) statusEl.value = 'blocked';
        filterComplianceData();
    } else if (filter === 'clear') {
        if (statusEl) statusEl.value = 'allowed';
        filterComplianceData();
    } else if (filter === 'cal-issues') {
        if (statusEl) statusEl.value = '';
        setComplianceTab('calibration');
    } else if (filter === 'maint-issues') {
        if (statusEl) statusEl.value = '';
        setComplianceTab('maintenance');
    } else {
        if (statusEl) statusEl.value = '';
        setComplianceTab('all');
    }
}

async function refreshTransfersSection() {
    if (currentTransferView === 'action') {
        await loadActionTransfers();
    } else {
        await loadTransfers();
    }
}

// ===== Transfer View State =====
let currentTransferView = 'requests'; // 'requests' | 'action'
let allActionTransfers = []; // transfers assigned to current user

function setTransferView(view) {
    currentTransferView = view;

    const reqBtn   = document.getElementById('transfer-view-btn-requests');
    const actBtn   = document.getElementById('transfer-view-btn-action');
    const reqPanel = document.getElementById('transfer-view-requests');
    const actPanel = document.getElementById('transfer-view-action');
    const newBtn   = document.getElementById('transfer-new-btn');
    const expBtn   = document.getElementById('transfer-export-btn');

    if (view === 'action') {
        actBtn?.classList.add('active');
        reqBtn?.classList.remove('active');
        actPanel?.classList.remove('hidden');
        reqPanel?.classList.add('hidden');
        if (newBtn) newBtn.style.display = 'none';
        if (expBtn) expBtn.style.display = 'none';
        loadActionTransfers();
    } else {
        reqBtn?.classList.add('active');
        actBtn?.classList.remove('active');
        reqPanel?.classList.remove('hidden');
        actPanel?.classList.add('hidden');
        if (newBtn) newBtn.style.display = '';
        if (expBtn) expBtn.style.display = '';
        loadTransfers();
    }
}

function formatDateValue(value) {
    if (!value) return '-';
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? '-' : parsed.toLocaleDateString();
}

function daysBetween(d1, d2) {
    return Math.round((d1 - d2) / (24 * 60 * 60 * 1000));
}

async function loadComplianceData() {
    const allBody = document.getElementById('compliance-all-body');
    const calibrationBody = document.getElementById('compliance-calibration-body');
    const maintenanceBody = document.getElementById('compliance-maintenance-body');

    if (!allBody && !calibrationBody && !maintenanceBody) return;

    try {
        const overview = await TransfersAPI.getEquipmentOverview();
        const allItems = Array.isArray(overview.items) ? overview.items : [];
        const calibrationItems = Array.isArray(overview.calibration_issues) ? overview.calibration_issues : [];
        const maintenanceItems = Array.isArray(overview.maintenance_issues) ? overview.maintenance_issues : [];

        allComplianceItems = allItems;
        allComplianceCalibration = calibrationItems;
        allComplianceMaintenance = maintenanceItems;

        // Update stats
        updateComplianceStats(allItems, calibrationItems, maintenanceItems);

        // Populate location filter
        populateComplianceLocationFilter(allItems);

        // Update tab counts
        const allCount = document.getElementById('compliance-all-count');
        const calCount = document.getElementById('compliance-cal-count');
        const maintCount = document.getElementById('compliance-maint-count');
        if (allCount) allCount.textContent = allItems.length;
        if (calCount) calCount.textContent = calibrationItems.length;
        if (maintCount) maintCount.textContent = maintenanceItems.length;

        // Reset filters
        const searchEl = document.getElementById('compliance-search');
        if (searchEl) searchEl.value = '';
        const statusEl = document.getElementById('compliance-status-filter');
        if (statusEl) statusEl.value = '';

        filteredComplianceAll = allItems;
        filteredComplianceCalibration = calibrationItems;
        filteredComplianceMaintenance = maintenanceItems;
        compliancePagination.all.currentPage = 1;
        compliancePagination.calibration.currentPage = 1;
        compliancePagination.maintenance.currentPage = 1;
        renderCompliancePage('all');
        renderCompliancePage('calibration');
        renderCompliancePage('maintenance');
    } catch (error) {
        console.error('Equipment compliance load error:', error);
        const errorRow = (cols) => `<tr><td colspan="${cols}" class="text-center text-muted">Error loading compliance data</td></tr>`;
        if (allBody) allBody.innerHTML = errorRow(8);
        if (calibrationBody) calibrationBody.innerHTML = errorRow(10);
        if (maintenanceBody) maintenanceBody.innerHTML = errorRow(10);
    }
}

function populateComplianceLocationFilter(items) {
    const sel = document.getElementById('compliance-location-filter');
    if (!sel) return;
    const locations = new Map();
    items.forEach(i => { if (i.location_id && i.location_name) locations.set(i.location_id, i.location_name); });
    const prev = sel.value;
    sel.innerHTML = '<option value="">All Locations</option>' +
        [...locations.entries()].sort((a, b) => a[1].localeCompare(b[1]))
            .map(([id, name]) => `<option value="${id}">${name}</option>`).join('');
    sel.value = prev;
}

function updateComplianceStats(allItems, calItems, maintItems) {
    const total = allItems.length;
    const blocked = allItems.filter(i => !i.can_transfer).length;
    const clear = allItems.filter(i => i.can_transfer).length;

    const el = (id, val) => { const e = document.getElementById(id); if (e) e.textContent = val; };
    el('cstat-total', total);
    el('cstat-blocked', blocked);
    el('cstat-cal', calItems.length);
    el('cstat-maint', maintItems.length);
    el('cstat-clear', clear);
}

// --- All Equipment Table (overview with combined status) ---
function renderAllEquipmentTable(items) {
    const tbody = document.getElementById('compliance-all-body');
    if (!tbody) return;

    if (!items || items.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8">
            <div class="compliance-empty-state">
                <i class="fas fa-clipboard-check"></i>
                <div class="empty-title">No equipment found</div>
                <div class="empty-desc">No serialized equipment has been registered yet</div>
            </div>
        </td></tr>`;
        return;
    }

    const now = new Date();

    tbody.innerHTML = items.map(item => {
        const rowClass = item.can_transfer ? '' : 'row-blocked';

        // Calibration summary
        let calHtml = '<span class="compliance-mini-badge badge-na">N/A</span>';
        if (item.requires_calibration === false) {
            calHtml = '<span class="compliance-mini-badge badge-na">Not Required</span>';
        } else if (item.calibration_due_at) {
            const due = new Date(item.calibration_due_at);
            const daysLeft = daysBetween(due, now);
            // Check result first — a fail overrides "valid" date display
            const resultRaw = (item.calibration_result || '').toLowerCase();
            const resultFailed = resultRaw && resultRaw !== 'pass' && resultRaw !== 'conditional';
            if (resultFailed) {
                calHtml = `<span class="compliance-mini-badge badge-overdue"><i class="fas fa-times-circle"></i> Failed</span>`;
            } else if (daysLeft < 0) {
                calHtml = `<span class="compliance-mini-badge badge-overdue"><i class="fas fa-exclamation-circle"></i> Expired (${Math.abs(daysLeft)}d ago)</span>`;
            } else if (daysLeft <= 7) {
                calHtml = `<span class="compliance-mini-badge badge-urgent"><i class="fas fa-exclamation-triangle"></i> Due in ${daysLeft}d</span>`;
            } else if (daysLeft <= 30) {
                calHtml = `<span class="compliance-mini-badge badge-due-soon"><i class="fas fa-exclamation-triangle"></i> Due in ${daysLeft}d</span>`;
            } else {
                calHtml = `<span class="compliance-mini-badge badge-ok"><i class="fas fa-check-circle"></i> Valid (${daysLeft}d)</span>`;
            }
        } else if (item.requires_calibration) {
            calHtml = '<span class="compliance-mini-badge badge-overdue"><i class="fas fa-exclamation-circle"></i> No Record</span>';
        }

        // Equipment has no periodic maintenance cycle; show only active vs under-maintenance.
        let maintHtml;
        if (item.maintenance_completed_this_period) {
            maintHtml = `<span class="compliance-mini-badge badge-ok"><i class="fas fa-check-circle"></i> Active</span>`;
        } else {
            maintHtml = `<span class="compliance-mini-badge badge-overdue"><i class="fas fa-wrench"></i> Under Maintenance</span>`;
        }

        // Status badge
        const statusHtml = item.can_transfer
            ? '<span class="compliance-status-badge status-clear"><i class="fas fa-check-circle"></i> Clear</span>'
            : '<span class="compliance-status-badge status-blocked"><i class="fas fa-ban"></i> Blocked</span>';

        // Issues
        const issuesHtml = renderComplianceReasons(item.blocked_reasons);

        const perms = getUserPermissions();
        const actionsHtml = perms.canManage ? `
            <div class="compliance-actions">
                ${item.requires_calibration !== false ? `<button class="btn btn-xs btn-outline-primary" onclick="showLogCalibrationModal('${item.asset_id}', '${escapeHtml(item.serial_number)}')" title="Log Calibration"><i class="fas fa-ruler-combined"></i> Calibration</button>` : ''}
                <button class="btn btn-xs btn-outline-success" onclick="showLogMaintenanceModal('${item.asset_id}', '${escapeHtml(item.serial_number)}')" title="Log repair/service history"><i class="fas fa-wrench"></i> Service History</button>
            </div>` : '';

        return `<tr class="${rowClass}">
            <td><strong>${item.serial_number || '-'}</strong></td>
            <td>${item.item_sku ? '<span class="text-muted">' + item.item_sku + '</span> — ' : ''}${item.item_name || '-'}</td>
            <td>${item.location_name || '-'}</td>
            <td>${calHtml}</td>
            <td>${maintHtml}</td>
            <td>${statusHtml}</td>
            <td class="blocked-reasons">${issuesHtml}</td>
            <td>${actionsHtml}</td>
        </tr>`;
    }).join('');
}

function renderCalibrationTable(items) {
    const tbody = document.getElementById('compliance-calibration-body');
    if (!tbody) return;

    if (!items || items.length === 0) {
        tbody.innerHTML = `<tr><td colspan="9">
            <div class="compliance-empty-state">
                <i class="fas fa-check-circle"></i>
                <div class="empty-title">No calibration issues</div>
                <div class="empty-desc">All equipment calibrations are up to date</div>
            </div>
        </td></tr>`;
        return;
    }

    const now = new Date();

    tbody.innerHTML = items.map(item => {
        const rowClass = item.can_transfer ? '' : 'row-blocked';

        let dueCellClass = 'cal-due-cell';
        let dueHtml = '-';
        let daysHtml = '-';
        let severityBadge = '';

        if (item.calibration_due_at) {
            const due = new Date(item.calibration_due_at);
            const daysLeft = daysBetween(due, now);
            const dateStr = formatDateValue(item.calibration_due_at);
            if (daysLeft < 0) {
                dueCellClass += ' overdue';
                dueHtml = `<i class="fas fa-exclamation-circle"></i> ${dateStr}`;
                daysHtml = `<span class="days-badge days-overdue">${Math.abs(daysLeft)} days overdue</span>`;
                severityBadge = '<span class="compliance-mini-badge badge-overdue">Expired</span>';
            } else if (daysLeft <= 7) {
                dueCellClass += ' due-soon due-critical';
                dueHtml = `<i class="fas fa-exclamation-triangle"></i> ${dateStr}`;
                daysHtml = `<span class="days-badge days-urgent">${daysLeft}d left</span>`;
                severityBadge = '<span class="compliance-mini-badge badge-urgent">Critical</span>';
            } else if (daysLeft <= 30) {
                dueCellClass += ' due-soon';
                dueHtml = `<i class="fas fa-exclamation-triangle"></i> ${dateStr}`;
                daysHtml = `<span class="days-badge days-warning">${daysLeft}d left</span>`;
                severityBadge = '<span class="compliance-mini-badge badge-due-soon">Due Soon</span>';
            } else {
                dueCellClass += ' valid';
                dueHtml = dateStr;
                daysHtml = `<span class="days-badge days-ok">${daysLeft}d</span>`;
                severityBadge = '<span class="compliance-mini-badge badge-ok">Valid</span>';
            }
        } else {
            severityBadge = '<span class="compliance-mini-badge badge-overdue">No Record</span>';
        }

        // Result badge
        const resultKey = (item.calibration_result || '').toLowerCase();
        let resultHtml = '<span class="text-muted">—</span>';
        if (resultKey === 'pass') {
            resultHtml = '<span class="result-badge result-pass"><i class="fas fa-check"></i> Pass</span>';
        } else if (resultKey === 'fail') {
            resultHtml = '<span class="result-badge result-fail"><i class="fas fa-times"></i> Fail</span>';
        } else if (resultKey === 'conditional' || resultKey === 'limited') {
            resultHtml = '<span class="result-badge result-limited"><i class="fas fa-exclamation"></i> ' + item.calibration_result + '</span>';
        } else if (item.calibration_result) {
            resultHtml = escapeHtml(item.calibration_result);
        }

        const issuesHtml = renderComplianceReasons(item.blocked_reasons);

        const perms = getUserPermissions();
        const actionsHtml = perms.canManage ? `
            <div class="compliance-actions">
                <button class="btn btn-xs btn-outline-primary" onclick="showLogCalibrationModal('${item.asset_id}', '${escapeHtml(item.serial_number)}')" title="Log Calibration">
                    <i class="fas fa-ruler-combined"></i> Log Calibration
                </button>
            </div>` : '';

        return `<tr class="${rowClass}">
            <td><strong>${item.serial_number || '-'}</strong></td>
            <td>${item.id_number || '-'}</td>
            <td>${item.item_sku ? '<span class="text-muted">' + item.item_sku + '</span> — ' : ''}${item.item_name || '-'}</td>
            <td>${item.location_name || '-'}</td>
            <td class="${dueCellClass}">${dueHtml}</td>
            <td>${daysHtml}</td>
            <td>${resultHtml}</td>
            <td>${severityBadge}</td>
            <td class="blocked-reasons">${issuesHtml}</td>
            <td>${actionsHtml}</td>
        </tr>`;
    }).join('');
}

// --- Service History Table ---
function renderMaintenanceTable(items) {
    const tbody = document.getElementById('compliance-maintenance-body');
    if (!tbody) return;

    if (!items || items.length === 0) {
        tbody.innerHTML = `<tr><td colspan="9">
            <div class="compliance-empty-state">
                <i class="fas fa-wrench"></i>
                <div class="empty-title">No maintenance issues</div>
                <div class="empty-desc">All equipment maintenance is up to date for their scheduled interval</div>
            </div>
        </td></tr>`;
        return;
    }

    const now = new Date();

    tbody.innerHTML = items.map(item => {
        const rowClass = item.can_transfer ? '' : 'row-blocked';

        // Frequency badge — interval_days always set from backend (default 30)
        const d = item.maintenance_interval_days;
        let freqLabel;
        if (!d) freqLabel = 'Monthly';
        else if (d <= 1) freqLabel = 'Daily';
        else if (d <= 7) freqLabel = 'Weekly';
        else if (d <= 14) freqLabel = 'Bi-Weekly';
        else if (d <= 31) freqLabel = 'Monthly';
        else if (d <= 92) freqLabel = 'Quarterly';
        else if (d <= 183) freqLabel = 'Semi-Annual';
        else if (d <= 366) freqLabel = 'Annual';
        else freqLabel = d + ' days';
        const freqHtml = `<span class="freq-badge"><i class="fas fa-redo"></i> ${freqLabel}</span>`;

        // Next due date
        let nextDueHtml = '-';
        if (item.maintenance_next_due_at) {
            const nextDue = new Date(item.maintenance_next_due_at);
            const daysUntil = daysBetween(nextDue, now);
            const dateStr = formatDateValue(item.maintenance_next_due_at);
            if (daysUntil > 0) {
                nextDueHtml = `<span class="days-badge days-overdue">${daysUntil}d overdue</span><br><small class="text-muted">${dateStr}</small>`;
            } else if (daysUntil >= -7) {
                nextDueHtml = `<span class="days-badge days-urgent">Due in ${Math.abs(daysUntil)}d</span><br><small class="text-muted">${dateStr}</small>`;
            } else {
                nextDueHtml = `<span class="days-badge days-ok">Due ${dateStr}</span>`;
            }
        } else {
            nextDueHtml = `<span class="days-badge days-overdue">Never done</span>`;
        }

        // Days since last maintenance
        let daysSinceHtml = '<span class="text-muted">—</span>';
        if (item.maintenance_last_completed_at) {
            const last = new Date(item.maintenance_last_completed_at);
            const daysSince = daysBetween(now, last);
            if (daysSince > (d || 30)) {
                daysSinceHtml = `<span class="days-badge days-overdue">${daysSince}d ago</span>`;
            } else {
                daysSinceHtml = `<span class="days-badge days-ok">${daysSince}d ago</span>`;
            }
        } else {
            daysSinceHtml = `<span class="days-badge days-overdue">Never</span>`;
        }

        // Period status
        const periodHtml = item.maintenance_completed_this_period
            ? `<span class="compliance-mini-badge badge-ok"><i class="fas fa-check-circle"></i> Done</span>`
            : `<span class="compliance-mini-badge badge-overdue"><i class="fas fa-clock"></i> Pending</span>`;

        const issuesHtml = renderComplianceReasons(item.blocked_reasons);

        const perms = getUserPermissions();
        const actionsHtml = perms.canManage ? `
            <div class="compliance-actions">
                <button class="btn btn-xs btn-outline-success" onclick="showLogMaintenanceModal('${item.asset_id}', '${escapeHtml(item.serial_number)}')" title="Log repair/service history">
                    <i class="fas fa-wrench"></i> Service History
                </button>
            </div>` : '';

        return `<tr class="${rowClass}">
            <td><strong>${item.serial_number || '-'}</strong></td>
            <td>${item.item_sku ? '<span class="text-muted">' + item.item_sku + '</span> — ' : ''}${item.item_name || '-'}</td>
            <td>${freqHtml}</td>
            <td>${item.location_name || '-'}</td>
            <td>${formatDateValue(item.maintenance_last_completed_at)}</td>
            <td>${daysSinceHtml}</td>
            <td>${nextDueHtml}</td>
            <td>${periodHtml}</td>
            <td class="blocked-reasons">${issuesHtml}</td>
            <td>${actionsHtml}</td>
        </tr>`;
    }).join('');
}

// ── Compliance: Log Calibration ─────────────────────────────────────────────

function showLogCalibrationModal(assetId, serialNumber) {
    const today = localDateInputValue();
    // Default next due = 1 year from today
    const nextYear = new Date();
    nextYear.setFullYear(nextYear.getFullYear() + 1);
    const nextYearStr = localDateInputValue(nextYear);

    openModal(`Log Calibration — ${serialNumber}`, `
        <form id="log-calibration-form">
            <div class="form-row">
                <div class="form-group">
                    <label>Certificate Number *</label>
                    <input type="text" name="certificate_number" required placeholder="e.g., CAL-2026-001">
                </div>
                <div class="form-group">
                    <label>Result *</label>
                    <select name="result" required>
                        <option value="pass">Pass</option>
                        <option value="fail">Fail</option>
                        <option value="limited">Limited</option>
                    </select>
                </div>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label>Performed On *</label>
                    <input type="date" name="performed_at" required value="${today}" max="${today}">
                </div>
                <div class="form-group">
                    <label>Next Due Date *</label>
                    <input type="date" name="due_at" required value="${nextYearStr}">
                </div>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label>Performed By *</label>
                    <input type="text" name="performed_by" required placeholder="Technician / Lab name">
                </div>
                <div class="form-group">
                    <label>Supplier Name</label>
                    <input type="text" name="calibration_lab" placeholder="Supplier / calibration lab">
                </div>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label>Sent Date</label>
                    <input type="date" name="sent_date" max="${today}">
                </div>
                <div class="form-group">
                    <label>Receive Date</label>
                    <input type="date" name="receive_date" max="${today}">
                </div>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label>As Found Condition</label>
                    <input type="text" name="as_found_condition" placeholder="e.g., Within tolerance">
                </div>
                <div class="form-group">
                    <label>As Left Condition</label>
                    <input type="text" name="as_left_condition" placeholder="e.g., Adjusted">
                </div>
            </div>
            <div class="form-group">
                <label>Procedure / Standard</label>
                <input type="text" name="calibration_procedure" placeholder="e.g., ISO 9001:2015">
            </div>
            <div class="form-group">
                <label>Notes</label>
                <textarea name="notes" rows="2" placeholder="Optional notes"></textarea>
            </div>
            <div class="modal-actions">
                <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                <button type="submit" class="btn btn-primary"><i class="fas fa-save"></i> Save Calibration</button>
            </div>
        </form>
    `, 'modal-lg');

    document.getElementById('log-calibration-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        await withSubmitLock(e.target, async () => {
            const fd = new FormData(e.target);
            const performedAt = fd.get('performed_at');
            const dueAt = fd.get('due_at');
            const sentDate = fd.get('sent_date');
            const receiveDate = fd.get('receive_date');
            if (dueAt <= performedAt) {
                showToast('Next due date must be after the calibration date', 'error');
                return;
            }
            if (sentDate && receiveDate && receiveDate < sentDate) {
                showToast('Receive date cannot be before the sent date', 'error');
                return;
            }
            const extraNotes = [
                sentDate ? `Sent Date: ${sentDate}` : '',
                receiveDate ? `Receive Date: ${receiveDate}` : '',
                fd.get('notes') || ''
            ].filter(Boolean).join('\n');
            const payload = {
                certificate_number: fd.get('certificate_number').trim(),
                result: fd.get('result'),
                performed_at: performedAt,
                due_at: dueAt,
                performed_by: fd.get('performed_by').trim(),
                calibration_lab: fd.get('calibration_lab').trim() || null,
                as_found_condition: fd.get('as_found_condition').trim() || null,
                as_left_condition: fd.get('as_left_condition').trim() || null,
                calibration_procedure: fd.get('calibration_procedure').trim() || null,
                notes: extraNotes || null,
            };
            try {
                await CalibrationAPI.create(assetId, payload);
                closeModal();
                showToast(`Calibration recorded for ${serialNumber}`, 'success');
                await loadComplianceData();
            } catch (error) {
                showToast('Failed to save calibration: ' + error.message, 'error');
            }
        });
    });
}

async function showCalibrationSupplierTransactionModal() {
    try {
        const assetData = await AssetsAPI.getAllPages({ sort_by: 'created_at', sort_order: 'desc' });
        const assets = Array.isArray(assetData) ? assetData : (assetData.items || []);
        const instruments = assets.filter(asset => {
            const typeKey = canonicalInventoryTypeKey(asset.item_asset_type || asset.category_type_key || asset.item_category_name || asset.item_name);
            return typeKey === 'instrument' || asset.item_requires_calibration === true;
        });

        if (!instruments.length) {
            showToast('No instruments available for supplier calibration transaction.', 'info');
            return;
        }

        const today = localDateInputValue();
        const options = instruments.map(asset => {
            const label = [
                asset.item_name || 'Instrument',
                asset.serial_number ? `Serial: ${asset.serial_number}` : '',
                asset.item_id_number ? `ID: ${asset.item_id_number}` : '',
            ].filter(Boolean).join(' - ');
            return `<option value="${asset.id}">${escapeHtml(label)}</option>`;
        }).join('');

        openModal('Calibration Supplier Transaction', `
            <form id="calibration-supplier-transaction-form">
                <div class="form-group">
                    <label>Instrument Name *</label>
                    <select name="asset_id" required>${options}</select>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Date *</label>
                        <input type="date" name="sent_at" required value="${today}" max="${today}">
                    </div>
                    <div class="form-group">
                        <label>Receive Date from Supplier</label>
                        <input type="date" name="received_at" max="${today}">
                    </div>
                </div>
                <div class="form-group">
                    <label>Supplier Name *</label>
                    <input type="text" name="supplier_name" required placeholder="Supplier / calibration lab name">
                </div>
                <div class="form-group">
                    <label>Notes</label>
                    <textarea name="notes" rows="2" placeholder="Optional transaction notes"></textarea>
                </div>
                <div class="modal-actions">
                    <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary"><i class="fas fa-save"></i> Save Transaction</button>
                </div>
            </form>
        `);

        document.getElementById('calibration-supplier-transaction-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            await withSubmitLock(e.target, async () => {
                const formData = new FormData(e.target);
                const sentAt = formData.get('sent_at');
                const receivedAt = formData.get('received_at') || null;
                if (receivedAt && receivedAt < sentAt) {
                    showToast('Receive date cannot be before the sent date', 'error');
                    return;
                }
                const payload = {
                    asset_id: formData.get('asset_id'),
                    sent_at: sentAt,
                    supplier_name: formData.get('supplier_name').trim(),
                    received_at: receivedAt,
                    notes: formData.get('notes').trim() || null,
                };
                try {
                    await CalibrationAPI.createSupplierTransaction(payload);
                    closeModal();
                    showToast(
                        receivedAt
                            ? 'Instrument receipt from calibration supplier recorded'
                            : 'Instrument marked as under calibration',
                        'success'
                    );
                    if (currentPage === 'compliance') await loadComplianceData();
                    if (currentPage === 'items') await loadItems();
                } catch (error) {
                    showToast('Failed to save transaction: ' + error.message, 'error');
                }
            });
        });
    } catch (error) {
        showToast('Unable to load instruments: ' + error.message, 'error');
    }
}

// Compliance: log repair/service history

function showLogMaintenanceModal(assetId, serialNumber) {
    const today = localDateInputValue();
    const todayDT = localDateTimeInputValue(); // datetime-local format

    openModal(`Service History - ${serialNumber}`, `
        <form id="log-maintenance-form">
            <div class="form-row">
                <div class="form-group">
                    <label>Service Type *</label>
                    <select name="maintenance_type" required>
                        <option value="preventive">Preventive</option>
                        <option value="corrective">Corrective</option>
                        <option value="inspection">Inspection</option>
                        <option value="cleaning">Cleaning</option>
                        <option value="other">Other</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>Work Order Number</label>
                    <input type="text" name="work_order_number" placeholder="e.g., WO-2026-042">
                </div>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label>Scheduled Date/Time *</label>
                    <input type="datetime-local" name="scheduled_at" required value="${todayDT}">
                </div>
                <div class="form-group">
                    <label>Completed Date/Time</label>
                    <input type="datetime-local" name="completed_at" value="${todayDT}">
                </div>
            </div>
            <div class="form-group">
                <label>Description / Work Required *</label>
                <textarea name="description" rows="2" required placeholder="Describe service or repair performed..."></textarea>
            </div>
            <div class="form-group">
                <label>Work Performed</label>
                <textarea name="work_performed" rows="2" placeholder="Detail of actual work done..."></textarea>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label>Labor Hours</label>
                    <input type="number" name="labor_hours" min="0" step="0.5" placeholder="e.g., 2.5">
                </div>
                <div class="form-group">
                    <label>Labor Cost</label>
                    <input type="number" name="labor_cost" min="0" step="0.01" placeholder="e.g., 500.00">
                </div>
                <div class="form-group">
                    <label>Parts Cost</label>
                    <input type="number" name="parts_cost" min="0" step="0.01" placeholder="e.g., 200.00">
                </div>
            </div>
            <div class="form-group">
                <label>Result / Outcome</label>
                <input type="text" name="result" placeholder="e.g., Passed inspection, Replaced component">
            </div>
            <div class="form-group">
                <label>Notes</label>
                <textarea name="notes" rows="2" placeholder="Optional notes"></textarea>
            </div>
            <div class="modal-actions">
                <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                <button type="submit" class="btn btn-primary"><i class="fas fa-save"></i> Save Service Record</button>
            </div>
        </form>
    `, 'modal-lg');

    document.getElementById('log-maintenance-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const fd = new FormData(e.target);
        const payload = {
            maintenance_type: fd.get('maintenance_type'),
            work_order_number: fd.get('work_order_number') || null,
            scheduled_at: fd.get('scheduled_at'),
            completed_at: fd.get('completed_at') || null,
            description: fd.get('description'),
            work_performed: fd.get('work_performed') || null,
            labor_hours: fd.get('labor_hours') ? parseFloat(fd.get('labor_hours')) : null,
            labor_cost: fd.get('labor_cost') ? parseFloat(fd.get('labor_cost')) : null,
            parts_cost: fd.get('parts_cost') ? parseFloat(fd.get('parts_cost')) : null,
            result: fd.get('result') || null,
            notes: fd.get('notes') || null,
        };
        try {
            await MaintenanceAPI.create(assetId, payload);
            closeModal();
            showToast(`Service history recorded for ${serialNumber}`, 'success');
            await loadComplianceData();
        } catch (error) {
            showToast('Failed to save service history: ' + error.message, 'error');
        }
    });
}

function renderComplianceReasons(reasons) {
    if (!reasons || reasons.length === 0) {
        return '<span class="text-success" style="font-size:12px;">—</span>';
    }
    return reasons.map(r => `<span class="reason-tag"><i class="fas fa-exclamation-triangle"></i> ${r}</span>`).join(' ');
}

// Dashboard
async function loadDashboard() {
    try {
        // Welcome banner
        const user = JSON.parse(localStorage.getItem('user') || '{}');
        const greetEl = document.getElementById('welcome-greeting');
        const dateEl = document.getElementById('welcome-date');
        if (greetEl) {
            const hour = new Date().getHours();
            const period = hour < 12 ? 'Good Morning' : hour < 17 ? 'Good Afternoon' : 'Good Evening';
            greetEl.textContent = `${period}, ${user.name || 'User'}`;
        }
        if (dateEl) {
            dateEl.textContent = new Date().toLocaleDateString('en-IN', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });
        }

        // Load dashboard summary + low stock + calibration alerts + recent activity in parallel
        const [dashboardSummary, lowStockItems, calAlerts, recentActivity] = await Promise.all([
            DashboardAPI.getStats().catch(() => null),
            DashboardAPI.getLowStockItems(50).catch(() => []),
            DashboardAPI.getCalibrationAlerts(15).catch(() => []),
            DashboardAPI.getRecentTransactions(15).catch(() => [])
        ]);
        
        // Animate stat cards
        if (dashboardSummary) {
            animateCount('total-assets', dashboardSummary.total_assets ?? 0);
            animateCount('total-locations', dashboardSummary.total_locations ?? 0);
            animateCount('low-stock-count', dashboardSummary.low_stock_count ?? 0);
            // Use the actual alerts list count so the card always matches what is shown below
            const calTotal = Array.isArray(calAlerts) ? calAlerts.length
                : ((dashboardSummary.calibration_due_soon ?? 0) + (dashboardSummary.calibration_expired ?? 0));
            animateCount('calibration-count', calTotal);
            animateCount('total-jobs', dashboardSummary.total_jobs ?? 0);
        }
        
        // Populate location filter
        try {
            const locationsData = await LocationsAPI.getAll({ is_active: true }).catch(() => []);
            const locs = activeRecords(Array.isArray(locationsData) ? locationsData : (locationsData.items || []));
            const locationFilter = document.getElementById('dashboard-location-filter');
            if (locationFilter) {
                const perms = getUserPermissions();
                const allLocationsLabel = perms.canViewAllLocations
                    ? 'All Locations'
                    : 'All Assigned Locations';
                locationFilter.innerHTML = `<option value="">${allLocationsLabel}</option>` +
                    locs.map(loc => `<option value="${loc.id}">${loc.name}</option>`).join('');
            }
        } catch (e) {
            console.log('Failed to load location filter:', e.message);
        }
        
        // Render low stock alerts grouped by category
        const alertsDiv = document.getElementById('low-stock-alerts');
        if (alertsDiv) {
            if (Array.isArray(lowStockItems) && lowStockItems.length > 0) {
                // Group by category
                const byCategory = {};
                lowStockItems.forEach(item => {
                    const cat = item.category_name || 'Uncategorized';
                    if (!byCategory[cat]) byCategory[cat] = [];
                    byCategory[cat].push(item);
                });
                
                const categoryColors = ['#6366f1', '#f59e0b', '#10b981', '#ef4444', '#3b82f6', '#8b5cf6', '#ec4899'];
                let colorIdx = 0;
                
                alertsDiv.innerHTML = Object.entries(byCategory).map(([category, items]) => {
                    const color = categoryColors[colorIdx++ % categoryColors.length];
                    return `
                    <div class="low-stock-category-group" style="margin-bottom:12px;">
                        <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
                            <span style="width:10px;height:10px;border-radius:50%;background:${color};display:inline-block;"></span>
                            <strong style="font-size:13px;color:var(--text-primary);">${category}</strong>
                            <span class="badge-sm badge badge-secondary" style="font-size:11px;">${items.length}</span>
                        </div>
                        <div style="display:flex;flex-direction:column;gap:6px;padding-left:18px;">
                            ${items.slice(0, 4).map(item => {
                                const pct = item.reorder_point > 0 ? Math.round((item.current_quantity / item.reorder_point) * 100) : 0;
                                return `
                                <div class="alert-item">
                                    <i class="fas fa-exclamation-triangle"></i>
                                    <div class="alert-info">
                                        <strong>${item.name || 'Unknown Item'}</strong>
                                        <span>${item.current_quantity} / ${item.reorder_point || '?'} at ${item.location_name || 'Unknown'}</span>
                                    </div>
                                    <span class="badge-sm badge ${pct <= 25 ? 'badge-danger' : 'badge-warning'}">${pct}%</span>
                                </div>`;
                            }).join('')}
                            ${items.length > 4 ? `<span style="font-size:12px;color:var(--text-muted);">+${items.length - 4} more items</span>` : ''}
                        </div>
                    </div>`;
                }).join('');
            } else {
                alertsDiv.innerHTML = `<div class="empty-state"><i class="fas fa-check-circle"></i><p>All stock levels are healthy</p></div>`;
            }
        }

        // Render calibration alerts panel
        const calDiv = document.getElementById('calibration-alerts');
        if (calDiv) {
            const alerts = Array.isArray(calAlerts) ? calAlerts : [];
            if (alerts.length > 0) {
                calDiv.innerHTML = `<div style="display:flex;flex-direction:column;gap:8px;">` + alerts.slice(0, 8).map(a => {
                    const isExpired = a.status === 'expired';
                    return `
                    <div class="cal-alert-item">
                        <i class="fas fa-${isExpired ? 'times-circle text-danger' : 'clock text-warning'}"></i>
                        <div class="alert-info">
                            <strong>${a.asset_name || a.serial_number || '-'} (${a.serial_number || '-'})</strong>
                            <span>${a.location_name || '-'} &middot; Due: ${a.due_date || '-'}</span>
                        </div>
                        <span class="badge-sm badge ${isExpired ? 'badge-danger' : 'badge-warning'}">${isExpired ? 'Expired' : a.days_until_due + 'd'}</span>
                    </div>`;
                }).join('') + `</div>`;
            } else {
                calDiv.innerHTML = `<div class="empty-state"><i class="fas fa-check-circle"></i><p>All calibrations are up to date</p></div>`;
            }
        }
        
        // Render recent activity feed
        const activityDiv = document.getElementById('recent-activity-feed');
        if (activityDiv) {
            const activities = Array.isArray(recentActivity) ? recentActivity : [];
            if (activities.length > 0) {
                const actionIcon = (action) => {
                    const a = String(action).toLowerCase();
                    if (a.includes('receipt') || a.includes('return')) return 'fa-arrow-down text-success';
                    if (a.includes('issue') || a.includes('scrap')) return 'fa-arrow-up text-danger';
                    if (a.includes('adjustment') || a.includes('cycle')) return 'fa-sliders-h text-warning';
                    if (a.includes('transfer')) return 'fa-exchange-alt text-info';
                    return 'fa-circle text-muted';
                };
                const formatAction = (a) => String(a || 'unknown').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
                
                activityDiv.innerHTML = `<div style="display:flex;flex-direction:column;gap:8px;">` + activities.slice(0, 10).map(act => `
                    <div class="alert-item" style="padding:8px 10px;">
                        <i class="fas ${actionIcon(act.action)}" style="font-size:14px;width:20px;text-align:center;"></i>
                        <div class="alert-info" style="flex:1;">
                            <strong>${act.performed_by || 'System'}</strong>
                            <span>${formatAction(act.action)} — ${act.item_name || ''} ${act.quantity ? '(Qty: ' + Math.abs(act.quantity) + ')' : ''} at ${act.location_name || '-'}</span>
                        </div>
                        <span style="font-size:11px;color:var(--text-muted);white-space:nowrap;">${act.created_at ? new Date(act.created_at).toLocaleDateString('en-IN', {day:'2-digit',month:'short'}) : '-'}</span>
                    </div>
                `).join('') + `</div>`;
            } else {
                activityDiv.innerHTML = `<div class="empty-state"><i class="fas fa-check-circle"></i><p>No recent activity</p></div>`;
            }
        }
        
        // Load location-wise stock summary
        try {
            await loadLocationStockSummary();
        } catch (e) {
            console.log('Location stock summary error:', e.message);
        }

        // Update notification dot in header
        const lowCount = (Array.isArray(lowStockItems) ? lowStockItems.length : 0);
        const calCount = (Array.isArray(calAlerts) ? calAlerts.length : 0);
        const notifDot = document.getElementById('notification-dot');
        if (notifDot) {
            notifDot.style.display = (lowCount + calCount) > 0 ? '' : 'none';
        }

        // Load Charts
        if (typeof loadDashboardCharts === 'function') {
            loadDashboardCharts().catch(function(e) { console.log('Charts error:', e.message); });
        }
        
    } catch (error) {
        console.error('Dashboard load error:', error, error.stack);
        showToast('Error loading dashboard: ' + error.message, 'error');
    }
}

// Animate number count-up
function animateCount(elementId, target) {
    const el = document.getElementById(elementId);
    if (!el) return;
    const duration = 600;
    const start = 0;
    const startTime = performance.now();
    function step(currentTime) {
        const elapsed = currentTime - startTime;
        const progress = Math.min(elapsed / duration, 1);
        const ease = 1 - Math.pow(1 - progress, 3);
        el.textContent = Math.round(start + (target - start) * ease);
        if (progress < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
}



// Logs
async function loadLogs() {
    const tbody = document.getElementById('logs-table-body');
    if (!tbody) {
        return;
    }

    try {
        const params = { page_size: 200, sort_by: 'created_at', sort_order: 'desc', important_only: true };
        const data = await AuditAPI.getAll(params);
        const logs = Array.isArray(data) ? data : (data.items || []);
        allLogs = logs;

        // Populate resource type filter
        populateLogsResourceFilter(logs);

        // Reset filter inputs
        const searchEl = document.getElementById('logs-search');
        if (searchEl) searchEl.value = '';
        const actionEl = document.getElementById('logs-action-filter');
        if (actionEl) actionEl.value = '';
        const resourceEl = document.getElementById('logs-resource-filter');
        if (resourceEl) resourceEl.value = '';
        const dateFromEl = document.getElementById('logs-date-from');
        if (dateFromEl) dateFromEl.value = '';
        const dateToEl = document.getElementById('logs-date-to');
        if (dateToEl) dateToEl.value = '';

        renderLogsTable(logs);
    } catch (error) {
        console.error('Logs load error:', error);
        tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">Unable to load logs</td></tr>';
    }
}

// Refresh dashboard data in background (works whether on dashboard or not)
// If currently viewing dashboard, updates immediately. Otherwise, data will be fresh when user navigates there.
async function refreshDashboardAsync() {
    try {
        const dashboardGrid = document.getElementById('dashboard-locations-grid');
        // Only update UI if dashboard is currently visible
        if (dashboardGrid) {
            await loadLocationStockSummary();
        }
        // Otherwise data will be fresh when user navigates back to dashboard
    } catch (error) {
        console.log('Dashboard refresh error:', error.message);
    }
}

// Location-wise Stock Summary
async function loadLocationStockSummary() {
    try {
        const locationFilter = document.getElementById('dashboard-location-filter');
        const selectedLocation = locationFilter ? locationFilter.value : '';
        
        const summary = await DashboardAPI.getLocationStockSummary(selectedLocation || null);
        
        // Update summary stats
        document.getElementById('summary-total-qty').textContent = summary.total_quantity.toLocaleString();
        document.getElementById('summary-received-today').textContent = summary.total_received_today.toLocaleString();
        document.getElementById('summary-issued-today').textContent = summary.total_issued_today.toLocaleString();
        document.getElementById('summary-low-stock').textContent = summary.low_stock_count.toLocaleString();
        
        // Build location cards for DASHBOARD
        const dashboardGrid = document.getElementById('dashboard-locations-grid');
        
        if (summary.locations.length === 0) {
            dashboardGrid.innerHTML = '<p class="text-muted">No stock data available</p>';
            return;
        }
        
        dashboardGrid.innerHTML = summary.locations.map(loc => {
            // Calculate totals for this location
            let openingTotal = 0, receivedTotal = 0, issuedTotal = 0, adjustedTotal = 0, closingTotal = 0;
            loc.items.forEach(item => {
                openingTotal += item.opening_balance;
                receivedTotal += item.received_today;
                issuedTotal += item.issued_today;
                adjustedTotal += item.adjusted_today;
                closingTotal += item.closing_balance;
            });
            
            return `
                <div class="location-card ${loc.low_stock_count > 0 ? 'has-low-stock' : ''}">
                    <div class="location-card-header">
                        <h4><i class="fas fa-map-marker-alt"></i> ${loc.location_name}</h4>
                        <span class="location-code">${loc.location_code}</span>
                    </div>
                    <div class="location-card-body">
                        <div class="stock-flow">
                            <div class="flow-item opening">
                                <span class="flow-label">Opening</span>
                                <span class="flow-value">${openingTotal.toLocaleString()}</span>
                            </div>
                            <div class="flow-arrow">
                                <i class="fas fa-plus"></i>
                            </div>
                            <div class="flow-item received">
                                <span class="flow-label">Received</span>
                                <span class="flow-value">+${receivedTotal.toLocaleString()}</span>
                            </div>
                            <div class="flow-arrow">
                                <i class="fas fa-minus"></i>
                            </div>
                            <div class="flow-item issued">
                                <span class="flow-label">Issued</span>
                                <span class="flow-value">-${issuedTotal.toLocaleString()}</span>
                            </div>
                            ${adjustedTotal !== 0 ? `
                            <div class="flow-arrow">
                                <i class="fas fa-plus-minus"></i>
                            </div>
                            <div class="flow-item adjusted">
                                <span class="flow-label">Adjusted</span>
                                <span class="flow-value">${adjustedTotal > 0 ? '+' : ''}${adjustedTotal.toLocaleString()}</span>
                            </div>
                            ` : ''}
                            <div class="flow-arrow">
                                <i class="fas fa-equals"></i>
                            </div>
                            <div class="flow-item closing">
                                <span class="flow-label">Closing</span>
                                <span class="flow-value">${closingTotal.toLocaleString()}</span>
                            </div>
                        </div>
                        <div class="location-stats">
                            <div class="location-stat">
                                <span class="stat-num">${loc.total_items}</span>
                                <span class="stat-text">Items</span>
                            </div>
                            ${loc.low_stock_count > 0 ? `
                            <div class="location-stat warning">
                                <span class="stat-num">${loc.low_stock_count}</span>
                                <span class="stat-text">Low Stock</span>
                            </div>
                            ` : ''}
                        </div>
                        ${loc.items.length > 0 ? `
                        <button class="btn btn-sm btn-outline" onclick="toggleLocationDetails('${loc.location_id}')">
                            <i class="fas fa-list"></i> View Details
                        </button>
                        <div class="location-details" id="loc-details-${loc.location_id}" style="display: none;">
                            <table class="mini-table">
                                <thead>
                                    <tr>
                                        <th>Item</th>
                                        <th>Opening</th>
                                        <th>In</th>
                                        <th>Out</th>
                                        <th>Closing</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    ${loc.items.slice(0, 10).map(item => `
                                    <tr class="${item.is_low_stock ? 'low-stock-row' : ''}">
                                        <td title="${item.name}">${item.sku}</td>
                                        <td>${item.opening_balance}</td>
                                        <td class="text-success">+${item.received_today}</td>
                                        <td class="text-danger">-${item.issued_today}</td>
                                        <td><strong>${item.closing_balance}</strong></td>
                                    </tr>
                                    `).join('')}
                                    ${loc.items.length > 10 ? `
                                    <tr><td colspan="5" class="text-muted text-center">... and ${loc.items.length - 10} more items</td></tr>
                                    ` : ''}
                                </tbody>
                            </table>
                        </div>
                        ` : ''}
                    </div>
                </div>
            `;
        }).join('');
        
    } catch (error) {
        console.error('Location stock summary load error:', error);
        document.getElementById('dashboard-locations-grid').innerHTML = 
            '<p class="text-muted">Error loading location stock data</p>';
    }
}

function toggleLocationDetails(locationId) {
    const details = document.getElementById(`loc-details-${locationId}`);
    if (details) {
        details.style.display = details.style.display === 'none' ? 'block' : 'none';
    }
}

function buildStockAdjustmentReasonOptions(defaultReason = '') {
    const groups = [
        {
            label: 'Increase / Add Correction',
            options: [
                ['Physical Count Excess', 'Physical count excess'],
                ['Opening Balance Correction', 'Opening balance correction'],
                ['Data Entry Correction - Added Stock', 'Data entry correction - added stock'],
                ['Unrecorded Return Correction', 'Unrecorded return correction'],
            ],
        },
        {
            label: 'Decrease / Deduct Correction',
            options: [
                ['Physical Count Shortage', 'Physical count shortage'],
                ['Damaged Stock Write-off', 'Damaged stock write-off'],
                ['Expired Stock Write-off', 'Expired stock write-off'],
                ['Lost / Missing Stock', 'Lost / missing stock'],
                ['Data Entry Correction - Deducted Stock', 'Data entry correction - deducted stock'],
            ],
        },
        {
            label: 'Audit / Other',
            options: [
                ['Audit Correction', 'Audit correction'],
                ['Stock Reconciliation', 'Stock reconciliation'],
                ['Other - Specify in Notes', 'Other - specify in notes'],
            ],
        },
    ];

    return '<option value="">Select reason</option>' + groups.map(group => `
        <optgroup label="${group.label}">
            ${group.options.map(([value, label]) =>
                `<option value="${value}" ${value === defaultReason ? 'selected' : ''}>${label}</option>`
            ).join('')}
        </optgroup>
    `).join('');
}

// Items (Products)
let allProducts = [];
let productStockMap = {};
const productsPaginationState = {
    currentPage: 1,
    itemsPerPage: 20,
    filteredItems: []
};

function productFromAsset(asset, categoryMap = {}) {
    const category = categoryMap[asset.item_category_id] || {};
    return {
        id: asset.item_id,
        asset_id: asset.id,
        id_number: asset.item_id_number || asset.asset_tag || '',
        sku: asset.serial_number,
        serial_number: asset.serial_number,
        name: asset.item_name || 'Serialized Product',
        description: asset.notes || '',
        category_id: asset.item_category_id,
        category_name: category.name || '-',
        category_type_key: category.category_type_key || asset.item_asset_type || '',
        stock_behavior: 'serialized',
        unit_of_measure: 'EA',
        manufacturer: asset.item_manufacturer || '',
        model: asset.item_model || '',
        asset_type: asset.item_asset_type || category.category_type_key || 'equipment',
        requires_calibration: asset.item_requires_calibration,
        location_id: asset.location_id,
        location_name: asset.location_name,
        status: asset.status,
        calibration_status: asset.calibration_status,
        next_calibration_due: asset.next_calibration_due,
        is_serialized: true,
        is_active: !['retired', 'lost'].includes(String(asset.status || '').toLowerCase()),
        _qty: 1,
        _low: false,
        _locations: asset.location_name ? [{ name: asset.location_name, qty: 1, reserved: 0, reorder_point: 0 }] : []
    };
}

async function loadItems() {
    try {
        const [data, catData] = await Promise.all([
            AssetsAPI.getAllPages({ sort_by: 'created_at', sort_order: 'desc' }),
            CategoriesAPI.getAll()
        ]);
        const assets = Array.isArray(data) ? data : (data.items || []);
        categories = Array.isArray(catData) ? catData : (catData.items || []);
        const categoryMap = {};
        categories.forEach(c => { categoryMap[c.id] = c; });
        
        // Populate category filter dropdown
        const catFilter = document.getElementById('products-category-filter');
        if (catFilter) {
            catFilter.innerHTML = '<option value="">All Types</option>' +
                categories
                    .filter(c => (c.stock_behavior || '').toLowerCase() === 'serialized')
                    .map(c => `<option value="${c.id}">${c.name}</option>`)
                    .join('');
        }
        
        productStockMap = {};
        allProducts = assets
            .filter(asset => {
                const type = String(asset.item_asset_type || categoryMap[asset.item_category_id]?.category_type_key || '').toLowerCase();
                return ['equipment', 'instrument'].includes(type) || asset.item_requires_calibration || asset.serial_number;
            })
            .map(asset => productFromAsset(asset, categoryMap));
        
        filterProducts();
    } catch (error) {
        console.error('Items load error:', error);
        document.getElementById('items-table-body').innerHTML = 
            '<tr><td colspan="8" class="text-center text-muted">Error loading products</td></tr>';
    }
}

function filterProducts() {
    const search = (document.getElementById('products-search')?.value || '').toLowerCase().trim();
    const catId = document.getElementById('products-category-filter')?.value || '';
    const typeFilter = currentProductTypeTab || document.getElementById('products-type-filter')?.value || 'equipment';
    
    let filtered = allProducts;
    
    if (search) {
        filtered = filtered.filter(p => 
            (p.name || '').toLowerCase().includes(search) ||
            (p.id_number || '').toLowerCase().includes(search) ||
            (p.sku || '').toLowerCase().includes(search) ||
            (p.manufacturer || '').toLowerCase().includes(search) ||
            (p.location_name || '').toLowerCase().includes(search)
        );
    }
    if (catId) {
        filtered = filtered.filter(p => p.category_id === catId);
    }
    if (typeFilter === 'equipment') {
        filtered = filtered.filter(p => (p.asset_type || p.category_type_key || '').toLowerCase() === 'equipment');
    } else if (typeFilter === 'instrument') {
        filtered = filtered.filter(p => (p.asset_type || p.category_type_key || '').toLowerCase() === 'instrument');
    } else if (typeFilter === 'calibration') {
        filtered = filtered.filter(p => p.requires_calibration);
    }
    
    productsPaginationState.filteredItems = filtered;
    productsPaginationState.currentPage = 1;
    renderProductsPage();
    
    const countEl = document.getElementById('products-count');
    if (countEl) {
        countEl.textContent = filtered.length === allProducts.length 
            ? `${allProducts.length} products` 
            : `${filtered.length} of ${allProducts.length} products`;
    }
}

function renderProductsPage() {
    const totalItems = productsPaginationState.filteredItems.length;
    const totalPages = Math.max(1, Math.ceil(totalItems / productsPaginationState.itemsPerPage));
    productsPaginationState.currentPage = Math.min(productsPaginationState.currentPage, totalPages);

    const start = (productsPaginationState.currentPage - 1) * productsPaginationState.itemsPerPage;
    const end = Math.min(start + productsPaginationState.itemsPerPage, totalItems);
    renderProductsTable(productsPaginationState.filteredItems.slice(start, end));

    const pagination = document.getElementById('products-pagination');
    if (!pagination) return;
    pagination.style.display = totalItems > productsPaginationState.itemsPerPage ? 'block' : 'none';
    document.getElementById('products-page-input').value = productsPaginationState.currentPage;
    document.getElementById('products-page-input').max = totalPages;
    document.getElementById('products-total-pages').textContent = totalPages;
    document.getElementById('products-page-info').textContent =
        totalItems ? `Showing ${start + 1} - ${end} of ${totalItems}` : 'Showing 0 of 0';
    document.getElementById('products-first-page').disabled = productsPaginationState.currentPage === 1;
    document.getElementById('products-prev-page').disabled = productsPaginationState.currentPage === 1;
    document.getElementById('products-next-page').disabled = productsPaginationState.currentPage === totalPages;
    document.getElementById('products-last-page').disabled = productsPaginationState.currentPage === totalPages;
}

function goToProductsPage(pageNumber) {
    const totalPages = Math.max(
        1,
        Math.ceil(productsPaginationState.filteredItems.length / productsPaginationState.itemsPerPage)
    );
    const parsedPage = Number.parseInt(pageNumber, 10);
    productsPaginationState.currentPage = Number.isFinite(parsedPage)
        ? Math.max(1, Math.min(parsedPage, totalPages))
        : 1;
    renderProductsPage();
}

function previousProductsPage() {
    goToProductsPage(productsPaginationState.currentPage - 1);
}

function nextProductsPage() {
    goToProductsPage(productsPaginationState.currentPage + 1);
}

function renderProductsTable(items) {
    const tbody = document.getElementById('items-table-body');
    
    if (items.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" class="text-center text-muted">No serial-number tracked products found</td></tr>';
        return;
    }
    
    const perms = getUserPermissions();
    tbody.innerHTML = items.map(item => {
        // Type badges
        let typeBadges = '';
        const typeLabel = (item.asset_type || item.category_type_name || 'Serialized').replace(/_/g, ' ');
        typeBadges += `<span class="badge badge-info badge-sm">${escapeHtml(typeLabel)}</span> `;
        if (item.requires_calibration) {
            typeBadges += '<span class="badge badge-warning badge-sm">Cal</span>';
        }
        
        return `
        <tr>
            <td class="text-muted">${item.id_number || '-'}</td>
            <td>
                <a href="#" class="product-name-link" onclick="viewAsset('${item.asset_id}'); return false;">
                    <strong>${escapeHtml(item.name)}</strong>
                </a>
                <br><small class="text-muted">${escapeHtml(item.location_name || '')}</small>
            </td>
            <td>${escapeHtml(item.manufacturer || '-')}</td>
            <td>${escapeHtml(item.category_name || item.category?.name || '-')}</td>
            <td class="text-muted">${escapeHtml(item.sku || '-')}</td>
            <td>${item.unit_of_measure}</td>
            <td>${typeBadges}</td>
            <td class="actions">
                <div class="action-group">
                    <button class="btn-icon" onclick="viewAsset('${item.asset_id}')" title="View product">
                        <i class="fas fa-eye"></i>
                    </button>
                    <button class="btn-icon" onclick="editAsset('${item.asset_id}')" title="Edit product">
                        <i class="fas fa-edit"></i>
                    </button>
                    <button class="btn-icon" onclick="quickTransferProduct('${item.id}'); return false;" title="Create transfer">
                        <i class="fas fa-exchange-alt"></i>
                    </button>
                    <button class="btn-icon" onclick="deactivateProduct('${item.asset_id}')" title="Deactivate">
                        <i class="fas fa-ban"></i>
                    </button>
                    ${perms.isAdmin ? `<button class="btn-icon text-danger" onclick="permanentlyDeleteProduct('${item.asset_id}')" title="Permanent Delete"><i class="fas fa-trash"></i></button>` : ''}
                </div>
            </td>
        </tr>`;
    }).join('');
}

// ============ SECTION FILTER FUNCTIONS ============

// --- Stock Levels Filter ---
let stockAllItemsUnfiltered = []; // full copy before client-side filter

function filterStock() {
    const search = (document.getElementById('stock-search')?.value || '').toLowerCase().trim();
    const catFilter = document.getElementById('stock-category-filter')?.value || '';
    const statusFilter = document.getElementById('stock-status-filter')?.value || '';
    const typeFilter = currentStockTypeTab || 'consumable';

    let filtered = stockAllItemsUnfiltered;

    if (typeFilter) {
        filtered = filtered.filter(s => quantityTypeKeyForRecord(s) === typeFilter);
    }

    if (search) {
        filtered = filtered.filter(s =>
            (s.name || '').toLowerCase().includes(search) ||
            (s.sku || '').toLowerCase().includes(search) ||
            (s.manufacturer || '').toLowerCase().includes(search) ||
            (s.model || '').toLowerCase().includes(search) ||
            (s.category_name || '').toLowerCase().includes(search) ||
            (s.unit_of_measure || '').toLowerCase().includes(search) ||
            (s.location_name || '').toLowerCase().includes(search)
        );
    }
    if (catFilter) {
        filtered = filtered.filter(s => (s.category_name || '') === catFilter);
    }
    if (statusFilter === 'low') {
        filtered = filtered.filter(s => s.is_low_stock);
    } else if (statusFilter === 'ok') {
        filtered = filtered.filter(s => !s.is_low_stock);
    }

    stockPaginationState.allItems = filtered;
    stockPaginationState.totalItems = filtered.length;
    stockPaginationState.totalPages = Math.ceil(filtered.length / stockPaginationState.itemsPerPage) || 1;
    stockPaginationState.currentPage = 1;
    const paginationDiv = document.getElementById('stock-pagination');
    if (paginationDiv) paginationDiv.style.display = stockPaginationState.totalPages > 1 ? 'block' : 'none';
    renderStockPage();
}

function syncStockTypeTabs() {
    document.querySelectorAll('#stock-tab-consumable, #stock-tab-accessory').forEach(btn => {
        btn.classList.remove('active');
    });
    document.getElementById(`stock-tab-${currentStockTypeTab}`)?.classList.add('active');
}

function switchStockTypeTab(type) {
    currentStockTypeTab = normalizeTypeKey(type) === 'accessory' ? 'accessory' : 'consumable';
    syncStockTypeTabs();
    filterStock();
}

function populateStockCategoryFilter(items) {
    const catSet = new Set(items.map(i => i.category_name).filter(Boolean));
    const sel = document.getElementById('stock-category-filter');
    if (!sel) return;
    const val = sel.value;
    sel.innerHTML = '<option value="">All Categories</option>' +
        [...catSet].sort().map(c => `<option value="${c}">${c}</option>`).join('');
    sel.value = val;
}

// --- Locations Filter ---
function filterLocations() {
    const search = (document.getElementById('locations-search')?.value || '').toLowerCase().trim();
    let filtered = locations;
    if (search) {
        filtered = filtered.filter(loc =>
            (loc.name || '').toLowerCase().includes(search) ||
            (loc.code || '').toLowerCase().includes(search) ||
            (loc.city || '').toLowerCase().includes(search) ||
            (loc.contact_person || '').toLowerCase().includes(search)
        );
    }
    renderLocationsGrid(filtered);
}

// --- Categories Filter ---
function filterCategories() {
    const search = (document.getElementById('categories-search')?.value || '').toLowerCase().trim();
    const statusFilter = document.getElementById('categories-status-filter')?.value || '';
    const stockFilter = document.getElementById('categories-stock-filter')?.value || '';
    let filtered = categories;
    if (search) {
        filtered = filtered.filter(c =>
            (c.name || '').toLowerCase().includes(search) ||
            (c.description || '').toLowerCase().includes(search)
        );
    }
    if (statusFilter === 'active') {
        filtered = filtered.filter(c => c.is_active);
    } else if (statusFilter === 'inactive') {
        filtered = filtered.filter(c => !c.is_active);
    }
    if (stockFilter) {
        filtered = filtered.filter(c => (c.stock_behavior || 'quantity') === stockFilter);
    }
    renderCategoriesTable(filtered);
}

function switchProductTypeTab(type) {
    currentProductTypeTab = normalizeTypeKey(type) === 'instrument' ? 'instrument' : 'equipment';
    document.querySelectorAll('#products-tab-equipment, #products-tab-instrument').forEach(btn => {
        btn.classList.remove('active');
    });
    document.getElementById(`products-tab-${currentProductTypeTab}`)?.classList.add('active');
    const typeFilter = document.getElementById('products-type-filter');
    if (typeFilter) typeFilter.value = currentProductTypeTab;
    filterProducts();
}

// --- Transfers Filter ---
function filterTransfers() {
    const search = (document.getElementById('transfers-search')?.value || '').toLowerCase().trim();
    const statusFilter = document.getElementById('transfers-status-filter')?.value || '';
    const priorityFilter = document.getElementById('transfers-priority-filter')?.value || '';
    let filtered = allTransfers;
    if (search) {
        filtered = filtered.filter(t =>
            (t.transfer_number || '').toLowerCase().includes(search) ||
            (t.from_location_name || '').toLowerCase().includes(search) ||
            (t.to_location_name || '').toLowerCase().includes(search) ||
            (Array.isArray(t.items) && t.items.some(i =>
                (i.item_name || '').toLowerCase().includes(search) ||
                (i.item_sku || '').toLowerCase().includes(search)
            ))
        );
    }
    if (statusFilter) {
        filtered = filtered.filter(t => (t.status || '').toLowerCase() === statusFilter);
    }
    if (priorityFilter) {
        filtered = filtered.filter(t => (t.priority || '').toLowerCase() === priorityFilter);
    }
    renderTransfersTables(filtered);
}

// --- Logs Filter ---
function filterLogs() {
    const search = (document.getElementById('logs-search')?.value || '').toLowerCase().trim();
    const actionFilter = document.getElementById('logs-action-filter')?.value || '';
    const resourceFilter = document.getElementById('logs-resource-filter')?.value || '';
    const dateFrom = document.getElementById('logs-date-from')?.value || '';
    const dateTo = document.getElementById('logs-date-to')?.value || '';
    let filtered = allLogs;
    if (search) {
        filtered = filtered.filter(l =>
            (l.user_name || l.user_email || '').toLowerCase().includes(search) ||
            (l.resource_type || '').toLowerCase().includes(search) ||
            (l.resource_id || '').toLowerCase().includes(search)
        );
    }
    if (actionFilter) {
        filtered = filtered.filter(l => (l.action || '').toLowerCase().includes(actionFilter));
    }
    if (resourceFilter) {
        filtered = filtered.filter(l => (l.resource_type || '') === resourceFilter);
    }
    if (dateFrom) {
        const from = new Date(dateFrom);
        filtered = filtered.filter(l => {
            const d = l.created_at ? new Date(l.created_at) : null;
            return d && d >= from;
        });
    }
    if (dateTo) {
        const to = new Date(dateTo);
        to.setHours(23, 59, 59, 999);
        filtered = filtered.filter(l => {
            const d = l.created_at ? new Date(l.created_at) : null;
            return d && d <= to;
        });
    }
    renderLogsTable(filtered);
}

function populateLogsResourceFilter(logs) {
    const types = new Set(logs.map(l => l.resource_type).filter(Boolean));
    const sel = document.getElementById('logs-resource-filter');
    if (!sel) return;
    const val = sel.value;
    sel.innerHTML = '<option value="">All Resources</option>' +
        [...types].sort().map(t => `<option value="${t}">${t}</option>`).join('');
    sel.value = val;
}

// --- Users Filter ---
function filterUsers() {
    const search = (document.getElementById('users-search')?.value || '').toLowerCase().trim();
    const roleFilter = document.getElementById('users-role-filter')?.value || '';
    const statusFilter = document.getElementById('users-status-filter')?.value || '';
    let filtered = usersCache;
    if (search) {
        filtered = filtered.filter(u =>
            (u.name || '').toLowerCase().includes(search) ||
            (u.email || '').toLowerCase().includes(search)
        );
    }
    if (roleFilter) {
        filtered = filtered.filter(u => u.role === roleFilter);
    }
    if (statusFilter === 'active') {
        filtered = filtered.filter(u => u.is_active);
    } else if (statusFilter === 'inactive') {
        filtered = filtered.filter(u => !u.is_active);
    }
    renderUsersTable(filtered);
}

// --- Employee Records Filter ---
function filterEmployeeRecords() {
    const search = (document.getElementById('personal-search')?.value || '').toLowerCase().trim();
    const statusFilter = document.getElementById('personal-status-filter')?.value || '';
    let filtered = allEmployeeRecords;
    if (search) {
        filtered = filtered.filter(r =>
            (r.user_name || '').toLowerCase().includes(search) ||
            (r.title || '').toLowerCase().includes(search) ||
            (r.certificate_number || '').toLowerCase().includes(search) ||
            (r.user_location || '').toLowerCase().includes(search)
        );
    }
    if (statusFilter === 'active') {
        filtered = filtered.filter(r => r.is_active);
    } else if (statusFilter === 'inactive') {
        filtered = filtered.filter(r => !r.is_active);
    }
    window.filteredEmployeeRecords = filtered;
    personnelPaginationState.currentPage = 1;
    renderPersonnelPage();
}

// ============ RENDER FUNCTIONS FOR FILTERED SECTIONS ============

function renderLocationsGrid(locs) {
    const grid = document.getElementById('locations-grid');
    if (!grid) return;
    if (!locs || locs.length === 0) {
        grid.innerHTML = '<p class="text-muted">No locations found</p>';
        return;
    }
    grid.innerHTML = locs.map(loc => {
        const perms = getUserPermissions();
        const actionsHtml = (perms.isAdmin || perms.isHOManager || perms.isLocationManager) ? `
            <div class="location-actions">
                ${(perms.isAdmin || perms.isHOManager) ? `<button class="btn btn-sm btn-primary" onclick="editLocation('${loc.id}')"><i class="fas fa-edit"></i> Edit</button>` : ''}
                ${loc.is_active ? `<button class="btn btn-sm btn-danger" onclick="deleteLocation('${loc.id}')"><i class="fas fa-ban"></i> Deactivate</button>` : ''}
                ${perms.isAdmin ? `<button class="btn btn-sm btn-danger" onclick="permanentlyDeleteLocation('${loc.id}')"><i class="fas fa-trash"></i> Permanent Delete</button>` : ''}
            </div>` : '';
        return `
        <div class="location-card">
            <div class="location-header">
                <h4><i class="fas fa-map-marker-alt"></i> ${loc.name}</h4>
                <span class="location-status ${loc.is_active ? 'active' : 'inactive'}">
                    <i class="fas ${loc.is_active ? 'fa-check-circle' : 'fa-times-circle'}"></i>
                    ${loc.is_active ? 'Active' : 'Inactive'}
                </span>
            </div>
            <div class="location-details">
                <div class="detail-row">
                    <span class="detail-label">Code:</span>
                    <span class="detail-value">${loc.code}</span>
                </div>
                ${loc.contact_person ? `<div class="detail-row highlight"><span class="detail-label"><i class="fas fa-user"></i> Contact Person:</span><span class="detail-value">${loc.contact_person}</span></div>` : ''}
                ${loc.phone || loc.email ? `<div class="detail-row"><span class="detail-label"><i class="fas fa-phone"></i> Contact:</span><span class="detail-value">${loc.phone ? '<a href="tel:' + loc.phone + '">' + loc.phone + '</a>' : ''}${loc.phone && loc.email ? ' | ' : ''}${loc.email ? '<a href="mailto:' + loc.email + '">' + loc.email + '</a>' : ''}</span></div>` : ''}
                ${loc.address ? `<div class="detail-row"><span class="detail-label"><i class="fas fa-map-pin"></i> Address:</span><span class="detail-value">${loc.address}</span></div>` : ''}
                ${[loc.city, loc.state, loc.country].filter(Boolean).length > 0 ? `<div class="detail-row"><span class="detail-label"><i class="fas fa-globe"></i> Location:</span><span class="detail-value">${[loc.city, loc.state, loc.country].filter(Boolean).join(', ')}</span></div>` : ''}
                ${loc.postal_code ? `<div class="detail-row"><span class="detail-label">Postal Code:</span><span class="detail-value">${loc.postal_code}</span></div>` : ''}
                ${loc.assigned_users && loc.assigned_users.length > 0 ? `
                <div class="detail-row highlight">
                    <span class="detail-label"><i class="fas fa-users"></i> Assigned Users:</span>
                    <span class="detail-value">
                        ${loc.assigned_users.map(u => `<span class="assigned-user-tag"><i class="fas fa-user-circle"></i> ${u.name} <small class="text-muted">(${ROLE_LABELS[u.role] || u.role})</small></span>`).join('')}
                    </span>
                </div>` : ''}
            </div>
            ${actionsHtml}
        </div>
    `;
    }).join('');
}

function renderCategoriesTable(cats) {
    const tbody = document.getElementById('categories-table-body');
    if (!tbody) return;
    if (cats.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted">No categories found</td></tr>';
        return;
    }
    const perms = getUserPermissions();
    tbody.innerHTML = cats.map(cat => {
        const itemCount = cat.item_count || 0;
        const countDisplay = (cat.stock_behavior || '').toLowerCase() === 'serialized'
            ? '<span class="text-muted">Serial-wise</span>'
            : itemCount;
        const actionsHtml = perms.canManageCategories ? `
                <button class="btn-icon" onclick="editCategory('${cat.id}')" title="Edit"><i class="fas fa-edit"></i></button>
                <button class="btn-icon ${itemCount > 0 ? 'disabled' : ''}" ${itemCount > 0 ? 'disabled' : `onclick="deleteCategory('${cat.id}')"`} title="${itemCount > 0 ? 'Cannot deactivate category with existing items' : 'Deactivate category'}"><i class="fas fa-ban"></i></button>
                ${perms.isAdmin ? `<button class="btn-icon text-danger" onclick="permanentlyDeleteCategory('${cat.id}', '${encodeURIComponent(cat.name)}')" title="Permanent Delete"><i class="fas fa-trash-alt"></i></button>` : ''}
            ` : '<span class="text-muted">-</span>';
        return `
        <tr>
            <td><strong>${escapeHtml(cat.name)}</strong></td>
            <td><span class="badge badge-info">${stockBehaviorLabel(cat.stock_behavior)}</span></td>
            <td>${escapeHtml(cat.description || '-')}</td>
            <td>${countDisplay}</td>
            <td>${cat.is_active ? '<span class="badge badge-success">Active</span>' : '<span class="badge badge-danger">Inactive</span>'}</td>
            <td class="actions">${actionsHtml}</td>
        </tr>
    `;
    }).join('');
}

function renderTransfersTables(transfers) {
    const consumablesTbody = document.getElementById('transfers-table-body');
    const equipmentTbody = document.getElementById('equipment-transfers-table-body');

    const consumableTransfers = [];
    const equipmentTransfers = [];
    transfers.forEach(transfer => {
        if (isSerializedTransferType(transfer.transfer_type)) {
            equipmentTransfers.push(transfer);
        } else if (isQuantityTransferType(transfer.transfer_type)) {
            consumableTransfers.push(transfer);
        } else {
            const itemList = Array.isArray(transfer.items) ? transfer.items : [];
            const hasEquipmentItems = itemList.some(item => {
                if (item.item_is_serialized === true) return true;
                if (item.item_is_serialized === false) return false;
                const serialNumbers = Array.isArray(item.serial_numbers) ? item.serial_numbers : [];
                return serialNumbers.length > 0;
            }) || String(transfer.transfer_number || '').includes('-EQ-');
            if (hasEquipmentItems) {
                equipmentTransfers.push(transfer);
            } else {
                consumableTransfers.push(transfer);
            }
        }
    });

    // Update stat cards
    updateTransferStats(transfers);

    // Update tab counts
    const cCount = document.getElementById('consumable-tab-count');
    const eCount = document.getElementById('equipment-tab-count');
    if (cCount) cCount.textContent = consumableTransfers.length;
    if (eCount) eCount.textContent = equipmentTransfers.length;

    // Helper: status badge with icon
    const getStatusBadge = (statusKey) => {
        const map = {
            requested: { cls: 'badge-warning', icon: 'fa-clock', label: 'Requested' },
            approved: { cls: 'badge-info', icon: 'fa-check', label: 'Approved' },
            in_transit: { cls: 'badge-info', icon: 'fa-shipping-fast', label: 'In Transit' },
            received: { cls: 'badge-success', icon: 'fa-check-circle', label: 'Received' },
            partially_received: { cls: 'badge-warning', icon: 'fa-exclamation-circle', label: 'Partial' },
            completed: { cls: 'badge-success', icon: 'fa-check-double', label: 'Completed' },
            cancelled: { cls: 'badge-danger', icon: 'fa-ban', label: 'Cancelled' },
            rejected: { cls: 'badge-danger', icon: 'fa-times-circle', label: 'Rejected' },
            draft: { cls: 'badge-secondary', icon: 'fa-pencil-alt', label: 'Draft' },
            pending: { cls: 'badge-warning', icon: 'fa-hourglass-half', label: 'Pending' },
        };
        const m = map[statusKey] || { cls: 'badge-secondary', icon: 'fa-question', label: statusKey };
        return `<span class="badge-status ${m.cls}"><i class="fas ${m.icon}"></i> ${m.label}</span>`;
    };

    const priorityDot = (p) => {
        const key = (p || 'normal').toLowerCase();
        return `<span class="priority-dot ${key}" title="${key}"></span>`;
    };

    const formatShortDate = (val) => {
        if (!val) return '-';
        const d = new Date(val);
        return d.toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' });
    };

    // Empty state HTML
    const emptyStateHtml = (cols, icon, title, desc) =>
        `<tr><td colspan="${cols}">
            <div class="transfer-empty-state">
                <i class="fas ${icon}"></i>
                <div class="empty-title">${title}</div>
                <div class="empty-desc">${desc}</div>
            </div>
        </td></tr>`;

    // Render consumable transfers
    const renderConsumableRows = (tbody, tableTransfers) => {
        if (!tbody) return;
        if (!tableTransfers || tableTransfers.length === 0) {
            tbody.innerHTML = emptyStateHtml(11, 'fa-boxes', 'No quantity-based transfers', 'Create a new consumable or accessory transfer to get started');
            return;
        }
        const rows = [];
        tableTransfers.forEach(transfer => {
            const statusKey = String(transfer.status || '').toLowerCase();
            const createdAt = transfer.created_at || transfer.requested_date;
            const dateLabel = formatShortDate(createdAt);
            const items = Array.isArray(transfer.items) ? transfer.items : [];
            if (items.length === 0) {
                rows.push(`<tr class="transfer-group-first" data-transfer-id="${transfer.id}">
                    <td class="transfer-number-cell">${priorityDot(transfer.priority)}${transfer.transfer_number || '-'}${transfer.purchase_indent_number ? `<br><small class='pi-badge' title='Purchase Indent'>PI: ${transfer.purchase_indent_number}</small>` : ''}</td>
                    <td>-</td><td>-</td><td>-</td><td>0</td>
                    <td class="location-cell">${transfer.from_location_name || '-'}</td>
                    <td class="location-cell">${transfer.to_location_name || '-'}</td>
                    <td class="assigned-to-cell">${transfer.assigned_to_name ? `<span class='user-chip'><i class='fas fa-user'></i> ${transfer.assigned_to_name}</span>` : '<span class="text-muted">-</span>'}</td>
                    <td>${dateLabel}</td>
                    <td>${getStatusBadge(statusKey)}</td>
                    <td><div class="transfer-actions">
                        ${transfer.purchase_indent_id ? `<button class="btn-icon" onclick="viewPurchaseIndent('${transfer.purchase_indent_id}')" title="View Purchase Indent (PI)"><i class="fas fa-file-alt"></i></button>` : ''}
                        <button class="btn-icon" onclick="viewTransfer('${transfer.id}')" title="View Details"><i class="fas fa-eye"></i></button>
                        <button class="btn-icon btn-pdf" onclick="generateTransferPDF('${transfer.id}')" title="Download PDF"><i class="fas fa-file-pdf"></i></button>
                        ${['approved','in_transit','received','partially_received'].includes(statusKey) ? `<button class="btn-icon btn-dc" onclick="printDeliveryChallan('${transfer.id}')" title="View / Print Delivery Challan (DC)"><i class="fas fa-file-invoice"></i></button>` : ''}
                        ${canReceiveTransfer(transfer, statusKey) ? `<button class="btn-receive-inline" onclick="receiveTransfer('${transfer.id}')" title="Confirm Receipt"><i class="fas fa-download"></i> Receive</button>` : ''}
                    </div></td>
                </tr>`);
            } else {
                items.forEach((item, idx) => {
                    const isFirst = idx === 0;
                    const rowClass = isFirst ? 'transfer-group-first' : 'transfer-group-continuation';
                    rows.push(`<tr class="${rowClass}"${isFirst ? ` data-transfer-id="${transfer.id}"` : ''}>
                        <td class="transfer-number-cell">${isFirst ? priorityDot(transfer.priority) + (transfer.transfer_number || '-') + (transfer.purchase_indent_number ? `<br><small class='pi-badge' title='Purchase Indent'>PI: ${transfer.purchase_indent_number}</small>` : '') : ''}</td>
                        <td><strong>${item.item_name || item.item_sku || '-'}</strong></td>
                        <td>${item.item_manufacturer || '-'}</td>
                        <td>${item.lot_number || '-'}</td>
                        <td>${item.quantity_requested || 0}</td>
                        <td class="location-cell">${isFirst ? (transfer.from_location_name || '-') : ''}</td>
                        <td class="location-cell">${isFirst ? (transfer.to_location_name || '-') : ''}</td>
                        <td class="assigned-to-cell">${isFirst ? (transfer.assigned_to_name ? `<span class='user-chip'><i class='fas fa-user'></i> ${transfer.assigned_to_name}</span>` : '-') : ''}</td>
                        <td>${isFirst ? dateLabel : ''}</td>
                        <td>${isFirst ? getStatusBadge(statusKey) : ''}</td>
                        <td>${isFirst ? `<div class="transfer-actions">
                            ${transfer.purchase_indent_id ? `<button class="btn-icon" onclick="viewPurchaseIndent('${transfer.purchase_indent_id}')" title="View Purchase Indent (PI)"><i class="fas fa-file-alt"></i></button>` : ''}
                            <button class="btn-icon" onclick="viewTransfer('${transfer.id}')" title="View Details"><i class="fas fa-eye"></i></button>
                            <button class="btn-icon btn-pdf" onclick="generateTransferPDF('${transfer.id}')" title="Download PDF"><i class="fas fa-file-pdf"></i></button>
                            ${['approved','in_transit','received','partially_received'].includes(statusKey) ? `<button class="btn-icon btn-dc" onclick="printDeliveryChallan('${transfer.id}')" title="View / Print Delivery Challan (DC)"><i class="fas fa-file-invoice"></i></button>` : ''}
                            ${canReceiveTransfer(transfer, statusKey) ? `<button class="btn-receive-inline" onclick="receiveTransfer('${transfer.id}')" title="Confirm Receipt"><i class="fas fa-download"></i> Receive</button>` : ''}
                        </div>` : ''}</td>
                    </tr>`);
                });
            }
        });
        tbody.innerHTML = rows.join('');
    };

    // Render equipment transfers
    const renderEquipmentRows = (tbody, tableTransfers) => {
        if (!tbody) return;
        if (!tableTransfers || tableTransfers.length === 0) {
            tbody.innerHTML = emptyStateHtml(13, 'fa-tools', 'No serialized transfers', 'Equipment and instrument transfers track one serial-numbered item at a time');
            return;
        }
        const rows = [];
        tableTransfers.forEach(transfer => {
            const statusKey = String(transfer.status || '').toLowerCase();
            const createdAt = transfer.created_at || transfer.requested_date;
            const dateLabel = formatShortDate(createdAt);
            let returnDateHtml = '-';
            if (transfer.return_date) {
                const rd = new Date(transfer.return_date);
                const rdLabel = formatShortDate(transfer.return_date);
                const diff = rd.getTime() - Date.now();
                const reminderMs = (transfer.return_reminder_days || 3) * 24 * 60 * 60 * 1000;
                if (diff < 0) {
                    returnDateHtml = `<span class="return-date-cell">${rdLabel} <span class="overdue-tag"><i class="fas fa-exclamation-circle"></i> Overdue</span></span>`;
                } else if (diff <= reminderMs) {
                    returnDateHtml = `<span class="return-date-cell">${rdLabel} <span class="due-soon-tag"><i class="fas fa-exclamation-triangle"></i> Due Soon</span></span>`;
                } else {
                    returnDateHtml = rdLabel;
                }
            }
            const items = Array.isArray(transfer.items) ? transfer.items : [];
            if (items.length === 0) {
                rows.push(`<tr class="transfer-group-first" data-transfer-id="${transfer.id}">
                    <td class="transfer-number-cell">${priorityDot(transfer.priority)}${transfer.transfer_number || '-'}${transfer.purchase_indent_number ? `<br><small class='pi-badge' title='Purchase Indent'>PI: ${transfer.purchase_indent_number}</small>` : ''}</td>
                    <td>${dateLabel}</td>
                    <td>-</td><td>-</td><td>-</td><td>-</td><td>0</td>
                    <td class="location-cell">${transfer.from_location_name || '-'}</td>
                    <td class="location-cell">${transfer.to_location_name || '-'}</td>
                    <td class="assigned-to-cell">${transfer.assigned_to_name ? `<span class='user-chip'><i class='fas fa-user'></i> ${transfer.assigned_to_name}</span>` : '<span class="text-muted">-</span>'}</td>
                    <td>${returnDateHtml}</td>
                    <td>${getStatusBadge(statusKey)}</td>
                    <td><div class="transfer-actions">
                        ${transfer.purchase_indent_id ? `<button class="btn-icon" onclick="viewPurchaseIndent('${transfer.purchase_indent_id}')" title="View Purchase Indent (PI)"><i class="fas fa-file-alt"></i></button>` : ''}
                        <button class="btn-icon" onclick="viewTransfer('${transfer.id}')" title="View Details"><i class="fas fa-eye"></i></button>
                        <button class="btn-icon btn-pdf" onclick="generateTransferPDF('${transfer.id}')" title="Download PDF"><i class="fas fa-file-pdf"></i></button>
                        <button class="btn-icon btn-calendar" onclick="showModifyReturnDate('${transfer.id}', '${transfer.return_date || ''}', ${transfer.return_reminder_days || 3})" title="Modify Return Date"><i class="fas fa-calendar-alt"></i></button>
                        ${['approved','in_transit','received','partially_received'].includes(statusKey) ? `<button class="btn-icon btn-dc" onclick="printDeliveryChallan('${transfer.id}')" title="View / Print Delivery Challan (DC)"><i class="fas fa-file-invoice"></i></button>` : ''}
                        ${canReceiveTransfer(transfer, statusKey) ? `<button class="btn-receive-inline" onclick="receiveTransfer('${transfer.id}')" title="Confirm Receipt"><i class="fas fa-download"></i> Receive</button>` : ''}
                    </div></td>
                </tr>`);
            } else {
                items.forEach((item, idx) => {
                    const isFirst = idx === 0;
                    const rowClass = isFirst ? 'transfer-group-first' : 'transfer-group-continuation';
                    const serials = Array.isArray(item.serial_numbers) ? item.serial_numbers.join(', ') : (item.serial_numbers || '-');
                    rows.push(`<tr class="${rowClass}"${isFirst ? ` data-transfer-id="${transfer.id}"` : ''}>
                        <td class="transfer-number-cell">${isFirst ? priorityDot(transfer.priority) + (transfer.transfer_number || '-') + (transfer.purchase_indent_number ? `<br><small class='pi-badge' title='Purchase Indent'>PI: ${transfer.purchase_indent_number}</small>` : '') : ''}</td>
                        <td>${isFirst ? dateLabel : ''}</td>
                        <td><strong>${item.item_name || item.item_sku || '-'}</strong></td>
                        <td>${serials}</td>
                        <td>${item.lot_number || '-'}</td>
                        <td>${item.notes || '-'}</td>
                        <td>${item.quantity_requested || 0}</td>
                        <td class="location-cell">${isFirst ? (transfer.from_location_name || '-') : ''}</td>
                        <td class="location-cell">${isFirst ? (transfer.to_location_name || '-') : ''}</td>
                        <td class="assigned-to-cell">${isFirst ? (transfer.assigned_to_name ? `<span class='user-chip'><i class='fas fa-user'></i> ${transfer.assigned_to_name}</span>` : '-') : ''}</td>
                        <td>${isFirst ? returnDateHtml : ''}</td>
                        <td>${isFirst ? getStatusBadge(statusKey) : ''}</td>
                        <td>${isFirst ? `<div class="transfer-actions">
                            ${transfer.purchase_indent_id ? `<button class="btn-icon" onclick="viewPurchaseIndent('${transfer.purchase_indent_id}')" title="View Purchase Indent (PI)"><i class="fas fa-file-alt"></i></button>` : ''}
                            <button class="btn-icon" onclick="viewTransfer('${transfer.id}')" title="View Details"><i class="fas fa-eye"></i></button>
                            <button class="btn-icon btn-pdf" onclick="generateTransferPDF('${transfer.id}')" title="Download PDF"><i class="fas fa-file-pdf"></i></button>
                            <button class="btn-icon btn-calendar" onclick="showModifyReturnDate('${transfer.id}', '${transfer.return_date || ''}', ${transfer.return_reminder_days || 3})" title="Modify Return Date"><i class="fas fa-calendar-alt"></i></button>
                            ${['approved','in_transit','received','partially_received'].includes(statusKey) ? `<button class="btn-icon btn-dc" onclick="printDeliveryChallan('${transfer.id}')" title="View / Print Delivery Challan (DC)"><i class="fas fa-file-invoice"></i></button>` : ''}
                            ${canReceiveTransfer(transfer, statusKey) ? `<button class="btn-receive-inline" onclick="receiveTransfer('${transfer.id}')" title="Confirm Receipt"><i class="fas fa-download"></i> Receive</button>` : ''}
                        </div>` : ''}</td>
                    </tr>`);
                });
            }
        });
        tbody.innerHTML = rows.join('');
    };

    renderConsumableRows(consumablesTbody, consumableTransfers);
    renderEquipmentRows(equipmentTbody, equipmentTransfers);

    if (getUserPermissions().isAdmin) {
        [consumablesTbody, equipmentTbody].forEach(tbody => {
            tbody?.querySelectorAll('tr[data-transfer-id]').forEach(row => {
                const actions = row.querySelector('.transfer-actions');
                if (!actions || actions.querySelector('.transfer-permanent-delete')) return;
                const transferId = row.dataset.transferId;
                actions.insertAdjacentHTML('beforeend', `<button class="btn-icon text-danger transfer-permanent-delete" onclick="permanentlyDeleteTransfer('${transferId}')" title="Permanent Delete"><i class="fas fa-trash-alt"></i></button>`);
            });
        });
    }

    // Also load blocked equipment items
    if (equipmentTbody) {
        loadBlockedEquipmentRows(equipmentTbody, equipmentTransfers);
    }
}

async function permanentlyDeleteTransfer(id) {
    if (!confirm('Permanently delete this transfer and all of its line items? This action cannot be undone. Inventory transactions and audit logs will be retained.')) return;
    try {
        await TransfersAPI.permanentDelete(id);
        showToast('Transfer permanently deleted', 'success');
        await loadTransfers();
    } catch (error) {
        showToast(error.message || 'Failed to permanently delete transfer', 'error');
    }
}

function updateTransferStats(transfers) {
    const total = transfers.length;
    const pending = transfers.filter(t => ['requested', 'approved'].includes((t.status || '').toLowerCase())).length;
    const transit = transfers.filter(t => (t.status || '').toLowerCase() === 'in_transit').length;
    const completed = transfers.filter(t => ['received', 'completed', 'partially_received'].includes((t.status || '').toLowerCase())).length;
    const rejected = transfers.filter(t => ['rejected', 'cancelled'].includes((t.status || '').toLowerCase())).length;

    const el = (id, val) => { const e = document.getElementById(id); if (e) e.textContent = val; };
    el('tstat-total', total);
    el('tstat-pending', pending);
    el('tstat-transit', transit);
    el('tstat-completed', completed);
    el('tstat-rejected', rejected);

    // Stat card click-to-filter
    document.querySelectorAll('.transfer-stat-card').forEach(card => {
        card.onclick = () => {
            const status = card.dataset.status;
            const statusEl = document.getElementById('transfers-status-filter');
            // Toggle off if same clicked again
            const wasActive = card.classList.contains('active-filter');
            document.querySelectorAll('.transfer-stat-card').forEach(c => c.classList.remove('active-filter'));
            if (wasActive) {
                if (statusEl) statusEl.value = '';
                filterTransfers();
            } else {
                card.classList.add('active-filter');
                if (status === 'all') {
                    if (statusEl) statusEl.value = '';
                } else if (status === 'requested') {
                    if (statusEl) statusEl.value = 'requested';
                } else if (status === 'in_transit') {
                    if (statusEl) statusEl.value = 'in_transit';
                } else if (status === 'received') {
                    if (statusEl) statusEl.value = 'received';
                } else if (status === 'rejected') {
                    if (statusEl) statusEl.value = 'rejected';
                }
                filterTransfers();
            }
        };
    });
}

async function loadBlockedEquipmentRows(tbody, existingTransfers) {
    try {
        const overview = await TransfersAPI.getEquipmentOverview();
        const allIssues = [
            ...(overview.calibration_issues || []),
            ...(overview.maintenance_issues || []),
        ];
        // Collect unique blocked items
        const blockedMap = {};
        allIssues.forEach(item => {
            if (!item.can_transfer && item.item_id && !blockedMap[item.asset_id]) {
                blockedMap[item.asset_id] = item;
            }
        });
        const blockedItems = Object.values(blockedMap);
        if (blockedItems.length === 0) return;

        // Add a separator header row
        const sepRow = `<tr style="background:#fff3cd;">
            <td colspan="12" style="font-weight:600;color:#856404;padding:8px 12px;">
                <i class="fas fa-ban"></i> Blocked Equipment — Transfer not allowed
            </td>
        </tr>`;

        const blockedRows = blockedItems.map(item => {
            const reasons = (item.blocked_reasons || []).join('; ');
            return `<tr style="opacity:0.7;">
                <td>-</td>
                <td>-</td>
                <td><strong>${item.item_name || item.item_sku || '-'}</strong></td>
                <td>${item.serial_number || '-'}</td>
                <td>-</td>
                <td>-</td>
                <td>-</td>
                <td>${item.location_name || '-'}</td>
                <td>-</td>
                <td>-</td>
                <td><span class="badge-status badge-danger"><i class="fas fa-ban"></i> Blocked</span></td>
                <td class="actions" title="${reasons}">
                    <span class="text-danger" style="font-size:12px;cursor:help;" title="${reasons}"><i class="fas fa-info-circle"></i> ${reasons}</span>
                </td>
            </tr>`;
        });
        tbody.insertAdjacentHTML('beforeend', sepRow + blockedRows.join(''));
    } catch (e) {
        // Silently fail - blocked info is supplementary
        console.warn('Could not load blocked equipment:', e);
    }
}

function renderLogsTable(logs) {
    const tbody = document.getElementById('logs-table-body');
    if (!tbody) return;
    if (!logs.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">No logs found</td></tr>';
        return;
    }
    const actionBadge = (action) => {
        const key = String(action || '').toLowerCase();
        if (key.includes('delete')) return 'badge-danger';
        if (key.includes('create')) return 'badge-success';
        if (key.includes('update')) return 'badge-warning';
        return 'badge-info';
    };
    tbody.innerHTML = logs.map(log => {
        const userDisplay = log.user_name || log.user_email || (log.user_id ? `User #${log.user_id.slice(0,8)}` : '-');
        const resourceDisplay = log.resource_name
            ? `<span title="${log.resource_id || ''}">${log.resource_name}</span>`
            : (log.resource_id ? `<span class="text-muted" title="${log.resource_id}">${log.resource_id.slice(0,8)}…</span>` : '-');
        return `
        <tr>
            <td>${log.created_at ? new Date(log.created_at).toLocaleString() : '-'}</td>
            <td><span class="badge ${actionBadge(log.action)}">${log.action || '-'}</span></td>
            <td>${log.resource_type || '-'}</td>
            <td title="${log.user_email || ''}">${userDisplay}</td>
            <td>${resourceDisplay}</td>
        </tr>
    `}).join('');
}

function renderUsersTable(users) {
    const tbody = document.getElementById('users-table-body');
    if (!tbody) return;
    if (users.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted">No users found</td></tr>';
        return;
    }
    const perms = getUserPermissions();
    // Build a location name lookup
    const locationMap = {};
    (locations || []).forEach(loc => { locationMap[loc.id] = loc.name; });

    tbody.innerHTML = users.map(user => {
        const roleBadge = ROLE_BADGES[user.role] || 'badge-secondary';
        const roleLabel = ROLE_LABELS[user.role] || user.role;
        const locNames = (user.assigned_location_ids || []).map(id => locationMap[id] || id).join(', ') || '<span class="text-muted">All / None</span>';
        let actionsHtml = (
            perms.isAdmin || (perms.isHOManager && user.role === 'location_manager')
        ) ? `<button class="btn-icon" onclick="editUser('${user.id}')" title="Edit"><i class="fas fa-edit"></i></button>` : '';
        if ((perms.isAdmin || perms.isHOManager) && user.is_active) actionsHtml += `<button class="btn-icon" onclick="deactivateUser('${user.id}')" title="Deactivate"><i class="fas fa-ban"></i></button>`;
        if (perms.isAdmin) actionsHtml += `<button class="btn-icon text-danger" onclick="permanentlyDeleteUser('${user.id}')" title="Permanent Delete"><i class="fas fa-trash"></i></button>`;
        return `<tr>
            <td><strong>${user.name}</strong></td>
            <td>${user.email}</td>
            <td><span class="badge ${roleBadge}">${roleLabel}</span></td>
            <td>${locNames}</td>
            <td>${user.is_active ? '<span class="badge badge-success">Active</span>' : '<span class="badge badge-danger">Inactive</span>'}</td>
            <td class="actions">${actionsHtml}</td>
        </tr>`;
    }).join('');
}

async function deactivateProduct(assetId) {
    if (!confirm('Deactivate this product? It will be marked Retired.')) return;
    try {
        await AssetsAPI.delete(assetId);
        showToast('Product deactivated', 'success');
        await loadItems();
    } catch (error) { showToast(error.message || 'Failed to deactivate product', 'error'); }
}

async function permanentlyDeleteProduct(assetId) {
    if (!confirm('Permanently delete this product? This action cannot be undone. If business history exists, deletion will be blocked and the related records will be listed.')) return;
    try {
        await AssetsAPI.permanentDelete(assetId);
        showToast('Product permanently deleted', 'success');
        await loadItems();
    } catch (error) { showToast(error.message || 'Failed to permanently delete product', 'error'); }
}

async function deactivateUser(id) {
    if (!confirm('Deactivate this user?')) return;
    try {
        await UsersAPI.delete(id);
        showToast('User deactivated', 'success');
        await loadUsers();
    } catch (error) { showToast(error.message || 'Failed to deactivate user', 'error'); }
}

async function permanentlyDeleteUser(id) {
    if (!confirm('Permanently delete this user? This action cannot be undone.')) return;
    try {
        await UsersAPI.permanentDelete(id);
        users = users.filter(user => user.id !== id);
        renderUsersTable(users);
        showToast('User permanently deleted', 'success');
        await loadUsers();
    } catch (error) {
        const message = error.message || 'Failed to permanently delete user';
        if (!message.includes('referenced by')) {
            showToast(message, 'error');
            return;
        }
        const warning = `${message}\n\nDelete this user and all records owned by them anyway? Requested transfers and their lines, purchase indents and their lines, inventory transactions, uploaded attachments, personnel records, and personal notifications may be deleted. Nullable approvals, assignments, job attribution, generated documents, calibration, and maintenance attribution will be detached. Audit logs will remain. This action cannot be undone.`;
        if (!confirm(warning)) return;
        try {
            await UsersAPI.permanentDelete(id, true);
            users = users.filter(user => user.id !== id);
            renderUsersTable(users);
            showToast('User and owned dependent records permanently deleted', 'success');
            await loadUsers();
        } catch (forceError) {
            showToast(forceError.message || 'Failed to permanently delete user', 'error');
        }
    }
}

function renderEmployeeRecordsTable(records) {
    const tbody = document.getElementById('employee-records-table-body');
    if (!tbody) return;
    if (!records.length) {
        tbody.innerHTML = '<tr><td colspan="10" class="text-center text-muted">No employee records found</td></tr>';
        return;
    }
    const perms = getUserPermissions();
    tbody.innerHTML = records.map(record => {
        const statusBadge = record.is_active ? 'badge-success' : 'badge-secondary';
        const statusLabel = record.is_active ? 'Active' : 'Inactive';
        const method = getEmployeeRecordMethod(record);
        const actionsHtml = perms.canManage ? `
                <button class="btn-icon" onclick="editEmployeeRecord('${record.id}')" title="Edit"><i class="fas fa-edit"></i></button>
                ${perms.isAdmin ? `<button class="btn-icon text-danger" onclick="deleteEmployeeRecord('${record.id}')" title="Permanent Delete"><i class="fas fa-trash"></i></button>` : ''}
            ` : '';
        return `<tr>
            <td><strong>${record.employee_name || record.user_name || '-'}</strong></td>
            <td>${record.user_location || '-'}</td>
            <td>${method || '-'}</td>
            <td>${record.title || '-'}</td>
            <td>${record.certificate_number || '-'}</td>
            <td>${record.issuer || '-'}</td>
            <td>${record.issue_date ? new Date(record.issue_date).toLocaleDateString() : '-'}</td>
            <td>${record.expiry_date ? new Date(record.expiry_date).toLocaleDateString() : '-'}</td>
            <td><span class="badge ${statusBadge}">${statusLabel}</span></td>
            <td class="actions">${actionsHtml}</td>
        </tr>`;
    }).join('');
}

// Product Detail Modal
async function showProductDetail(itemId) {
    try {
        const item = await ItemsAPI.getById(itemId);
        const perms = getUserPermissions();
        const stockInfo = productStockMap[itemId] || { qty: 0, locations: [] };
        const serialTracked = isSerialTrackedRecord(item);
        
        const stockRows = stockInfo.locations.length > 0 
            ? stockInfo.locations.map(loc => `
                <tr>
                    <td>${loc.name}</td>
                    <td class="text-right"><strong>${loc.qty}</strong></td>
                    <td class="text-right">${loc.reserved}</td>
                    <td class="text-right">${loc.qty - loc.reserved}</td>
                </tr>
            `).join('')
            : '<tr><td colspan="4" class="text-center text-muted">No stock records</td></tr>';
        
        openModal('Product Details', `
            <div class="product-detail">
                <div class="product-detail-header">
                    <div>
                        <h3 style="margin:0">${item.name}</h3>
                        <span class="text-muted">${item.id_number ? 'ID: ' + item.id_number + ' · ' : ''}Batch: ${item.sku || '-'}</span>
                    </div>
                    <div style="display:flex;gap:6px;flex-wrap:wrap">
                        ${serialTracked ? '<span class="badge badge-info">Serial Number Tracked</span>' : '<span class="badge badge-secondary">Quantity Based</span>'}
                        ${item.requires_calibration ? '<span class="badge badge-warning">Requires Calibration</span>' : ''}
                        ${item.is_active ? '<span class="badge badge-success">Active</span>' : '<span class="badge badge-danger">Inactive</span>'}
                    </div>
                </div>
                
                <div class="product-detail-grid">
                    <div class="detail-item">
                        <span class="detail-label"><i class="fas fa-industry"></i> Make</span>
                        <span class="detail-value">${item.manufacturer || '-'}</span>
                    </div>
                    <div class="detail-item">
                        <span class="detail-label"><i class="fas fa-folder"></i> Category</span>
                        <span class="detail-value">${item.category_name || '-'}</span>
                    </div>
                    <div class="detail-item">
                        <span class="detail-label"><i class="fas fa-ruler"></i> Unit</span>
                        <span class="detail-value">${item.unit_of_measure || 'EA'}</span>
                    </div>
                    <div class="detail-item">
                        <span class="detail-label"><i class="fas fa-cubes"></i> Quantity</span>
                        <span class="detail-value"><strong>${serialTracked ? '1 per serial number' : stockInfo.qty}</strong></span>
                    </div>
                </div>
                
                ${item.description ? `<div style="margin:16px 0;padding:12px;background:#f8f9fa;border-radius:8px;font-size:13px;color:#555">${item.description}</div>` : ''}
                
                ${serialTracked ? '' : `<h4 style="margin:16px 0 8px;font-size:14px;color:#555"><i class="fas fa-warehouse"></i> Stock by Location</h4>
                <table class="data-table" style="font-size:13px">
                    <thead>
                        <tr>
                            <th>Location</th>
                            <th class="text-right">On Hand</th>
                            <th class="text-right">Reserved</th>
                            <th class="text-right">Available</th>
                        </tr>
                    </thead>
                    <tbody>${stockRows}</tbody>
                </table>`}
                
                <div class="product-detail-actions">
                    ${perms.canManage ? `<button class="btn btn-primary btn-sm" onclick="editItem('${item.id}')">
                        <i class="fas fa-edit"></i> Edit
                    </button>` : ''}
                    ${(perms.isAdmin || perms.isHOManager || perms.isLocationManager) && item.is_active ? `<button class="btn btn-outline btn-sm" onclick="deleteItem('${item.id}')"><i class="fas fa-ban"></i> Deactivate</button>` : ''}
                    ${perms.isAdmin ? `<button class="btn btn-danger btn-sm" onclick="permanentlyDeleteItem('${item.id}')"><i class="fas fa-trash"></i> Permanent Delete</button>` : ''}
                    ${serialTracked ? '' : `<button class="btn btn-outline btn-sm" onclick="showProductStock('${item.id}', '${item.name.replace(/'/g, "\\'")}')">
                        <i class="fas fa-boxes"></i> Stock Details
                    </button>`}
                    <button class="btn btn-outline btn-sm" onclick="quickTransferProduct('${item.id}')">
                        <i class="fas fa-exchange-alt"></i> Transfer
                    </button>
                    ${serialTracked ? '' : `<button class="btn btn-outline btn-sm" onclick="goToStockForProduct('${item.id}', '${item.name.replace(/'/g, "\\'")}')">
                        <i class="fas fa-chart-bar"></i> Stock Levels
                    </button>`}
                </div>
            </div>
        `, 'modal-lg');
    } catch (error) {
        showToast('Error loading product details: ' + error.message, 'error');
    }
}

// Product Stock Detail Modal
async function showProductStock(itemId, itemName) {
    try {
        const product = allProducts.find(p => p.id === itemId);
        if (product && isSerialTrackedRecord(product)) {
            showToast('Serial-number tracked products are managed in Products, not Stock Levels.', 'info');
            return;
        }
        const stockData = await StockAPI.getAll({ page_size: 500 });
        const stocks = Array.isArray(stockData) ? stockData : (stockData.items || []);
        const itemStocks = stocks.filter(s => s.item_id === itemId);
        
        const totalQty = itemStocks.reduce((sum, s) => sum + (s.quantity_on_hand || 0), 0);
        const totalReserved = itemStocks.reduce((sum, s) => sum + (s.quantity_reserved || 0), 0);
        
        const stockRows = itemStocks.length > 0 
            ? itemStocks.map(s => `
                <tr class="${s.is_low_stock ? 'low-stock-row' : ''}">
                    <td><strong>${s.location_name || 'Unknown'}</strong></td>
                    <td class="text-right">${s.quantity_on_hand || 0}</td>
                    <td class="text-right">${s.quantity_reserved || 0}</td>
                    <td class="text-right">${(s.quantity_on_hand || 0) - (s.quantity_reserved || 0)}</td>
                    <td class="text-right">${s.reorder_point || '-'}</td>
                    <td>
                        ${s.is_low_stock ? '<span class="badge badge-warning badge-sm">Low</span>' : '<span class="badge badge-success badge-sm">OK</span>'}
                    </td>
                </tr>
            `).join('')
            : '<tr><td colspan="6" class="text-center text-muted">No stock at any location</td></tr>';
        
        openModal(`Stock: ${itemName}`, `
            <div class="stock-summary-bar">
                <div class="stock-stat">
                    <span class="stock-stat-num">${totalQty}</span>
                    <span class="stock-stat-label">On Hand</span>
                </div>
                <div class="stock-stat">
                    <span class="stock-stat-num">${totalReserved}</span>
                    <span class="stock-stat-label">Reserved</span>
                </div>
                <div class="stock-stat">
                    <span class="stock-stat-num">${totalQty - totalReserved}</span>
                    <span class="stock-stat-label">Available</span>
                </div>
                <div class="stock-stat">
                    <span class="stock-stat-num">${itemStocks.length}</span>
                    <span class="stock-stat-label">Locations</span>
                </div>
            </div>
            <table class="data-table" style="font-size:13px;margin-top:12px">
                <thead>
                    <tr>
                        <th>Location</th>
                        <th class="text-right">On Hand</th>
                        <th class="text-right">Reserved</th>
                        <th class="text-right">Available</th>
                        <th class="text-right">Reorder Pt</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>${stockRows}</tbody>
            </table>
            <div style="margin-top:16px;display:flex;gap:8px;justify-content:flex-end">
                <button class="btn btn-outline btn-sm" onclick="goToStockForProduct('${itemId}', '${itemName.replace(/'/g, "\\'")}')"> 
                    <i class="fas fa-chart-bar"></i> Go to Stock Levels
                </button>
                <button class="btn btn-primary btn-sm" onclick="quickTransferProduct('${itemId}')">
                    <i class="fas fa-exchange-alt"></i> Transfer
                </button>
            </div>
        `);
    } catch (error) {
        showToast('Error loading stock: ' + error.message, 'error');
    }
}

// Quick Transfer from Products page
async function quickTransferProduct(itemId) {
    // Navigate to transfers and trigger create modal
    closeModal();
    navigateTo('transfers');
    // Small delay to let the page render, then open modal
    setTimeout(() => {
        if (typeof showCreateTransferModal === 'function') {
            showCreateTransferModal(itemId);
        }
    }, 300);
}

// Show Low Stock Details Modal
async function showLowStockDetails() {
    try {
        const items = await DashboardAPI.getLowStockItems(100);
        
        if (!Array.isArray(items) || items.length === 0) {
            showToast('No low stock items found', 'info');
            return;
        }
        
        // Group by category
        const byCategory = {};
        items.forEach(item => {
            const cat = item.category_name || 'Uncategorized';
            if (!byCategory[cat]) byCategory[cat] = [];
            byCategory[cat].push(item);
        });
        
        const categoryBadges = Object.entries(byCategory).map(([cat, list]) => 
            `<span class="badge badge-secondary" style="margin-right:4px;">${cat}: ${list.length}</span>`
        ).join('');
        
        const tableRows = items.map(item => `
            <tr>
                <td><strong>${item.sku || '-'}</strong></td>
                <td>${item.name || 'Unknown Item'}</td>
                <td>${item.category_name || '-'}</td>
                <td>${item.location_name || 'Unknown Location'}</td>
                <td class="text-danger"><strong>${item.current_quantity}</strong></td>
                <td>${item.reorder_point || 0}</td>
                <td>${item.reorder_point - item.current_quantity || 0}</td>
                <td>
                    <button class="btn btn-sm btn-primary" onclick="closeModal(); adjustStockForItem('${item.item_id}', '${item.location_id}', '${item.sku || ''}')">
                        <i class="fas fa-plus"></i> Adjust
                    </button>
                </td>
            </tr>
        `).join('');
        
        openModal('Low Stock Items - Complete Details', `
            <div class="low-stock-details-modal">
                <div class="alert alert-warning" style="margin-bottom: 15px;">
                    <i class="fas fa-exclamation-triangle"></i>
                    <strong>${items.length} item(s)</strong> are below their reorder point and need attention.
                    <div style="margin-top:6px;">${categoryBadges}</div>
                </div>
                <div class="table-responsive">
                    <table class="data-table">
                        <thead>
                            <tr>
                                <th>ID No</th>
                                <th>Item Name</th>
                                <th>Category</th>
                                <th>Location</th>
                                <th>Current Qty</th>
                                <th>Reorder Point</th>
                                <th>Shortage</th>
                                <th>Action</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${tableRows}
                        </tbody>
                    </table>
                </div>
                <div class="modal-footer" style="margin-top: 15px;">
                    <button type="button" class="btn btn-outline" onclick="closeModal()">Close</button>
                </div>
            </div>
        `, 'modal-lg');
    } catch (error) {
        console.error('Error loading low stock details:', error);
        showToast('Error loading low stock details', 'error');
    }
}

// Show serialized equipment/instrument detail popup
async function showAssetsDetails() {
    try {
        const data = await AssetsAPI.getAll({ page_size: 500 });
        const assets = Array.isArray(data) ? data : (data.items || []);

        if (assets.length === 0) {
            showToast('No equipment or instruments found', 'info');
            return;
        }

        const statusBadge = (s) => {
            const colors = { in_service: 'success', out_of_service: 'danger', in_calibration: 'warning', retired: 'secondary' };
            return `<span class="badge badge-${colors[s] || 'secondary'}">${(s || '').replace(/_/g, ' ')}</span>`;
        };
        const calBadge = (s) => {
            const colors = { valid: 'success', due_soon: 'warning', expired: 'danger', not_required: 'secondary' };
            return `<span class="badge badge-${colors[s] || 'secondary'}">${(s || '').replace(/_/g, ' ')}</span>`;
        };

        const tableRows = assets.map(a => `
            <tr>
                <td><strong>${a.serial_number || '-'}</strong></td>
                <td>${a.item_name || a.item_sku || '-'}</td>
                <td>${a.location_name || '-'}</td>
                <td>${statusBadge(a.status)}</td>
                <td>${calBadge(a.calibration_status)}</td>
                <td>${a.next_calibration_due || '-'}</td>
            </tr>
        `).join('');

        openModal('Equipment / Instruments - Complete Details', `
            <div>
                <div class="alert alert-info" style="margin-bottom: 15px;">
                    <i class="fas fa-tools"></i>
                    <strong>${assets.length} serialized product(s)</strong> registered in the system.
                </div>
                <div class="table-responsive">
                    <table class="data-table">
                        <thead>
                            <tr>
                                <th>Serial No.</th>
                                <th>Item Name</th>
                                <th>Location</th>
                                <th>Status</th>
                                <th>Calibration</th>
                                <th>Next Cal. Due</th>
                            </tr>
                        </thead>
                        <tbody>${tableRows}</tbody>
                    </table>
                </div>
                <div class="modal-footer" style="margin-top: 15px;">
                    <button type="button" class="btn btn-outline" onclick="closeModal()">Close</button>
                </div>
            </div>
        `, 'modal-lg');
    } catch (error) {
        console.error('Error loading equipment/instrument details:', error);
        showToast('Error loading equipment/instrument details', 'error');
    }
}

// Show locations detail popup
async function showLocationsDetails() {
    try {
        const data = await LocationsAPI.getAll({ page_size: 500 });
        const locations = Array.isArray(data) ? data : (data.items || []);

        if (locations.length === 0) {
            showToast('No locations found', 'info');
            return;
        }

        const tableRows = locations.map(loc => `
            <tr>
                <td><strong>${loc.code || '-'}</strong></td>
                <td>${loc.name || '-'}</td>
                <td>${loc.city || '-'}</td>
                <td>${loc.contact_person || '-'}</td>
                <td>${loc.phone || '-'}</td>
                <td>${loc.is_active ? '<span class="badge badge-success">Active</span>' : '<span class="badge badge-danger">Inactive</span>'}</td>
            </tr>
        `).join('');

        openModal('All Locations - Complete Details', `
            <div>
                <div class="alert alert-info" style="margin-bottom: 15px;">
                    <i class="fas fa-map-marker-alt"></i>
                    <strong>${locations.length} location(s)</strong> configured in the system.
                </div>
                <div class="table-responsive">
                    <table class="data-table">
                        <thead>
                            <tr>
                                <th>Code</th>
                                <th>Name</th>
                                <th>City</th>
                                <th>Contact Person</th>
                                <th>Phone</th>
                                <th>Status</th>
                            </tr>
                        </thead>
                        <tbody>${tableRows}</tbody>
                    </table>
                </div>
                <div class="modal-footer" style="margin-top: 15px;">
                    <button type="button" class="btn btn-outline" onclick="closeModal()">Close</button>
                </div>
            </div>
        `, 'modal-lg');
    } catch (error) {
        console.error('Error loading locations details:', error);
        showToast('Error loading locations details', 'error');
    }
}

// Show calibration alerts detail popup
async function showCalibrationDetails() {
    try {
        const alerts = await DashboardAPI.getCalibrationAlerts(15);

        if (!Array.isArray(alerts) || alerts.length === 0) {
            showToast('No calibration alerts found', 'info');
            return;
        }

        const statusBadge = (s) => {
            if (s === 'expired') return '<span class="badge badge-danger">Expired</span>';
            if (s === 'due_soon') return '<span class="badge badge-warning">Due Soon</span>';
            return `<span class="badge badge-secondary">${s || '-'}</span>`;
        };

        const tableRows = alerts.map(a => `
            <tr>
                <td><strong>${a.serial_number || '-'}</strong></td>
                <td>${a.asset_name || '-'}</td>
                <td>${a.location_name || '-'}</td>
                <td>${a.last_calibration || '-'}</td>
                <td>${a.due_date || '-'}</td>
                <td>${a.days_until_due != null ? a.days_until_due : '-'}</td>
                <td>${statusBadge(a.status)}</td>
            </tr>
        `).join('');

        openModal('Calibration Alerts - Complete Details', `
            <div>
                <div class="alert alert-warning" style="margin-bottom: 15px;">
                    <i class="fas fa-certificate"></i>
                    <strong>${alerts.length} instrument(s)</strong> require calibration attention.
                </div>
                <div class="table-responsive">
                    <table class="data-table">
                        <thead>
                            <tr>
                                <th>Serial No.</th>
                                <th>Instrument Name</th>
                                <th>Location</th>
                                <th>Last Calibration</th>
                                <th>Due Date</th>
                                <th>Days Until Due</th>
                                <th>Status</th>
                            </tr>
                        </thead>
                        <tbody>${tableRows}</tbody>
                    </table>
                </div>
                <div class="modal-footer" style="margin-top: 15px;">
                    <button type="button" class="btn btn-outline" onclick="closeModal()">Close</button>
                </div>
            </div>
        `, 'modal-lg');
    } catch (error) {
        console.error('Error loading calibration details:', error);
        showToast('Error loading calibration details', 'error');
    }
}

// Show jobs detail popup
async function showJobsDetails() {
    try {
        const data = await JobsAPI.getAll({ limit: 50 });
        const jobs = Array.isArray(data) ? data : (data.items || data.jobs || []);

        if (jobs.length === 0) {
            showToast('No jobs found', 'info');
            return;
        }

        const statusBadge = (s) => {
            const colors = { hold: 'warning', in_progress: 'primary', completed: 'success', verified: 'info' };
            return `<span class="badge badge-${colors[s] || 'secondary'}">${(s || '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}</span>`;
        };

        const tableRows = jobs.map(job => `
            <tr>
                <td>${job.job_number || '-'}</td>
                <td>${job.job_date ? new Date(job.job_date).toLocaleDateString() : '-'}</td>
                <td>${job.customer || '-'}</td>
                <td>${job.job_name || '-'}</td>
                <td>${(job.method || '').toUpperCase()}</td>
                <td>${job.quantity != null ? job.quantity : '-'}</td>
                <td>${job.coverage || '-'}</td>
                <td>${job.total != null ? job.total : '-'}</td>
                <td>${job.person_name || '-'}</td>
                <td>${statusBadge(job.status)}</td>
            </tr>
        `).join('');

        openModal('Jobs (Hold) - Complete Details', `
            <div>
                <div class="alert alert-info" style="margin-bottom: 15px;">
                    <i class="fas fa-clipboard-list"></i>
                    <strong>${jobs.length} job(s)</strong> recorded in the system.
                </div>
                <div class="table-responsive">
                    <table class="data-table">
                        <thead>
                            <tr>
                                <th>Job #</th>
                                <th>Date</th>
                                <th>Customer</th>
                                <th>Job</th>
                                <th>Method</th>
                                <th>Qty</th>
                                <th>Coverage</th>
                                <th>Total</th>
                                <th>Person</th>
                                <th>Status</th>
                            </tr>
                        </thead>
                        <tbody>${tableRows}</tbody>
                    </table>
                </div>
                <div class="modal-footer" style="margin-top: 15px;">
                    <button type="button" class="btn btn-outline" onclick="closeModal()">Close</button>
                </div>
            </div>
        `, 'modal-lg');
    } catch (error) {
        console.error('Error loading jobs details:', error);
        showToast('Error loading jobs details', 'error');
    }
}

// Adjust stock for a specific item (called from low stock modal)
function adjustStockForItem(itemId, locationId, itemSku) {
    // Load items and locations for the modal
    Promise.all([
        ItemsAPI.getAllPages(),
        LocationsAPI.getAll({ is_active: true })
    ]).then(([itemData, locData]) => {
        const items = (Array.isArray(itemData) ? itemData : (itemData.items || []))
            .filter(item => isQuantityTrackedRecord(item) && ['consumable', 'accessory'].includes(quantityTypeKeyForRecord(item)));
        const locs = activeRecords(Array.isArray(locData) ? locData : (locData.items || []));

        if (items.length === 0) {
            showToast('No quantity-based products are available for stock return.', 'warning');
            return;
        }
        
        const matchedItem = items.find(i => i.id === itemId);
        const displayName = matchedItem ? (matchedItem.id_number ? matchedItem.id_number + ' - ' : '') + matchedItem.name : itemSku;
        const itemOptions = items.map(i => `<option value="${i.id}" ${i.id === itemId ? 'selected' : ''}>${i.id_number ? i.id_number + ' - ' : ''}${i.name}</option>`).join('');
        const locOptions = locs.map(l => `<option value="${l.id}" ${l.id === locationId ? 'selected' : ''}>${l.name}</option>`).join('');
        
        openModal(`Adjust Stock — ${displayName}`, `
            <form id="adjust-stock-form">
                <div class="form-row">
                    <div class="form-group">
                        <label>Type *</label>
                        <select name="item_id" required>
                            <option value="">Select consumable/accessory</option>
                            ${itemOptions}
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Location *</label>
                        <select name="location_id" required>
                            <option value="">Select location</option>
                            ${locOptions}
                        </select>
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Quantity Change *</label>
                        <input type="number" name="quantity_change" required placeholder="e.g., 10 or -5">
                        <small class="form-help">Enter the correction difference only. Positive adds, negative deducts.</small>
                    </div>
                    <div class="form-group">
                        <label>Reason *</label>
                        <select name="reason" required>
                            ${buildStockAdjustmentReasonOptions('Physical Count Excess')}
                        </select>
                    </div>
                </div>
                <div class="form-group">
                    <label>Notes</label>
                    <textarea name="notes" rows="2" placeholder="Audit note, count sheet ref, approval ref, or explanation"></textarea>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-outline" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary"><i class="fas fa-check"></i> Submit Adjustment</button>
                </div>
            </form>
        `);
        
        document.getElementById('adjust-stock-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            await withSubmitLock(e.target, async () => {
                const formData = new FormData(e.target);
                const data = {
                    item_id: formData.get('item_id'),
                    location_id: formData.get('location_id'),
                    quantity_change: parseInt(formData.get('quantity_change')),
                    reason: formData.get('reason'),
                    notes: formData.get('notes') || null
                };
                try {
                    await StockAPI.adjust(data);
                    closeModal();
                    showToast('Stock adjusted successfully', 'success');
                    if (currentPage === 'stock') {
                        await loadStock();
                    } else if (currentPage === 'dashboard') {
                        await loadDashboard();
                    }
                    await refreshDashboardAsync();
                } catch (error) {
                    showToast(error.message, 'error');
                }
            });
        });
    }).catch(error => {
        showToast('Error loading data: ' + error.message, 'error');
    });
}

async function showAddItemModal() {
    // Load categories and locations first
    try {
        const [catData, locData] = await Promise.all([
            CategoriesAPI.getAll(),
            LocationsAPI.getAll({ is_active: true })
        ]);
        categories = Array.isArray(catData) ? catData : (catData.items || []);
        locations = Array.isArray(locData) ? locData : (locData.items || []);
    } catch (e) {
        categories = [];
        locations = [];
    }
    
    const serialCategories = categories.filter(c =>
        c.is_active !== false &&
        (c.stock_behavior || '').toLowerCase() === 'serialized'
    );
    const locationOptions = locations.map(l => `<option value="${l.id}">${escapeHtml(l.name)}</option>`).join('');
    if (locations.length === 0) {
        showToast('No active locations are available for product assignment.', 'warning');
        return;
    }
    if (serialCategories.length === 0) {
        showToast('No Equipment or Instrument types are available for Products.', 'warning');
        return;
    }
    
    openModal('Add New Product', `
        <form id="add-item-form">
            <div class="form-row">
                <div class="form-group">
                    <label>Type *</label>
                    <select name="category_id" required>
                        <option value="">Select type</option>
                        ${serialCategories.map(c => `<option value="${c.id}" data-type-key="${c.category_type_key || c.name || ''}">${escapeHtml(c.name)}</option>`).join('')}
                    </select>
                </div>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label id="product-name-label">Equipment / Instrument Name *</label>
                    <input type="text" name="name" required placeholder="Equipment or instrument name">
                </div>
                <div class="form-group">
                    <label id="product-id-label">Product Code / ID Number</label>
                    <input type="text" name="id_number" placeholder="Optional internal or supplier code">
                </div>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label>Make</label>
                    <input type="text" name="manufacturer" placeholder="Brand / Manufacturer">
                </div>
                <div class="form-group">
                    <label id="product-model-label">Model / Model Number</label>
                    <input type="text" name="model" placeholder="Model or model number">
                </div>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label id="product-serial-label">Serial Number *</label>
                    <input type="text" name="serial_number" required placeholder="Unique serial number">
                </div>
                <div class="form-group">
                    <label>Quantity</label>
                    <input type="text" value="1" disabled>
                    <small class="form-help">Serialized products are always one item per serial/ID.</small>
                </div>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label>Location *</label>
                    <select name="location_id" required>
                        <option value="">Select location</option>
                        ${locationOptions}
                    </select>
                </div>
                <div class="form-group">
                    <label>Acquired Date *</label>
                    <input type="date" name="acquired_at" required value="${localDateInputValue()}">
                </div>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label>Supplier Name</label>
                    <input type="text" name="supplier_name" placeholder="Supplier name for purchase register">
                </div>
                <div class="form-group">
                    <label>Invoice No</label>
                    <input type="text" name="invoice_number" placeholder="Invoice number">
                </div>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label>Purchase Order</label>
                    <input type="text" name="purchase_order" placeholder="PO number">
                </div>
                <div class="form-group">
                    <label>Cost (₹)</label>
                    <input type="number" name="cost" min="0" step="0.01" placeholder="Purchase cost">
                </div>
            </div>
            <div class="form-group">
                <label>Description</label>
                <textarea name="description" rows="2" placeholder="Product description"></textarea>
            </div>
            <div id="add-product-calibration-fields" style="display:none">
                <div class="form-row">
                    <div class="form-group">
                        <label>Calibration Date</label>
                        <input type="date" name="calibration_date" max="${localDateInputValue()}">
                    </div>
                    <div class="form-group">
                        <label>Calibration Due Date</label>
                        <input type="date" name="calibration_due_date">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Supplier Name</label>
                        <input type="text" name="calibration_supplier" placeholder="Supplier / calibration lab">
                    </div>
                    <div class="form-group">
                        <label>Certificate Number</label>
                        <input type="text" name="calibration_certificate" placeholder="Calibration certificate no.">
                    </div>
                </div>
            </div>
            <div class="modal-footer">
                <button type="button" class="btn btn-outline" onclick="closeModal()">Cancel</button>
                <button type="submit" class="btn btn-primary">Create Product</button>
            </div>
        </form>
    `);

    const addItemForm = document.getElementById('add-item-form');
    const typeSelect = addItemForm.querySelector('[name="category_id"]');
    const idInput = addItemForm.querySelector('[name="id_number"]');
    const serialInput = addItemForm.querySelector('[name="serial_number"]');
    const modelInput = addItemForm.querySelector('[name="model"]');
    const descriptionInput = addItemForm.querySelector('[name="description"]');
    const calibrationFields = document.getElementById('add-product-calibration-fields');
    const syncProductType = () => {
        const selectedCategory = categories.find(c => c.id === typeSelect.value);
        const type = productTypeForCategory(selectedCategory);
        const isInstrument = type === 'instrument';
        document.getElementById('product-name-label').textContent = isInstrument ? 'Instrument Name *' : 'Equipment Name *';
        document.getElementById('product-id-label').textContent = 'Product Code / ID Number';
        document.getElementById('product-model-label').textContent = isInstrument ? 'Model Number' : 'Model';
        document.getElementById('product-serial-label').textContent = isInstrument ? 'Serial Number *' : 'Serial Number *';
        idInput.required = false;
        modelInput.required = false;
        serialInput.required = true;
        descriptionInput.required = false;
        calibrationFields.style.display = isInstrument ? 'block' : 'none';
        calibrationFields.querySelectorAll('input[name="calibration_date"], input[name="calibration_due_date"]').forEach(input => {
            input.required = false;
        });
        if (!isInstrument) {
            calibrationFields.querySelectorAll('input').forEach(input => { input.value = ''; });
        }
    };
    typeSelect.addEventListener('change', syncProductType);
    syncProductType();
    
    addItemForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const submitButton = e.target.querySelector('button[type="submit"]');
        if (submitButton?.disabled) return;
        if (submitButton) submitButton.disabled = true;
        const formData = new FormData(e.target);
        
        const serialNumber = formData.get('serial_number') || '';
        const category = categories.find(c => c.id === formData.get('category_id'));
        const productType = productTypeForCategory(category);
        if (!productType) {
            showToast('Select a valid serialized type', 'error');
            if (submitButton) submitButton.disabled = false;
            return;
        }
        const serializedCategory = isSerializedCategory(formData.get('category_id'));
        if (!serializedCategory) {
            showToast('Products tab accepts only Equipment or Instrument categories.', 'error');
            if (submitButton) submitButton.disabled = false;
            return;
        }

        const calibrationDate = formData.get('calibration_date');
        const calibrationDueDate = formData.get('calibration_due_date');
        const calibrationSupplier = formData.get('calibration_supplier');
        const calibrationCertificate = formData.get('calibration_certificate');
        const hasAnyCalibrationDetail = Boolean(
            calibrationDate || calibrationDueDate || calibrationSupplier || calibrationCertificate
        );
        if (productType === 'instrument' && hasAnyCalibrationDetail && (!calibrationDate || !calibrationDueDate)) {
            showToast('Enter both calibration date and next due date, or leave all calibration details blank', 'error');
            if (submitButton) submitButton.disabled = false;
            return;
        }
        if (calibrationDate && calibrationDueDate && calibrationDueDate <= calibrationDate) {
            showToast('Calibration due date must be after the calibration date', 'error');
            if (submitButton) submitButton.disabled = false;
            return;
        }
        const data = {
            id_number: formData.get('id_number') || null,
            serial_number: serialNumber,
            name: formData.get('name'),
            description: formData.get('description') || null,
            category_id: formData.get('category_id'),
            location_id: formData.get('location_id'),
            acquired_at: formData.get('acquired_at'),
            manufacturer: formData.get('manufacturer') || null,
            model: formData.get('model') || null,
            supplier_name: formData.get('supplier_name') || null,
            invoice_number: formData.get('invoice_number') || null,
            purchase_order: formData.get('purchase_order') || null,
            cost: formData.get('cost') ? parseFloat(formData.get('cost')) : null,
            calibration: productType === 'instrument' && calibrationDate && calibrationDueDate
                ? {
                    certificate_number: calibrationCertificate || `CAL-${serialNumber}`,
                    performed_at: calibrationDate,
                    due_at: calibrationDueDate,
                    performed_by: calibrationSupplier || 'Supplier',
                    calibration_lab: calibrationSupplier || null,
                    result: 'pass',
                    notes: 'Initial calibration added during product creation'
                }
                : null
        };

        try {
            if (!await confirmProbableDuplicateProduct(data)) {
                if (submitButton) submitButton.disabled = false;
                return;
            }
            await AssetsAPI.createProduct(data);
            closeModal();
            await loadItems();
            switchProductTypeTab(productType);
            showToast('Product created successfully', 'success');
        } catch (error) {
            showToast(error.message, 'error');
            if (submitButton) submitButton.disabled = false;
        }
    });
}

async function editItem(id) {
    try {
        // Load categories and item data
        const [catData, item] = await Promise.all([
            CategoriesAPI.getAll(),
            ItemsAPI.getById(id)
        ]);
        categories = Array.isArray(catData) ? catData : (catData.items || []);
        
        const serialCategories = categories.filter(c => (c.stock_behavior || '').toLowerCase() === 'serialized' || c.id === item.category_id);
        const categoryOptions = serialCategories.map(c =>
            `<option value="${c.id}" data-behavior="${c.stock_behavior || ''}" data-type-key="${c.category_type_key || ''}" ${c.id === item.category_id ? 'selected' : ''}>${c.name}</option>`
        ).join('');
        
        openModal('Edit Product', `
            <form id="edit-item-form">
                <input type="hidden" name="id" value="${item.id}">
                <div class="form-row">
                    <div class="form-group">
                        <label>ID No</label>
                        <input type="text" name="id_number" value="${item.id_number || ''}" placeholder="e.g., PRD-001">
                    </div>
                    <div class="form-group">
                        <label>Equipment / Instrument Name *</label>
                        <input type="text" name="name" required value="${item.name}" placeholder="Equipment or instrument name">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Make</label>
                        <input type="text" name="manufacturer" value="${item.manufacturer || ''}" placeholder="Brand / Manufacturer">
                    </div>
                    <div class="form-group">
                        <label>Model / Model Number</label>
                        <input type="text" name="model" value="${item.model || ''}" placeholder="Model or model number">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Type *</label>
                        <select name="category_id" required>
                            <option value="">Select type</option>
                            ${categoryOptions}
                        </select>
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Serial Number *</label>
                        <input type="text" name="batch_no" required value="${item.sku || ''}" placeholder="Unique serial number">
                    </div>
                    <div class="form-group">
                        <label>Unit</label>
                        <input type="text" name="unit_of_measure" value="${item.unit_of_measure || 'EA'}" placeholder="EA, PCS, etc.">
                    </div>
                </div>
                <div class="form-group">
                    <label>Description</label>
                    <textarea name="description" rows="2" placeholder="Product description">${item.description || ''}</textarea>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>
                            <input type="checkbox" name="is_serialized" checked disabled> Serialized (tracked by serial number)
                        </label>
                    </div>
                    <div class="form-group">
                        <label>
                            <input type="checkbox" name="requires_calibration" ${item.requires_calibration ? 'checked' : ''}> Requires Calibration
                        </label>
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>
                            <input type="checkbox" name="is_active" ${item.is_active ? 'checked' : ''}> Active
                        </label>
                    </div>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-outline" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary">Update Product</button>
                </div>
            </form>
        `);

        const editForm = document.getElementById('edit-item-form');
        const categorySelect = editForm.querySelector('[name="category_id"]');
        const serializedInput = editForm.querySelector('[name="is_serialized"]');
        const syncEditCategoryMode = () => {
            const serialized = isSerializedCategory(categorySelect.value);
            if (serializedInput) {
                serializedInput.checked = serialized || serializedInput.checked;
                serializedInput.disabled = serialized;
            }
        };
        categorySelect.addEventListener('change', syncEditCategoryMode);
        syncEditCategoryMode();
        
        editForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const formData = new FormData(e.target);
            
            const batchNo = formData.get('batch_no') || '';
            if (!isSerializedCategory(formData.get('category_id'))) {
                showToast('Products tab accepts only serial-number tracked categories.', 'error');
                return;
            }
            const data = {
                id_number: formData.get('id_number') || null,
                sku: batchNo || undefined,
                name: formData.get('name'),
                description: formData.get('description') || null,
                category_id: formData.get('category_id'),
                unit_of_measure: formData.get('unit_of_measure') || 'EA',
                manufacturer: formData.get('manufacturer') || null,
                model: formData.get('model') || null,
                is_serialized: true,
                requires_calibration: formData.has('requires_calibration'),
                is_active: formData.has('is_active')
            };
            
            try {
                if (!await confirmProbableDuplicateProduct(data, id)) return;
                await ItemsAPI.update(id, data);
                closeModal();
                showToast('Product updated successfully', 'success');
                loadItems();
            } catch (error) {
                showToast(error.message, 'error');
            }
        });
    } catch (error) {
        showToast('Error loading product: ' + error.message, 'error');
    }
}

async function deleteItem(id) {
    if (confirm('Deactivate this product?')) {
        try {
            await ItemsAPI.delete(id);
            closeModal();
            showToast('Product deactivated successfully', 'success');
            loadItems();
        } catch (error) {
            showToast(error.message, 'error');
        }
    }
}

// Stock
async function loadStock() {
    try {
        currentStockTypeTab = currentStockTypeTab || 'consumable';
        syncStockTypeTabs();
        // Reset stock filter inputs before loading data.
        const stockSearchEl = document.getElementById('stock-search');
        if (stockSearchEl) stockSearchEl.value = '';
        const stockCatEl = document.getElementById('stock-category-filter');
        if (stockCatEl) stockCatEl.value = '';
        const stockStatusEl = document.getElementById('stock-status-filter');
        if (stockStatusEl) stockStatusEl.value = '';

        // Load reference data and stock rows in parallel; the stock summary endpoint is the slowest call.
        const stockDataPromise = loadStockData();
        const [locData, catData] = await Promise.all([
            LocationsAPI.getAll({ is_active: true }),
            CategoriesAPI.getAll(),
        ]);
        const locs = activeRecords(Array.isArray(locData) ? locData : (locData.items || []));
        locations = locs;
        categories = Array.isArray(catData) ? catData : (catData.items || []);
        
        // Populate location filter
        const locationFilter = document.getElementById('stock-location-filter');
        locationFilter.innerHTML = '<option value="">All Locations</option>' +
            locs.map(loc => `<option value="${loc.id}">${loc.name}</option>`).join('');

        await stockDataPromise;
        
        // Apply pending item filter if navigated from Products
        if (pendingStockItemFilter) {
            const filter = pendingStockItemFilter;
            pendingStockItemFilter = null;
            applyStockItemFilter(filter.itemId, filter.itemName);
        }
    } catch (error) {
        console.error('Stock load error:', error);
        document.getElementById('stock-table-body').innerHTML = 
            '<tr><td colspan="13" class="text-center text-muted">Error loading stock</td></tr>';
    }
}

function applyStockItemFilter(itemId, itemName) {
    const filtered = stockPaginationState.allItems.filter(s => s.item_id === itemId && isQuantityTrackedRecord(s));
    
    // Show filter banner
    let banner = document.getElementById('stock-item-filter-banner');
    if (!banner) {
        banner = document.createElement('div');
        banner.id = 'stock-item-filter-banner';
        banner.className = 'stock-filter-banner';
        const stockSection = document.getElementById('stock-section');
        const stockCard = stockSection.querySelector('.card');
        stockSection.insertBefore(banner, stockCard);
    }
    banner.innerHTML = `
        <i class="fas fa-filter"></i>
        Showing stock for: <strong>${itemName}</strong> (${filtered.length} record${filtered.length !== 1 ? 's' : ''})
        <button class="btn btn-sm btn-outline" onclick="clearStockItemFilter()" style="margin-left:auto">
            <i class="fas fa-times"></i> Clear Filter
        </button>
    `;
    banner.style.display = 'flex';
    
    // Update pagination with filtered items
    stockPaginationState.allItems = filtered;
    stockPaginationState.totalItems = filtered.length;
    stockPaginationState.totalPages = Math.ceil(filtered.length / stockPaginationState.itemsPerPage) || 1;
    stockPaginationState.currentPage = 1;
    renderStockPage();
}

function clearStockItemFilter() {
    const banner = document.getElementById('stock-item-filter-banner');
    if (banner) banner.style.display = 'none';
    loadStockData();
}

function goToStockForProduct(itemId, itemName) {
    closeModal();
    pendingStockItemFilter = { itemId, itemName };
    navigateTo('stock');
}

async function sendLowStockAlert() {
    try {
        showToast('Sending low stock alert email...', 'info');
        const result = await StockAPI.sendLowStockAlert();
        
        if (result.data && result.data.count === 0) {
            showToast('No low stock items found', 'info');
        } else if (result.data && result.data.error) {
            showToast('Failed to send email alert', 'error');
        } else {
            showToast(result.message || 'Low stock alert sent successfully', 'success');
        }
    } catch (error) {
        showToast('Error sending alert: ' + error.message, 'error');
    }
}

// Stock pagination state
let stockPaginationState = {
    currentPage: 1,
    itemsPerPage: 10,
    totalItems: 0,
    totalPages: 0,
    allItems: [],
    locationId: null
};

async function loadStockByLocation() {
    const locationId = document.getElementById('stock-location-filter').value;
    stockPaginationState.currentPage = 1;
    stockPaginationState.locationId = locationId;
    await loadStockData(locationId);
}

function goToStockPage(pageNum) {
    const page = Math.max(1, Math.min(parseInt(pageNum), stockPaginationState.totalPages));
    stockPaginationState.currentPage = page;
    renderStockPage();
}

function previousStockPage() {
    if (stockPaginationState.currentPage > 1) {
        stockPaginationState.currentPage--;
        document.getElementById('stock-page-input').value = stockPaginationState.currentPage;
        renderStockPage();
    }
}

function nextStockPage() {
    if (stockPaginationState.currentPage < stockPaginationState.totalPages) {
        stockPaginationState.currentPage++;
        document.getElementById('stock-page-input').value = stockPaginationState.currentPage;
        renderStockPage();
    }
}

function renderStockPage() {
    const start = (stockPaginationState.currentPage - 1) * stockPaginationState.itemsPerPage;
    const end = start + stockPaginationState.itemsPerPage;
    const pageItems = stockPaginationState.allItems.slice(start, end);
    
    const tbody = document.getElementById('stock-table-body');
    
    if (pageItems.length === 0) {
        const label = currentStockTypeTab === 'accessory' ? 'accessory' : 'consumable';
        tbody.innerHTML = `<tr><td colspan="13" class="text-center text-muted">No ${label} stock records found</td></tr>`;
        return;
    }
    
    const perms = getUserPermissions();
    const stockRows = pageItems.map(item => {
        const alertQty = item.reorder_point || 0;
        const itemNameArg = encodeURIComponent(item.name || '');
        const actionsHtml = item.stock_id
            ? `<div class="stock-row-actions">
                 <button class="stock-action-btn stock-action-view" onclick="showStockItemDetails('${item.stock_id}')" title="View complete stock details" aria-label="View complete stock details"><i class="fas fa-eye"></i></button>
                 ${perms.canManage ? `<button class="stock-action-btn stock-action-edit" onclick="showEditStockItemModal('${item.stock_id}')" title="Edit item and location" aria-label="Edit item and location"><i class="fas fa-edit"></i></button>` : ''}
                 ${perms.canManage ? `<button class="stock-action-btn stock-action-alert" onclick="showEditLowStockQtyModal('${item.stock_id}', decodeURIComponent('${itemNameArg}'), ${alertQty})" title="Edit low-stock alert" aria-label="Edit low-stock alert"><i class="fas fa-bell"></i></button>` : ''}
                 <button class="stock-action-btn stock-action-deactivate" onclick="deactivateStock('${item.stock_id}')" title="Deactivate stock record" aria-label="Deactivate stock record"><i class="fas fa-ban"></i></button>
                 ${perms.isAdmin ? `<button class="stock-action-btn stock-action-delete" onclick="permanentlyDeleteStock('${item.stock_id}')" title="Permanent Delete" aria-label="Permanently delete stock record"><i class="fas fa-trash-alt"></i></button>` : ''}
               </div>`
            : '-';
        return `
            <tr class="${item.is_low_stock ? 'low-stock-row' : ''}">
                <td>${formatDateValue(item.latest_activity_date || item.latest_received_date)}</td>
                <td>${escapeHtml(item.name || item.item_id)}${item.sku ? `<br><small class="text-muted">${escapeHtml(item.sku)}</small>` : ''}</td>
                <td>${escapeHtml(item.location_name || '-')}</td>
                <td class="text-right">${item.opening_balance || 0}</td>
                <td class="text-right text-success">${item.received_today > 0 ? '+' + item.received_today : '-'}</td>
                <td class="text-right text-danger">${item.issued_today > 0 ? '-' + item.issued_today : '-'}</td>
                <td class="text-right">${item.adjusted_today !== 0 ? (item.adjusted_today > 0 ? '+' : '') + item.adjusted_today : '-'}</td>
                <td class="text-right"><strong>${item.closing_balance || 0}</strong></td>
                <td class="text-right">${item.reserved || 0}</td>
                <td class="text-right">${item.available || 0}</td>
                <td class="text-right">${alertQty || '-'}</td>
                <td>${item.is_low_stock ? '<span class="badge badge-warning">Low Stock</span>' : '<span class="badge badge-success">OK</span>'}</td>
                <td>${actionsHtml}</td>
            </tr>
        `;
    }).join('');
    
    tbody.innerHTML = stockRows;
    
    // Update pagination info
    const pageInfo = `Showing ${start + 1} - ${Math.min(end, stockPaginationState.totalItems)} of ${stockPaginationState.totalItems}`;
    document.getElementById('stock-page-info').textContent = pageInfo;
    document.getElementById('stock-page-input').value = stockPaginationState.currentPage;
    document.getElementById('stock-total-pages').textContent = stockPaginationState.totalPages;
    
    // Update button states
    document.getElementById('stock-first-page').disabled = stockPaginationState.currentPage === 1;
    document.getElementById('stock-prev-page').disabled = stockPaginationState.currentPage === 1;
    document.getElementById('stock-next-page').disabled = stockPaginationState.currentPage === stockPaginationState.totalPages;
    document.getElementById('stock-last-page').disabled = stockPaginationState.currentPage === stockPaginationState.totalPages;
}

function showStockItemDetails(stockId) {
    const item = stockAllItemsUnfiltered.find(record => record.stock_id === stockId)
        || stockPaginationState.allItems.find(record => record.stock_id === stockId);
    if (!item) {
        showToast('Stock item details are no longer available. Refresh the page.', 'error');
        return;
    }

    const batches = Array.isArray(item.batches) ? item.batches : [];
    const batchRows = batches.length
        ? batches.map(batch => `
            <tr>
                <td>${escapeHtml(batch.lot_number || '-')}</td>
                <td class="text-right">${batch.quantity_on_hand ?? 0}</td>
                <td>${formatDateValue(batch.received_at)}</td>
                <td>${formatDateValue(batch.expiry_date)}</td>
                <td>${escapeHtml(batch.supplier || '-')}</td>
            </tr>
        `).join('')
        : '<tr><td colspan="5" class="text-center text-muted">No batch details recorded</td></tr>';

    const statusClass = item.is_low_stock ? 'is-low' : 'is-ok';
    const statusText = item.is_low_stock ? 'Low Stock' : 'Stock OK';
    openModal('Stock Item Details', `
        <div class="stock-detail-hero">
            <div class="stock-detail-identity">
                <div class="stock-detail-icon"><i class="fas fa-box"></i></div>
                <div>
                    <h3>${escapeHtml(item.name || 'Unnamed Item')}</h3>
                    <div class="stock-detail-meta">
                        <span class="stock-detail-code">${escapeHtml(item.sku || 'No product code')}</span>
                        <span><i class="fas fa-map-marker-alt"></i> ${escapeHtml(item.location_name || '-')}</span>
                        <span><i class="far fa-calendar-alt"></i> ${formatDateValue(item.latest_activity_date || item.latest_received_date)}</span>
                    </div>
                </div>
            </div>
            <span class="stock-detail-status ${statusClass}">${statusText}</span>
        </div>

        <section class="stock-detail-section">
            <h4><i class="fas fa-info-circle"></i> Product Information</h4>
            <div class="stock-detail-grid stock-detail-product-grid">
                <div><span>Category</span><strong>${escapeHtml(item.category_name || '-')}</strong></div>
                <div><span>Unit</span><strong>${escapeHtml(item.unit_of_measure || '-')}</strong></div>
                <div><span>Manufacturer</span><strong>${escapeHtml(item.manufacturer || '-')}</strong></div>
                <div><span>Model / Grade / Pack</span><strong>${escapeHtml(item.model || '-')}</strong></div>
            </div>
            ${item.description ? `<div class="stock-detail-description"><span>Description</span><p>${escapeHtml(item.description)}</p></div>` : ''}
        </section>

        <section class="stock-detail-section">
            <h4><i class="fas fa-chart-bar"></i> Stock Summary</h4>
            <div class="stock-metric-grid">
                <div><span>Opening</span><strong>${item.opening_balance ?? 0}</strong></div>
                <div class="metric-received"><span>Received</span><strong>+${item.received_today ?? 0}</strong></div>
                <div class="metric-issued"><span>Issued</span><strong>-${item.issued_today ?? 0}</strong></div>
                <div class="metric-adjusted"><span>Adjusted</span><strong>${(item.adjusted_today ?? 0) > 0 ? '+' : ''}${item.adjusted_today ?? 0}</strong></div>
                <div class="metric-closing"><span>Closing</span><strong>${item.closing_balance ?? 0}</strong></div>
                <div><span>Reserved</span><strong>${item.reserved ?? 0}</strong></div>
                <div class="metric-available"><span>Available</span><strong>${item.available ?? 0}</strong></div>
                <div><span>Alert At</span><strong>${item.reorder_point ?? 0}</strong></div>
            </div>
        </section>

        <section class="stock-detail-section">
        <h4><i class="fas fa-layer-group"></i> Batch / Lot Information</h4>
        <div class="table-container">
            <table class="data-table stock-detail-batches">
                <thead>
                    <tr><th>Batch No.</th><th>Qty</th><th>Received</th><th>Expiry</th><th>Supplier</th></tr>
                </thead>
                <tbody>${batchRows}</tbody>
            </table>
        </div>
        </section>
        <div class="modal-footer">
            <button type="button" class="btn btn-outline" onclick="closeModal()">Close</button>
        </div>
    `, 'modal-lg');
}

async function showEditStockItemModal(stockId) {
    const perms = getUserPermissions();
    if (!perms.canManage) {
        showToast('Only managers or Admin can edit stock item details', 'error');
        return;
    }

    try {
        const stockRow = stockAllItemsUnfiltered.find(record => record.stock_id === stockId)
            || stockPaginationState.allItems.find(record => record.stock_id === stockId);
        if (!stockRow) {
            showToast('Stock item is no longer available. Refresh the page.', 'error');
            return;
        }
        const [item, categoryData, locationData] = await Promise.all([
            ItemsAPI.getById(stockRow.item_id),
            CategoriesAPI.getAll(),
            LocationsAPI.getAll({ is_active: true })
        ]);
        const allCategories = Array.isArray(categoryData)
            ? categoryData
            : (categoryData.items || []);
        const quantityCategories = allCategories.filter(category =>
            category.is_active !== false &&
            (category.stock_behavior || '').toLowerCase() !== 'serialized'
        );
        const locations = Array.isArray(locationData)
            ? locationData
            : (locationData.items || []);

        openModal('Edit Stock Item', `
            <form id="edit-stock-item-form">
                <div class="alert alert-info" style="margin-bottom:15px;padding:10px 14px;background:rgba(37,99,235,.06);border-radius:8px;border-left:3px solid var(--primary-color);font-size:13px;color:var(--text-muted);">
                    <i class="fas fa-info-circle" style="color:var(--primary-color);margin-right:6px;"></i>
                    Product details are shared across all locations. Changing location moves this balance without changing its quantity and records the correction in stock history. Use <strong>Adjust Stock</strong> only to correct quantities.
                </div>
                <div class="form-group">
                    <label>Stock Location *</label>
                    <select name="location_id" required>
                        ${locations.map(location => `
                            <option value="${location.id}" ${location.id === stockRow.location_id ? 'selected' : ''}>
                                ${escapeHtml(location.name)}${location.code ? ` (${escapeHtml(location.code)})` : ''}
                            </option>
                        `).join('')}
                    </select>
                    <small class="form-text">If this item was assigned to the wrong office, selecting another location moves the complete balance and preserves its history.</small>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Type *</label>
                        <select name="category_id" required>
                            ${quantityCategories.map(category => `
                                <option value="${category.id}" ${category.id === item.category_id ? 'selected' : ''}>
                                    ${escapeHtml(category.name)}
                                </option>
                            `).join('')}
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Product Name *</label>
                        <input type="text" name="name" required value="${escapeHtml(item.name || '')}">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>SKU / Product Code</label>
                        <input type="text" name="sku" value="${escapeHtml(item.sku || '')}" placeholder="Optional">
                    </div>
                    <div class="form-group">
                        <label>Unit *</label>
                        <input type="text" name="unit_of_measure" required value="${escapeHtml(item.unit_of_measure || 'EA')}">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Make / Manufacturer</label>
                        <input type="text" name="manufacturer" value="${escapeHtml(item.manufacturer || '')}">
                    </div>
                    <div class="form-group">
                        <label>Model / Grade / Pack Size</label>
                        <input type="text" name="model" value="${escapeHtml(item.model || '')}">
                    </div>
                </div>
                <div class="form-group">
                    <label>Description</label>
                    <textarea name="description" rows="2">${escapeHtml(item.description || '')}</textarea>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-outline" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary"><i class="fas fa-save"></i> Save Changes</button>
                </div>
            </form>
        `, 'modal-lg');

        document.getElementById('edit-stock-item-form').addEventListener('submit', async (event) => {
            event.preventDefault();
            await withSubmitLock(event.target, async () => {
                const formData = new FormData(event.target);
                try {
                    await ItemsAPI.update(item.id, {
                        category_id: formData.get('category_id'),
                        name: formData.get('name').trim(),
                        sku: formData.get('sku').trim() || null,
                        unit_of_measure: formData.get('unit_of_measure').trim() || 'EA',
                        manufacturer: formData.get('manufacturer').trim(),
                        model: formData.get('model').trim(),
                        description: formData.get('description').trim()
                    });
                    const newLocationId = formData.get('location_id');
                    if (newLocationId !== stockRow.location_id) {
                        await StockAPI.correctLocation(stockId, {
                            location_id: newLocationId,
                            reason: 'Incorrect stock location corrected from Edit Stock Item'
                        });
                    }
                    closeModal();
                    showToast('Stock item details updated', 'success');
                    await loadStockData(stockPaginationState.locationId || null);
                } catch (error) {
                    showToast(error.message || 'Failed to update stock item', 'error');
                }
            });
        });
    } catch (error) {
        showToast(error.message || 'Failed to load stock item', 'error');
    }
}

async function deactivateStock(id) {
    if (!confirm('Deactivate this stock record?')) return;
    try {
        await StockAPI.delete(id);
        showToast('Stock record deactivated', 'success');
        await loadStockData();
    } catch (error) { showToast(error.message || 'Failed to deactivate stock', 'error'); }
}

async function permanentlyDeleteStock(id) {
    if (!confirm('Permanently delete this stock record? This action cannot be undone.')) return;
    try {
        await StockAPI.permanentDelete(id);
        stockPaginationState.allItems = stockPaginationState.allItems.filter(item => item.stock_id !== id);
        renderStockPage();
        showToast('Stock record permanently deleted', 'success');
        await loadStockData();
    } catch (error) {
        const message = error.message || 'Failed to permanently delete stock';
        const canForceBalanceDelete = message.includes('non-zero quantities') || message.includes('transaction history records retained');
        if (!canForceBalanceDelete) {
            showToast(message, 'error');
            return;
        }
        const warning = `${message}\n\nDelete the current stock balance anyway? Transaction history will be retained. This action cannot be undone.`;
        if (!confirm(warning)) return;
        try {
            await StockAPI.permanentDelete(id, true);
            stockPaginationState.allItems = stockPaginationState.allItems.filter(item => item.stock_id !== id);
            renderStockPage();
            showToast('Stock balance permanently deleted; transaction history was retained', 'success');
            await loadStockData();
        } catch (forceError) {
            showToast(forceError.message || 'Failed to permanently delete stock', 'error');
        }
    }
}

async function loadStockData(locationId = null) {
    const summaryCard = document.getElementById('location-summary-card');
    const paginationDiv = document.getElementById('stock-pagination');
    
    try {
        if (locationId) {
            // Load location-specific stock with daily movements
            const summary = await StockAPI.getByLocation(locationId);
            
            const quantityItems = summary.items.filter(isQuantityTrackedRecord);

            // Show summary card
            summaryCard.classList.remove('hidden');
            document.getElementById('stock-summary-location-name').textContent = summary.location_name;
            document.getElementById('stock-summary-total-items').textContent = quantityItems.length;
            document.getElementById('stock-summary-total-qty').textContent = quantityItems.reduce((sum, item) => sum + (item.closing_balance || 0), 0);
            document.getElementById('stock-summary-low-stock').textContent = quantityItems.filter(item => item.is_low_stock).length;
            
            if (summary.items.length === 0) {
                document.getElementById('stock-table-body').innerHTML = '<tr><td colspan="13" class="text-center text-muted">No stock at this location</td></tr>';
                paginationDiv.style.display = 'none';
                return;
            }
            
            // Setup pagination
            if (quantityItems.length === 0) {
                document.getElementById('stock-table-body').innerHTML = '<tr><td colspan="13" class="text-center text-muted">No quantity-based stock records found at this location</td></tr>';
                paginationDiv.style.display = 'none';
                return;
            }
            stockPaginationState.allItems = quantityItems;
            stockPaginationState.totalItems = quantityItems.length;
            stockPaginationState.totalPages = Math.ceil(quantityItems.length / stockPaginationState.itemsPerPage) || 1;
            stockPaginationState.currentPage = 1;
            stockAllItemsUnfiltered = quantityItems;
            populateStockCategoryFilter(quantityItems);
            
            // Show pagination if needed
            paginationDiv.style.display = stockPaginationState.totalPages > 1 ? 'block' : 'none';
            
            filterStock();
        } else {
            // Load all stock with movements (all locations view)
            summaryCard.classList.add('hidden');
            
            // Use location stock summary API to get movement data
            const summary = await DashboardAPI.getLocationStockSummary();
            
            // Flatten all items from all locations
            const allItems = [];
            summary.locations.forEach(location => {
                location.items.filter(isQuantityTrackedRecord).forEach(item => {
                    allItems.push({
                        ...item,
                        location_name: location.location_name,
                        location_code: location.location_code
                    });
                });
            });
            
            if (allItems.length === 0) {
                document.getElementById('stock-table-body').innerHTML = '<tr><td colspan="13" class="text-center text-muted">No quantity-based stock records found</td></tr>';
                paginationDiv.style.display = 'none';
                return;
            }
            
            // Setup pagination
            stockPaginationState.allItems = allItems;
            stockPaginationState.totalItems = allItems.length;
            stockPaginationState.totalPages = Math.ceil(allItems.length / stockPaginationState.itemsPerPage);
            stockPaginationState.currentPage = 1;
            stockAllItemsUnfiltered = allItems;
            populateStockCategoryFilter(allItems);
            
            // Show pagination if needed
            paginationDiv.style.display = stockPaginationState.totalPages > 1 ? 'block' : 'none';
            
            filterStock();
        }
    } catch (error) {
        console.error('Stock data load error:', error);
        document.getElementById('stock-table-body').innerHTML = '<tr><td colspan="13" class="text-center text-muted">Error loading stock data</td></tr>';
        paginationDiv.style.display = 'none';
    }
}

async function permanentlyDeleteItem(id) {
    if (!confirm('Permanently delete this product? This action cannot be undone.')) return;
    try {
        await ItemsAPI.permanentDelete(id);
        allProducts = allProducts.filter(product => product.id !== id);
        closeModal();
        filterProducts();
        showToast('Product permanently deleted', 'success');
        await loadItems();
    } catch (error) {
        showToast(error.message || 'Failed to permanently delete product', 'error');
    }
}

function showEditLowStockQtyModal(stockId, itemName, currentQty) {
    const perms = getUserPermissions();
    if (!perms.canManage) {
        showToast('Only managers or Admin can change low stock alert quantity', 'error');
        return;
    }

    openModal('Edit Low Stock Alert Qty', `
        <form id="edit-low-stock-qty-form">
            <div class="form-group">
                <label>Product</label>
                <input type="text" value="${escapeHtml(itemName)}" disabled>
            </div>
            <div class="form-group">
                <label>Low Stock Alert Qty *</label>
                <input type="number" name="reorder_point" min="0" step="1" required value="${parseInt(currentQty || 0)}">
                <small class="form-help">Alert triggers when available stock is at or below this quantity. Use 0 to disable low-stock alerting for this stock row.</small>
            </div>
            <div class="modal-footer">
                <button type="button" class="btn btn-outline" onclick="closeModal()">Cancel</button>
                <button type="submit" class="btn btn-primary">Update Alert Qty</button>
            </div>
        </form>
    `);

    document.getElementById('edit-low-stock-qty-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        await withSubmitLock(e.target, async () => {
            const formData = new FormData(e.target);
            const reorderPoint = parseInt(formData.get('reorder_point')) || 0;
            try {
                await StockAPI.updateThresholds(stockId, { reorder_point: reorderPoint });
                closeModal();
                showToast('Low stock alert quantity updated', 'success');
                await loadStockData(stockPaginationState.locationId || null);
            } catch (error) {
                showToast(error.message, 'error');
            }
        });
    });
}

function showAdjustStockModal() {
    // Load items and locations for the modal
    Promise.all([
        ItemsAPI.getAllPages(),
        LocationsAPI.getAll({ is_active: true })
    ]).then(([itemData, locData]) => {
        const items = (Array.isArray(itemData) ? itemData : (itemData.items || []))
            .filter(item => isQuantityTrackedRecord(item) && ['consumable', 'accessory'].includes(quantityTypeKeyForRecord(item)));
        const locs = activeRecords(Array.isArray(locData) ? locData : (locData.items || []));
        
        if (items.length === 0) {
            showToast('No quantity-based products are available for stock adjustment.', 'warning');
            return;
        }

        const itemOptions = items.map(i => `<option value="${i.id}">${i.id_number ? i.id_number + ' - ' : ''}${i.name}</option>`).join('');
        const locOptions = locs.map(l => `<option value="${l.id}">${l.name}</option>`).join('');
        
        openModal('Adjust Stock', `
            <form id="adjust-stock-form">
                <div class="form-row">
                    <div class="form-group">
                        <label>Product *</label>
                        <select name="item_id" required>
                            <option value="">Select product</option>
                            ${itemOptions}
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Location *</label>
                        <select name="location_id" required>
                            <option value="">Select location</option>
                            ${locOptions}
                        </select>
                    </div>
                </div>
                <div id="adjust-current-info" style="display:none; margin-bottom:12px; padding:8px 12px; background:var(--bg-alt); border-radius:6px; font-size:13px;">
                    Current Stock: <strong id="adjust-current-qty" style="color:var(--primary-color)">0</strong>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Quantity Difference *</label>
                        <input type="number" name="quantity_change" required placeholder="e.g., 10 or -5">
                        <small class="form-help">Enter the correction difference only. Positive adds, negative deducts.</small>
                    </div>
                    <div class="form-group">
                        <label>Reason *</label>
                        <select name="reason" required>
                            ${buildStockAdjustmentReasonOptions()}
                        </select>
                    </div>
                </div>
                <div class="form-group">
                    <label>Notes</label>
                    <textarea name="notes" rows="2" placeholder="Audit note, count sheet ref, approval ref, or explanation"></textarea>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-outline" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary"><i class="fas fa-check"></i> Submit Adjustment</button>
                </div>
            </form>
        `);
        
        document.getElementById('adjust-stock-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const formData = new FormData(e.target);
            const qtyChange = Number.parseInt(formData.get('quantity_change'), 10);
            if (!Number.isInteger(qtyChange) || qtyChange === 0) {
                showToast('Enter a non-zero quantity difference, for example 10 or -5', 'error');
                return;
            }
            // Client-side guard: deductions cannot exceed on-hand
            if (qtyChange < 0) {
                const infoEl = document.getElementById('adjust-current-info');
                if (infoEl && infoEl.style.display !== 'none') {
                    const onHand = parseInt(document.getElementById('adjust-current-qty').textContent) || 0;
                    if (Math.abs(qtyChange) > onHand) {
                        showToast(`Cannot deduct ${Math.abs(qtyChange)} — only ${onHand} on hand`, 'error');
                        return;
                    }
                }
            }
            await withSubmitLock(e.target, async () => {
                const data = {
                    item_id: formData.get('item_id'),
                    location_id: formData.get('location_id'),
                    quantity_change: qtyChange,
                    reason: formData.get('reason'),
                    notes: formData.get('notes') || null
                };
                try {
                    await StockAPI.adjust(data);
                    closeModal();
                    showToast('Stock adjusted successfully', 'success');
                    await loadStock();
                    await refreshDashboardAsync();
                } catch (error) {
                    const message = error.message === 'Failed to fetch'
                        ? 'Could not reach the backend while adjusting stock. Please retry after checking the server connection.'
                        : error.message;
                    showToast(message || 'Stock adjustment failed', 'error');
                }
            });
        });

        // Live current-stock lookup for Adjust modal
        const updateAdjustInfo = async () => {
            const form = document.getElementById('adjust-stock-form');
            if (!form) return;
            const itemId = form.querySelector('[name="item_id"]').value;
            const locId = form.querySelector('[name="location_id"]').value;
            const infoEl = document.getElementById('adjust-current-info');
            const qtyEl = document.getElementById('adjust-current-qty');
            const qtyInput = form.querySelector('[name="quantity_change"]');
            if (qtyInput) {
                qtyInput.title = '';
            }
            if (itemId && locId) {
                qtyEl.textContent = '…';
                infoEl.style.display = 'block';
                try {
                    const res = await StockAPI.getAvailable(itemId, locId);
                    qtyEl.textContent = res.on_hand ?? 0;
                } catch (err) {
                    console.error('Stock lookup failed:', err);
                    qtyEl.textContent = '?';
                }
            } else {
                infoEl.style.display = 'none';
            }
        };
        document.querySelector('#adjust-stock-form [name="item_id"]').addEventListener('change', updateAdjustInfo);
        document.querySelector('#adjust-stock-form [name="location_id"]').addEventListener('change', updateAdjustInfo);
    }).catch(error => {
        showToast('Error loading data: ' + error.message, 'error');
    });
}

async function showAddStockItemModal() {
    try {
        const [catData, locData] = await Promise.all([
            CategoriesAPI.getAll(),
            LocationsAPI.getAll({ is_active: true })
        ]);
        categories = Array.isArray(catData) ? catData : (catData.items || []);
        locations = activeRecords(Array.isArray(locData) ? locData : (locData.items || []));

        const quantityCategories = categories.filter(c =>
            c.is_active !== false &&
            (c.stock_behavior || '').toLowerCase() !== 'serialized'
        );
        if (quantityCategories.length === 0) {
            showToast('No quantity-based categories are available for Stock Levels.', 'warning');
            return;
        }

        openModal('Add Stock Item', `
            <form id="add-stock-item-form">
                <div class="alert alert-info" style="margin-bottom: 15px; padding: 10px 14px; background: rgba(37,99,235,0.06); border-radius: 8px; border-left: 3px solid var(--primary-color); font-size: 13px; color: var(--text-muted);">
                    <i class="fas fa-info-circle" style="color: var(--primary-color); margin-right: 6px;"></i>
                    Create the product master here. Market purchases are recorded separately in the Purchase Registry.
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Type *</label>
                        <select name="category_id" required>
                            <option value="">Select type</option>
                            ${quantityCategories.map(c => `<option value="${c.id}" data-type-key="${c.category_type_key || c.name || ''}">${escapeHtml(c.name)}</option>`).join('')}
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Product *</label>
                        <input type="text" name="name" required placeholder="e.g., Couplant Gel, DPT Cleaner, Probe Cable">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>SKU / Product Code</label>
                        <input type="text" name="sku" placeholder="Optional product code">
                        <small class="form-help">Leave blank when the supplier or product has no code.</small>
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Unit</label>
                        <input type="text" name="unit_of_measure" value="EA" placeholder="EA, PCS, LTR">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Initial Location *</label>
                        <select name="initial_location_id" required>
                            <option value="">Select location</option>
                            ${locations.map(l => `<option value="${l.id}">${escapeHtml(l.name)}</option>`).join('')}
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Opening Quantity</label>
                        <input type="number" name="initial_quantity" min="0" step="1" value="0">
                    </div>
                </div>
                <div class="form-group" id="initial-low-stock-group">
                    <label>Low Stock Alert Qty *</label>
                    <input type="number" name="initial_reorder_point" min="0" step="1" value="0" required>
                    <small class="form-help">Alert triggers when this item's stock at the selected location is at or below this quantity.</small>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Make / Manufacturer</label>
                        <input type="text" name="manufacturer" placeholder="Brand / Manufacturer">
                    </div>
                    <div class="form-group">
                        <label>Model</label>
                        <input type="text" name="model" placeholder="Model, grade, pack size">
                    </div>
                </div>
                <div class="form-group">
                    <label>Description</label>
                    <textarea name="description" rows="2" placeholder="Product description"></textarea>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-outline" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary">Create Stock Item</button>
                </div>
            </form>
        `, 'modal-lg');

        const stockForm = document.getElementById('add-stock-item-form');

        stockForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const formData = new FormData(e.target);
            const categoryId = formData.get('category_id');
            const initialLocationId = formData.get('initial_location_id') || null;
            const initialQuantity = parseInt(formData.get('initial_quantity')) || 0;
            const category = categories.find(c => c.id === categoryId);
            if (category && (category.stock_behavior || '').toLowerCase() === 'serialized') {
                showToast('Stock Levels accepts only quantity-based categories.', 'error');
                return;
            }
            if (!category) {
                showToast('Select a valid quantity-based type.', 'error');
                return;
            }
            if (!initialLocationId) {
                showToast('Select initial location so this stock item appears in Stock Levels.', 'error');
                return;
            }

            const data = {
                name: formData.get('name'),
                sku: formData.get('sku').trim() || null,
                category_id: categoryId,
                asset_type: canonicalInventoryTypeKey(category?.category_type_key || category?.name || 'quantity'),
                unit_of_measure: formData.get('unit_of_measure') || 'EA',
                manufacturer: formData.get('manufacturer') || null,
                model: formData.get('model') || null,
                description: formData.get('description') || null,
                is_serialized: false,
                initial_location_id: initialLocationId,
                initial_quantity: initialQuantity,
                initial_reorder_point: parseInt(formData.get('initial_reorder_point')) || 0,
                is_active: true
            };

            try {
                if (!await confirmProbableDuplicateProduct(data)) return;
                await ItemsAPI.create(data);
                closeModal();
                showToast('Stock item created. Record purchase quantity with Receive Stock.', 'success');
                loadStock();
            } catch (error) {
                showToast(error.message, 'error');
            }
        });
    } catch (error) {
        showToast('Error loading data: ' + error.message, 'error');
    }
}

function showIssueStockModal() {
    // Load items and locations only — stock looked up live per selection
    Promise.all([
        ItemsAPI.getAllPages(),
        LocationsAPI.getAll({ is_active: true }),
        LocationsAPI.getTransferDestinations().catch(() => LocationsAPI.getAll({ is_active: true }))
    ]).then(([itemData, locData, destinationLocData]) => {
        const items = (Array.isArray(itemData) ? itemData : (itemData.items || []))
            .filter(item => isQuantityTrackedRecord(item) && ['consumable', 'accessory'].includes(quantityTypeKeyForRecord(item)));
        const locs = activeRecords(Array.isArray(locData) ? locData : (locData.items || []));
        const destinationLocs = activeRecords(Array.isArray(destinationLocData) ? destinationLocData : (destinationLocData.items || []));
        
        if (items.length === 0) {
            showToast('No quantity-based products are available for stock issue.', 'warning');
            return;
        }

        const typeOptions = stockRegisterTypeOptions(items);
        const locOptions = locs.map(l => `<option value="${l.id}">${l.name}</option>`).join('');
        const destinationLocOptions = destinationLocs.map(l => `<option value="${l.id}">${l.name}</option>`).join('');
        
        openModal('Issue Stock', `
            <form id="issue-stock-form">
                <div class="alert alert-info" style="margin-bottom: 15px; padding: 10px 14px; background: rgba(37,99,235,0.06); border-radius: 8px; border-left: 3px solid var(--primary-color); font-size: 13px; color: var(--text-muted);">
                    <i class="fas fa-minus-circle" style="color: var(--danger-color); margin-right: 6px;"></i>
                    This will <strong>deduct</strong> the entered quantity from stock.
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Type *</label>
                        <select name="stock_type" required>
                            <option value="">Select type</option>
                            ${typeOptions}
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Description *</label>
                        <select name="item_id" required>
                            <option value="">Select type first</option>
                        </select>
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>From Location *</label>
                        <select name="location_id" id="issue-from-location" required>
                            <option value="">Select from location</option>
                            ${locOptions}
                        </select>
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Issue Date *</label>
                        <input type="date" name="issue_date" required value="${localDateInputValue()}">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>To Location *</label>
                        <select name="to_location_id" id="issue-to-location" required>
                            <option value="">Select to location</option>
                            ${destinationLocOptions}
                        </select>
                    </div>
                    <div class="form-group">
                        <label>DC Number *</label>
                        <input type="text" name="dc_number" required placeholder="Delivery challan number">
                    </div>
                </div>
                <div class="form-group" id="same-location-receiver-group" style="display:none;">
                    <label>Receiving Area / Person / Location *</label>
                    <input type="text" name="receiving_details" placeholder="e.g., Lab bench, site engineer, dark room">
                </div>
                <div id="issue-available-info" style="display:none; margin-bottom:12px; padding:8px 12px; background:var(--bg-alt); border-radius:6px; font-size:13px;">
                    Available: <strong id="issue-available-qty">0</strong>
                </div>
                <div class="form-row">
                    <div class="form-group" id="issue-qty-group">
                        <label>No. of Quantity to Issue *</label>
                        <input type="number" name="quantity" min="1" required placeholder="Enter quantity">
                    </div>
                </div>
                <div class="form-group">
                    <label>Remarks</label>
                    <textarea name="description" rows="2" placeholder="Issue purpose, job, or supporting details"></textarea>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-outline" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-warning"><i class="fas fa-minus-circle"></i> Issue Stock</button>
                </div>
            </form>
        `);

        // Fetch available quantity live when item + location are both selected
        const issueForm = document.getElementById('issue-stock-form');
        const issueTypeSelect = issueForm.querySelector('[name="stock_type"]');
        const issueItemSelect = issueForm.querySelector('[name="item_id"]');
        let currentAvailable = 0;
        const updateAvailable = async () => {
            const form = document.getElementById('issue-stock-form');
            if (!form) return;
            const itemId = form.querySelector('[name="item_id"]').value;
            const locId = form.querySelector('[name="location_id"]').value;
            const infoEl = document.getElementById('issue-available-info');
            const qtyEl = document.getElementById('issue-available-qty');
            const quantityInput = form.querySelector('[name="quantity"]');
            const quantityGroup = document.getElementById('issue-qty-group');
            const serialized = false;
            if (quantityGroup) quantityGroup.style.display = '';
            if (quantityInput) {
                quantityInput.value = serialized ? '1' : quantityInput.value;
                quantityInput.readOnly = serialized;
                quantityInput.required = !serialized;
                quantityInput.title = serialized ? 'Serialized items are issued one serial number at a time' : '';
            }
            if (itemId && locId) {
                qtyEl.textContent = '…';
                infoEl.style.display = 'block';
                try {
                    const res = await StockAPI.getAvailable(itemId, locId);
                    currentAvailable = res.available ?? 0;
                } catch (err) {
                    console.error('Stock available lookup failed:', err);
                    currentAvailable = 0;
                }
                qtyEl.textContent = currentAvailable;
                qtyEl.style.color = currentAvailable <= 0 ? 'var(--danger-color)' : 'var(--success-color)';
                form.querySelector('[name="quantity"]').max = currentAvailable;
            } else {
                infoEl.style.display = 'none';
                currentAvailable = 0;
            }
        };
        const syncIssueItems = () => {
            const selectedType = normalizeTypeKey(issueTypeSelect.value);
            const matchingItems = items.filter(item => quantityTypeKeyForRecord(item) === selectedType);
            issueItemSelect.disabled = !selectedType;
            issueItemSelect.innerHTML = selectedType
                ? '<option value="">Select description</option>' + matchingItems.map(i => `<option value="${i.id}">${escapeHtml(stockItemDescriptionLabel(i))}</option>`).join('')
                : '<option value="">Select type first</option>';
            updateAvailable();
        };
        issueTypeSelect.addEventListener('change', syncIssueItems);
        syncIssueItems();
        document.querySelector('#issue-stock-form [name="item_id"]').addEventListener('change', updateAvailable);
        document.querySelector('#issue-stock-form [name="location_id"]').addEventListener('change', updateAvailable);
        const syncSameLocationReceiver = () => {
            const form = document.getElementById('issue-stock-form');
            const fromLoc = form.querySelector('[name="location_id"]').value;
            const toLoc = form.querySelector('[name="to_location_id"]').value;
            const group = document.getElementById('same-location-receiver-group');
            const input = form.querySelector('[name="receiving_details"]');
            const sameLocation = fromLoc && toLoc && fromLoc === toLoc;
            group.style.display = sameLocation ? '' : 'none';
            input.required = sameLocation;
            if (!sameLocation) input.value = '';
        };
        document.querySelector('#issue-stock-form [name="location_id"]').addEventListener('change', syncSameLocationReceiver);
        document.querySelector('#issue-stock-form [name="to_location_id"]').addEventListener('change', syncSameLocationReceiver);
        
        document.getElementById('issue-stock-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const formData = new FormData(e.target);
            const itemId = formData.get('item_id');
            const locId = formData.get('location_id');
            const toLocId = formData.get('to_location_id');
            const qty = parseInt(formData.get('quantity'));
            if (locId === toLocId && !formData.get('receiving_details')) {
                showToast('Enter receiving area/person/location for same-location issue', 'error');
                return;
            }
            if (qty > currentAvailable) {
                showToast(`Cannot issue ${qty} — only ${currentAvailable} available at this location`, 'error');
                return;
            }
            await withSubmitLock(e.target, async () => {
                const data = {
                    item_id: itemId,
                    location_id: locId,
                    to_location_id: toLocId || locId,
                    transfer_type: normalizeTypeKey(formData.get('stock_type')) === 'accessory' ? 'accessory' : 'consumable',
                    quantity: qty,
                    reason: 'Issued for stock movement',
                    reference_number: formData.get('dc_number') || null,
                    notes: [
                        `Issue date: ${formData.get('issue_date') || '-'}`,
                        `To location: ${destinationLocs.find(l => l.id === toLocId)?.name || toLocId || '-'}`,
                        formData.get('receiving_details') ? `Receiving details: ${formData.get('receiving_details')}` : '',
                        formData.get('description') || ''
                    ].filter(Boolean).join('\n')
                };
                try {
                    const result = await StockAPI.documentedIssue(data);
                    closeModal();
                    showDocumentedIssueResult(result.data || {});
                    showToast('Stock issued with PI and DC', 'success');
                    loadStock();
                    await refreshDashboardAsync();
                } catch (error) {
                    showToast(error.message, 'error');
                }
            });
        });
    }).catch(error => {
        showToast('Error loading data: ' + error.message, 'error');
    });
}

function showDocumentedIssueResult(data) {
    const piId = data.purchase_indent_id || '';
    const transferId = data.transfer_id || '';
    openModal('Stock Issue Documents', `
        <div style="display:flex;flex-direction:column;gap:12px;">
            <div class="alert alert-info" style="padding:10px 14px;background:rgba(37,99,235,0.06);border-radius:8px;border-left:3px solid var(--primary-color);">
                Stock issue completed. Purchase Indent and Delivery Challan are ready for audit/print.
            </div>
            <div>
                <strong>PI:</strong> ${escapeHtml(data.purchase_indent_number || '-')}<br>
                <strong>Transfer/DC Ref:</strong> ${escapeHtml(data.transfer_number || '-')}
            </div>
            <div class="modal-footer">
                <button type="button" class="btn btn-outline" onclick="closeModal()">Close</button>
                ${piId ? `<button type="button" class="btn btn-primary" onclick="printPIDocument('${piId}')"><i class="fas fa-print"></i> Print PI</button>` : ''}
                ${transferId ? `<button type="button" class="btn btn-primary" onclick="printDeliveryChallan('${transferId}')"><i class="fas fa-file-invoice"></i> Print DC</button>` : ''}
            </div>
        </div>
    `);
}

function showReceiptStockModal() {
    Promise.all([
        ItemsAPI.getAllPages(),
        LocationsAPI.getAll({ is_active: true })
    ]).then(([itemData, locData]) => {
        const items = (Array.isArray(itemData) ? itemData : (itemData.items || [])).filter(isQuantityTrackedRecord);
        const locs = activeRecords(Array.isArray(locData) ? locData : (locData.items || []));
        
        if (items.length === 0) {
            showToast('No quantity-based products are available for stock receipt.', 'warning');
            return;
        }

        const typeOptions = stockRegisterTypeOptions(items);
        const locOptions = locs.map(l => `<option value="${l.id}">${l.name}</option>`).join('');
        
        openModal('Receive Stock', `
            <form id="receipt-stock-form">
                <div class="alert alert-info" style="margin-bottom: 15px; padding: 10px 14px; background: rgba(16,185,129,0.08); border-radius: 8px; border-left: 3px solid var(--success-color); font-size: 13px; color: var(--text-muted);">
                    <i class="fas fa-receipt" style="color: var(--success-color); margin-right: 6px;"></i>
                    Receive market purchases here. This creates the purchase register entry and adds the received quantity to stock.
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Type *</label>
                        <select name="stock_type" required>
                            <option value="">Select type</option>
                            ${typeOptions}
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Description *</label>
                        <select name="item_id" required>
                            <option value="">Select type first</option>
                        </select>
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Location *</label>
                        <select name="location_id" required>
                            <option value="">Select location</option>
                            ${locOptions}
                        </select>
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Purchase / Receipt Date *</label>
                        <input type="date" name="received_date" required value="${localDateInputValue()}">
                    </div>
                    <div class="form-group">
                        <label>Purchased Quantity *</label>
                        <input type="number" name="quantity" min="1" required placeholder="Enter quantity">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Supplier Name *</label>
                        <input type="text" name="supplier" required placeholder="Supplier name">
                    </div>
                    <div class="form-group">
                        <label>Invoice Number</label>
                        <input type="text" name="invoice_number" placeholder="Invoice number (optional)">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>PO Number</label>
                        <input type="text" name="po_number" placeholder="PO number (optional)">
                    </div>
                    <div class="form-group">
                        <label>Batch Number</label>
                        <input type="text" name="batch_number" placeholder="Batch number (optional)">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Expiry Date</label>
                        <input type="date" name="expiry_date">
                    </div>
                    <div class="form-group">
                        <label>Unit Cost</label>
                        <input type="number" name="unit_cost" min="0" step="0.01" placeholder="Cost per unit (optional)">
                    </div>
                </div>
                <div class="form-group">
                    <label>Purchase Notes</label>
                    <textarea name="description" rows="2" placeholder="Market purchase details, delivery note, or remarks"></textarea>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-outline" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-success"><i class="fas fa-receipt"></i> Record Purchase</button>
                </div>
            </form>
        `);

        const receiptForm = document.getElementById('receipt-stock-form');
        const receiptTypeSelect = receiptForm.querySelector('[name="stock_type"]');
        const receiptItemSelect = receiptForm.querySelector('[name="item_id"]');
        const syncReceiptItems = () => {
            const selectedType = normalizeTypeKey(receiptTypeSelect.value);
            const matchingItems = items.filter(item => quantityTypeKeyForRecord(item) === selectedType);
            receiptItemSelect.disabled = !selectedType;
            receiptItemSelect.innerHTML = selectedType
                ? '<option value="">Select description</option>' + matchingItems.map(i => `<option value="${i.id}">${escapeHtml(stockItemDescriptionLabel(i))}</option>`).join('')
                : '<option value="">Select type first</option>';
        };
        receiptTypeSelect.addEventListener('change', syncReceiptItems);
        syncReceiptItems();
        const syncReceiptMode = () => {
            const qtyGroup = document.getElementById('receipt-qty-group');
            const qtyInput = receiptForm.querySelector('[name="quantity"]');
            if (qtyGroup) qtyGroup.style.display = '';
            if (qtyInput) {
                qtyInput.readOnly = false;
                qtyInput.required = true;
                qtyInput.max = '';
                qtyInput.title = '';
            }
        };
        receiptForm.querySelector('[name="item_id"]').addEventListener('change', syncReceiptMode);
        syncReceiptMode();
        
        receiptForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            await withSubmitLock(e.target, async () => {
                const formData = new FormData(e.target);
                const unitCost = formData.get('unit_cost');
                const invoiceNumber = formData.get('invoice_number') || '';
                const poNumber = formData.get('po_number') || '';
                const referenceNumber = invoiceNumber || poNumber || null;
                const data = {
                    location_id: formData.get('location_id'),
                    reference_number: referenceNumber,
                    supplier: formData.get('supplier') || null,
                    received_date: formData.get('received_date') ? dateInputToIsoEndOfDay(formData.get('received_date')) : null,
                    notes: [
                        invoiceNumber ? `Invoice number: ${invoiceNumber}` : '',
                        poNumber ? `PO number: ${poNumber}` : '',
                        formData.get('description') || ''
                    ].filter(Boolean).join('\n') || null,
                    line_items: [{
                        item_id: formData.get('item_id'),
                        quantity: parseInt(formData.get('quantity')),
                        unit_cost: unitCost ? parseFloat(unitCost) : null,
                        lot_number: formData.get('batch_number') || null,
                        expiry_date: formData.get('expiry_date') || null,
                    }]
                };
                try {
                    await TransactionsAPI.receipt(data);
                    closeModal();
                    showToast('Purchase recorded successfully — stock quantity added', 'success');
                    loadStock();
                    await refreshDashboardAsync();
                } catch (error) {
                    showToast(error.message, 'error');
                }
            });
        });
    }).catch(error => {
        showToast('Error loading data: ' + error.message, 'error');
    });
}

function showReturnStockModal() {
    Promise.all([
        TransactionsAPI.getAll({ transaction_type: 'issue', page_size: 100 }),
        TransactionsAPI.getAll({ transaction_type: 'return', page_size: 100 })
    ]).then(([issueData, returnData]) => {
        const issues = issueData.items || [];
        const returns = returnData.items || [];
        const returnedByIssue = returns.reduce((totals, txn) => {
            if (txn.reference_type === 'transaction' && txn.reference_id) {
                totals[txn.reference_id] = (totals[txn.reference_id] || 0) + txn.quantity;
            }
            return totals;
        }, {});
        const returnableIssues = issues.map(issue => ({
            ...issue,
            returnable_quantity: issue.quantity - (returnedByIssue[issue.id] || 0)
        })).filter(issue => issue.returnable_quantity > 0);
        const issueOptions = returnableIssues.map(issue =>
            `<option value="${issue.id}">${issue.reference_number || issue.id} — ${issue.item_name || issue.item_id} (${issue.returnable_quantity} returnable at ${issue.location_code || issue.location_id})</option>`
        ).join('');
        
        openModal('Return Stock', `
            <form id="return-stock-form">
                <div class="alert alert-info" style="margin-bottom: 15px; padding: 10px 14px; background: rgba(107,114,128,0.08); border-radius: 8px; border-left: 3px solid var(--secondary-color); font-size: 13px; color: var(--text-muted);">
                    <i class="fas fa-undo" style="color: var(--secondary-color); margin-right: 6px;"></i>
                    Return previously issued stock back to inventory.
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Original Issue *</label>
                        <select name="original_issue_id" required>
                            <option value="">Select issued stock</option>
                            ${issueOptions}
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Issue Location</label>
                        <input type="text" name="location_display" readonly>
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group" id="return-qty-group">
                        <label>No. of Quantity to Return *</label>
                        <input type="number" name="quantity" min="1" required placeholder="Enter quantity">
                    </div>
                    <div class="form-group">
                        <label>Condition *</label>
                        <select name="condition" required>
                            <option value="good">Good</option>
                            <option value="damaged">Damaged</option>
                            <option value="expired">Expired</option>
                        </select>
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Returned By</label>
                        <input type="text" name="returned_by" placeholder="Person returning the stock">
                    </div>
                    <div class="form-group">
                        <label>Reason</label>
                        <input type="text" name="reason" placeholder="Reason for return">
                    </div>
                </div>
                <div class="form-group">
                    <label>Notes</label>
                    <textarea name="notes" rows="2" placeholder="Additional notes"></textarea>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-outline" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-secondary"><i class="fas fa-undo"></i> Return Stock</button>
                </div>
            </form>
        `);

        const returnForm = document.getElementById('return-stock-form');
        const syncReturnMode = () => {
            const qtyInput = returnForm.querySelector('[name="quantity"]');
            const issue = returnableIssues.find(candidate =>
                candidate.id === returnForm.elements.original_issue_id.value
            );
            returnForm.elements.location_display.value = issue?.location_code || '';
            qtyInput.max = issue ? issue.returnable_quantity : '';
            qtyInput.placeholder = issue ? `Maximum ${issue.returnable_quantity}` : 'Select an issue first';
        };
        returnForm.querySelector('[name="original_issue_id"]').addEventListener('change', syncReturnMode);
        syncReturnMode();
        
        returnForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            await withSubmitLock(e.target, async () => {
                const formData = new FormData(e.target);
                const originalIssue = returnableIssues.find(issue => issue.id === formData.get('original_issue_id'));
                if (!originalIssue) throw new Error('Select a valid original issue');
                const data = {
                    location_id: originalIssue.location_id,
                    idempotency_key: crypto.randomUUID(),
                    returned_by: formData.get('returned_by') || null,
                    reason: formData.get('reason') || null,
                    notes: formData.get('notes') || null,
                    line_items: [{
                        item_id: originalIssue.item_id,
                        original_issue_id: originalIssue.id,
                        quantity: parseInt(formData.get('quantity')),
                        condition: formData.get('condition'),
                    }]
                };
                try {
                    await TransactionsAPI.returnStock(data);
                    closeModal();
                    showToast('Stock returned successfully', 'success');
                    loadStock();
                    await refreshDashboardAsync();
                } catch (error) {
                    showToast(error.message, 'error');
                }
            });
        });
    }).catch(error => {
        showToast('Error loading data: ' + error.message, 'error');
    });
}

// Locations
async function loadLocations() {
    try {
        const data = await LocationsAPI.getAll();
        
        const locs = Array.isArray(data) ? data : (data.items || []);
        locations = locs;
        
        // Reset search
        const searchEl = document.getElementById('locations-search');
        if (searchEl) searchEl.value = '';

        // Update ONLY the Locations page grid (not dashboard)
        renderLocationsGrid(locs);
        
    } catch (error) {
        console.error('Locations load error:', error);
        const grid = document.getElementById('locations-grid');
        const errorHTML = `
            <div style="padding: 20px; background: #ffebee; border-radius: 8px; color: #d32f2f;">
                <strong><i class="fas fa-exclamation-circle"></i> Error Loading Locations</strong>
                <p>${error.message}</p>
                <p style="font-size: 12px; margin: 10px 0 0;">
                    Make sure you are logged in. If the issue persists, try refreshing the page.
                </p>
                <button class="btn btn-sm btn-danger" onclick="loadLocations()" style="margin-top: 10px;">
                    <i class="fas fa-redo"></i> Retry
                </button>
            </div>
        `;
        if (grid) grid.innerHTML = errorHTML;
    }
}

function showAddLocationModal() {
    openModal('Add New Location', `
        <form id="add-location-form">
            <div class="form-row">
                <div class="form-group">
                    <label>Code *</label>
                    <input type="text" name="code" required placeholder="e.g., LOC-007">
                </div>
                <div class="form-group">
                    <label>Name *</label>
                    <input type="text" name="name" required placeholder="Location name">
                </div>
            </div>
            <div class="form-group">
                <label>Address</label>
                <input type="text" name="address" placeholder="Street address">
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label>City</label>
                    <input type="text" name="city" placeholder="City">
                </div>
                <div class="form-group">
                    <label>State</label>
                    <input type="text" name="state" placeholder="State/Province">
                </div>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label>Country</label>
                    <input type="text" name="country" placeholder="Country">
                </div>
                <div class="form-group">
                    <label>Postal Code</label>
                    <input type="text" name="postal_code" placeholder="Postal/ZIP code">
                </div>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label>Contact Person</label>
                    <input type="text" name="contact_person" placeholder="Name of contact person">
                </div>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label>Phone</label>
                    <input type="tel" name="phone" placeholder="+1 (555) 123-4567">
                </div>
                <div class="form-group">
                    <label>Email</label>
                    <input type="email" name="email" placeholder="contact@example.com">
                </div>
            </div>
            <div class="modal-footer">
                <button type="button" class="btn btn-outline" onclick="closeModal()">Cancel</button>
                <button type="submit" class="btn btn-primary">Create Location</button>
            </div>
        </form>
    `);
    
    document.getElementById('add-location-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const formData = new FormData(e.target);
        
        const data = {
            code: formData.get('code'),
            name: formData.get('name'),
            address: formData.get('address') || null,
            city: formData.get('city') || null,
            state: formData.get('state') || null,
            country: formData.get('country') || null,
            postal_code: formData.get('postal_code') || null,
            contact_person: formData.get('contact_person') || null,
            phone: formData.get('phone') || null,
            email: formData.get('email') || null,
            is_active: true
        };
        
        try {
            await LocationsAPI.create(data);
            closeModal();
            showToast('Location created successfully', 'success');
            loadLocations();
        } catch (error) {
            showToast(error.message, 'error');
        }
    });
}

async function editLocation(locationId) {
    const location = locations.find(l => l.id === locationId);
    if (!location) {
        showToast('Location not found', 'error');
        return;
    }

    // Fetch all users so we can populate the assign dropdown
    let allUsers = [];
    try {
        const ud = await UsersAPI.getAll({ page_size: 200 });
        allUsers = Array.isArray(ud) ? ud : (ud.items || []);
    } catch (_) {}

    // Track assigned users in a mutable Set (by user id)
    // Use fresh data from location.assigned_users
    const assignedMap = {}; // id -> { id, name, role }
    (location.assigned_users || []).forEach(u => { assignedMap[u.id] = u; });

    function renderAssignedUserTags() {
        const container = document.getElementById('loc-assigned-users-container');
        if (!container) return;
        const entries = Object.values(assignedMap);
        if (entries.length === 0) {
            container.innerHTML = '<span class="text-muted" style="font-size:13px;">No users assigned</span>';
            return;
        }
        container.innerHTML = entries.map(u => `
            <span class="assigned-user-tag" style="display:inline-flex;align-items:center;gap:6px;background:#e8f0fe;border:1px solid #c5d5f5;border-radius:20px;padding:3px 10px 3px 8px;margin:3px 4px 3px 0;font-size:13px;">
                <i class="fas fa-user-circle" style="color:#4a6cf7;"></i>
                <strong>${u.name}</strong>
                <small class="text-muted">(${ROLE_LABELS[u.role] || u.role})</small>
                <button type="button" onclick="window._locRemoveUser('${u.id}')" style="background:none;border:none;cursor:pointer;color:#d32f2f;padding:0;line-height:1;font-size:14px;margin-left:2px;" title="Remove">
                    <i class="fas fa-times-circle"></i>
                </button>
            </span>
        `).join('');
    }

    // Build dropdown options — exclude already-assigned users
    function renderAddUserDropdown() {
        const sel = document.getElementById('loc-add-user-select');
        if (!sel) return;
        const unassigned = allUsers.filter(u => !assignedMap[u.id]);
        sel.innerHTML = '<option value="">— Select user to assign —</option>' +
            unassigned.map(u => `<option value="${u.id}" data-name="${u.name}" data-role="${u.role}">${u.name} (${ROLE_LABELS[u.role] || u.role})</option>`).join('');
    }

    openModal('Edit Location', `
        <form id="edit-location-form">
            <div class="form-row">
                <div class="form-group">
                    <label>Code *</label>
                    <input type="text" name="code" required placeholder="e.g., LOC-007" value="${location.code}">
                </div>
                <div class="form-group">
                    <label>Name *</label>
                    <input type="text" name="name" required placeholder="Location name" value="${location.name}">
                </div>
            </div>
            <div class="form-group">
                <label>Address</label>
                <input type="text" name="address" placeholder="Street address" value="${location.address || ''}">
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label>City</label>
                    <input type="text" name="city" placeholder="City" value="${location.city || ''}">
                </div>
                <div class="form-group">
                    <label>State</label>
                    <input type="text" name="state" placeholder="State/Province" value="${location.state || ''}">
                </div>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label>Country</label>
                    <input type="text" name="country" placeholder="Country" value="${location.country || ''}">
                </div>
                <div class="form-group">
                    <label>Postal Code</label>
                    <input type="text" name="postal_code" placeholder="Postal/ZIP code" value="${location.postal_code || ''}">
                </div>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label>Contact Person</label>
                    <input type="text" name="contact_person" placeholder="Name of contact person" value="${location.contact_person || ''}">
                </div>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label>Phone</label>
                    <input type="tel" name="phone" placeholder="+1 (555) 123-4567" value="${location.phone || ''}">
                </div>
                <div class="form-group">
                    <label>Email</label>
                    <input type="email" name="email" placeholder="contact@example.com" value="${location.email || ''}">
                </div>
            </div>
            <div class="form-group">
                <label><input type="checkbox" name="is_active" ${location.is_active ? 'checked' : ''}> Active</label>
            </div>

            <hr style="margin:16px 0 12px;">
            <div class="form-group">
                <label style="font-weight:600;"><i class="fas fa-users" style="color:#4a6cf7;margin-right:6px;"></i>Assigned Users</label>
                <div id="loc-assigned-users-container" style="margin:8px 0 10px;min-height:32px;"></div>
                <div style="display:flex;gap:8px;align-items:center;">
                    <select id="loc-add-user-select" style="flex:1;padding:7px 10px;border:1px solid #d0d5e8;border-radius:6px;font-size:13px;"></select>
                    <button type="button" id="loc-assign-btn" class="btn btn-sm btn-primary" style="white-space:nowrap;">
                        <i class="fas fa-user-plus"></i> Assign
                    </button>
                </div>
            </div>

            <div class="modal-footer">
                <button type="button" class="btn btn-outline" onclick="closeModal()">Cancel</button>
                <button type="submit" class="btn btn-primary"><i class="fas fa-save"></i> Update Location</button>
            </div>
        </form>
    `, 'modal-lg');

    // Render initial state
    renderAssignedUserTags();
    renderAddUserDropdown();

    // Remove user handler (global so inline onclick works inside modal)
    window._locRemoveUser = (uid) => {
        delete assignedMap[uid];
        renderAssignedUserTags();
        renderAddUserDropdown();
    };

    // Assign button handler
    document.getElementById('loc-assign-btn').addEventListener('click', () => {
        const sel = document.getElementById('loc-add-user-select');
        const uid = sel.value;
        if (!uid) return;
        const opt = sel.options[sel.selectedIndex];
        assignedMap[uid] = { id: uid, name: opt.dataset.name, role: opt.dataset.role };
        renderAssignedUserTags();
        renderAddUserDropdown();
    });

    document.getElementById('edit-location-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const formData = new FormData(e.target);

        const locationData = {
            code: formData.get('code'),
            name: formData.get('name'),
            address: formData.get('address') || null,
            city: formData.get('city') || null,
            state: formData.get('state') || null,
            country: formData.get('country') || null,
            postal_code: formData.get('postal_code') || null,
            contact_person: formData.get('contact_person') || null,
            phone: formData.get('phone') || null,
            email: formData.get('email') || null,
            is_active: formData.has('is_active')
        };

        try {
            await LocationsAPI.update(locationId, locationData);

            // Sync user-location assignments:
            // For each user, determine their new assigned_location_ids
            const newAssignedIds = new Set(Object.keys(assignedMap));
            const oldAssignedIds = new Set((location.assigned_users || []).map(u => u.id));

            // Users added to this location
            const toAdd = [...newAssignedIds].filter(uid => !oldAssignedIds.has(uid));
            // Users removed from this location
            const toRemove = [...oldAssignedIds].filter(uid => !newAssignedIds.has(uid));

            const userPatches = [];
            for (const uid of toAdd) {
                const u = allUsers.find(x => x.id === uid);
                if (u) {
                    const current = new Set(u.assigned_location_ids || []);
                    current.add(locationId);
                    userPatches.push(UsersAPI.update(uid, { assigned_location_ids: [...current] }));
                }
            }
            for (const uid of toRemove) {
                const u = allUsers.find(x => x.id === uid);
                if (u) {
                    const current = (u.assigned_location_ids || []).filter(id => id !== locationId);
                    userPatches.push(UsersAPI.update(uid, { assigned_location_ids: current }));
                }
            }
            if (userPatches.length) await Promise.all(userPatches);

            closeModal();
            showToast('Location updated successfully', 'success');
            loadLocations();
        } catch (error) {
            showToast(error.message, 'error');
        }
    });
}

function deleteLocation(locationId) {
    const location = locations.find(l => l.id === locationId);
    if (!location) {
        showToast('Location not found', 'error');
        return;
    }
    
    if (!confirm(`Deactivate location "${location.name}"? It will be hidden from active location lists.`)) {
        return;
    }
    
    (async () => {
        try {
            await LocationsAPI.delete(locationId);
            showToast('Location deactivated successfully', 'success');
            loadLocations();
        } catch (error) {
            showToast(error.message, 'error');
        }
    })();
}

// Categories
async function loadCategories() {
    try {
        const [data] = await Promise.all([
            CategoriesAPI.getAll()
        ]);
        const cats = Array.isArray(data) ? data : (data.items || []);
        categories = cats;

        // Reset filter inputs
        const searchEl = document.getElementById('categories-search');
        if (searchEl) searchEl.value = '';
        const statusEl = document.getElementById('categories-status-filter');
        if (statusEl) statusEl.value = '';
        const stockEl = document.getElementById('categories-stock-filter');
        if (stockEl) stockEl.value = '';

        renderCategoriesTable(cats);
    } catch (error) {
        console.error('Categories load error:', error);
        document.getElementById('categories-table-body').innerHTML = 
            '<tr><td colspan="6" class="text-center text-muted">Error loading categories</td></tr>';
    }
}

async function showAddCategoryModal() {
    openModal('Add New Category', `
        <form id="add-category-form">
            <div class="form-group">
                <label>Category Name *</label>
                <input type="text" name="name" required placeholder="e.g., Ultrasonic Flaw Detector, Couplant Gel, Cables">
            </div>
            <div class="form-group">
                <label>Stock Input / Handling *</label>
                <select name="stock_behavior" required>
                    <option value="serialized">Serialized</option>
                    <option value="quantity">Quantity Based</option>
                </select>
                <small class="text-muted" data-stock-behavior-hint></small>
            </div>
            <div class="form-group">
                <label>Description</label>
                <textarea name="description" rows="3" placeholder="Category description"></textarea>
            </div>
            <div class="form-group">
                <label>Status *</label>
                <select name="is_active" required>
                    <option value="true" selected>Active</option>
                    <option value="false">Inactive</option>
                </select>
            </div>
            <div class="modal-footer">
                <button type="button" class="btn btn-outline" onclick="closeModal()">Cancel</button>
                <button type="submit" class="btn btn-primary">Create Category</button>
            </div>
        </form>
    `);

    const addForm = document.getElementById('add-category-form');
    bindCategoryStockBehaviorHint(addForm);
    
    addForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        try {
            const formData = new FormData(e.target);
            const stockBehavior = formData.get('stock_behavior') || 'quantity';

            const data = {
                name: formData.get('name'),
                stock_behavior: stockBehavior,
                description: formData.get('description') || null,
                is_active: formData.get('is_active') === 'true'
            };

            await CategoriesAPI.create(data);
            closeModal();
            showToast('Category created successfully', 'success');
            loadCategories();
        } catch (error) {
            showToast(error.message, 'error');
        }
    });
}

async function editCategory(id) {
    try {
        const cat = categories.find(c => c.id === id);
        if (!cat) {
            showToast('Category not found', 'error');
            return;
        }
        
        openModal('Edit Category', `
            <form id="edit-category-form">
                <div class="form-group">
                    <label>Category Name *</label>
                    <input type="text" name="name" required value="${escapeHtml(cat.name)}" placeholder="e.g., Ultrasonic Flaw Detector, Couplant Gel, Cables">
                </div>
                <div class="form-group">
                    <label>Description</label>
                    <textarea name="description" rows="3" placeholder="Category description">${escapeHtml(cat.description || '')}</textarea>
                </div>
                <div class="form-group">
                    <label>Stock Input / Handling *</label>
                    <select name="stock_behavior" required data-initial-behavior="${cat.stock_behavior || 'quantity'}">
                        <option value="serialized" ${cat.stock_behavior === 'serialized' ? 'selected' : ''}>Serialized</option>
                        <option value="quantity" ${cat.stock_behavior !== 'serialized' ? 'selected' : ''}>Quantity Based</option>
                    </select>
                    <small class="text-muted" data-stock-behavior-hint></small>
                </div>
                <div class="form-group">
                    <label>Status *</label>
                    <select name="is_active" required>
                        <option value="true" ${cat.is_active ? 'selected' : ''}>Active</option>
                        <option value="false" ${!cat.is_active ? 'selected' : ''}>Inactive</option>
                    </select>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-outline" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary">Update Category</button>
                </div>
            </form>
        `);

        const editForm = document.getElementById('edit-category-form');
        bindCategoryStockBehaviorHint(editForm);
        editForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            try {
                const formData = new FormData(e.target);
                const nextBehavior = formData.get('stock_behavior') || 'quantity';
                const data = {
                    name: formData.get('name'),
                    stock_behavior: nextBehavior,
                    description: formData.get('description') || null,
                    is_active: formData.get('is_active') === 'true'
                };

                if (nextBehavior !== cat.stock_behavior && (cat.item_count || 0) > 0) {
                    const firstConfirm = confirm(`This category has ${cat.item_count} product(s). Changing its stock handling can move related records between Products and Stock Levels rules. Continue?`);
                    if (!firstConfirm) return;
                    const secondConfirm = confirm('Please confirm again. Existing products under this category will follow the selected stock handling workflow.');
                    if (!secondConfirm) return;
                    data.confirm_type_change = true;
                }

                await CategoriesAPI.update(id, data);
                closeModal();
                showToast('Category updated successfully', 'success');
                loadCategories();
            } catch (error) {
                showToast(error.message, 'error');
            }
        });
    } catch (error) {
        showToast('Error loading category: ' + error.message, 'error');
    }
}

async function deleteCategory(id) {
    const perms = getUserPermissions();
    if (!perms.canManageCategories) {
        showToast('Only Admin or General Manager can delete categories', 'error');
        return;
    }

    const cat = categories.find(c => c.id === id);
    if (!cat) {
        showToast('Category not found', 'error');
        return;
    }

    if ((cat.item_count || 0) > 0) {
        showToast(`Cannot delete "${cat.name}" because it has ${cat.item_count} item(s). Reassign items first.`, 'error');
        return;
    }

    if (confirm(`Delete category "${cat.name}"? It will be deactivated and hidden from active dropdowns.`)) {
        try {
            await CategoriesAPI.delete(id);
            showToast('Category deleted successfully', 'success');
            loadCategories();
        } catch (error) {
            showToast(error.message, 'error');
        }
    }
}

// Transfers
async function exportTransferStockRegisterXLSX() {
    try {
        showToast('Preparing stock register...', 'info');
        const params = new URLSearchParams({
            format: 'xlsx',
            include_zero_stock: 'true'
        });

        const token = TokenStorage.getAccessToken();
        const response = await API._fetch(`${API_BASE_URL}/reports/inventory/export?${params.toString()}`, {
            method: 'GET',
            headers: token ? { Authorization: `Bearer ${token}` } : {},
        }, true);

        if (!response.ok) {
            let message = 'Export failed';
            try {
                const body = await response.json();
                message = body.error?.message || body.detail || message;
            } catch (_) { /* non-JSON error response */ }
            throw new Error(message);
        }

        const blob = await response.blob();
        const disposition = response.headers.get('content-disposition') || '';
        const filenameMatch = disposition.match(/filename="?([^"]+)"?/i);
        const filename = filenameMatch ? filenameMatch[1] : `stock_register_${new Date().toISOString().slice(0,10)}.xlsx`;

        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        showToast('Stock register exported successfully', 'success');
    } catch (error) {
        showToast('Export failed: ' + error.message, 'error');
    }
}

async function loadTransfers() {
    try {
        const consumablesTbody = document.getElementById('transfers-table-body');
        const equipmentTbody = document.getElementById('equipment-transfers-table-body');

        if (!consumablesTbody && !equipmentTbody) {
            return;
        }

        if (consumablesTbody) {
            consumablesTbody.innerHTML = '<tr><td colspan="11" class="text-center text-muted">Loading quantity-based transfers...</td></tr>';
        }
        if (equipmentTbody) {
            equipmentTbody.innerHTML = '<tr><td colspan="13" class="text-center text-muted">Loading serialized transfers...</td></tr>';
        }

        // Admin/head-office sees all; others see only their own requests
        const currentUser = AuthAPI.getUser();
        const isAdmin = currentUser && (currentUser.role === 'admin' || currentUser.role === 'head_office_manager');
        let data;
        if (isAdmin) {
            data = await TransfersAPI.getAll({ page_size: 500 });
        } else {
            data = await TransfersAPI.getMyRequests();
        }
        const transfers = Array.isArray(data) ? data : (data.items || data.transfers || []);

        allTransfers = transfers;

        // Update view badge
        const badge = document.getElementById('view-badge-requests');
        if (badge) badge.textContent = transfers.length;

        // Reset filter inputs
        const searchEl = document.getElementById('transfers-search');
        if (searchEl) searchEl.value = '';
        const statusEl = document.getElementById('transfers-status-filter');
        if (statusEl) statusEl.value = '';
        const priorityEl = document.getElementById('transfers-priority-filter');
        if (priorityEl) priorityEl.value = '';

        renderTransfersTables(transfers);

        // Also load action badge count in background
        loadActionBadgeCount();
    } catch (error) {
        console.error('Transfers load error:', error);
        const errorMarkup = `
                <tr>
                    <td colspan="13" style="padding: 20px;">
                        <div style="background: #ffebee; border-radius: 8px; padding: 20px; color: #d32f2f;">
                            <strong><i class="fas fa-exclamation-circle"></i> Error Loading Transfers</strong>
                            <p style="margin: 10px 0;">${error.message}</p>
                            <button class="btn btn-sm btn-danger" onclick="loadTransfers()" style="margin-top: 10px;">
                                <i class="fas fa-redo"></i> Retry
                            </button>
                        </div>
                    </td>
                </tr>
            `;
        const consumablesTbody = document.getElementById('transfers-table-body');
        const equipmentTbody = document.getElementById('equipment-transfers-table-body');
        if (consumablesTbody) consumablesTbody.innerHTML = errorMarkup;
        if (equipmentTbody) equipmentTbody.innerHTML = errorMarkup;
    }
}

async function loadActionBadgeCount() {
    try {
        const data = await TransfersAPI.getForMyAction();
        const transfers = Array.isArray(data) ? data : (data.items || []);
        const pending = transfers.filter(t => ['requested', 'approved'].includes((t.status || '').toLowerCase())).length;
        const badge = document.getElementById('view-badge-action');
        if (badge) {
            badge.textContent = transfers.length;
            if (pending > 0) {
                badge.classList.add('has-items');
            } else {
                badge.classList.remove('has-items');
            }
        }
    } catch (_) {}
}

async function loadActionTransfers() {
    const container = document.getElementById('action-transfers-container');
    if (!container) return;

    container.innerHTML = `<div class="text-center" style="padding:40px;">
        <i class="fas fa-spinner fa-spin fa-2x text-muted"></i>
        <p class="text-muted mt-2">Loading...</p>
    </div>`;

    try {
        const data = await TransfersAPI.getForMyAction();
        allActionTransfers = Array.isArray(data) ? data : (data.items || []);

        // Update badge
        const badge = document.getElementById('view-badge-action');
        const pending = allActionTransfers.filter(t => ['requested', 'approved'].includes((t.status || '').toLowerCase())).length;
        if (badge) {
            badge.textContent = allActionTransfers.length;
            badge.classList.toggle('has-items', pending > 0);
        }

        renderActionTransfers(allActionTransfers);
    } catch (error) {
        container.innerHTML = `<div class="atc-empty">
            <i class="fas fa-exclamation-circle text-danger"></i>
            <p class="text-danger">Failed to load: ${error.message}</p>
            <button class="btn btn-sm btn-outline" onclick="loadActionTransfers()">Retry</button>
        </div>`;
    }
}

function filterActionTransfers() {
    const search = (document.getElementById('action-transfers-search')?.value || '').toLowerCase();
    const statusFilter = (document.getElementById('action-transfers-status-filter')?.value || '');
    let filtered = allActionTransfers;
    if (search) {
        filtered = filtered.filter(t =>
            (t.transfer_number || '').toLowerCase().includes(search) ||
            (t.from_location_name || '').toLowerCase().includes(search) ||
            (t.to_location_name || '').toLowerCase().includes(search) ||
            (Array.isArray(t.items) && t.items.some(i =>
                (i.item_name || '').toLowerCase().includes(search) ||
                (i.item_sku || '').toLowerCase().includes(search)
            ))
        );
    }
    if (statusFilter) {
        filtered = filtered.filter(t => (t.status || '').toLowerCase() === statusFilter);
    }
    renderActionTransfers(filtered);
}

function renderActionTransfers(transfers) {
    const container = document.getElementById('action-transfers-container');
    if (!container) return;

    if (!transfers || transfers.length === 0) {
        container.innerHTML = `<div class="atc-empty">
            <i class="fas fa-inbox"></i>
            <p>No transfers assigned to you requiring action.</p>
            <p style="font-size:12px; margin-top:8px;">When someone assigns a transfer request to you, it will appear here.</p>
        </div>`;
        return;
    }

    const formatShortDate = (val) => {
        if (!val) return '-';
        return new Date(val).toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' });
    };

    const statusConfig = {
        requested: { cls: 'badge-warning', icon: 'fa-clock', label: 'Awaiting Approval' },
        approved:  { cls: 'badge-info',    icon: 'fa-check', label: 'Ready to Dispatch' },
        in_transit: { cls: 'badge-info',   icon: 'fa-shipping-fast', label: 'In Transit' },
        received:  { cls: 'badge-success', icon: 'fa-check-circle', label: 'Received' },
        rejected:  { cls: 'badge-danger',  icon: 'fa-times-circle', label: 'Rejected' },
        cancelled: { cls: 'badge-danger',  icon: 'fa-ban', label: 'Cancelled' },
    };

    const priorityDot = (p) => {
        const key = (p || 'normal').toLowerCase();
        return `<span class="priority-dot ${key}" title="${key}"></span>`;
    };

    const cards = transfers.map(t => {
        const statusKey = (t.status || '').toLowerCase();
        const sc = statusConfig[statusKey] || { cls: 'badge-secondary', icon: 'fa-question', label: statusKey };
        const items = Array.isArray(t.items) ? t.items : [];

        const itemsHtml = items.length
            ? `<ul class="atc-items-list">${items.slice(0, 5).map(i =>
                `<li><strong>${i.item_name || i.item_sku || '-'}</strong> &times; ${i.quantity_requested || 0}${i.lot_number ? ` <span class="text-muted">(${i.lot_number})</span>` : ''}</li>`
              ).join('')}${items.length > 5 ? `<li class="text-muted">…and ${items.length - 5} more</li>` : ''}</ul>`
            : '<span class="text-muted" style="font-size:12px;">No items</span>';

        // Action buttons based on status
        let actionHtml = '';
        if (statusKey === 'requested') {
            actionHtml = `
                <button class="btn-approve" onclick="quickApproveTransfer('${t.id}')">
                    <i class="fas fa-check"></i> Approve
                </button>
                <button class="btn-reject" onclick="quickRejectTransfer('${t.id}')">
                    <i class="fas fa-times"></i> Reject
                </button>`;
        } else if (statusKey === 'approved') {
            actionHtml = `
                <button class="btn-dispatch" onclick="markTransferDispatched('${t.id}')">
                    <i class="fas fa-truck"></i> Mark Dispatched
                </button>`;
        } else if (statusKey === 'in_transit') {
            actionHtml = `<span class="badge-status badge-info"><i class="fas fa-shipping-fast"></i> Awaiting Receipt Confirmation</span>`;
        }

        const reqDate = t.requested_date || t.created_at;
        const requiredBy = t.required_by_date ? ` · Required by <strong>${formatShortDate(t.required_by_date)}</strong>` : '';

        return `<div class="action-transfer-card status-${statusKey}">
            <div class="atc-header">
                <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
                    ${priorityDot(t.priority)}
                    <span class="atc-number">${t.transfer_number || '-'}</span>
                    ${t.purchase_indent_number ? `<span class="atc-pi">PI: ${t.purchase_indent_number}</span>` : ''}
                    <span class="badge-status ${sc.cls}"><i class="fas ${sc.icon}"></i> ${sc.label}</span>
                    <span class="badge-status" style="background:var(--neutral-15);color:var(--text-secondary);">
                        ${isSerializedTransferType(t.transfer_type) ? '<i class="fas fa-tools"></i> Serialized' : '<i class="fas fa-boxes"></i> Quantity Based'} (${transferTypeLabel(t.transfer_type)})
                    </span>
                </div>
                <div class="atc-meta">
                    <span title="Requested date"><i class="fas fa-calendar-alt"></i> ${formatShortDate(reqDate)}</span>
                    ${requiredBy}
                </div>
            </div>

            <div class="atc-body">
                <div>
                    <div class="atc-section-label">Route</div>
                    <div class="atc-route">
                        <span>${t.from_location_name || '-'}</span>
                        <span class="route-arrow"><i class="fas fa-long-arrow-alt-right"></i></span>
                        <span>${t.to_location_name || '-'}</span>
                    </div>
                    <div class="atc-requester" style="margin-top:6px;">
                        <i class="fas fa-user" style="opacity:.5;"></i> Requested by <strong>${t.requested_by_name || 'Unknown'}</strong>
                    </div>
                </div>
                <div>
                    <div class="atc-section-label">Items (${items.length})</div>
                    ${itemsHtml}
                </div>
                ${t.request_notes ? `<div style="grid-column:1/-1;">
                    <div class="atc-section-label">Notes</div>
                    <div class="atc-notes">${t.request_notes}</div>
                </div>` : ''}
            </div>

            <div class="atc-footer">
                <div class="atc-action-group">
                    ${actionHtml}
                    <button class="btn btn-sm btn-outline" onclick="viewTransfer('${t.id}')" title="View full details">
                        <i class="fas fa-eye"></i> View Details
                    </button>
                    ${t.purchase_indent_id
                        ? `<button class="btn btn-sm btn-outline" onclick="viewPurchaseIndent('${t.purchase_indent_id}')" title="Purchase Indent">
                            <i class="fas fa-file-alt"></i> PI
                           </button>` : ''}
                    ${['approved','in_transit','received','partially_received'].includes(statusKey)
                        ? `<button class="btn btn-sm btn-outline" onclick="printDeliveryChallan('${t.id}')" title="Delivery Challan">
                            <i class="fas fa-file-invoice"></i> DC
                           </button>` : ''}
                </div>
                <div style="font-size:11px;color:var(--text-muted);">
                    Transfer #${t.transfer_number || '-'}
                </div>
            </div>
        </div>`;
    });

    container.innerHTML = `<div class="action-transfers-grid">${cards.join('')}</div>`;
}

async function quickApproveTransfer(transferId) {
    let notes = '';
    const swal = window.Swal;
    if (swal?.fire) {
        const result = await swal.fire({
            title: 'Approve Transfer',
            input: 'textarea',
            inputLabel: 'Notes (optional)',
            inputPlaceholder: 'Add any approval notes...',
            showCancelButton: true,
            confirmButtonText: '<i class="fas fa-check"></i> Approve',
            confirmButtonColor: '#16a34a',
            cancelButtonText: 'Cancel',
        });
        if (!result.isConfirmed) return;
        notes = result.value || '';
    } else {
        if (!confirm('Approve this transfer?')) return;
    }

    try {
        await TransfersAPI.approve(transferId, { notes: notes || null });
        showToast('Transfer approved successfully', 'success');
        await loadActionTransfers();
        await loadTransfers();
    } catch (err) {
        showToast('Failed to approve: ' + err.message, 'error');
    }
}

async function permanentlyDeleteCategory(id, encodedName) {
    const name = decodeURIComponent(encodedName || 'category');
    if (!confirm(`Permanently delete category "${name}"? This action cannot be undone. If products reference it, deletion will be blocked.`)) return;
    try {
        await CategoriesAPI.permanentDelete(id);
        categories = categories.filter(category => category.id !== id);
        renderCategoriesTable(categories);
        showToast('Category permanently deleted', 'success');
        await loadCategories();
    } catch (error) {
        const message = error.message || 'Failed to permanently delete category';
        if (!message.includes('items')) {
            showToast(message, 'error');
            return;
        }
        const warning = `${message}\n\nDelete this category and ALL linked product data anyway? This includes stock balances, lots, serialized products, calibration and maintenance records, inventory transactions, transfer lines, purchase-indent lines, and attributes. Audit logs will remain. This action cannot be undone.`;
        if (!confirm(warning)) return;
        try {
            await CategoriesAPI.permanentDelete(id, true);
            categories = categories.filter(category => category.id !== id);
            renderCategoriesTable(categories);
            showToast('Category and all linked product data permanently deleted', 'success');
            await loadCategories();
        } catch (forceError) {
            showToast(forceError.message || 'Failed to permanently delete category', 'error');
        }
    }
}

async function permanentlyDeleteLocation(locationId) {
    const location = locations.find(loc => loc.id === locationId);
    if (!confirm(`Permanently delete location "${location?.name || locationId}"? This action cannot be undone.`)) return;
    try {
        await LocationsAPI.permanentDelete(locationId);
        locations = locations.filter(loc => loc.id !== locationId);
        renderLocationsGrid(locations);
        showToast('Location permanently deleted', 'success');
        await loadLocations();
    } catch (error) { showToast(error.message || 'Failed to permanently delete location', 'error'); }
}

async function quickRejectTransfer(transferId) {
    let reason = '';
    const swal = window.Swal;
    if (swal?.fire) {
        const result = await swal.fire({
            title: 'Reject Transfer',
            input: 'textarea',
            inputLabel: 'Reason for rejection *',
            inputPlaceholder: 'Explain why this transfer is being rejected...',
            showCancelButton: true,
            confirmButtonText: '<i class="fas fa-times"></i> Reject',
            confirmButtonColor: '#dc2626',
            cancelButtonText: 'Cancel',
            inputValidator: (value) => {
                if (!value?.trim()) return 'Please provide a rejection reason';
            }
        });
        if (!result.isConfirmed || !result.value?.trim()) return;
        reason = result.value.trim();
    } else {
        reason = prompt('Reason for rejection (required):') || '';
        if (!reason.trim()) return;
    }

    try {
        await TransfersAPI.reject(transferId, { rejection_reason: reason });
        showToast('Transfer rejected', 'warning');
        await loadActionTransfers();
        await loadTransfers();
    } catch (err) {
        showToast('Failed to reject: ' + err.message, 'error');
    }
}

async function markTransferDispatched(transferId) {
    let dispatchData = {};
    const swal = window.Swal;
    if (swal?.fire) {
        const result = await swal.fire({
            title: 'Mark as Dispatched',
            html: `<div style="text-align:left">
                <label style="font-size:13px;font-weight:600;display:block;margin-bottom:4px;">Tracking / Reference (optional)</label>
                <input id="dispatch-tracking" class="swal2-input" placeholder="e.g. DTDC-12345">
                <label style="font-size:13px;font-weight:600;display:block;margin-top:12px;margin-bottom:4px;">Shipping Method (optional)</label>
                <input id="dispatch-method" class="swal2-input" placeholder="e.g. Courier, Hand Delivery">
                <label style="font-size:13px;font-weight:600;display:block;margin-top:12px;margin-bottom:4px;">Notes (optional)</label>
                <textarea id="dispatch-notes" class="swal2-textarea" placeholder="Any notes..."></textarea>
            </div>`,
            showCancelButton: true,
            confirmButtonText: '<i class="fas fa-truck"></i> Mark Dispatched',
            confirmButtonColor: '#2563eb',
            cancelButtonText: 'Cancel',
            preConfirm: () => ({
                tracking_number: document.getElementById('dispatch-tracking')?.value || null,
                shipping_method: document.getElementById('dispatch-method')?.value || null,
                notes: document.getElementById('dispatch-notes')?.value || null,
            })
        });
        if (!result.isConfirmed) return;
        dispatchData = result.value || {};
    } else {
        if (!confirm('Mark this transfer as dispatched?')) return;
    }

    try {
        await TransfersAPI.ship(transferId, dispatchData);
        showToast('Transfer marked as dispatched', 'success');
        await loadActionTransfers();
        await loadTransfers();
    } catch (err) {
        showToast('Failed to mark dispatched: ' + err.message, 'error');
    }
}

async function showCreateTransferModal(preselectedItemId) {
    try {
        transferSourceAvailableItemIds = new Set();
        // Load locations and items (no need to fetch PIs — auto-created on submit)
        const [sourceLocationsData, destinationLocationsData, itemsData] = await Promise.all([
            LocationsAPI.getTransferSources().catch(() => LocationsAPI.getAll({ is_active: true })),
            LocationsAPI.getTransferDestinations().catch(() => LocationsAPI.getAll({ is_active: true })),
            ItemsAPI.getAllPages(),
        ]);

        const sourceLocations = activeRecords(Array.isArray(sourceLocationsData) ? sourceLocationsData : (sourceLocationsData.items || []));
        const allDestinationLocations = activeRecords(Array.isArray(destinationLocationsData) ? destinationLocationsData : (destinationLocationsData.items || []));
        const transferUser = AuthAPI.getUser();
        const assignedLocationIds = new Set(transferUser?.assigned_location_ids || []);
        const destinationLocations = transferUser?.role === 'location_manager'
            ? allDestinationLocations.filter(loc => assignedLocationIds.has(loc.id))
            : allDestinationLocations;
        const items = Array.isArray(itemsData) ? itemsData : (itemsData.items || []);

        transferItemMetadata = {};
        allTransferItems = items;
        items.forEach(item => {
            transferItemMetadata[item.id] = {
                is_serialized: !!item.is_serialized,
                stock_behavior: item.stock_behavior,
                asset_type: item.asset_type,
                category_name: item.category_name,
                category_type_key: item.category_type_key,
                sku: item.sku,
                name: item.name,
            };
        });

        const consumableItems = items.filter(i => itemMatchesTransferType(i, 'consumable'));

        function buildItemOptions(filteredItems) {
            if (filteredItems.length === 0) {
                return '<option value="" disabled>No items available for this type</option>';
            }
            return '<option value="">Select item</option>' +
                filteredItems.map(item =>
                    `<option value="${item.id}">${item.sku ? `${escapeHtml(item.sku)} - ` : ''}${escapeHtml(item.name)}</option>`
                ).join('');
        }

        // Expose to outer scope for addTransferItem
        window._currentTransferItemOptions = '<option value="" disabled>Select a source location first</option>';
        
        const modalTitle = document.getElementById('modal-title');
        const modalBody = document.getElementById('modal-body');
        
        modalTitle.textContent = 'Create Transfer Request';
        
        modalBody.innerHTML = `
            <form id="create-transfer-form">
                <div class="form-row">
                    <div class="form-group">
                        <label for="from_location_id">From Location *</label>
                        <select id="from_location_id" name="from_location_id" class="form-select" required>
                            <option value="">Select source location</option>
                            ${sourceLocations.map(loc => `<option value="${loc.id}">${loc.name} (${loc.code || '-'})</option>`).join('')}
                        </select>
                    </div>
                    <div class="form-group">
                        <label for="to_location_id">To Location *</label>
                        <select id="to_location_id" name="to_location_id" class="form-select" required>
                            <option value="">Select destination location</option>
                            ${destinationLocations.map(loc => `<option value="${loc.id}">${loc.name} (${loc.code || '-'})</option>`).join('')}
                        </select>
                    </div>
                </div>

                <!-- Assigned To — loads dynamically after From Location is selected -->
                <div class="form-group" id="assigned-to-group" style="display:none;">
                    <label for="assigned_to_id">
                        Assign To (Responsible Person at Source) *
                        <span style="font-weight:400;font-size:12px;color:var(--text-muted);">Who at the source location will handle this request?</span>
                    </label>
                    <select id="assigned_to_id" name="assigned_to_id" class="form-select" required>
                        <option value="">Loading users...</option>
                    </select>
                    <div id="assigned-to-hint" style="font-size:12px;color:var(--text-muted);margin-top:4px;"></div>
                </div>

                <div class="form-group" id="destination-responsible-group" style="display:none;">
                    <label for="destination_responsible_id">
                        Responsible Person at Destination
                    </label>
                    <select id="destination_responsible_id" name="destination_responsible_id" class="form-select">
                        <option value="">Select destination first</option>
                    </select>
                    <div id="destination-responsible-hint" style="font-size:12px;color:var(--text-muted);margin-top:4px;"></div>
                </div>

                <div class="form-group" id="local-receiving-group" style="display:none;">
                    <label for="local_receiving_details">Receiving Area / Person inside Same Location *</label>
                    <input type="text" id="local_receiving_details" name="local_receiving_details" class="form-control" placeholder="e.g., Lab bench, dark room, field kit, technician name">
                </div>
                
                <div class="form-row">
                    <div class="form-group">
                        <label for="transfer_type">Transfer Type *</label>
                        <select id="transfer_type" name="transfer_type" class="form-select" required>
                            <option value="consumable" selected>Consumable</option>
                            <option value="accessory">Accessory</option>
                            <option value="equipment">Equipment</option>
                            <option value="instrument">Instrument</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label for="priority">Priority</label>
                        <select id="priority" name="priority" class="form-select">
                            <option value="low">Low</option>
                            <option value="normal" selected>Normal</option>
                            <option value="high">High</option>
                            <option value="urgent">Urgent</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label for="required_by_date">Required By</label>
                        <input type="date" id="required_by_date" name="required_by_date" class="form-control">
                    </div>
                    <div class="form-group" id="return-date-group">
                        <label for="return_date">Expected Return Date</label>
                        <input type="date" id="return_date" name="return_date" class="form-control">
                        <div style="margin-top:8px;">
                            <label for="return_reminder_days">Remind Before (days)</label>
                            <input type="number" id="return_reminder_days" name="return_reminder_days" class="form-control" min="1" max="365" value="3" placeholder="e.g. 3" style="max-width:120px;">
                            <small class="text-muted">You'll receive notifications this many days before the return date</small>
                        </div>
                    </div>
                </div>
                
                <div class="form-group">
                    <label for="request_notes">Request Notes</label>
                    <textarea id="request_notes" name="request_notes" class="form-control" rows="2" placeholder="Optional notes about this transfer request"></textarea>
                </div>
                
                <!-- Purchase Indent is auto-created when the transfer is submitted -->
                <div class="pi-auto-info">
                    <i class="fas fa-info-circle"></i>
                    A Purchase Indent (PI) will be automatically generated and sent to the
                    supplying location's manager for review and approval.
                </div>
                
                <div class="form-group">
                    <label>Items to Transfer *</label>
                    <p id="transfer-item-type-hint" class="text-muted" style="font-size:12px;margin:2px 0 6px;">Showing quantity-based consumable items</p>
                    <div id="transfer-items-container">
                        <div class="transfer-item-row">
                            <select class="form-select item-select" required>
                                <option value="" disabled>Select a source location first</option>
                            </select>
                            <input type="text" class="form-control batch-input" placeholder="Batch No" style="max-width:120px;">
                            <input type="number" class="form-control quantity-input" placeholder="Qty" min="1" required>
                            <button type="button" class="btn btn-danger btn-sm" onclick="removeTransferItem(this)" disabled>
                                <i class="fas fa-trash"></i>
                            </button>
                            <div class="transfer-stock-info">
                                Select a source location and item to check available stock.
                            </div>
                        </div>
                    </div>
                    <button type="button" class="btn btn-secondary btn-sm" onclick="addTransferItem()" style="margin-top: 10px;">
                        <i class="fas fa-plus"></i> Add Item
                    </button>
                </div>
                
                <div class="modal-actions">
                    <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary">
                        <i class="fas fa-check"></i> Create Transfer
                    </button>
                </div>
            </form>
        `;
        
        // Show modal
        document.getElementById('modal-overlay').classList.remove('hidden');
        
        // Handle form submission
        document.getElementById('create-transfer-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            await withSubmitLock(e.target, () => handleCreateTransfer(e.target));
        });

        const transferTypeEl = document.getElementById('transfer_type');
        transferTypeEl.addEventListener('change', () => {
            applyTransferTypeFilter(transferTypeEl.value);
        });

        // From-location change: load users at that location for "Assign To" dropdown
        const fromLocEl = document.getElementById('from_location_id');
        const assignedToGroup = document.getElementById('assigned-to-group');
        const assignedToSelect = document.getElementById('assigned_to_id');
        const assignedToHint = document.getElementById('assigned-to-hint');
        const toLocEl = document.getElementById('to_location_id');
        const destinationResponsibleGroup = document.getElementById('destination-responsible-group');
        const destinationResponsibleSelect = document.getElementById('destination_responsible_id');
        const destinationResponsibleHint = document.getElementById('destination-responsible-hint');
        const transferItemsContainer = document.getElementById('transfer-items-container');
        const localReceivingGroup = document.getElementById('local-receiving-group');
        const localReceivingInput = document.getElementById('local_receiving_details');
        const locationUsersCache = new Map();

        const getUsersForLocation = async (locId) => {
            if (!locId) return [];
            if (locationUsersCache.has(locId)) {
                return locationUsersCache.get(locId);
            }
            const users = await UsersAPI.getByLocation(locId);
            const scopedUsers = Array.isArray(users) ? users : [];
            locationUsersCache.set(locId, scopedUsers);
            return scopedUsers;
        };

        const renderLocationUserSelect = async ({
            locId,
            groupEl,
            selectEl,
            hintEl,
            emptyLabel,
            emptyHint,
            loadingLabel,
            placeholderLabel,
            includeDataName = false,
        }) => {
            if (!locId) {
                groupEl.style.display = 'none';
                selectEl.innerHTML = '<option value="">Select location first</option>';
                hintEl.textContent = '';
                return;
            }

            groupEl.style.display = '';
            selectEl.innerHTML = `<option value="">${loadingLabel}</option>`;
            hintEl.textContent = '';

            try {
                const users = await getUsersForLocation(locId);
                if (!users.length) {
                    selectEl.innerHTML = `<option value="">${emptyLabel}</option>`;
                    hintEl.textContent = emptyHint;
                    return;
                }

                selectEl.innerHTML = `<option value="">${placeholderLabel}</option>` +
                    users.map(u => {
                        const roleLabel = ROLE_LABELS[u.role] || String(u.role || '').replace(/_/g, ' ');
                        const dataName = includeDataName ? ` data-name="${escapeHtml(u.name)}"` : '';
                        return `<option value="${u.id}"${dataName}>${escapeHtml(u.name)} (${escapeHtml(roleLabel)})</option>`;
                    }).join('');
                hintEl.textContent = `${users.length} user${users.length > 1 ? 's' : ''} found at this location.`;
            } catch (e) {
                selectEl.innerHTML = '<option value="">Could not load users</option>';
                hintEl.textContent = '';
            }
        };

        const loadSourceUsers = () => renderLocationUserSelect({
            locId: fromLocEl.value,
            groupEl: assignedToGroup,
            selectEl: assignedToSelect,
            hintEl: assignedToHint,
            emptyLabel: 'No users assigned to this location',
            emptyHint: 'No users found for the selected source location.',
            loadingLabel: 'Loading users...',
            placeholderLabel: 'Select responsible person',
        });

        const loadDestinationUsers = () => renderLocationUserSelect({
            locId: toLocEl.value,
            groupEl: destinationResponsibleGroup,
            selectEl: destinationResponsibleSelect,
            hintEl: destinationResponsibleHint,
            emptyLabel: 'No users assigned to destination',
            emptyHint: 'No users found for the selected destination location.',
            loadingLabel: 'Loading users...',
            placeholderLabel: 'Select destination responsible person',
            includeDataName: true,
        });

        const syncLocalReceivingDetails = () => {
            const sameLocation = fromLocEl.value && toLocEl.value && fromLocEl.value === toLocEl.value;
            localReceivingGroup.style.display = sameLocation ? '' : 'none';
            localReceivingInput.required = sameLocation;
            if (!sameLocation) localReceivingInput.value = '';
        };

        fromLocEl.addEventListener('change', async () => {
            transferStockAvailabilityCache = new Map();
            transferComplianceBlockerCache = new Map();
            transferSourceAvailableItemIds = new Set();
            applyTransferTypeFilter(transferTypeEl.value);
            syncLocalReceivingDetails();
            if (fromLocEl.value) {
                try {
                    const options = await StockAPI.getTransferOptions(fromLocEl.value);
                    transferSourceAvailableItemIds = new Set(options.item_ids || []);
                } catch (error) {
                    showToast(error.message || 'Could not load available source items', 'error');
                }
            }
            applyTransferTypeFilter(transferTypeEl.value);
            await Promise.all([loadSourceUsers(), loadDestinationUsers()]);
        });

        toLocEl.addEventListener('change', async () => {
            syncLocalReceivingDetails();
            await loadDestinationUsers();
        });

        transferItemsContainer.addEventListener('change', (event) => {
            if (event.target.matches('.item-select')) {
                updateTransferRowStockAvailability(event.target.closest('.transfer-item-row'));
            }
        });

        transferItemsContainer.addEventListener('input', (event) => {
            if (event.target.matches('.quantity-input')) {
                updateTransferRowStockAvailability(event.target.closest('.transfer-item-row'));
            }
        });
        syncLocalReceivingDetails();
        if (fromLocEl.value) loadSourceUsers();
        if (toLocEl.value) loadDestinationUsers();
        applyTransferTypeFilter(transferTypeEl.value);
        
        // Pre-select item if provided (from Products page quick transfer)
        if (preselectedItemId) {
            const meta = transferItemMetadata[preselectedItemId];
            if (meta) {
                // Set correct transfer type 
                if (meta.is_serialized) {
                    const preselectedType = normalizeTypeKey(meta.asset_type) === 'instrument' ? 'instrument' : 'equipment';
                    transferTypeEl.value = preselectedType;
                    applyTransferTypeFilter(preselectedType);
                }
                // Select the item in the first row
                const firstSelect = document.querySelector('#transfer-items-container .item-select');
                if (firstSelect) {
                    firstSelect.value = preselectedItemId;
                    updateTransferRowStockAvailability(firstSelect.closest('.transfer-item-row'));
                }
            }
        }
    } catch (error) {
        console.error('Error loading transfer form:', error);
        showToast('Failed to load transfer form: ' + error.message, 'error');
    }
}

function applyTransferTypeFilter(transferType) {
    const isSerializedType = isSerializedTransferType(transferType);
    const isReturnableType = isReturnableTransferType(transferType);
    const filteredItems = allTransferItems.filter(i =>
        itemMatchesTransferType(i, transferType) && transferSourceAvailableItemIds.has(i.id)
    );
    const returnDateGroup = document.getElementById('return-date-group');
    const returnDateInput = document.getElementById('return_date');
    const returnReminderInput = document.getElementById('return_reminder_days');

    if (returnDateGroup) {
        returnDateGroup.style.display = isReturnableType ? '' : 'none';
    }
    if (!isReturnableType) {
        if (returnDateInput) returnDateInput.value = '';
        if (returnReminderInput) returnReminderInput.value = '';
    } else if (returnReminderInput && !returnReminderInput.value) {
        returnReminderInput.value = '3';
    }

    let optionsHTML;
    if (filteredItems.length === 0) {
        optionsHTML = '<option value="" disabled>No available items at the selected source for this type</option>';
    } else {
        optionsHTML = '<option value="">Select item</option>' +
            filteredItems.map(item =>
                `<option value="${item.id}">${item.sku ? `${escapeHtml(item.sku)} - ` : ''}${escapeHtml(item.name)}</option>`
            ).join('');
    }

    // Cache for addTransferItem
    window._currentTransferItemOptions = optionsHTML;

    // Rebuild every existing item select
    document.querySelectorAll('#transfer-items-container .item-select').forEach(select => {
        const previousValue = select.value;
        select.innerHTML = optionsHTML;
        if (previousValue && Array.from(select.options).some(opt => opt.value === previousValue)) {
            select.value = previousValue;
        }
    });

    document.querySelectorAll('#transfer-items-container .transfer-item-row').forEach(row => {
        const batchInput = row.querySelector('.batch-input');
        const quantityInput = row.querySelector('.quantity-input');
        if (batchInput) {
            batchInput.style.display = isSerializedType ? 'none' : '';
            batchInput.value = isSerializedType ? '' : batchInput.value;
        }
        if (quantityInput) {
            quantityInput.value = isSerializedType ? '1' : quantityInput.value;
            quantityInput.readOnly = isSerializedType;
            quantityInput.title = isSerializedType ? 'Serialized items are transferred one unit per serial number' : '';
        }
    });

    // Update hint text
    const hint = document.getElementById('transfer-item-type-hint');
    if (hint) {
        hint.textContent = isSerializedType
            ? `Showing ${filteredItems.length} serialized ${transferTypeLabel(transferType).toLowerCase()} item(s)`
            : `Showing ${filteredItems.length} quantity-based ${transferTypeLabel(transferType).toLowerCase()} item(s)`;
    }

    refreshTransferStockAvailability();
}

function ensureTransferStockInfo(row) {
    let infoEl = row.querySelector('.transfer-stock-info');
    if (!infoEl) {
        infoEl = document.createElement('div');
        infoEl.className = 'transfer-stock-info';
        row.appendChild(infoEl);
    }
    return infoEl;
}

function setTransferStockInfo(infoEl, status, message) {
    infoEl.className = `transfer-stock-info ${status ? `is-${status}` : ''}`.trim();
    infoEl.textContent = message;
}

function transferStockCacheKey(itemId, locationId) {
    return `${itemId || ''}::${locationId || ''}`;
}

async function getTransferStockAvailability(itemId, locationId) {
    const key = transferStockCacheKey(itemId, locationId);
    if (transferStockAvailabilityCache.has(key)) {
        return transferStockAvailabilityCache.get(key);
    }
    const availability = await StockAPI.getAvailable(itemId, locationId);
    transferStockAvailabilityCache.set(key, availability);
    return availability;
}

function transferComplianceCacheKey(locationId) {
    return locationId || '';
}

async function getTransferComplianceBlockers(locationId) {
    const key = transferComplianceCacheKey(locationId);
    if (transferComplianceBlockerCache.has(key)) {
        return transferComplianceBlockerCache.get(key);
    }

    const overview = await TransfersAPI.getEquipmentOverview({ location_id: locationId });
    const blockerMap = {};
    [...(overview.calibration_issues || []), ...(overview.maintenance_issues || [])].forEach(item => {
        if (!item.can_transfer && item.item_id) {
            const existingReasons = blockerMap[item.item_id]?.reasons || [];
            blockerMap[item.item_id] = {
                item_id: item.item_id,
                item_name: item.item_name,
                item_sku: item.item_sku,
                reasons: Array.from(new Set([...existingReasons, ...(item.blocked_reasons || [])])),
            };
        }
    });

    transferComplianceBlockerCache.set(key, blockerMap);
    return blockerMap;
}

async function updateTransferRowStockAvailability(row) {
    const infoEl = ensureTransferStockInfo(row);
    const itemSelect = row.querySelector('.item-select');
    const quantityInput = row.querySelector('.quantity-input');
    const fromLocationId = document.getElementById('from_location_id')?.value || '';
    const itemId = itemSelect?.value || '';
    const quantity = parseInt(quantityInput?.value || '0', 10) || 0;

    row.dataset.availableStock = '';
    row.dataset.complianceBlocked = '';
    row.dataset.complianceReason = '';
    if (quantityInput) {
        quantityInput.removeAttribute('max');
    }

    if (!fromLocationId || !itemId) {
        setTransferStockInfo(
            infoEl,
            'muted',
            !fromLocationId
                ? 'Select a source location to check available stock.'
                : 'Select an item to check available stock.'
        );
        return null;
    }

    setTransferStockInfo(infoEl, 'muted', 'Checking available stock...');

    try {
        const res = await getTransferStockAvailability(itemId, fromLocationId);
        const onHand = Number(res.on_hand || 0);
        const reserved = Number(res.reserved || 0);
        const available = Number(res.available || 0);
        const meta = transferItemMetadata[itemId] || {};
        const itemLabel = meta.sku || itemSelect?.selectedOptions?.[0]?.textContent || 'Selected item';
        const shouldCheckCompliance = meta.is_serialized || isSerializedTransferType(document.getElementById('transfer_type')?.value || '');

        row.dataset.availableStock = String(available);
        if (quantityInput && available > 0) {
            quantityInput.max = String(available);
        }

        if (available > 0 && shouldCheckCompliance) {
            try {
                const blockers = await getTransferComplianceBlockers(fromLocationId);
                const blocker = blockers[itemId];
                if (blocker) {
                    const reason = blocker.reasons.join('; ') || 'Calibration or maintenance is pending';
                    row.dataset.complianceBlocked = 'true';
                    row.dataset.complianceReason = reason;
                    setTransferStockInfo(
                        infoEl,
                        'error',
                        `Transfer blocked: ${reason}. Stock available: ${available} | On hand: ${onHand} | Reserved: ${reserved}`
                    );
                    return { onHand, reserved, available, itemLabel, complianceBlocked: true, complianceReason: reason };
                }
            } catch (error) {
                console.warn('Transfer compliance lookup failed:', error);
            }
        }

        if (available <= 0) {
            setTransferStockInfo(
                infoEl,
                'error',
                `No stock at selected source. On hand: ${onHand} | Reserved: ${reserved} | Available: 0`
            );
        } else if (quantity > available) {
            setTransferStockInfo(
                infoEl,
                'warning',
                `Only ${available} available. On hand: ${onHand} | Reserved: ${reserved} | Requested: ${quantity}`
            );
        } else {
            setTransferStockInfo(
                infoEl,
                'ok',
                `Available at source: ${available} | On hand: ${onHand} | Reserved: ${reserved}`
            );
        }
        return { onHand, reserved, available, itemLabel, complianceBlocked: false };
    } catch (error) {
        console.error('Transfer stock lookup failed:', error);
        setTransferStockInfo(infoEl, 'warning', 'Could not check available stock for this item.');
        return null;
    }
}

function refreshTransferStockAvailability() {
    document.querySelectorAll('#transfer-items-container .transfer-item-row').forEach(row => {
        updateTransferRowStockAvailability(row);
    });
}

async function validateTransferStockAvailability(itemRows, fromLocationId) {
    for (const row of itemRows) {
        const itemId = row.querySelector('.item-select')?.value || '';
        const quantity = parseInt(row.querySelector('.quantity-input')?.value || '0', 10) || 0;
        if (!itemId || quantity <= 0) continue;

        const availability = await getTransferStockAvailability(itemId, fromLocationId);
        const onHand = Number(availability.on_hand || 0);
        const reserved = Number(availability.reserved || 0);
        const available = Number(availability.available || 0);
        const meta = transferItemMetadata[itemId] || {};
        const itemLabel = meta.sku || row.querySelector('.item-select')?.selectedOptions?.[0]?.textContent || 'Selected item';

        await updateTransferRowStockAvailability(row);

        if (row.dataset.complianceBlocked === 'true') {
            showToast(`Transfer blocked for ${itemLabel}: ${row.dataset.complianceReason || 'Calibration or maintenance is pending'}.`, 'error');
            return false;
        }
        if (available <= 0) {
            showToast(`No stock available for ${itemLabel} at the selected source. On hand: ${onHand}, reserved: ${reserved}.`, 'error');
            return false;
        }
        if (quantity > available) {
            showToast(`Only ${available} available for ${itemLabel}; requested ${quantity}.`, 'error');
            return false;
        }
    }
    return true;
}

function addTransferItem() {
    const container = document.getElementById('transfer-items-container');
    const itemRows = container.querySelectorAll('.transfer-item-row');

    // Use cached filtered options for current transfer type
    const optionsHTML = window._currentTransferItemOptions || '<option value="">Select item</option>';

    const newRow = document.createElement('div');
    newRow.className = 'transfer-item-row';
    newRow.innerHTML = `
        <select class="form-select item-select" required>${optionsHTML}</select>
        <input type="text" class="form-control batch-input" placeholder="Batch No" style="max-width:120px;">
        <input type="number" class="form-control quantity-input" placeholder="Qty" min="1" required>
        <button type="button" class="btn btn-danger btn-sm" onclick="removeTransferItem(this)">
            <i class="fas fa-trash"></i>
        </button>
        <div class="transfer-stock-info">
            Select an item to check available stock.
        </div>
    `;

    container.appendChild(newRow);
    const transferType = document.getElementById('transfer_type')?.value || 'consumable';
    applyTransferTypeFilter(transferType);
    updateTransferRowStockAvailability(newRow);

    // Enable delete button on first row if there are now multiple rows
    if (itemRows.length === 1) {
        itemRows[0].querySelector('.btn-danger').disabled = false;
    }
}

function removeTransferItem(button) {
    const container = document.getElementById('transfer-items-container');
    const row = button.closest('.transfer-item-row');
    row.remove();
    
    // Disable delete button on first row if only one row remains
    const remainingRows = container.querySelectorAll('.transfer-item-row');
    if (remainingRows.length === 1) {
        remainingRows[0].querySelector('.btn-danger').disabled = true;
    }
}

function dateInputToIsoEndOfDay(dateValue) {
    if (!dateValue) return null;
    const [year, month, day] = dateValue.split('-').map(Number);
    if (!year || !month || !day) return null;
    return new Date(year, month - 1, day, 23, 59, 59, 999).toISOString();
}

async function handleCreateTransfer(form) {
    try {
        const formData = new FormData(form);
        const container = document.getElementById('transfer-items-container');
        const itemRows = container.querySelectorAll('.transfer-item-row');
        const transferType = formData.get('transfer_type') || 'consumable';
        
        // Build items array
        const items = [];
        itemRows.forEach(row => {
            const itemId = row.querySelector('.item-select').value;
            const quantity = parseInt(row.querySelector('.quantity-input').value);
            const batchInput = row.querySelector('.batch-input');
            const batchNo = batchInput ? batchInput.value.trim() : '';
            
            if (itemId && quantity > 0) {
                const itemObj = {
                    item_id: itemId,
                    quantity_requested: quantity
                };
                if (batchNo) {
                    itemObj.lot_number = batchNo;
                }
                items.push(itemObj);
            }
        });
        
        if (items.length === 0) {
            showToast('Please add at least one item to transfer', 'error');
            return;
        }

        const fromLocationId = formData.get('from_location_id');
        const toLocationId = formData.get('to_location_id');

        const invalidTypeItem = items.find(item => {
            const meta = transferItemMetadata[item.item_id];
            if (!meta) return false;
            return !itemMatchesTransferType(meta, transferType);
        });

        if (invalidTypeItem) {
            showToast(
                `${transferTypeLabel(transferType)} transfer allows only matching ${isSerializedTransferType(transferType) ? 'serialized' : 'quantity-based'} items.`,
                'error'
            );
            return;
        }

        // Check for blocked equipment items
        if (isSerializedTransferType(transferType)) {
            try {
                const blockers = await getTransferComplianceBlockers(fromLocationId);
                const blockedItem = items.find(i => blockers[i.item_id]);
                if (blockedItem) {
                    const meta = transferItemMetadata[blockedItem.item_id];
                    const reason = blockers[blockedItem.item_id]?.reasons?.join('; ') || 'Calibration or maintenance is pending';
                    showToast(`Transfer blocked for "${meta?.name || 'item'}": ${reason}`, 'error');
                    return;
                }
            } catch (e) {
                console.warn('Could not check blocked equipment:', e);
            }
        }
        
        const destinationResponsibleSelect = form.querySelector('[name="destination_responsible_id"]');
        const destinationResponsibleId = destinationResponsibleSelect?.value || '';
        const localReceivingDetails = (formData.get('local_receiving_details') || '').trim();

        if (fromLocationId === toLocationId && !destinationResponsibleId) {
            showToast('Select a destination responsible person for same-location local transfers', 'error');
            return;
        }
        if (fromLocationId === toLocationId && !localReceivingDetails) {
            showToast('Enter the receiving area/person inside the same location', 'error');
            return;
        }

        const stockIsAvailable = await validateTransferStockAvailability(itemRows, fromLocationId);
        if (!stockIsAvailable) {
            return;
        }
        
        const transferData = {
            from_location_id: fromLocationId,
            to_location_id: toLocationId,
            priority: formData.get('priority') || 'normal',
            items: items,
            transfer_type: transferType,
            // purchase_indent_id is omitted — auto-created by backend
        };
        
        // Add optional fields
        const requiredByDate = formData.get('required_by_date');
        if (requiredByDate) {
            transferData.required_by_date = dateInputToIsoEndOfDay(requiredByDate);
        }
        
        const returnDate = formData.get('return_date');
        if (isReturnableTransferType(transferType) && returnDate) {
            transferData.return_date = dateInputToIsoEndOfDay(returnDate);
            const reminderDays = parseInt(formData.get('return_reminder_days'));
            if (reminderDays && reminderDays > 0) {
                transferData.return_reminder_days = reminderDays;
            }
        }
        
        const notes = formData.get('request_notes');
        const destinationResponsibleName = destinationResponsibleSelect?.selectedOptions?.[0]?.dataset?.name || '';
        const noteParts = [];
        if (notes) noteParts.push(notes);
        if (destinationResponsibleName) noteParts.push(`Destination responsible person: ${destinationResponsibleName}`);
        if (noteParts.length) transferData.request_notes = noteParts.join('\n');
        if (destinationResponsibleId) transferData.destination_responsible_id = destinationResponsibleId;
        if (localReceivingDetails) transferData.local_receiving_details = localReceivingDetails;
        
        // Include assigned user (responsible person at source location)
        const assignedToId = formData.get('assigned_to_id');
        if (!assignedToId) {
            showToast('Select a responsible person at the source location', 'error');
            return;
        }
        transferData.assigned_to_id = assignedToId;
        const createdTransfer = await TransfersAPI.create(transferData);
        
        closeModal();
        await loadTransfers();

        // Surface the new transfer immediately — scroll it to top and open detail
        const newId = createdTransfer?.id;
        if (newId) {
            // Brief pause so the table renders before we open the detail modal
            setTimeout(async () => {
                const piNum = createdTransfer?.purchase_indent_number;
                if (piNum) {
                    showToast(
                        `Transfer created. Purchase Indent ${piNum} has been auto-generated and sent to the supplying location manager.`,
                        'success',
                        6000
                    );
                } else {
                    showToast('Transfer request created successfully', 'success');
                }
                // Highlight the row briefly then open detail
                const row = document.querySelector(`[data-transfer-id="${newId}"]`);
                if (row) {
                    row.classList.add('row-highlight-new');
                    setTimeout(() => row.classList.remove('row-highlight-new'), 3000);
                }
                await viewTransfer(newId);
            }, 400);
        } else {
            showToast('Transfer request created successfully', 'success');
        }
    } catch (error) {
        console.error('Error creating transfer:', error);
        showToast('Failed to create transfer: ' + error.message, 'error');
    }
}

async function showModifyReturnDate(transferId, currentDate, currentReminderDays) {
    const currentVal = currentDate ? localDateInputValue(new Date(currentDate)) : '';
    const reminderVal = currentReminderDays || 3;
    const content = `
        <form id="modify-return-date-form">
            <div class="form-group">
                <label for="new_return_date">New Return Date *</label>
                <input type="date" id="new_return_date" class="form-control" value="${currentVal}" required>
            </div>
            <div class="form-group">
                <label for="return_reminder_days_edit">Remind Before (days)</label>
                <input type="number" id="return_reminder_days_edit" class="form-control" min="1" max="365" value="${reminderVal}" style="max-width:120px;">
                <small class="text-muted">Receive notifications this many days before the return date</small>
            </div>
            <div class="form-group">
                <label for="return_date_reason">Reason for Change *</label>
                <textarea id="return_date_reason" class="form-control" rows="3" placeholder="Provide a reason for modifying the return date" required></textarea>
            </div>
            <div class="modal-actions">
                <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                <button type="submit" class="btn btn-primary"><i class="fas fa-save"></i> Update Return Date</button>
            </div>
        </form>
    `;
    openModal('Modify Return Date', content);
    document.getElementById('modify-return-date-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const newDate = document.getElementById('new_return_date').value;
        const reason = document.getElementById('return_date_reason').value.trim();
        const reminderDays = parseInt(document.getElementById('return_reminder_days_edit').value) || null;
        if (!newDate || !reason) {
            showToast('Please provide both a new date and reason', 'error');
            return;
        }
        try {
            await TransfersAPI.updateReturnDate(transferId, {
                return_date: dateInputToIsoEndOfDay(newDate),
                reason: reason,
                return_reminder_days: reminderDays
            });
            showToast('Return date updated successfully', 'success');
            closeModal();
            loadTransfers();
        } catch (error) {
            showToast('Failed to update return date: ' + error.message, 'error');
        }
    });
}

function downloadTransferDetails(transfer) {
    // Redirect to unified PDF generator
    generateTransferPDFFromData(transfer);
}

async function generateTransferPDF(transferId) {
    try {
        const transfer = await TransfersAPI.getById(transferId);
        generateTransferPDFFromData(transfer);
    } catch (error) {
        showToast('Failed to generate PDF: ' + error.message, 'error');
    }
}

function generateTransferPDFFromData(transfer) {
    const items = Array.isArray(transfer.items) ? transfer.items : [];
    const isEquipment = isSerializedTransferType(transfer.transfer_type) ||
        items.some(item => item.item_is_serialized === true);
    const formatDate = (v) => {
        if (!v) return '';
        const d = new Date(v);
        const dd = String(d.getDate()).padStart(2, '0');
        const mm = String(d.getMonth() + 1).padStart(2, '0');
        const yy = String(d.getFullYear()).slice(-2);
        return dd + '-' + mm + '-' + yy;
    };

    const dcDate = formatDate(transfer.requested_date || transfer.created_at);
    const dcNo = transfer.transfer_number || transfer.id;
    const toName = transfer.to_location_name || '-';
    const toCode = transfer.to_location_code || '';
    const fromName = transfer.from_location_name || '-';
    const returnDate = transfer.return_date ? formatDate(transfer.return_date) : '';
    const refDate = transfer.required_by_date ? formatDate(transfer.required_by_date) : dcDate;
    const refNumber = dcNo;
    const remarks = transfer.request_notes || (returnDate ? 'Return Date: ' + returnDate : '');
    const returnableLabel = 'RETURNABLE';

    // Build item rows
    let totalQty = 0;
    const itemRowsHtml = items.map((item, idx) => {
        const desc = (item.item_name || item.item_sku || '-') +
            (item.lot_number ? '<br>' + item.lot_number : '') +
            (item.item_manufacturer ? '<br>' + item.item_manufacturer : '');
        const qty = item.quantity_requested ?? 0;
        totalQty += qty;
        const serials = Array.isArray(item.serial_numbers) && item.serial_numbers.length
            ? item.serial_numbers.join(', ') : '';
        const itemRemarks = item.notes || serials || '';
        return `<tr>
            <td class="center">${idx + 1}</td>
            <td class="center">${desc}</td>
            <td class="center">${qty} No's</td>
            <td>${itemRemarks}</td>
        </tr>`;
    }).join('');

    // Pad empty rows to fill the page
    const emptyRowCount = Math.max(0, 6 - items.length);
    const emptyRows = Array(emptyRowCount).fill('<tr><td>&nbsp;</td><td></td><td></td><td></td></tr>').join('');

    // Remarks row spanning if we have transfer notes
    const remarksRow = remarks ? `<tr>
        <td></td><td></td><td></td>
        <td>${remarks}</td>
    </tr>` : '';

    const html = `<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>DC - ${dcNo}</title>
<style>
    @page { size: A4; margin: 15mm; }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: Arial, sans-serif; font-size: 12px; color: #000; padding: 0; }
    .page { width: 100%; max-width: 210mm; margin: 0 auto; border: 2px solid #000; }
    
    /* Header */
    .header-table { width: 100%; border-collapse: collapse; }
    .header-table td { border: 1px solid #000; padding: 4px 8px; vertical-align: middle; }
    .logo-cell { width: 90px; text-align: center; padding: 8px; }
    .logo-ss { font-size: 38px; font-weight: bold; color: #c00; font-family: serif; line-height: 1; }
    .company-name { font-size: 14px; font-weight: bold; text-align: center; }
    .doc-title { font-size: 13px; font-weight: bold; text-align: center; }
    .doc-info { font-size: 11px; text-align: center; }
    .doc-label { text-align: left; font-size: 11px; }
    .doc-value { text-align: center; font-size: 11px; }
    .accreditation { text-align: center; font-weight: bold; font-size: 11px; padding: 4px; }
    
    /* Info section */
    .info-table { width: 100%; border-collapse: collapse; }
    .info-table td { border: 1px solid #000; padding: 5px 8px; font-size: 11px; vertical-align: top; }
    .info-label { font-weight: bold; width: 90px; }
    .info-value { }
    
    /* Body */
    .greeting { padding: 10px 12px 4px; font-size: 12px; }
    .returnable-label { text-align: center; font-weight: bold; font-size: 13px; padding: 8px 0 6px; }
    
    /* Items table */
    .items-table { width: 100%; border-collapse: collapse; }
    .items-table th, .items-table td { border: 1px solid #000; padding: 6px 10px; font-size: 11px; vertical-align: top; }
    .items-table th { font-weight: bold; text-align: center; background: #fff; }
    .items-table .center { text-align: center; }
    .items-table td:first-child { width: 50px; text-align: center; }
    .items-table td:nth-child(2) { width: 40%; text-align: center; }
    .items-table td:nth-child(3) { width: 100px; text-align: center; }
    
    .total-row td { font-weight: bold; border-top: 2px solid #000; }
    
    /* Signatures */
    .sig-table { width: 100%; border-collapse: collapse; }
    .sig-table td { border: 1px solid #000; padding: 8px 12px; font-size: 12px; font-weight: bold; height: 40px; vertical-align: bottom; }
    
    /* Footer */
    .footer { text-align: center; font-size: 10px; padding: 10px 8px; border-top: 2px solid #000; line-height: 1.5; color: #00c; text-decoration: underline; }
    .footer .gst { color: #000; font-weight: bold; text-decoration: none; }
    
    @media print {
        body { padding: 0; }
        .page { border: 2px solid #000; }
    }
</style></head><body>
<div class="page">
    <!-- Header -->
    <table class="header-table">
        <tr>
            <td class="logo-cell" rowspan="3">
                <div class="logo-ss">SS</div>
            </td>
            <td class="company-name" rowspan="1">M/s Scientech Services</td>
            <td class="doc-label">Doc. No.</td>
            <td class="doc-value">STR-F-05</td>
        </tr>
        <tr>
            <td class="doc-title" rowspan="1">DELIVERY CHALLAN</td>
            <td class="doc-label">Rev. No.</td>
            <td class="doc-value">01</td>
        </tr>
        <tr>
            <td class="doc-info">&nbsp;</td>
            <td class="doc-label">Rev. Date</td>
            <td class="doc-value">13-Jul-23</td>
        </tr>
        <tr>
            <td colspan="4" class="accreditation">AS9100 and ISO 9001:2015 Accredited Lab (UKAS Accreditation)</td>
        </tr>
    </table>

    <!-- DC Info -->
    <table class="info-table">
        <tr>
            <td class="info-label">DC NO</td>
            <td class="info-value">${dcNo}</td>
            <td class="info-label" style="width:60px;">Date:</td>
            <td class="info-value" style="width:110px;">${dcDate}</td>
        </tr>
        <tr>
            <td class="info-label">To :</td>
            <td colspan="3" class="info-value" style="font-weight:bold;">${toName}${toCode ? ' (' + toCode + ')' : ''}</td>
        </tr>
        <tr>
            <td class="info-label">From :</td>
            <td class="info-value">${fromName}</td>
            <td class="info-label">Reference<br>Number</td>
            <td class="info-value">${refNumber}</td>
        </tr>
        <tr>
            <td class="info-label">&nbsp;</td>
            <td class="info-value">&nbsp;</td>
            <td class="info-label">Ref. Date:</td>
            <td class="info-value">${refDate}</td>
        </tr>
    </table>

    <!-- Body -->
    <div class="greeting">Dear Sir/Madam,</div>
    <div class="returnable-label">${returnableLabel}</div>

    <!-- Items Table -->
    <table class="items-table">
        <thead>
            <tr>
                <th>Sl No</th>
                <th>Description</th>
                <th>Quantity</th>
                <th>Remarks</th>
            </tr>
        </thead>
        <tbody>
            ${itemRowsHtml}
            ${emptyRows}
            ${remarksRow}
        </tbody>
        <tfoot>
            <tr class="total-row">
                <td></td>
                <td class="center">Total</td>
                <td class="center">${totalQty > 0 ? totalQty + " No's" : ''}</td>
                <td></td>
            </tr>
        </tfoot>
    </table>

    <!-- Signatures -->
    <table class="sig-table">
        <tr>
            <td>Issued by,</td>
            <td style="text-align:right;">Receiver's Signature</td>
        </tr>
    </table>

    <!-- Footer -->
    <div class="footer">
        15, Singasandra, 14th K.M. Hosur Road, Bangalore-560068. Ph:080-25730691, 25730719,<br>
        Mob:9945060978 Email:contact@scientechservices.com, www.scientechservices.com<br>
        <span class="gst">GST NO : 29AKQPB1576N1ZJ</span>
    </div>
</div>

<script>window.onload = function() { window.print(); }</script>
</body></html>`;

    const printWindow = window.open('', '_blank');
    if (!printWindow) {
        // Popup blocked - fallback to iframe print
        const iframe = document.createElement('iframe');
        iframe.style.position = 'fixed';
        iframe.style.right = '0';
        iframe.style.bottom = '0';
        iframe.style.width = '0';
        iframe.style.height = '0';
        iframe.style.border = '0';
        document.body.appendChild(iframe);
        iframe.contentDocument.write(html);
        iframe.contentDocument.close();
        iframe.onload = () => {
            iframe.contentWindow.print();
            setTimeout(() => document.body.removeChild(iframe), 1000);
        };
        return;
    }
    printWindow.document.write(html);
    printWindow.document.close();
}

async function viewTransfer(id) {
    try {
        const transfer = await TransfersAPI.getById(id);
        const statusKey = String(transfer.status || '').toLowerCase();

        const statusLabel = statusKey
            ? statusKey.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
            : '-';

        const formatDate = (value) => value ? new Date(value).toLocaleString() : '-';
        const formatShortDate = (value) => value ? new Date(value).toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' }) : null;
        const items = Array.isArray(transfer.items) ? transfer.items : [];
        const isEquipment = isSerializedTransferType(transfer.transfer_type) ||
            items.some(item => item.item_is_serialized === true);

        // Timeline steps
        const steps = [
            { key: 'requested', label: 'Requested', date: transfer.requested_date || transfer.created_at, icon: 'fa-paper-plane' },
            { key: 'approved', label: 'Approved', date: transfer.approved_at, icon: 'fa-check' },
            { key: 'in_transit', label: 'Shipped', date: transfer.shipped_at, icon: 'fa-shipping-fast' },
            { key: 'received', label: 'Received', date: transfer.received_at, icon: 'fa-check-double' },
        ];
        const statusOrder = ['requested', 'approved', 'in_transit', 'received', 'completed', 'partially_received'];
        const currentIdx = statusOrder.indexOf(statusKey);
        const isRejected = ['rejected', 'cancelled'].includes(statusKey);

        const timelineHtml = `<div class="transfer-timeline">${steps.map((step, i) => {
            let cls = '';
            if (isRejected && i === 0) cls = 'completed';
            else if (isRejected && i === 1) cls = 'rejected';
            else if (i <= currentIdx) cls = 'completed';
            else if (i === currentIdx + 1) cls = 'active';
            return `<div class="tl-step ${cls}">
                <div class="tl-dot"><i class="fas ${step.icon}"></i></div>
                <div class="tl-label">${step.label}</div>
                ${step.date ? `<div class="tl-date">${formatShortDate(step.date)}</div>` : '<div class="tl-date">—</div>'}
            </div>`;
        }).join('')}${isRejected ? `<div class="tl-step rejected"><div class="tl-dot"><i class="fas fa-times"></i></div><div class="tl-label">${statusLabel}</div><div class="tl-date">${formatShortDate(transfer.updated_at) || '—'}</div></div>` : ''}</div>`;

        // Return date section for any returnable transfer
        let returnDateHtml = '';
        if (transfer.return_date) {
            const rd = new Date(transfer.return_date);
            const diff = rd.getTime() - Date.now();
            const reminderMs = (transfer.return_reminder_days || 3) * 24 * 60 * 60 * 1000;
            let tag = '';
            if (diff < 0) tag = '<span class="overdue-tag"><i class="fas fa-exclamation-circle"></i> Overdue</span>';
            else if (diff <= reminderMs) tag = '<span class="due-soon-tag"><i class="fas fa-exclamation-triangle"></i> Due Soon</span>';
            returnDateHtml = `
                <div class="transfer-detail-card">
                    <div class="tdc-label"><i class="fas fa-calendar-alt"></i> Return Date</div>
                    <div class="tdc-value">${formatShortDate(transfer.return_date)} ${tag}</div>
                    <div class="tdc-sub"><i class="fas fa-bell"></i> Reminder: ${transfer.return_reminder_days || 3} day(s) before</div>
                    ${transfer.return_date_modified_reason ? `<div class="tdc-sub"><strong>Reason:</strong> ${transfer.return_date_modified_reason}</div>` : ''}
                </div>`;
        }

        // Location flow
        const locationFlowHtml = `<div class="transfer-location-flow">
            <div class="tlf-loc">
                <div class="tdc-label">From</div>
                <div class="tlf-name">${transfer.from_location_name || '-'}</div>
                <div class="tlf-code">${transfer.from_location_code || ''}</div>
            </div>
            <div class="tlf-arrow"><i class="fas fa-long-arrow-alt-right"></i></div>
            <div class="tlf-loc">
                <div class="tdc-label">To</div>
                <div class="tlf-name">${transfer.to_location_name || '-'}</div>
                <div class="tlf-code">${transfer.to_location_code || ''}</div>
            </div>
        </div>`;

        // Priority display
        const priorityKey = (transfer.priority || 'normal').toLowerCase();
        const priorityLabel = priorityKey.charAt(0).toUpperCase() + priorityKey.slice(1);

        // Items table
        const itemsRows = items.length
            ? items.map(item => {
                const itemLabel = `${item.item_sku || '-'} - ${item.item_name || '-'}`;
                const serials = Array.isArray(item.serial_numbers) && item.serial_numbers.length
                    ? item.serial_numbers.join(', ')
                    : '-';
                return `<tr>
                    <td>${itemLabel}</td>
                    <td>${item.quantity_requested ?? 0}</td>
                    <td>${item.quantity_shipped ?? 0}</td>
                    <td>${item.quantity_received ?? 0}</td>
                    <td>${item.quantity_damaged ?? 0}</td>
                    <td>${item.quantity_lost ?? 0}</td>
                    <td>${item.lot_number || '-'}</td>
                    <td>${serials}</td>
                </tr>`;
            }).join('')
            : '<tr><td colspan="8" class="text-center text-muted">No items found</td></tr>';

        // Notes section
        const allNotes = [
            { label: 'Request', val: transfer.request_notes },
            { label: 'Approval', val: transfer.approval_notes },
            { label: 'Shipping', val: transfer.shipping_notes },
            { label: 'Receiving', val: transfer.receiving_notes },
            { label: 'Rejection', val: transfer.rejection_reason },
        ].filter(n => n.val);

        const notesHtml = allNotes.length ? `<div class="transfer-notes-section">
            <div class="tns-title"><i class="fas fa-sticky-note"></i> Notes</div>
            ${allNotes.map(n => `<div class="tns-item"><strong>${n.label}:</strong> ${n.val}</div>`).join('')}
        </div>` : '';

        // Store transfer data for download
        window._currentViewTransfer = transfer;

        // Determine action buttons based on status
        const user = AuthAPI.getUser();
        const isManager = user && ['admin', 'head_office_manager', 'location_manager'].includes(user.role);
        let actionButtons = '';
        if (statusKey === 'requested' && isManager) {
            actionButtons += `<button type="button" class="btn btn-success" onclick="approveTransfer('${transfer.id}')"><i class="fas fa-check"></i> Approve</button>`;
            actionButtons += `<button type="button" class="btn btn-danger" onclick="rejectTransfer('${transfer.id}')"><i class="fas fa-times"></i> Reject</button>`;
        }
        if (statusKey === 'approved' && isManager) {
            actionButtons += `<button type="button" class="btn btn-primary" onclick="shipTransfer('${transfer.id}')"><i class="fas fa-shipping-fast"></i> Ship</button>`;
        }
        if (canReceiveTransfer(transfer, statusKey)) {
            actionButtons += `<button type="button" class="btn btn-success" onclick="receiveTransfer('${transfer.id}')"><i class="fas fa-check-double"></i> Receive</button>`;
        }
        if (['requested', 'approved'].includes(statusKey) && isManager) {
            actionButtons += `<button type="button" class="btn btn-outline btn-danger" onclick="cancelTransfer('${transfer.id}')"><i class="fas fa-ban"></i> Cancel</button>`;
        }

        const content = `
            ${timelineHtml}
            ${locationFlowHtml}
            <div class="transfer-detail-grid">
                <div class="transfer-detail-card">
                    <div class="tdc-label"><i class="fas fa-hashtag"></i> Transfer Info</div>
                    <div class="tdc-value">${transfer.transfer_number || transfer.id}</div>
                    <div class="tdc-sub">${transferTypeLabel(transfer.transfer_type)} &middot; <span class="priority-dot ${priorityKey}"></span> ${priorityLabel} &middot; ${statusLabel}</div>
                </div>
                <div class="transfer-detail-card">
                    <div class="tdc-label"><i class="fas fa-user"></i> People</div>
                    <div class="tdc-value">${transfer.requested_by_name || '-'}</div>
                    <div class="tdc-sub">Approved by: ${transfer.approved_by_name || '-'}</div>
                </div>
                ${transfer.purchase_indent_number ? `
                <div class="transfer-detail-card">
                    <div class="tdc-label"><i class="fas fa-file-invoice"></i> Purchase Indent</div>
                    <div class="tdc-value">${transfer.purchase_indent_number}</div>
                    <div class="tdc-sub">Auto-generated &middot; linked to this request</div>
                </div>` : ''}
                ${returnDateHtml}
            </div>

            ${notesHtml}

            <div class="form-group" style="margin-top:16px;">
                <label style="font-weight:600;font-size:0.95em;"><i class="fas fa-boxes"></i> Items</label>
                <div class="table-container">
                    <table class="data-table">
                        <thead>
                            <tr>
                                <th>Item</th>
                                <th>Requested</th>
                                <th>Shipped</th>
                                <th>Received</th>
                                <th>Damaged</th>
                                <th>Lost</th>
                                <th>Lot #</th>
                                <th>Serial Numbers</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${itemsRows}
                        </tbody>
                    </table>
                </div>
            </div>

            <div class="modal-actions">
                <button type="button" class="btn btn-secondary" onclick="closeModal()">Close</button>
                ${actionButtons}
                ${transfer.purchase_indent_id ? `
                <button type="button" class="btn btn-outline" onclick="viewPurchaseIndent('${transfer.purchase_indent_id}')" title="View linked Purchase Indent">
                    <i class="fas fa-file-invoice"></i> View PI
                </button>
                <button type="button" class="btn btn-outline" onclick="printPIDocument('${transfer.purchase_indent_id}')" title="Print Purchase Indent document">
                    <i class="fas fa-print"></i> Print PI
                </button>` : ''}
                ${['approved','in_transit','received','partially_received'].includes(statusKey) ? `
                <button type="button" class="btn btn-primary" onclick="printDeliveryChallan('${transfer.id}')" title="View / Print Delivery Challan">
                    <i class="fas fa-file-invoice"></i> Delivery Challan
                </button>` : ''}
                <button type="button" class="btn btn-primary" onclick="generateTransferPDF('${transfer.id}')">
                    <i class="fas fa-file-pdf"></i> Download PDF
                </button>
                ${isEquipment ? `
                    <button type="button" class="btn btn-warning" onclick="closeModal(); showModifyReturnDate('${transfer.id}', '${transfer.return_date || ''}', ${transfer.return_reminder_days || 3})">
                        <i class="fas fa-calendar-alt"></i> Modify Return Date
                    </button>
                ` : ''}
            </div>
        `;

        openModal('Transfer Details', content, 'modal-xl');
    } catch (error) {
        console.error('Error loading transfer details:', error);
        showToast('Failed to load transfer details: ' + error.message, 'error');
    }
}

// Transfer workflow actions
async function approveTransfer(id) {
    try {
        const transfer = await TransfersAPI.getById(id);

        // Check for compliance blockers on equipment transfers
        let blockerHtml = '';
        let approvalBlocked = false;
        if (isSerializedTransferType(transfer.transfer_type)) {
            try {
                const overview = await TransfersAPI.getEquipmentOverview({ location_id: transfer.from_location_id });
                const blocked = (overview.calibration_issues || []).concat(overview.maintenance_issues || []);
                const relevant = blocked.filter(b =>
                    transfer.items && transfer.items.some(ti => ti.item_id === b.item_id)
                );
                if (relevant.length) {
                    approvalBlocked = true;
                    blockerHtml = `
                        <div style="background:#fef2f2;border:1px solid #fecaca;border-radius:8px;padding:10px 14px;margin-bottom:14px;">
                            <p style="font-weight:600;color:#b91c1c;margin:0 0 6px;"><i class="fas fa-ban"></i> Transfer Blocked</p>
                            ${relevant.map(b => `<p style="margin:2px 0;font-size:13px;color:#7f1d1d;">${b.item_name || b.item_id}: ${(b.blocked_reasons || []).join(', ')}</p>`).join('')}
                            <p style="font-size:12px;color:#991b1b;margin:6px 0 0;">Complete the pending calibration or maintenance before approval.</p>
                        </div>`;
                }
            } catch (_) { /* ignore — don't block approval if overview fails */ }
        }

        openModal(`Approve Transfer — ${transfer.transfer_number}`, `
            <div>
                ${blockerHtml}
                <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:12px 16px;margin-bottom:14px;">
                    <p style="margin:0 0 4px;font-size:12px;color:#64748b;font-weight:600;text-transform:uppercase;">Transfer Summary</p>
                    <p style="margin:2px 0;"><strong>From:</strong> ${transfer.from_location_name || '-'} → <strong>To:</strong> ${transfer.to_location_name || '-'}</p>
                    <p style="margin:2px 0;"><strong>Items:</strong> ${(transfer.items || []).map(i => `${i.item_name || i.item_id} ×${i.quantity_requested}`).join(', ')}</p>
                    ${transfer.purchase_indent_number ? `<p style="margin:2px 0;"><strong>PI:</strong> ${transfer.purchase_indent_number}</p>` : ''}
                </div>
                <div class="form-group">
                    <label>Approval Notes (optional)</label>
                    <textarea id="approve-notes" class="form-control" rows="2" placeholder="Any shipping instructions or notes..."></textarea>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-outline" onclick="closeModal()">Cancel</button>
                    <button type="button" class="btn btn-danger" onclick="_doRejectTransfer('${id}')"><i class="fas fa-times"></i> Reject</button>
                    <button type="button" class="btn btn-success" ${approvalBlocked ? 'disabled title="Resolve calibration or maintenance blockers first"' : `onclick="_doApproveTransfer('${id}')"`}><i class="fas fa-check"></i> Approve & Generate DC</button>
                </div>
            </div>
        `);
    } catch (error) {
        showToast('Error: ' + error.message, 'error');
    }
}

async function _doApproveTransfer(id) {
    const notes = document.getElementById('approve-notes')?.value || '';
    try {
        await API.patch(`/transfers/${id}/approve`, { approved: true, notes });
        closeModal();
        showToast('Transfer approved — Delivery Challan generated', 'success');
        loadTransfers();
    } catch (error) {
        showToast('Approve failed: ' + error.message, 'error');
    }
}

async function _doRejectTransfer(id) {
    const reason = prompt('Reason for rejection (required):');
    if (!reason) return;
    try {
        await API.patch(`/transfers/${id}/approve`, { approved: false, rejection_reason: reason });
        closeModal();
        showToast('Transfer rejected', 'success');
        loadTransfers();
    } catch (error) {
        showToast('Reject failed: ' + error.message, 'error');
    }
}

async function rejectTransfer(id) {
    const reason = prompt('Reason for rejection:');
    if (reason === null) return;
    try {
        await API.patch(`/transfers/${id}/approve`, { approved: false, rejection_reason: reason || 'Rejected' });
        closeModal();
        showToast('Transfer rejected', 'success');
        loadTransfers();
    } catch (error) {
        showToast('Reject failed: ' + error.message, 'error');
    }
}

async function shipTransfer(id) {
    if (!confirm('Mark this transfer as shipped?')) return;
    try {
        await TransfersAPI.ship(id, {});
        closeModal();
        showToast('Transfer marked as shipped', 'success');
        loadTransfers();
    } catch (error) {
        showToast('Ship failed: ' + error.message, 'error');
    }
}

async function receiveTransfer(id) {
    try {
        const transfer = await TransfersAPI.getById(id);
        const receivable = (transfer.items || []).map(item => ({
            ...item,
            remaining: Math.max(
                0,
                Number(item.quantity_shipped || 0)
                - Number(item.quantity_received || 0)
                - Number(item.quantity_damaged || 0)
                - Number(item.quantity_lost || 0)
            ),
        })).filter(item => item.remaining > 0);
        if (!receivable.length) {
            showToast('No shipped quantity remains to be received', 'warning');
            return;
        }
        const rows = receivable.map(item => `
            <div class="form-group" data-receipt-line="${item.id}"
                 data-remaining="${item.remaining}">
                <label>${escapeHtml(item.item_name || item.item_sku || item.item_id)}
                    <small>(remaining: ${item.remaining})</small>
                </label>
                <div class="form-row">
                    <input type="number" name="received-${item.id}" min="0"
                           max="${item.remaining}" value="${item.remaining}"
                           aria-label="Good quantity received">
                    <input type="number" name="damaged-${item.id}" min="0"
                           max="${item.remaining}" value="0"
                           aria-label="Damaged quantity">
                    <input type="number" name="lost-${item.id}" min="0"
                           max="${item.remaining}" value="0"
                           aria-label="Lost quantity">
                </div>
                <small>Good received / Damaged / Lost</small>
                <textarea name="condition-${item.id}" rows="2"
                          placeholder="Required when damaged or lost quantity is entered"></textarea>
            </div>
        `).join('');
        openModal('Receive Transfer', `
            <form id="receive-transfer-form">
                <p>Record the physical disposition of every shipped unit. Only good
                   quantities are added to usable destination stock.</p>
                ${rows}
                <div class="form-group">
                    <label>General receiving notes</label>
                    <textarea name="notes" rows="2"></textarea>
                </div>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-success">Confirm Receipt</button>
                </div>
            </form>
        `);
        document.getElementById('receive-transfer-form').addEventListener('submit', async event => {
            event.preventDefault();
            const form = event.currentTarget;
            try {
                const receivedItems = receivable.map(item => {
                    const received = Number(form.elements[`received-${item.id}`].value || 0);
                    const damaged = Number(form.elements[`damaged-${item.id}`].value || 0);
                    const lost = Number(form.elements[`lost-${item.id}`].value || 0);
                    if (received + damaged + lost > item.remaining) {
                        throw new Error(`Disposition for ${item.item_name || item.item_id} exceeds remaining quantity ${item.remaining}`);
                    }
                    const conditionNotes = form.elements[`condition-${item.id}`].value.trim();
                    if ((damaged || lost) && !conditionNotes) {
                        throw new Error(`Condition notes are required for ${item.item_name || item.item_id}`);
                    }
                    return {
                        transfer_item_id: item.id,
                        quantity_received: received,
                        quantity_damaged: damaged,
                        quantity_lost: lost,
                        condition_notes: conditionNotes || null,
                    };
                });
                await TransfersAPI.receive(id, {
                    notes: form.elements.notes.value.trim() || null,
                    received_items: receivedItems,
                });
                closeModal();
                showToast('Transfer receipt recorded — usable stock updated', 'success');
                loadTransfers();
                await refreshDashboardAsync();
            } catch (error) {
                showToast('Receive failed: ' + error.message, 'error');
            }
        });
    } catch (error) {
        showToast('Receive failed: ' + error.message, 'error');
    }
}

async function cancelTransfer(id) {
    if (!confirm('Cancel this transfer? This cannot be undone.')) return;
    try {
        await TransfersAPI.cancel(id);
        closeModal();
        showToast('Transfer cancelled', 'success');
        loadTransfers();
    } catch (error) {
        showToast('Cancel failed: ' + error.message, 'error');
    }
}

function getCalibrationBadgeClass(status) {
    const map = {
        valid: 'badge-success',
        due_soon: 'badge-warning',
        expired: 'badge-danger',
        not_required: 'badge-secondary',
    };
    return map[(status || '').toLowerCase()] || 'badge-secondary';
}

async function editItemModal(itemId) {
    try {
        const [item, catData, stockData] = await Promise.all([
            ItemsAPI.getById(itemId),
            CategoriesAPI.getAll(),
            StockAPI.getAll({ item_id: itemId, page_size: 100 })
        ]);
        const cats = Array.isArray(catData) ? catData : (catData.items || []);
        categories = cats;
        const catOptions = cats
            .filter(c => (c.stock_behavior || '').toLowerCase() !== 'serialized')
            .map(c => `<option value="${c.id}" ${c.id === item.category_id ? 'selected' : ''}>${c.name}</option>`)
            .join('');
        const label = item.asset_type === 'accessory' ? 'Accessory' : 'Consumable';

        const stocks = Array.isArray(stockData) ? stockData : (stockData.items || []);
        const locationHtml = stocks.length
            ? stocks.map(s => `
                <div style="display:flex;justify-content:space-between;align-items:center;padding:6px 10px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;margin-bottom:6px;">
                    <span style="font-weight:500;">${s.location_name || s.location_id || '—'}</span>
                    <span class="badge badge-info" style="min-width:40px;text-align:center;">Qty: ${s.quantity_on_hand ?? 0}</span>
                </div>`).join('')
            : `<p style="color:#94a3b8;font-size:13px;margin:4px 0;">No stock at any location</p>`;

        openModal(`Edit ${label} — ${item.name}`, `
            <form id="edit-item-form">
                <div class="form-row">
                    <div class="form-group">
                        <label>Name *</label>
                        <input type="text" name="name" required value="${item.name || ''}">
                    </div>
                    <div class="form-group">
                    <label>SKU / Product Code</label>
                    <input type="text" name="sku" value="${item.sku || ''}" placeholder="Optional">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Type *</label>
                        <select name="category_id" required>
                            <option value="">Select type</option>
                            ${catOptions}
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Unit of Measure</label>
                        <input type="text" name="unit_of_measure" value="${item.unit_of_measure || 'EA'}">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Make / Manufacturer</label>
                        <input type="text" name="manufacturer" value="${item.manufacturer || ''}">
                    </div>
                    <div class="form-group">
                        <label>Model</label>
                        <input type="text" name="model" value="${item.model || ''}">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Standard Cost (₹)</label>
                        <input type="number" name="standard_cost" min="0" step="0.01" value="${item.standard_cost != null ? item.standard_cost : ''}">
                    </div>
                    <div class="form-group">
                        <label>Description</label>
                        <input type="text" name="description" value="${item.description || ''}">
                    </div>
                </div>
                <hr style="margin:12px 0 10px;border-color:#e2e8f0;">
                <div class="form-group">
                    <label style="font-weight:600;">Stock by Location</label>
                    <div style="margin-top:6px;">${locationHtml}</div>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-outline" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary"><i class="fas fa-save"></i> Save Changes</button>
                </div>
            </form>
        `, 'modal-lg');

        document.getElementById('edit-item-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const fd = new FormData(e.target);
            const selectedCategory = categories.find(c => c.id === fd.get('category_id'));
            const data = {
                name: fd.get('name'),
                sku: fd.get('sku').trim() || null,
                category_id: fd.get('category_id'),
                asset_type: canonicalInventoryTypeKey(selectedCategory?.name || item.asset_type),
                unit_of_measure: fd.get('unit_of_measure') || 'EA',
                manufacturer: fd.get('manufacturer') || null,
                model: fd.get('model') || null,
                standard_cost: fd.get('standard_cost') ? parseFloat(fd.get('standard_cost')) : null,
                description: fd.get('description') || null,
            };
            try {
                await ItemsAPI.update(itemId, data);
                closeModal();
                showToast(`${label} updated successfully`, 'success');
                loadItems();
            } catch (error) {
                showToast(error.message, 'error');
            }
        });
    } catch (error) {
        showToast('Error loading item: ' + error.message, 'error');
    }
}

async function viewAsset(id) {
    try {
        const asset = await AssetsAPI.getById(id);

        const statusBadgeMap = {
            in_service: 'badge-success',
            under_maintenance: 'badge-warning',
            under_calibration: 'badge-info',
            out_of_service: 'badge-danger',
            retired: 'badge-secondary',
            lost: 'badge-danger',
            transferred: 'badge-secondary',
        };
        const statusLabelMap = {
            in_service: 'Active',
            under_maintenance: 'Under Maintenance',
            under_calibration: 'Under Calibration',
            out_of_service: 'Out of Service',
            retired: 'Retired',
            lost: 'Lost',
            transferred: 'Transferred',
        };

        const rawStatus = (asset.status || '').toLowerCase();
        const statusBadge = statusBadgeMap[rawStatus] || 'badge-secondary';
        const statusLabel = statusLabelMap[rawStatus] || asset.status || '-';

        const calStatus = (asset.calibration_status || 'not_required').toLowerCase();
        const calLabel = calStatus.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
        const formatDate = (value) => value ? new Date(value).toLocaleDateString() : '-';

        const content = `
            <div class="form-row">
                <div class="form-group">
                    <label>Name</label>
                    <div><strong>${asset.item_name || '-'}</strong></div>
                </div>
                <div class="form-group">
                    <label>Serial Number</label>
                    <div>${asset.serial_number || '-'}</div>
                </div>
                <div class="form-group">
                    <label>ID Number</label>
                    <div>${asset.item_id_number || '-'}</div>
                </div>
            </div>

            <div class="form-row">
                <div class="form-group">
                    <label>Make</label>
                    <div>${asset.item_manufacturer || '-'}</div>
                </div>
                <div class="form-group">
                    <label>Model</label>
                    <div>${asset.item_model || '-'}</div>
                </div>
                <div class="form-group">
                    <label>Location</label>
                    <div>${asset.location_name || '-'}</div>
                </div>
            </div>

            <div class="form-row">
                <div class="form-group">
                    <label>Asset Status</label>
                    <div><span class="badge ${statusBadge}">${statusLabel}</span></div>
                </div>
                <div class="form-group">
                    <label>Calibration Status</label>
                    <div><span class="badge ${getCalibrationBadgeClass(asset.calibration_status)}">${calLabel}</span></div>
                </div>
                <div class="form-group">
                    <label>Next Calibration Due</label>
                    <div>${formatDate(asset.next_calibration_due)}</div>
                </div>
                <div class="form-group">
                    <label>Last Calibration</label>
                    <div>${formatDate(asset.last_calibration_date)}</div>
                </div>
            </div>

            <div class="form-row">
                <div class="form-group">
                    <label>Acquired At</label>
                    <div>${formatDate(asset.acquired_at)}</div>
                </div>
                <div class="form-group">
                    <label>Purchase Order</label>
                    <div>${asset.purchase_order || '-'}</div>
                </div>
                <div class="form-group">
                    <label>Cost</label>
                    <div>${asset.cost != null ? '₹' + Number(asset.cost).toLocaleString('en-IN', {maximumFractionDigits: 2}) : '-'}</div>
                </div>
                <div class="form-group">
                    <label>Warranty Expiry</label>
                    <div>${formatDate(asset.warranty_expiry)}</div>
                </div>
            </div>

            <div class="form-group">
                <label>Notes</label>
                <div>${asset.notes || '-'}</div>
            </div>

            <div class="modal-actions">
                ${asset.item_requires_calibration ? `<button type="button" class="btn btn-warning" onclick="closeModal(); showAddCalibrationModal('${asset.id}')"><i class="fas fa-certificate"></i> Add Calibration</button>` : ''}
                <button type="button" class="btn btn-secondary" onclick="closeModal(); editAsset('${asset.id}')"><i class="fas fa-edit"></i> Edit</button>
                <button type="button" class="btn btn-outline" onclick="closeModal()">Close</button>
            </div>
        `;

        openModal('Asset Details', content, 'modal-lg');
    } catch (error) {
        console.error('Asset details load error:', error);
        showToast('Failed to load asset details: ' + error.message, 'error');
    }
}

async function viewItemDetail(id) {
    try {
        const item = await ItemsAPI.getById(id);
        const catName = item.category_name || '-';
        const stockInfo = productStockMap[id] || { qty: 0, locations: [] };
        const locHtml = stockInfo.locations && stockInfo.locations.length > 0
            ? stockInfo.locations.map(l => `${l.name}: <strong>${l.qty}</strong>`).join('<br>')
            : '-';

        const content = `
            <div class="form-row">
                <div class="form-group">
                    <label>Name</label>
                    <div><strong>${item.name || '-'}</strong></div>
                </div>
                <div class="form-group">
                    <label>SKU / Batch No</label>
                    <div>${item.sku || '-'}</div>
                </div>
                <div class="form-group">
                    <label>Category</label>
                    <div>${catName}</div>
                </div>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label>Make</label>
                    <div>${item.manufacturer || '-'}</div>
                </div>
                <div class="form-group">
                    <label>Model</label>
                    <div>${item.model || '-'}</div>
                </div>
                <div class="form-group">
                    <label>Total Qty</label>
                    <div><strong>${stockInfo.qty}</strong></div>
                </div>
            </div>
            <div class="form-group">
                <label>Stock by Location</label>
                <div>${locHtml}</div>
            </div>
            <div class="form-group">
                <label>Description</label>
                <div>${item.description || '-'}</div>
            </div>
            <div class="modal-actions">
                <button type="button" class="btn btn-secondary" onclick="closeModal(); editItemModal('${item.id}')"><i class="fas fa-edit"></i> Edit</button>
                <button type="button" class="btn btn-outline" onclick="closeModal()">Close</button>
            </div>
        `;
        openModal('Item Details', content, 'modal-lg');
    } catch (error) {
        console.error('Item detail load error:', error);
        showToast('Failed to load item details: ' + error.message, 'error');
    }
}

async function editAsset(id) {
    try {
        const [asset, locData, catData] = await Promise.all([
            AssetsAPI.getById(id),
            LocationsAPI.getAll({ is_active: true }),
            CategoriesAPI.getAll()
        ]);
        const locs = activeRecords(Array.isArray(locData) ? locData : (locData.items || []));
        const cats = Array.isArray(catData) ? catData : (catData.items || []);
        categories = cats;
        const locOptions = locs.map(l => `<option value="${l.id}" ${l.id === asset.location_id ? 'selected' : ''}>${l.name}</option>`).join('');

        const statusLabels = { in_service: 'Active', under_maintenance: 'Under Maintenance' };
        const statusOptions = ['in_service', 'under_maintenance']
            .map(s => {
                const assetStatusNorm = (asset.status || '').toLowerCase().replace(/_/g, '_');
                const sel = assetStatusNorm === s ? 'selected' : '';
                return `<option value="${s}" ${sel}>${statusLabels[s]}</option>`;
            }).join('');

        const currentCategory = cats.find(c => c.id === asset.item_category_id);
        const assetType = canonicalInventoryTypeKey(asset.item_asset_type || currentCategory?.category_type_key || currentCategory?.name) === 'instrument' ? 'instrument' : 'equipment';
        const typeLabel = assetType === 'instrument' ? 'Instrument' : 'Equipment';
        const catOptions = cats
            .filter(c =>
                (c.stock_behavior || '').toLowerCase() === 'serialized' &&
                canonicalInventoryTypeKey(c.category_type_key || c.category_type_name || c.name) === assetType
            )
            .map(c => `<option value="${c.id}" ${c.id === asset.item_category_id ? 'selected' : ''}>${c.name}</option>`)
            .join('');

        openModal(`Edit ${typeLabel} — ${asset.item_name || asset.serial_number}`, `
            <form id="edit-asset-form">
                <input type="hidden" name="product_type" value="${assetType}">
                <p style="margin:0 0 14px;font-size:12px;color:#888;text-transform:uppercase;letter-spacing:.5px;font-weight:600;">Product Details</p>
                <div class="form-row">
                    <div class="form-group">
                        <label>${typeLabel} Name *</label>
                        <input type="text" name="item_name" required value="${asset.item_name || ''}">
                    </div>
                    <div class="form-group">
                        <label>ID Number</label>
                        <input type="text" name="id_number" value="${asset.item_id_number || ''}">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Make</label>
                        <input type="text" name="manufacturer" value="${asset.item_manufacturer || ''}">
                    </div>
                    <div class="form-group">
                        <label>${assetType === 'instrument' ? 'Model Number' : 'Model'}</label>
                        <input type="text" name="model" value="${asset.item_model || ''}">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Type</label>
                        <select name="category_id">
                            <option value="">— Select type —</option>
                            ${catOptions}
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Serial Number</label>
                        <input type="text" name="serial_number" required value="${asset.serial_number || ''}">
                    </div>
                </div>

                <hr style="margin:14px 0 12px;">
                <p style="margin:0 0 14px;font-size:12px;color:#888;text-transform:uppercase;letter-spacing:.5px;font-weight:600;">Asset Instance Details</p>
                <div class="form-row">
                    <div class="form-group">
                        <label>Location *</label>
                        <select name="location_id" required>${locOptions}</select>
                    </div>
                    <div class="form-group">
                        <label>Status *</label>
                        <select name="status" required>${statusOptions}</select>
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Acquired Date</label>
                        <input type="date" name="acquired_at" value="${asset.acquired_at || ''}">
                    </div>
                    <div class="form-group">
                        <label>Cost (₹)</label>
                        <input type="number" name="cost" min="0" step="0.01" value="${asset.cost != null ? asset.cost : ''}">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Supplier Name</label>
                        <input type="text" name="supplier_name" value="${asset.supplier_name || ''}">
                    </div>
                    <div class="form-group">
                        <label>Invoice No</label>
                        <input type="text" name="invoice_number" value="${asset.invoice_number || ''}">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Purchase Order</label>
                        <input type="text" name="purchase_order" value="${asset.purchase_order || ''}">
                    </div>
                    <div class="form-group">
                        <label>Warranty Expiry</label>
                        <input type="date" name="warranty_expiry" value="${asset.warranty_expiry || ''}">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Asset Tag</label>
                        <input type="text" name="asset_tag" value="${asset.asset_tag || ''}">
                    </div>
                    <div class="form-group">
                        <label>Barcode</label>
                        <input type="text" name="barcode" value="${asset.barcode || ''}">
                    </div>
                </div>
                <div class="form-group">
                    <label>${assetType === 'instrument' ? 'Description' : 'Notes'}</label>
                    <textarea name="notes" rows="2">${asset.notes || ''}</textarea>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-outline" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary"><i class="fas fa-save"></i> Save Changes</button>
                </div>
            </form>
        `, 'modal-lg');

        document.getElementById('edit-asset-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const formData = new FormData(e.target);

            const assetData = {
                serial_number: (formData.get('serial_number') || '').trim(),
                location_id: formData.get('location_id'),
                status: formData.get('status'),
                acquired_at: formData.get('acquired_at') || null,
                cost: formData.get('cost') ? parseFloat(formData.get('cost')) : null,
                supplier_name: formData.get('supplier_name') || null,
                invoice_number: formData.get('invoice_number') || null,
                purchase_order: formData.get('purchase_order') || null,
                warranty_expiry: formData.get('warranty_expiry') || null,
                asset_tag: formData.get('asset_tag') || null,
                barcode: formData.get('barcode') || null,
                notes: formData.get('notes') || null,
            };

            const itemData = {};
            const newName = formData.get('item_name');
            const newMfr  = formData.get('manufacturer');
            const newModel = formData.get('model');
            const newIdNo = formData.get('id_number');
            const newCat  = formData.get('category_id');
            const newCategory = categories.find(c => c.id === newCat);
            if (!newCategory || canonicalInventoryTypeKey(newCategory.category_type_key || newCategory.category_type_name || newCategory.name) !== assetType) {
                showToast(`Select a valid ${typeLabel} category`, 'error');
                return;
            }
            if (newName)  itemData.name         = newName;
            if (newMfr)   itemData.manufacturer  = newMfr;
            if (newModel) itemData.model         = newModel;
            if (newIdNo)  itemData.id_number     = newIdNo;
            if (newCat)   itemData.category_id   = newCat;
            itemData.asset_type = assetType;
            itemData.is_serialized = true;
            itemData.requires_calibration = assetType === 'instrument';

            try {
                const saves = [AssetsAPI.update(id, assetData)];
                if (Object.keys(itemData).length) saves.push(ItemsAPI.update(asset.item_id, itemData));
                await Promise.all(saves);
                closeModal();
                showToast(`${typeLabel} updated successfully`, 'success');
                loadItems();
            } catch (error) {
                showToast(error.message, 'error');
            }
        });
    } catch (error) {
        showToast('Error: ' + error.message, 'error');
    }
}

async function showAddCalibrationModal(assetId) {
    try {
        const asset = await AssetsAPI.getById(assetId);
        const today = localDateInputValue();
        // Default next due = 1 year from today
        const nextDue = new Date();
        nextDue.setFullYear(nextDue.getFullYear() + 1);
        const nextDueStr = localDateInputValue(nextDue);

        openModal(`Add Calibration Record — ${asset.serial_number}`, `
            <form id="add-calibration-form">
                <div class="form-row">
                    <div class="form-group">
                        <label>Certificate Number *</label>
                        <input type="text" name="certificate_number" required placeholder="CAL-2026-001">
                    </div>
                    <div class="form-group">
                        <label>Calibrated Date *</label>
                        <input type="date" name="performed_at" required value="${today}" max="${today}">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Next Due Date *</label>
                        <input type="date" name="due_at" required value="${nextDueStr}">
                    </div>
                    <div class="form-group">
                        <label>Result *</label>
                        <select name="result" required>
                            <option value="pass">Pass</option>
                            <option value="fail">Fail</option>
                            <option value="limited">Limited</option>
                        </select>
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Performed By *</label>
                        <input type="text" name="performed_by" required placeholder="Technician / Lab name">
                    </div>
                    <div class="form-group">
                        <label>Supplier Name</label>
                        <input type="text" name="calibration_lab" placeholder="Supplier / calibration lab">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Sent Date</label>
                        <input type="date" name="sent_date">
                    </div>
                    <div class="form-group">
                        <label>Receive Date</label>
                        <input type="date" name="receive_date">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>As-Found Condition</label>
                        <input type="text" name="as_found_condition" placeholder="e.g., In Tolerance">
                    </div>
                    <div class="form-group">
                        <label>As-Left Condition</label>
                        <input type="text" name="as_left_condition" placeholder="e.g., In Tolerance">
                    </div>
                </div>
                <div class="form-group">
                    <label>Notes</label>
                    <textarea name="notes" rows="2" placeholder="Observations, deviations..."></textarea>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-outline" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary"><i class="fas fa-certificate"></i> Save Calibration</button>
                </div>
            </form>
        `, 'modal-lg');

        document.getElementById('add-calibration-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const formData = new FormData(e.target);
            const extraNotes = [
                formData.get('sent_date') ? `Sent Date: ${formData.get('sent_date')}` : '',
                formData.get('receive_date') ? `Receive Date: ${formData.get('receive_date')}` : '',
                formData.get('notes') || ''
            ].filter(Boolean).join('\n');
            const data = {
                certificate_number: formData.get('certificate_number'),
                performed_at: formData.get('performed_at'),
                due_at: formData.get('due_at'),
                result: formData.get('result'),
                performed_by: formData.get('performed_by'),
                calibration_lab: formData.get('calibration_lab') || null,
                as_found_condition: formData.get('as_found_condition') || null,
                as_left_condition: formData.get('as_left_condition') || null,
                notes: extraNotes || null,
            };
            // Validate due_at > performed_at
            if (data.due_at <= data.performed_at) {
                showToast('Next due date must be after calibration date', 'error');
                return;
            }
            try {
                await AssetsAPI.addCalibration(assetId, data);
                closeModal();
                showToast('Calibration record saved successfully', 'success');
                loadItems();
            } catch (error) {
                showToast(error.message, 'error');
            }
        });
    } catch (error) {
        showToast('Error loading asset: ' + error.message, 'error');
    }
}

// Users
async function loadUsers() {
    try {
        // Ensure locations are loaded for the table display
        if (!locations || locations.length === 0) {
            try {
                const locData = await LocationsAPI.getAll({ page_size: 500 });
                locations = Array.isArray(locData) ? locData : (locData.items || []);
            } catch(e) {}
        }

        const data = await UsersAPI.getAll({ page_size: 500 });
        const users = Array.isArray(data) ? data : (data.items || []);
        usersCache = users;

        // Reset filter inputs
        const searchEl = document.getElementById('users-search');
        if (searchEl) searchEl.value = '';
        const roleEl = document.getElementById('users-role-filter');
        if (roleEl) roleEl.value = '';
        const statusEl = document.getElementById('users-status-filter');
        if (statusEl) statusEl.value = '';

        renderUsersTable(users);

    } catch (error) {
        console.error('Users load error:', error);
        document.getElementById('users-table-body').innerHTML = 
            '<tr><td colspan="6" class="text-center text-muted">Error loading users</td></tr>';
    }
}

function formatEmployeeRecordType(recordType) {
    const labelMap = {
        personal_qualification: 'Personal Qualification',
        personal_experience: 'Personal Experience',
        vision_certificate: 'Vision Certificate',
    };
    return labelMap[recordType] || recordType || '-';
}

function getEmployeeRecordMethod(record) {
    const match = String(record?.notes || '').match(/(?:^|\n)Method:\s*([A-Z0-9]+)/i);
    return match ? match[1].toUpperCase() : '';
}

function stripEmployeeRecordMethod(notes) {
    return String(notes || '').replace(/(?:^|\n)Method:\s*[A-Z0-9]+\s*/i, '').trim();
}

function methodOptions(selected = '') {
    const methods = ['RT', 'UT', 'MPT', 'PT', 'VT', 'BARC'];
    return methods.map(method => `<option value="${method}" ${method === selected ? 'selected' : ''}>${method}</option>`).join('');
}

function levelTitleOptions(selected = '') {
    const titles = ['Level 1', 'Level 2', 'Level 3'];
    return titles.map(title => `<option value="${title}" ${title === selected ? 'selected' : ''}>${title}</option>`).join('');
}

async function ensureUsersCache() {
    if (usersCache.length > 0) {
        return;
    }
    const currentUser = AuthAPI.getUser();
    if (!currentUser) {
        usersCache = [];
        return;
    }

    if (currentUser.role === 'admin') {
        const data = await UsersAPI.getAll({ page_size: 500 });
        usersCache = Array.isArray(data) ? data : (data.items || []);
        return;
    }

    let locationIds = currentUser.assigned_location_ids || [];
    if (currentUser.role === 'head_office_manager') {
        const locationData = await LocationsAPI.getAll({ page_size: 500, is_active: true });
        const allowedLocations = Array.isArray(locationData)
            ? locationData
            : (locationData.items || []);
        locationIds = allowedLocations.map(location => location.id);
    }

    if (locationIds.length === 0) {
        usersCache = [];
        return;
    }

    const results = await Promise.all(
        locationIds.map(locationId => UsersAPI.getByLocation(locationId))
    );
    const uniqueUsers = new Map();
    results.flat().forEach(user => uniqueUsers.set(user.id, user));
    usersCache = Array.from(uniqueUsers.values());
}

async function ensureEmployeesCache() {
    if (employeesCache.length > 0) return;
    try {
        const data = await EmployeesAPI.getAll({ page_size: 500, is_active: true });
        employeesCache = Array.isArray(data) ? data : (data.items || []);
    } catch (e) {
        console.warn('Could not load employees cache', e);
        employeesCache = [];
    }
}

// Build a combined options list: system users labelled "(User)" + non-login employees labelled "(Employee)"
// Value format: "usr:<id>" or "emp:<id>"
function buildPersonOptions(selectedValue = null) {
    const userOpts = usersCache.map(u =>
        `<option value="usr:${u.id}" ${selectedValue === 'usr:' + u.id ? 'selected' : ''}>${escapeHtml(u.name)}${u.email ? ' (' + escapeHtml(u.email) + ')' : ''}</option>`
    ).join('');
    const empOpts = employeesCache.map(e =>
        `<option value="emp:${e.id}" ${selectedValue === 'emp:' + e.id ? 'selected' : ''}>${escapeHtml(e.name)}${e.designation ? ' — ' + escapeHtml(e.designation) : ''} [Field Staff]</option>`
    ).join('');
    return `<optgroup label="System Users">${userOpts || '<option disabled>No users</option>'}</optgroup>
            <optgroup label="Field Employees (Non-Login)">${empOpts || '<option disabled>No employees yet</option>'}</optgroup>`;
}

// Parse the "usr:<id>" / "emp:<id>" value from the dropdown
function parsePersonValue(val) {
    if (!val) return { user_id: null, employee_id: null };
    if (val.startsWith('usr:')) return { user_id: val.slice(4), employee_id: null };
    if (val.startsWith('emp:')) return { user_id: null, employee_id: val.slice(4) };
    // Legacy: bare id treated as user_id
    return { user_id: val, employee_id: null };
}

// Personnel pagination state
let personnelPaginationState = {
    currentPage: 1,
    itemsPerPage: 10,
    totalItems: 0,
    totalPages: 0,
};

function goToPersonnelPage(pageNum) {
    const page = Math.max(1, Math.min(parseInt(pageNum), personnelPaginationState.totalPages));
    personnelPaginationState.currentPage = page;
    renderPersonnelPage();
}

function previousPersonnelPage() {
    if (personnelPaginationState.currentPage > 1) {
        personnelPaginationState.currentPage--;
        document.getElementById('personnel-page-input').value = personnelPaginationState.currentPage;
        renderPersonnelPage();
    }
}

function nextPersonnelPage() {
    if (personnelPaginationState.currentPage < personnelPaginationState.totalPages) {
        personnelPaginationState.currentPage++;
        document.getElementById('personnel-page-input').value = personnelPaginationState.currentPage;
        renderPersonnelPage();
    }
}

function renderPersonnelPage() {
    const records = window.filteredEmployeeRecords || allEmployeeRecords || [];
    const state = personnelPaginationState;
    state.totalItems = records.length;
    state.totalPages = Math.max(1, Math.ceil(records.length / state.itemsPerPage));
    if (state.currentPage > state.totalPages) state.currentPage = state.totalPages;

    const start = (state.currentPage - 1) * state.itemsPerPage;
    const end = start + state.itemsPerPage;
    const pageRecords = records.slice(start, end);

    renderEmployeeRecordsTable(pageRecords);

    const paginationDiv = document.getElementById('personnel-pagination');
    if (paginationDiv) {
        paginationDiv.style.display = records.length > 0 ? 'block' : 'none';
    }
    const infoEl = document.getElementById('personnel-page-info');
    if (infoEl) infoEl.textContent = `Showing ${records.length ? start + 1 : 0} - ${Math.min(end, state.totalItems)} of ${state.totalItems}`;
    const inputEl = document.getElementById('personnel-page-input');
    if (inputEl) inputEl.value = state.currentPage;
    const totalEl = document.getElementById('personnel-total-pages');
    if (totalEl) totalEl.textContent = state.totalPages;
    const firstBtn = document.getElementById('personnel-first-page');
    const prevBtn = document.getElementById('personnel-prev-page');
    const nextBtn = document.getElementById('personnel-next-page');
    const lastBtn = document.getElementById('personnel-last-page');
    if (firstBtn) firstBtn.disabled = state.currentPage === 1;
    if (prevBtn) prevBtn.disabled = state.currentPage === 1;
    if (nextBtn) nextBtn.disabled = state.currentPage === state.totalPages;
    if (lastBtn) lastBtn.disabled = state.currentPage === state.totalPages;
}

function exportEmployeeRecordsCSV() {
    const records = window.filteredEmployeeRecords || allEmployeeRecords || [];
    if (!records.length) {
        showToast('No records to export', 'warning');
        return;
    }
    const headers = ['Employee', 'Location', 'Method', 'Title', 'Certificate #', 'Issuer', 'Issue Date', 'Expiry Date', 'Status'];
    const escape = escapeSpreadsheetCSV;
    const rows = records.map(r => [
        escape(r.employee_name || r.user_name || ''),
        escape(r.user_location || ''),
        escape(getEmployeeRecordMethod(r)),
        escape(r.title || ''),
        escape(r.certificate_number || ''),
        escape(r.issuer || ''),
        escape(r.issue_date ? new Date(r.issue_date).toLocaleDateString() : ''),
        escape(r.expiry_date ? new Date(r.expiry_date).toLocaleDateString() : ''),
        escape(r.is_active ? 'Active' : 'Inactive'),
    ]);
    const csv = [headers.join(','), ...rows.map(r => r.join(','))].join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'personnel_records_' + new Date().toISOString().slice(0, 10) + '.csv';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

async function loadEmployeeRecords(recordType = null) {
    const tbody = document.getElementById('employee-records-table-body');
    if (!tbody) return;

    try {
        const params = { page_size: 500 };
        const data = await EmployeeRecordsAPI.getAll(params);
        const records = Array.isArray(data) ? data : (data.items || []);
        allEmployeeRecords = records;
        window.filteredEmployeeRecords = records;
        personnelPaginationState.currentPage = 1;

        // Reset filter inputs
        const searchEl = document.getElementById('personal-search');
        if (searchEl) searchEl.value = '';
        const statusEl = document.getElementById('personal-status-filter');
        if (statusEl) statusEl.value = '';

        renderPersonnelPage();
    } catch (error) {
        console.error('Employee records load error:', error);
        tbody.innerHTML = '<tr><td colspan="10" class="text-center text-muted">Error loading employee records</td></tr>';
    }
}

function showAddEmployeeRecordModal() {
    Promise.all([ensureUsersCache(), ensureEmployeesCache()]).then(() => {
        const personOptions = buildPersonOptions();

        openModal('Add Employee Digital Record', `
        <form id="add-employee-record-form">
            <div class="form-row">
                <div class="form-group">
                    <label>Employee / Personnel *
                        <button type="button" class="btn btn-xs btn-secondary" style="margin-left:8px" onclick="showAddEmployeeModal(true)">+ Add New Field Staff</button>
                    </label>
                    <select name="person_id" id="add-record-person-select" required>
                        <option value="">Select person</option>
                        ${personOptions}
                    </select>
                </div>
                <div class="form-group">
                    <label>Method *</label>
                    <select name="method" required>
                        ${methodOptions()}
                    </select>
                </div>
            </div>

            <div class="form-row">
                <div class="form-group">
                    <label>Title *</label>
                    <select name="title" required>
                        ${levelTitleOptions()}
                    </select>
                </div>
                <div class="form-group">
                    <label>Certificate Number</label>
                    <input type="text" name="certificate_number" placeholder="e.g., CERT-UT-2026-014">
                </div>
            </div>

            <div class="form-row">
                <div class="form-group">
                    <label>Issuer</label>
                    <input type="text" name="issuer" placeholder="Issuing authority">
                </div>
                <div class="form-group">
                    <label>Issue Date</label>
                    <input type="date" name="issue_date">
                </div>
                <div class="form-group">
                    <label>Expiry Date</label>
                    <input type="date" name="expiry_date">
                </div>
            </div>

            <div class="form-group">
                <label>Notes</label>
                <textarea name="notes" rows="2" placeholder="Optional notes"></textarea>
            </div>

            <div class="modal-actions">
                <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                <button type="submit" class="btn btn-primary">Save Record</button>
            </div>
        </form>
    `, 'modal-lg');

        document.getElementById('add-employee-record-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const formData = new FormData(e.target);
            const { user_id, employee_id } = parsePersonValue(formData.get('person_id'));

        const payload = {
            user_id,
            employee_id,
            record_type: 'personal_qualification',
            title: formData.get('title'),
            certificate_number: formData.get('certificate_number') || null,
            issuer: formData.get('issuer') || null,
            issue_date: formData.get('issue_date') || null,
            expiry_date: formData.get('expiry_date') || null,
            notes: [`Method: ${formData.get('method')}`, formData.get('notes') || ''].filter(Boolean).join('\n'),
            is_active: true,
        };

            try {
                await EmployeeRecordsAPI.create(payload);
                closeModal();
                showToast('Employee record saved successfully', 'success');
                await loadEmployeeRecords();
            } catch (error) {
                showToast('Failed to save employee record: ' + error.message, 'error');
            }
        });
    }).catch(error => {
        showToast('Failed to load personnel list: ' + error.message, 'error');
    });
}

async function editEmployeeRecord(recordId) {
    try {
        await Promise.all([ensureUsersCache(), ensureEmployeesCache()]);
        const record = await EmployeeRecordsAPI.getById(recordId);

        // Determine current person selection value
        const currentPersonValue = record.employee_id ? `emp:${record.employee_id}` : (record.user_id ? `usr:${record.user_id}` : '');
        const personOptions = buildPersonOptions(currentPersonValue);

        const selectedMethod = getEmployeeRecordMethod(record);
        const cleanNotes = stripEmployeeRecordMethod(record.notes);

        openModal('Edit Employee Digital Record', `
            <form id="edit-employee-record-form">
                <div class="form-row">
                    <div class="form-group">
                        <label>Employee / Personnel *</label>
                        <select name="person_id" required>
                            ${personOptions}
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Method *</label>
                        <select name="method" required>
                            ${methodOptions(selectedMethod)}
                        </select>
                    </div>
                </div>

                <div class="form-row">
                    <div class="form-group">
                        <label>Title *</label>
                        <select name="title" required>
                            ${levelTitleOptions(record.title || '')}
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Certificate Number</label>
                        <input type="text" name="certificate_number" value="${record.certificate_number || ''}">
                    </div>
                </div>

                <div class="form-row">
                    <div class="form-group">
                        <label>Issuer</label>
                        <input type="text" name="issuer" value="${record.issuer || ''}">
                    </div>
                    <div class="form-group">
                        <label>Issue Date</label>
                        <input type="date" name="issue_date" value="${record.issue_date || ''}">
                    </div>
                    <div class="form-group">
                        <label>Expiry Date</label>
                        <input type="date" name="expiry_date" value="${record.expiry_date || ''}">
                    </div>
                </div>

                <div class="form-group">
                    <label>Notes</label>
                    <textarea name="notes" rows="2">${cleanNotes || ''}</textarea>
                </div>

                <div class="form-group">
                    <label>
                        <input type="checkbox" name="is_active" ${record.is_active ? 'checked' : ''}> Active
                    </label>
                </div>

                <div class="modal-actions">
                    <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary">Update Record</button>
                </div>
            </form>
        `, 'modal-lg');

        document.getElementById('edit-employee-record-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const formData = new FormData(e.target);
            const { user_id, employee_id } = parsePersonValue(formData.get('person_id'));

            const payload = {
                user_id,
                employee_id,
                record_type: 'personal_qualification',
                title: formData.get('title'),
                certificate_number: formData.get('certificate_number') || null,
                issuer: formData.get('issuer') || null,
                issue_date: formData.get('issue_date') || null,
                expiry_date: formData.get('expiry_date') || null,
                notes: [`Method: ${formData.get('method')}`, formData.get('notes') || ''].filter(Boolean).join('\n'),
                is_active: formData.has('is_active'),
            };

            try {
                await EmployeeRecordsAPI.update(recordId, payload);
                closeModal();
                showToast('Employee record updated successfully', 'success');
                await loadEmployeeRecords();
            } catch (error) {
                showToast('Failed to update employee record: ' + error.message, 'error');
            }
        });
    } catch (error) {
        showToast('Failed to load employee record: ' + error.message, 'error');
    }
}

async function deleteEmployeeRecord(recordId) {
    if (!confirm('Delete this employee digital record?')) {
        return;
    }

    try {
        await EmployeeRecordsAPI.delete(recordId);
        showToast('Employee record deleted successfully', 'success');
        await loadEmployeeRecords();
    } catch (error) {
        showToast('Failed to delete employee record: ' + error.message, 'error');
    }
}

// ── Field Staff (Non-Login Employee) Management ──────────────────────────────

async function showManageEmployeesModal() {
    try {
        const data = await EmployeesAPI.getAll({ page_size: 200 });
        const employees = Array.isArray(data) ? data : (data.items || []);
        employeesCache = employees; // refresh cache

        const rows = employees.length
            ? employees.map(emp => `
                <tr>
                    <td>${escapeHtml(emp.name)}</td>
                    <td>${emp.employee_code ? escapeHtml(emp.employee_code) : '-'}</td>
                    <td>${emp.designation ? escapeHtml(emp.designation) : '-'}</td>
                    <td>${emp.location_name ? escapeHtml(emp.location_name) : '-'}</td>
                    <td>${emp.phone ? escapeHtml(emp.phone) : '-'}</td>
                    <td><span class="badge ${emp.is_active ? 'badge-success' : 'badge-secondary'}">${emp.is_active ? 'Active' : 'Inactive'}</span></td>
                    <td class="actions">
                        <button class="btn-icon" onclick="showEditEmployeeModal('${emp.id}')" title="Edit"><i class="fas fa-edit"></i></button>
                        ${getUserPermissions().isAdmin ? `<button class="btn-icon text-danger" onclick="deleteEmployee('${emp.id}', '${escapeHtml(emp.name)}')" title="Permanent Delete"><i class="fas fa-trash"></i></button>` : ''}
                    </td>
                </tr>`).join('')
            : '<tr><td colspan="7" class="text-center text-muted">No field staff added yet</td></tr>';

        openModal('Manage Field Staff (Non-Login Employees)', `
            <div style="margin-bottom:12px">
                <button class="btn btn-primary btn-sm" onclick="showAddEmployeeModal()">
                    <i class="fas fa-plus"></i> Add Field Staff
                </button>
            </div>
            <div class="table-wrapper">
                <table class="data-table">
                    <thead><tr>
                        <th>Name</th><th>Code</th><th>Designation</th><th>Location</th><th>Phone</th><th>Status</th><th>Actions</th>
                    </tr></thead>
                    <tbody id="employees-modal-table">${rows}</tbody>
                </table>
            </div>
            <div class="modal-actions">
                <button class="btn btn-secondary" onclick="closeModal()">Close</button>
            </div>
        `, 'modal-xl');
    } catch (error) {
        showToast('Failed to load field staff: ' + error.message, 'error');
    }
}

function showAddEmployeeModal(returnToRecord = false) {
    let locData = [];
    const doShow = () => {
        const locOptions = activeRecords(locData).map(loc =>
            `<option value="${loc.id}">${escapeHtml(loc.name)}</option>`
        ).join('');

        openModal('Add Field Staff (Non-Login Employee)', `
            <form id="add-employee-form">
                <div class="form-row">
                    <div class="form-group">
                        <label>Full Name *</label>
                        <input type="text" name="name" required placeholder="e.g., Ahmed Al-Rashid">
                    </div>
                    <div class="form-group">
                        <label>Employee Code</label>
                        <input type="text" name="employee_code" placeholder="e.g., EMP-001">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Designation</label>
                        <input type="text" name="designation" placeholder="e.g., NDT Level II Technician">
                    </div>
                    <div class="form-group">
                        <label>Department</label>
                        <input type="text" name="department" placeholder="e.g., Inspection">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Phone</label>
                        <input type="text" name="phone" placeholder="+966 5x xxx xxxx">
                    </div>
                    <div class="form-group">
                        <label>Email</label>
                        <input type="email" name="email" placeholder="Optional">
                    </div>
                </div>
                <div class="form-group">
                    <label>Location</label>
                    <select name="location_id">
                        <option value="">-- Select location --</option>
                        ${locOptions}
                    </select>
                </div>
                <div class="form-group">
                    <label>Notes</label>
                    <textarea name="notes" rows="2" placeholder="Optional notes"></textarea>
                </div>
                <div class="modal-actions">
                    <button type="button" class="btn btn-secondary" onclick="${returnToRecord ? 'showAddEmployeeRecordModal()' : 'showManageEmployeesModal()'}">Cancel</button>
                    <button type="submit" class="btn btn-primary">Save</button>
                </div>
            </form>
        `, 'modal-lg');

        document.getElementById('add-employee-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const fd = new FormData(e.target);
            const payload = {
                name: fd.get('name'),
                employee_code: fd.get('employee_code') || null,
                designation: fd.get('designation') || null,
                department: fd.get('department') || null,
                phone: fd.get('phone') || null,
                email: fd.get('email') || null,
                location_id: fd.get('location_id') || null,
                notes: fd.get('notes') || null,
            };
            try {
                await EmployeesAPI.create(payload);
                employeesCache = []; // reset cache
                showToast('Field staff added successfully', 'success');
                if (returnToRecord) {
                    await ensureEmployeesCache();
                    showAddEmployeeRecordModal();
                } else {
                    showManageEmployeesModal();
                }
            } catch (error) {
                showToast('Failed to add field staff: ' + error.message, 'error');
            }
        });
    };

        if (locData.length > 0) {
        doShow();
    } else {
        LocationsAPI.getAll({ page_size: 200, is_active: true }).then(data => {
            locData = Array.isArray(data) ? data : (data.items || []);
            doShow();
        }).catch(() => doShow());
    }
}

async function showEditEmployeeModal(employeeId) {
    try {
        const emp = await EmployeesAPI.getById(employeeId);
        let locData = [];
        if (!locData.length) {
            const d = await LocationsAPI.getAll({ page_size: 200, is_active: true });
            locData = Array.isArray(d) ? d : (d.items || []);
        }
        locData = activeRecords(locData);
        const locOptions = locData.map(loc =>
            `<option value="${loc.id}" ${loc.id === emp.location_id ? 'selected' : ''}>${escapeHtml(loc.name)}</option>`
        ).join('');

        openModal('Edit Field Staff', `
            <form id="edit-employee-form">
                <div class="form-row">
                    <div class="form-group">
                        <label>Full Name *</label>
                        <input type="text" name="name" required value="${escapeHtml(emp.name)}">
                    </div>
                    <div class="form-group">
                        <label>Employee Code</label>
                        <input type="text" name="employee_code" value="${emp.employee_code ? escapeHtml(emp.employee_code) : ''}">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Designation</label>
                        <input type="text" name="designation" value="${emp.designation ? escapeHtml(emp.designation) : ''}">
                    </div>
                    <div class="form-group">
                        <label>Department</label>
                        <input type="text" name="department" value="${emp.department ? escapeHtml(emp.department) : ''}">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Phone</label>
                        <input type="text" name="phone" value="${emp.phone ? escapeHtml(emp.phone) : ''}">
                    </div>
                    <div class="form-group">
                        <label>Email</label>
                        <input type="email" name="email" value="${emp.email ? escapeHtml(emp.email) : ''}">
                    </div>
                </div>
                <div class="form-group">
                    <label>Location</label>
                    <select name="location_id">
                        <option value="">-- No location --</option>
                        ${locOptions}
                    </select>
                </div>
                <div class="form-group">
                    <label><input type="checkbox" name="is_active" ${emp.is_active ? 'checked' : ''}> Active</label>
                </div>
                <div class="form-group">
                    <label>Notes</label>
                    <textarea name="notes" rows="2">${emp.notes ? escapeHtml(emp.notes) : ''}</textarea>
                </div>
                <div class="modal-actions">
                    <button type="button" class="btn btn-secondary" onclick="showManageEmployeesModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary">Update</button>
                </div>
            </form>
        `, 'modal-lg');

        document.getElementById('edit-employee-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const fd = new FormData(e.target);
            const payload = {
                name: fd.get('name'),
                employee_code: fd.get('employee_code') || null,
                designation: fd.get('designation') || null,
                department: fd.get('department') || null,
                phone: fd.get('phone') || null,
                email: fd.get('email') || null,
                location_id: fd.get('location_id') || null,
                is_active: fd.has('is_active'),
                notes: fd.get('notes') || null,
            };
            try {
                await EmployeesAPI.update(employeeId, payload);
                employeesCache = [];
                showToast('Field staff updated successfully', 'success');
                showManageEmployeesModal();
            } catch (error) {
                showToast('Failed to update field staff: ' + error.message, 'error');
            }
        });
    } catch (error) {
        showToast('Failed to load employee: ' + error.message, 'error');
    }
}

async function deleteEmployee(employeeId, name) {
    if (!confirm(`Delete field staff "${name}"? This will also remove all their personnel records.`)) return;
    try {
        await EmployeesAPI.delete(employeeId);
        employeesCache = [];
        showToast('Field staff deleted', 'success');
        showManageEmployeesModal();
    } catch (error) {
        showToast('Failed to delete field staff: ' + error.message, 'error');
    }
}

function showAddUserModal() {
    const perms = getUserPermissions();
    // Load locations for assignment
    const loadAndShow = async () => {
        let locData = [];
        try {
            const data = await LocationsAPI.getAll({ page_size: 500, is_active: true });
            locData = activeRecords(Array.isArray(data) ? data : (data.items || []));
        } catch(e) {}

        const locationCheckboxes = locData.map(loc =>
            `<label class="checkbox-item">
                <input type="checkbox" name="location_ids" value="${loc.id}">
                ${loc.name}
            </label>`
        ).join('');

        openModal('Add New User', `
            <form id="add-user-form">
                <div class="form-row">
                    <div class="form-group">
                        <label>Name *</label>
                        <input type="text" name="name" required placeholder="Full name">
                    </div>
                    <div class="form-group">
                        <label>Email *</label>
                        <input type="email" name="email" required placeholder="email@example.com">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Password *</label>
                        <input type="password" name="password" required placeholder="Password" minlength="8">
                    </div>
                    <div class="form-group">
                        <label>Role *</label>
                        <select name="role" required id="add-user-role-select" onchange="toggleAddUserLocationSection()">
                            <option value="location_manager">Location Manager</option>
                            ${perms.isAdmin ? '<option value="head_office_manager">General Manager</option>' : ''}
                            ${perms.isAdmin ? '<option value="admin">Admin</option>' : ''}
                        </select>
                    </div>
                </div>
                <div class="form-group" id="add-user-location-group">
                    <label>Assigned Locations</label>
                    <div class="checkbox-group">
                        ${locationCheckboxes || '<em>No locations available</em>'}
                    </div>
                    <small class="text-muted">Required for Location Manager. Admin and General Manager belong to all locations automatically.</small>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Phone</label>
                        <input type="text" name="phone" placeholder="Phone number">
                    </div>
                    <div class="form-group">
                        <label>Department</label>
                        <input type="text" name="department" placeholder="Department">
                    </div>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-outline" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary">Create User</button>
                </div>
            </form>
        `);

        toggleAddUserLocationSection();

        document.getElementById('add-user-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const formData = new FormData(e.target);
            const role = formData.get('role');
            const assignedLocationIds = role === 'location_manager' ? formData.getAll('location_ids') : [];

            if (role === 'location_manager' && assignedLocationIds.length === 0) {
                showToast('Assign at least one location for Location Manager', 'error');
                return;
            }

            const data = {
                name: formData.get('name'),
                email: formData.get('email'),
                password: formData.get('password'),
                role,
                assigned_location_ids: assignedLocationIds,
                phone: formData.get('phone') || null,
                department: formData.get('department') || null,
                is_active: true
            };

            try {
                await UsersAPI.create(data);
                closeModal();
                showToast('User created successfully', 'success');
                loadUsers();
            } catch (error) {
                showToast(error.message, 'error');
            }
        });
    };
    loadAndShow().catch(err => showToast('Error loading form: ' + err.message, 'error'));
}

function toggleAddUserLocationSection() {
    const roleSelect = document.getElementById('add-user-role-select');
    const locGroup = document.getElementById('add-user-location-group');
    if (!roleSelect || !locGroup) return;
    locGroup.style.display = roleSelect.value === 'location_manager' ? '' : 'none';
}

function toggleEditUserLocationSection() {
    const roleSelect = document.getElementById('edit-user-role-select');
    const locGroup = document.getElementById('edit-user-location-group');
    if (!roleSelect || !locGroup) return;
    locGroup.style.display = roleSelect.value === 'location_manager' ? '' : 'none';
}

async function editUser(id) {
    try {
        const user = await UsersAPI.getById(id);
        
        // Load locations for assignment
        let locData = [];
        try {
            const data = await LocationsAPI.getAll({ page_size: 500, is_active: true });
            locData = Array.isArray(data) ? data : (data.items || []);
        } catch(e) {}
        
        const userLocIds = user.assigned_location_ids || [];
        locData = activeRecords(locData);
        const locationCheckboxes = locData.map(loc => 
            `<label class="checkbox-item">
                <input type="checkbox" name="location_ids" value="${loc.id}" ${userLocIds.includes(loc.id) ? 'checked' : ''}>
                ${loc.name}
            </label>`
        ).join('');

        openModal('Edit User', `
            <form id="edit-user-form">
                <div class="form-row">
                    <div class="form-group">
                        <label>Name *</label>
                        <input type="text" name="name" required value="${user.name}" placeholder="Full name">
                    </div>
                    <div class="form-group">
                        <label>Email *</label>
                        <input type="email" name="email" required value="${user.email}" placeholder="user@example.com">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Role *</label>
                        <select name="role" required id="edit-user-role-select" onchange="toggleEditUserLocationSection()">
                            <option value="location_manager" ${user.role === 'location_manager' ? 'selected' : ''}>Location Manager</option>
                            ${getUserPermissions().isAdmin ? `<option value="head_office_manager" ${user.role === 'head_office_manager' ? 'selected' : ''}>General Manager</option>` : ''}
                            ${getUserPermissions().isAdmin ? `<option value="admin" ${user.role === 'admin' ? 'selected' : ''}>Admin</option>` : ''}
                        </select>
                    </div>
                    <div class="form-group">
                        <label>New Password (leave blank to keep current)</label>
                        <input type="password" name="password" placeholder="New password">
                    </div>
                </div>
                <div class="form-group" id="edit-user-location-group" style="display:${user.role === 'location_manager' ? '' : 'none'}">
                    <label>Assigned Locations</label>
                    <div class="checkbox-group">
                        ${locationCheckboxes || '<em>No locations available</em>'}
                    </div>
                    <small class="text-muted">Required for Location Manager. Admin and General Manager belong to all locations automatically.</small>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Phone</label>
                        <input type="text" name="phone" value="${user.phone || ''}" placeholder="Phone number">
                    </div>
                    <div class="form-group">
                        <label>Department</label>
                        <input type="text" name="department" value="${user.department || ''}" placeholder="Department">
                    </div>
                </div>
                <div class="form-group">
                    <label>
                        <input type="checkbox" name="is_active" ${user.is_active ? 'checked' : ''}> Active
                    </label>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-outline" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary">Update User</button>
                </div>
            </form>
        `);
        
        document.getElementById('edit-user-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const formData = new FormData(e.target);
            const role = formData.get('role');
            const assignedLocationIds = role === 'location_manager' ? formData.getAll('location_ids') : [];

            if (role === 'location_manager' && assignedLocationIds.length === 0) {
                showToast('Assign at least one location for Location Manager', 'error');
                return;
            }
            
            const data = {
                name: formData.get('name'),
                email: formData.get('email'),
                role,
                is_active: formData.has('is_active'),
                assigned_location_ids: assignedLocationIds,
                phone: formData.get('phone') || null,
                department: formData.get('department') || null,
            };
            
            // Only include password if provided
            if (formData.get('password')) {
                data.password = formData.get('password');
            }
            
            try {
                await UsersAPI.update(id, data);
                closeModal();
                showToast('User updated successfully', 'success');
                loadUsers();
            } catch (error) {
                showToast(error.message, 'error');
            }
        });
    } catch (error) {
        showToast('Error loading user: ' + error.message, 'error');
    }
}

// Modal functions
function openModal(title, content, sizeClass = '') {
    document.getElementById('modal-title').textContent = title;
    document.getElementById('modal-body').innerHTML = content;
    
    // Apply size class if provided
    const modal = document.querySelector('.modal');
    modal.classList.remove('modal-lg', 'modal-xl');
    if (sizeClass) {
        modal.classList.add(sizeClass);
    }
    
    document.getElementById('modal-overlay').classList.remove('hidden');
}

function closeModal() {
    document.getElementById('modal-overlay').classList.add('hidden');
    // Reset modal size
    const modal = document.querySelector('.modal');
    modal.classList.remove('modal-lg', 'modal-xl');
}

// Close modal on overlay click
document.getElementById('modal-overlay')?.addEventListener('click', (e) => {
    if (e.target.id === 'modal-overlay') {
        closeModal();
    }
});

// Toast notifications
function showToast(message, type = 'info', duration = 5000) {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    
    const icons = {
        success: 'fa-check-circle',
        error: 'fa-exclamation-circle',
        warning: 'fa-exclamation-triangle',
        info: 'fa-info-circle'
    };
    
    toast.innerHTML = `
        <i class="fas ${icons[type] || icons.info}"></i>
        <span>${message}</span>
    `;
    
    container.appendChild(toast);
    
    // Auto remove after specified duration
    setTimeout(() => {
        toast.remove();
    }, duration);
}

// Keyboard shortcuts
document.addEventListener('keydown', (e) => {
    // Close modal on Escape
    if (e.key === 'Escape') {
        closeModal();
    }
});

// ==========================================
// Jobs (Hold) Management
// ==========================================

const JOB_METHOD_LABELS = {
    rt: 'RT', ut: 'UT', mt: 'MT', pt: 'PT', vt: 'VT', et: 'ET', other: 'Other'
};

const JOB_STATUS_LABELS = {
    hold: 'Hold',
    in_progress: 'In Progress',
    completed: 'Completed',
    verified: 'Verified'
};

const JOB_STATUS_BADGES = {
    hold: 'badge-warning',
    in_progress: 'badge-info',
    completed: 'badge-primary',
    verified: 'badge-success'
};

// ============================================================
// PURCHASE INDENT UTILITIES
// PI is auto-created when a transfer is requested.
// These helpers are called from the Transfer detail modal.
// ============================================================

const PI_STATUS_BADGE = {
    draft: 'badge-secondary',
    submitted: 'badge-warning',
    approved: 'badge-info',
    rejected: 'badge-danger',
    fulfilled: 'badge-success',
    partially_fulfilled: 'badge-warning',
    cancelled: 'badge-danger',
};

async function viewPurchaseIndent(id) {
    try {
        const pi = await PurchaseIndentsAPI.getById(id);
        const statusCls = PI_STATUS_BADGE[pi.status] || 'badge-secondary';
        const statusLabel = (pi.status || '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
        const date = pi.indent_date ? new Date(pi.indent_date).toLocaleDateString() : '-';
        const itemsHtml = (pi.items || []).map(item => `
            <tr>
                <td>${item.item_sku || '-'}</td>
                <td>${item.item_name || '-'}</td>
                <td>${item.quantity_requested}</td>
                <td>${item.quantity_approved}</td>
                <td>${item.quantity_fulfilled}</td>
                <td>${item.notes || '-'}</td>
            </tr>`).join('') || '<tr><td colspan="6" class="text-muted text-center">No items</td></tr>';

        document.getElementById('modal-title').textContent = `Purchase Indent — ${pi.indent_number}`;
        document.getElementById('modal-body').innerHTML = `
            <div style="margin-bottom:12px;">
                <span class="badge-status ${statusCls}">${statusLabel}</span>
                <span style="margin-left:12px;color:#718096;font-size:13px;">Created ${date}</span>
            </div>
            <div class="form-row" style="gap:16px;margin-bottom:12px;">
                <div><strong>Requesting Location</strong><div>${pi.requesting_location_name || '-'}</div></div>
                <div><strong>Supplying Location</strong><div>${pi.supplying_location_name || '-'}</div></div>
                <div><strong>Requested By</strong><div>${pi.requested_by_name || '-'}</div></div>
                <div><strong>Approved By</strong><div>${pi.approved_by_name || '-'}</div></div>
            </div>
            ${pi.purpose ? `<div style="margin-bottom:8px;"><strong>Purpose:</strong> ${pi.purpose}</div>` : ''}
            ${pi.notes ? `<div style="margin-bottom:8px;"><strong>Notes:</strong> ${pi.notes}</div>` : ''}
            ${pi.rejection_reason ? `<div style="margin-bottom:8px;color:#e53e3e;"><strong>Rejection Reason:</strong> ${pi.rejection_reason}</div>` : ''}
            <table class="data-table" style="margin-top:12px;">
                <thead><tr><th>SKU</th><th>Name</th><th>Qty Requested</th><th>Qty Approved</th><th>Qty Fulfilled</th><th>Notes</th></tr></thead>
                <tbody>${itemsHtml}</tbody>
            </table>
            <div class="modal-actions" style="margin-top:16px;">
                <button class="btn btn-secondary" onclick="closeModal()">Close</button>
                <button class="btn btn-primary" onclick="printPIDocument('${pi.id}')"><i class="fas fa-print"></i> Print PI</button>
            </div>`;
        document.getElementById('modal-overlay').classList.remove('hidden');
    } catch (err) {
        showToast('Failed to load PI: ' + err.message, 'error');
    }
}

async function printPIDocument(id) {
    try {
        const doc = await PurchaseIndentsAPI.getDocument(id);
        const win = window.open('', '_blank', 'width=900,height=700');
        win.document.write(buildPIDocumentHTML(doc));
        win.document.close();
        win.focus();
        setTimeout(() => win.print(), 500);
    } catch (err) {
        showToast('Failed to generate PI document: ' + err.message, 'error');
    }
}

function buildPIDocumentHTML(doc) {
    const reqByDate = doc.required_by_date
        ? new Date(doc.required_by_date).toLocaleDateString('en-IN', {day:'2-digit',month:'2-digit',year:'numeric'})
        : '';
    const indentDate = doc.indent_date
        ? new Date(doc.indent_date).toLocaleDateString('en-IN', {day:'2-digit',month:'2-digit',year:'numeric'})
        : '';

    const itemRows = (doc.items || []).map((item, i) => `
        <tr>
            <td class="sl">${i + 1}</td>
            <td class="material">${item.sku ? `${escapeHtml(item.sku)} - ` : ''}${escapeHtml(item.name || '')}${item.notes ? `<br><span>${escapeHtml(item.notes)}</span>` : ''}</td>
            <td class="qty">${item.quantity_requested || ''}</td>
            <td class="date-cell">${reqByDate}</td>
            <td class="send-to">${escapeHtml(doc.supplying_location || '')}</td>
        </tr>`).join('');

    const emptyCount = Math.max(0, 10 - (doc.items || []).length);
    const emptyRows = Array.from({length: emptyCount}, () => `
        <tr>
            <td class="sl"></td><td class="material"></td><td class="qty"></td><td class="date-cell"></td><td class="send-to"></td>
        </tr>`).join('');
    const logoSrc = doc.logo_data_url || 'assets/scientech-logo.png';
    const signatureName = doc.printed_by || doc.requested_by || '';
    const signatureDate = doc.printed_date || indentDate || '';

    return `<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>Purchase Indent ${doc.indent_number}</title>
<style>
    * { box-sizing: border-box; }
    @page { size: A4 landscape; margin: 10mm; }
    body {
        font-family: Arial, Helvetica, sans-serif;
        color: #000;
        margin: 0;
        padding: 0;
        background: #fff;
        font-size: 11px;
    }
    .pi-sheet {
        width: 277mm;
        min-height: 188mm;
        margin: 0 auto;
        padding: 8mm 12mm 8mm;
        position: relative;
    }
    .letterhead {
        display: grid;
        grid-template-columns: 108px 1fr;
        align-items: center;
        column-gap: 14px;
        min-height: 84px;
        padding: 2px 0 4px;
    }
    .logo-wrap {
        width: 100px;
        height: 76px;
        display: flex;
        align-items: center;
        justify-content: center;
    }
    .logo-wrap img {
        max-width: 100px;
        max-height: 76px;
        object-fit: contain;
    }
    .company-name {
        font-family: "Times New Roman", serif;
        font-size: 34px;
        line-height: 0.95;
        font-weight: 700;
    }
    .company-sub {
        font-size: 16px;
        line-height: 1.15;
        font-weight: 700;
        margin-top: 1px;
    }
    .nabl,
    .address {
        font-size: 10px;
        line-height: 1.25;
        font-weight: 700;
    }
    .title {
        text-align: center;
        font-family: "Times New Roman", serif;
        font-size: 24px;
        font-weight: 700;
        margin: 4px 0 4px;
    }
    .meta-grid {
        display: grid;
        grid-template-columns: 1fr 145px;
        border-top: 2px solid #000;
        border-bottom: 2px solid #000;
        min-height: 52px;
    }
    .from-to {
        display: grid;
        grid-template-rows: 1fr 1fr;
        border-right: 2px solid #000;
        font-size: 14px;
        font-weight: 700;
    }
    .from-to div {
        display: grid;
        grid-template-columns: 70px 1fr;
        align-items: center;
        border-bottom: 1px solid #000;
        padding: 0 8px;
    }
    .from-to div:last-child { border-bottom: 0; }
    .meta-right {
        display: grid;
        grid-template-rows: 1fr 1fr;
        text-align: center;
        font-weight: 700;
        font-size: 13px;
    }
    .meta-right div {
        display: flex;
        align-items: center;
        justify-content: center;
        border-bottom: 1px solid #000;
    }
    .meta-right div:last-child { border-bottom: 0; }
    table {
        width: 100%;
        border-collapse: collapse;
        table-layout: fixed;
        margin-top: 0;
    }
    th,
    td {
        border-left: 2px solid #000;
        border-right: 2px solid #000;
        padding: 5px 6px;
        vertical-align: top;
        color: #000;
    }
    th {
        border-top: 2px solid #000;
        border-bottom: 2px solid #000;
        height: 42px;
        text-align: center;
        font-size: 11px;
        font-weight: 700;
    }
    tbody td {
        height: 28px;
        font-size: 11px;
    }
    tbody tr:last-child td { border-bottom: 2px solid #000; }
    .sl { width: 44px; text-align: center; }
    .material { width: auto; }
    .material span { font-size: 10px; }
    .qty { width: 90px; text-align: center; }
    .date-cell { width: 86px; text-align: center; }
    .send-to { width: 130px; }
    .footer {
        display: grid;
        grid-template-columns: 1fr 1fr;
        align-items: start;
        min-height: 72px;
        font-weight: 700;
        font-size: 12px;
        border-top: 2px solid #000;
        padding-top: 8px;
    }
    .footer .right {
        text-align: center;
        justify-self: end;
        min-width: 210px;
    }
    .signature-name {
        margin-top: 22px;
        font-weight: 700;
    }
    .signature-date {
        margin-top: 4px;
        font-weight: 400;
    }
    .signature-role {
        margin-top: 10px;
        font-weight: 700;
    }
    @media print {
        body { margin: 0; }
        .pi-sheet { margin: 0; }
    }
</style>
</head>
<body>
<div class="pi-sheet">
    <div class="letterhead">
        <div class="logo-wrap"><img src="${logoSrc}" alt="Scientech Services logo" onerror="this.style.display='none'"></div>
        <div>
            <div class="company-name">Scientech Services</div>
            <div class="company-sub">Non Destructive Testing Engineers</div>
            <div class="nabl">NABL ACCREDITED LAB IN ACCORDANCE WITH ISO/IEC 17025 IN THE NDT DISCIPLINES</div>
            <div class="address">No. 15, Singasandra 14th K.M., Hosur Road, Bangalore - 560 068.</div>
        </div>
    </div>
    <div class="title">Purchase Indent</div>
    <div class="meta-grid">
        <div class="from-to">
            <div><span>FROM :</span><span>${escapeHtml(doc.requesting_location || '')}</span></div>
            <div><span>TO :</span><span>${escapeHtml(doc.supplying_location || '')}</span></div>
        </div>
        <div class="meta-right">
            <div>DATE&nbsp;&nbsp;${indentDate}</div>
            <div>FM-PR-04</div>
        </div>
    </div>
    <table>
        <thead>
            <tr>
                <th class="sl">No.</th>
                <th>RAW MATERIAL &amp; SPECIFICATION</th>
                <th class="qty">Qty. Required</th>
                <th class="date-cell">Reqd By<br>Date</th>
                <th class="send-to">To be Sent To</th>
            </tr>
        </thead>
        <tbody>
            ${itemRows}
            ${emptyRows}
        </tbody>
    </table>
    <div class="footer">
        <div>FOR SCIENTECH SERVICES</div>
        <div class="right">
            <div class="signature-name">${escapeHtml(signatureName)}</div>
            <div class="signature-date">Date: ${escapeHtml(signatureDate)}</div>
            <div class="signature-role">Office Assistant</div>
        </div>
    </div>
</div>
</body></html>`;
}

async function printDeliveryChallan(transferId) {
    try {
        const dc = await TransfersAPI.getDeliveryChallan(transferId);
        const win = window.open('', '_blank', 'width=900,height=700');
        win.document.write(buildDCDocumentHTML(dc));
        win.document.close();
        win.focus();
        setTimeout(() => win.print(), 500);
    } catch (err) {
        showToast('Failed to generate Delivery Challan: ' + err.message, 'error');
    }
}

function buildDCDocumentHTML(dc) {
    const items = dc.items || [];
    const minimumItemRows = 7;
    const totalQty = items.reduce((s, it) => s + (it.quantity_shipped || 0), 0);
    const referenceNumber = dc.indent_number || dc.transfer_number || '';
    const refDate = dc.ref_date || dc.dc_date || '';
    const remarks = dc.shipping_notes || `Sending to ${dc.to_location || ''}.`;
    const logoMarkup = dc.logo_data_url
        ? `<img src="${dc.logo_data_url}" alt="Scientech Services logo">`
        : '<div class="ss-logo" aria-label="Scientech Services logo">SS</div>';
    const typeLabel = 'RETURNABLE/NON RETURNABLE';
    const remarksRowspan = Math.max(minimumItemRows, items.length) + 1;
    const companyName = dc.company_name || 'M/s Scientech Services';
    const issuedBy = dc.issued_by || dc.shipped_by || '';

    const itemDescription = (item) => {
        const parts = [item.name || ''];
        if (item.sku) parts.unshift(item.sku);
        if (item.lot_number) parts.push(`Batch: ${item.lot_number}`);
        if (Array.isArray(item.serial_numbers) && item.serial_numbers.length) {
            parts.push(`Serial: ${item.serial_numbers.join(', ')}`);
        }
        if (item.notes) parts.push(item.notes);
        return parts.filter(Boolean).map(escapeHtml).join('<br>');
    };

    let itemRows = items.map((item, i) => `
        <tr>
            <td class="sl">${i + 1}</td>
            <td class="description">${itemDescription(item)}</td>
            <td class="qty">${item.quantity_shipped || ''} No's</td>
            ${i === 0 ? `<td class="remarks" rowspan="${remarksRowspan}">${escapeHtml(remarks)}</td>` : ''}
        </tr>`).join('');

    for (let i = items.length; i < minimumItemRows; i++) {
        itemRows += `
        <tr>
            <td class="sl"></td>
            <td class="description"></td>
            <td class="qty"></td>
            ${i === 0 ? `<td class="remarks" rowspan="${remarksRowspan}">${escapeHtml(remarks)}</td>` : ''}
        </tr>`;
    }

    return `<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Delivery Challan — ${dc.dc_number}</title>
<style>
    * { box-sizing: border-box; }
    @page { size: A4 portrait; margin: 12mm; }
    body { font-family: Arial, Helvetica, sans-serif; font-size: 11px; color: #000; background: #fff; margin: 0; padding: 0; }
    .page { width: 176mm; margin: 0 auto; border: 2px solid #000; }
    table { width: 100%; border-collapse: collapse; table-layout: fixed; }
    td, th { border: 1px solid #000; padding: 3px 5px; vertical-align: middle; }
    .logo-cell { width: 100px; height: 70px; text-align: center; }
    .logo-cell img { max-width: 62px; max-height: 48px; object-fit: contain; }
    .ss-logo { display: inline-flex; align-items: center; justify-content: center; width: 54px; height: 46px; border: 3px solid #1769aa; border-radius: 8px; color: #1769aa; font-size: 23px; font-weight: 800; letter-spacing: -2px; }
    .company { text-align: center; font-weight: 700; }
    .company-name { font-size: 12px; margin-bottom: 8px; }
    .dc-title { font-size: 13px; margin-bottom: 4px; }
    .accred { font-size: 11px; line-height: 1.15; }
    .meta-label { width: 78px; font-weight: 700; }
    .meta-value { text-align: center; }
    .info-label { width: 74px; font-weight: 700; }
    .bold { font-weight: 700; }
    .address-box { height: 64px; line-height: 1.15; }
    .greeting { height: 38px; padding: 6px 5px; vertical-align: top; font-weight: 700; }
    .type-label { text-align: center; font-weight: 700; height: 28px; }
    .items th { height: 28px; text-align: center; font-weight: 700; }
    .items td { height: 27px; vertical-align: top; }
    .sl { width: 40px; text-align: center; }
    .description { width: auto; text-align: center; }
    .qty { width: 86px; text-align: center; }
    .remarks { width: 132px; text-align: left; vertical-align: middle; font-size: 10px; }
    .total-row td { height: 26px; }
    .signature { display: grid; grid-template-columns: 1fr 1fr; height: 44px; border-top: 1px solid #000; }
    .signature div { padding: 4px 6px; font-weight: 700; }
    .signature div:last-child { text-align: center; border-left: 1px solid #000; }
    .footer-address { border-top: 1px solid #000; text-align: center; color: #0070c0; font-size: 10px; line-height: 1.25; padding: 6px 8px; }
    @media print {
        body { margin: 0; }
        .page { margin: 0 auto; }
    }
</style>
</head>
<body>
<div class="page">
    <table>
        <tr>
            <td class="logo-cell" rowspan="3">${logoMarkup}</td>
            <td class="company" rowspan="3">
                <div class="company-name">${escapeHtml(companyName)}</div>
                <div class="dc-title">DELIVERY CHALLAN</div>
                <div class="accred">AS9100 and ISO 9001:2015 Accredited Lab<br>(UKAS Accreditation)</div>
            </td>
            <td class="meta-label">Doc. No.</td>
            <td class="meta-value">STR-F-05</td>
        </tr>
        <tr>
            <td class="meta-label">Rev. No.</td>
            <td class="meta-value">01</td>
        </tr>
        <tr>
            <td class="meta-label">Rev. Date</td>
            <td class="meta-value">13-Jul-23</td>
        </tr>
    </table>
    <table>
        <tr>
            <td class="info-label">DC NO</td>
            <td class="bold">${escapeHtml(dc.dc_number || dc.transfer_number || '')}</td>
            <td style="width:55px;">Date:</td>
            <td style="width:120px;text-align:center;">${escapeHtml(dc.dc_date || '')}</td>
        </tr>
        <tr>
            <td class="info-label">To :</td>
            <td colspan="3" class="bold">${escapeHtml(dc.to_location || '')}</td>
        </tr>
        <tr>
            <td class="info-label">Address</td>
            <td class="address-box">${escapeHtml(dc.to_location_address || '')}</td>
            <td class="bold">Reference<br>Number</td>
            <td style="text-align:center;">${escapeHtml(referenceNumber)}</td>
        </tr>
        <tr>
            <td class="info-label">From :</td>
            <td class="bold">${escapeHtml(dc.from_location || '')}</td>
            <td class="bold">Ref. Date:</td>
            <td style="text-align:center;">${escapeHtml(refDate)}</td>
        </tr>
        <tr>
            <td class="info-label">Address</td>
            <td colspan="3" class="address-box">${escapeHtml(dc.from_location_address || '')}</td>
        </tr>
    </table>
    <table>
        <tr><td class="greeting" colspan="4">Dear Sir/Madam,</td></tr>
        <tr><td class="type-label" colspan="4">${typeLabel}</td></tr>
    </table>
    <table class="items">
        <thead>
            <tr>
                <th class="sl">Sl No</th>
                <th>Description</th>
                <th class="qty">Quantity</th>
                <th class="remarks">Remarks</th>
            </tr>
        </thead>
        <tbody>
            ${itemRows}
            <tr class="total-row">
                <td></td>
                <td style="text-align:center;">Total</td>
                <td style="text-align:center;">${totalQty} No's</td>
            </tr>
        </tbody>
    </table>
    <div class="signature">
        <div>Issued by,<br><br>${escapeHtml(issuedBy)}</div>
        <div>Receiver's Signature</div>
    </div>
    <div class="footer-address">
        15, Singasandra, 14th K.M. Hosur Road, Bangalore-560068. Ph:080-25730691, 25730719,<br>
        Mob:9945060978 Email:contact@scientechservices.com, www.scientechservices.com<br>
        GST NO : 29AKQPB1576N1ZJ
    </div>
</div>
</body></html>`;
}

async function loadJobs() {
    // Jobs module is coming soon — no-op
}

// ============================================================
// PREMIUM FEATURE: NOTIFICATION DROPDOWN PANEL
// ============================================================

let _notifPollInterval = null;
let _notifPanelOpen = false;

function toggleNotificationsPanel() {
    const panel = document.getElementById('notifications-panel');
    if (!panel) return;
    _notifPanelOpen = !panel.classList.contains('hidden');
    if (_notifPanelOpen) {
        panel.classList.add('hidden');
        _notifPanelOpen = false;
    } else {
        panel.classList.remove('hidden');
        _notifPanelOpen = true;
        loadNotificationsPanel();
    }
}

function closeNotificationsPanel() {
    const panel = document.getElementById('notifications-panel');
    if (panel) panel.classList.add('hidden');
    _notifPanelOpen = false;
}

document.addEventListener('click', (e) => {
    const panel = document.getElementById('notifications-panel');
    const btn = document.getElementById('notifications-btn');
    if (!panel || !btn) return;
    if (!panel.classList.contains('hidden') && !panel.contains(e.target) && !btn.contains(e.target)) {
        closeNotificationsPanel();
    }
});

async function loadNotificationsPanel() {
    const listEl = document.getElementById('notifications-list');
    if (!listEl) return;
    listEl.innerHTML = '<div class="notif-loading"><i class="fas fa-spinner fa-spin"></i> Loading\u2026</div>';
    try {
        const data = await NotificationsAPI.getAll({ page_size: 20, sort_by: 'created_at', sort_order: 'desc' });
        const notifs = Array.isArray(data) ? data : (data.items || []);
        renderNotificationsPanel(notifs);
        updateNotificationBadge(notifs);
    } catch (e) {
        listEl.innerHTML = '<div class="notif-error"><i class="fas fa-exclamation-circle"></i> Could not load notifications</div>';
    }
}

function renderNotificationsPanel(notifs) {
    const listEl = document.getElementById('notifications-list');
    if (!listEl) return;
    if (!notifs || notifs.length === 0) {
        listEl.innerHTML = '<div class="notif-empty"><i class="fas fa-bell-slash"></i><p>No notifications</p></div>';
        return;
    }

    const typeIcon = (type) => {
        const icons = {
            low_stock: 'fa-exclamation-triangle text-warning',
            calibration_due: 'fa-certificate text-danger',
            maintenance_due: 'fa-wrench text-warning',
            transfer_request: 'fa-exchange-alt text-info',
            transfer_approved: 'fa-check-circle text-success',
            transfer_rejected: 'fa-times-circle text-danger',
            transfer_shipped: 'fa-truck text-info',
            transfer_received: 'fa-inbox text-success',
            return_date_due: 'fa-calendar-alt text-warning',
            system_alert: 'fa-cog text-secondary',
        };
        return icons[type] || 'fa-bell text-primary';
    };

    const timeAgo = (dateStr) => {
        if (!dateStr) return '';
        const diff = Date.now() - new Date(dateStr).getTime();
        const mins = Math.floor(diff / 60000);
        if (mins < 1) return 'Just now';
        if (mins < 60) return mins + 'm ago';
        const hrs = Math.floor(mins / 60);
        if (hrs < 24) return hrs + 'h ago';
        return Math.floor(hrs / 24) + 'd ago';
    };

    const total = notifs.length;
    const unreadCount = notifs.filter(function(n) { return n.status === 'pending' || n.status === 'sent'; }).length;
    const footerCount = document.getElementById('notif-footer-count');
    if (footerCount) footerCount.textContent = total + ' notification' + (total !== 1 ? 's' : '') + (unreadCount > 0 ? ' \u00b7 ' + unreadCount + ' unread' : '');

    listEl.innerHTML = notifs.map(function(n) {
        const isUnread = n.status === 'pending' || n.status === 'sent';
        return '<div class="notif-item' + (isUnread ? ' notif-unread' : '') + '" data-id="' + n.id + '" onclick="markNotificationRead(\'' + n.id + '\', this)">' +
            '<div class="notif-icon"><i class="fas ' + typeIcon(n.notification_type) + '"></i></div>' +
            '<div class="notif-body">' +
                '<div class="notif-subject">' + escapeHtml(n.subject || 'Notification') + '</div>' +
                '<div class="notif-time">' + timeAgo(n.sent_at || n.created_at) + '</div>' +
            '</div>' +
            (isUnread ? '<div class="notif-unread-dot"></div>' : '') +
            '<button class="notif-remove-btn" title="Remove" onclick="event.stopPropagation(); removeNotification(\'' + n.id + '\', this.closest(\'.notif-item\'))">' +
                '<i class="fas fa-times"></i>' +
            '</button>' +
        '</div>';
    }).join('');
}

function updateNotificationBadge(notifs) {
    const unread = (notifs || []).filter(function(n) { return n.status === 'pending' || n.status === 'sent'; }).length;
    const badge = document.getElementById('notification-badge');
    const dot = document.getElementById('notification-dot');
    if (badge) {
        badge.textContent = unread > 9 ? '9+' : unread;
        badge.style.display = unread > 0 ? '' : 'none';
    }
    if (dot) dot.style.display = unread > 0 ? '' : 'none';
}

async function markNotificationRead(notifId, el) {
    try {
        await NotificationsAPI.markRead([notifId]);
        if (el) {
            el.classList.remove('notif-unread');
            const dot = el.querySelector('.notif-unread-dot');
            if (dot) dot.remove();
        }
        const unreadItems = document.querySelectorAll('.notif-unread').length;
        const badge = document.getElementById('notification-badge');
        const dot2 = document.getElementById('notification-dot');
        if (badge) { badge.textContent = unreadItems > 9 ? '9+' : unreadItems; badge.style.display = unreadItems > 0 ? '' : 'none'; }
        if (dot2) dot2.style.display = unreadItems > 0 ? '' : 'none';
    } catch (e) { /* silent */ }
}

async function markAllNotificationsRead() {
    try {
        const ids = Array.from(document.querySelectorAll('.notif-unread')).map(function(el) { return el.dataset.id; }).filter(Boolean);
        if (!ids.length) return;
        await NotificationsAPI.markRead(ids);
        document.querySelectorAll('.notif-unread').forEach(function(el) {
            el.classList.remove('notif-unread');
            var dot = el.querySelector('.notif-unread-dot');
            if (dot) dot.remove();
        });
        const badge = document.getElementById('notification-badge');
        const dot = document.getElementById('notification-dot');
        if (badge) badge.style.display = 'none';
        if (dot) dot.style.display = 'none';
        showToast('All notifications marked as read', 'success');
    } catch (e) {
        showToast('Could not mark notifications as read', 'error');
    }
}

async function removeNotification(notifId, el) {
    if (!notifId || !el) return;
    el.classList.add('notif-removing');
    try {
        await NotificationsAPI.delete(notifId);
        setTimeout(function() {
            el.remove();
            // Update footer count
            const remaining = document.querySelectorAll('.notif-item').length;
            const unread = document.querySelectorAll('.notif-unread').length;
            const footerCount = document.getElementById('notif-footer-count');
            if (footerCount) {
                if (remaining === 0) {
                    const listEl = document.getElementById('notifications-list');
                    if (listEl) listEl.innerHTML = '<div class="notif-empty"><i class="fas fa-bell-slash"></i><p>No notifications</p></div>';
                    footerCount.textContent = '';
                } else {
                    footerCount.textContent = remaining + ' notification' + (remaining !== 1 ? 's' : '') + (unread > 0 ? ' \u00b7 ' + unread + ' unread' : '');
                }
            }
            const badge = document.getElementById('notification-badge');
            const dot = document.getElementById('notification-dot');
            if (badge) { badge.textContent = unread > 9 ? '9+' : unread; badge.style.display = unread > 0 ? '' : 'none'; }
            if (dot) dot.style.display = unread > 0 ? '' : 'none';
        }, 250);
    } catch (e) {
        el.classList.remove('notif-removing');
        showToast('Could not remove notification', 'error');
    }
}

async function clearAllNotifications() {
    const btn = document.getElementById('clear-all-notif-btn');
    const listEl = document.getElementById('notifications-list');
    const items = document.querySelectorAll('.notif-item');
    if (!items.length) { showToast('No notifications to clear', 'info'); return; }

    // Confirm with a brief visual state change
    if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Clearing\u2026'; }
    try {
        await NotificationsAPI.deleteAll();
        if (listEl) listEl.innerHTML = '<div class="notif-empty"><i class="fas fa-bell-slash"></i><p>All cleared</p></div>';
        const footerCount = document.getElementById('notif-footer-count');
        if (footerCount) footerCount.textContent = '';
        const badge = document.getElementById('notification-badge');
        const dot = document.getElementById('notification-dot');
        if (badge) badge.style.display = 'none';
        if (dot) dot.style.display = 'none';
        showToast('All notifications cleared', 'success');
    } catch (e) {
        showToast('Could not clear notifications', 'error');
    } finally {
        if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-trash-alt"></i> Clear all'; }
    }
}

function startNotificationPolling() {
    if (_notifPollInterval) return;
    var poll = async function() {
        try {
            const data = await NotificationsAPI.getAll({ page_size: 50 });
            const notifs = Array.isArray(data) ? data : (data.items || []);
            updateNotificationBadge(notifs);
        } catch (e) { /* silent */ }
    };
    poll();
    _notifPollInterval = setInterval(poll, 120000);
}

// ============================================================
// PREMIUM FEATURE: DARK MODE TOGGLE
// ============================================================

function toggleDarkMode() {
    const isDark = document.documentElement.classList.toggle('dark-mode');
    localStorage.setItem('sims_dark_mode', isDark ? '1' : '0');
    const icon = document.getElementById('dark-mode-icon');
    if (icon) icon.className = isDark ? 'fas fa-sun' : 'fas fa-moon';
    // Re-render charts with new theme colors if dashboard is visible
    if (currentPage === 'dashboard') {
        loadDashboardCharts();
    }
}

function initDarkMode() {
    const saved = localStorage.getItem('sims_dark_mode');
    if (saved === '1') {
        document.documentElement.classList.add('dark-mode');
        const icon = document.getElementById('dark-mode-icon');
        if (icon) icon.className = 'fas fa-sun';
    }
}

// ============================================================
// PREMIUM FEATURE: CHART.JS DASHBOARD CHARTS
// ============================================================

let _stockCategoryChart = null;
let _stockMovementChart = null;

async function loadDashboardCharts() {
    if (typeof Chart === 'undefined') return;
    await Promise.all([
        loadStockCategoryChart().catch(function(e) { console.log('Category chart error:', e.message); }),
        loadStockMovementChart().catch(function(e) { console.log('Movement chart error:', e.message); }),
    ]);
}

async function loadStockCategoryChart() {
    const canvas = document.getElementById('stock-category-chart');
    const emptyEl = document.getElementById('stock-category-chart-empty');
    if (!canvas) return;

    const data = await DashboardAPI.getStockByCategory().catch(function() { return null; });
    const items = Array.isArray(data) ? data : ((data && data.items) || []);

    if (!items.length) {
        canvas.style.display = 'none';
        if (emptyEl) emptyEl.style.display = '';
        return;
    }

    const labels = items.map(function(i) { return i.category_name || 'Uncategorized'; });
    const values = items.map(function(i) { return i.total_quantity != null ? i.total_quantity : (i.count || 0); });
    const palette = ['#6366f1','#f59e0b','#10b981','#ef4444','#3b82f6','#8b5cf6','#ec4899','#14b8a6','#f97316','#84cc16'];

    if (_stockCategoryChart) { _stockCategoryChart.destroy(); _stockCategoryChart = null; }

    const isDark = document.documentElement.classList.contains('dark-mode');
    _stockCategoryChart = new Chart(canvas, {
        type: 'doughnut',
        data: {
            labels: labels,
            datasets: [{
                data: values,
                backgroundColor: palette.slice(0, labels.length),
                borderWidth: 2,
                borderColor: isDark ? '#1e2433' : '#fff',
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'right',
                    labels: {
                        font: { family: 'Inter', size: 12 },
                        color: isDark ? '#c0c8e0' : '#374151',
                        padding: 12,
                    },
                },
                tooltip: {
                    callbacks: {
                        label: function(ctx) { return ' ' + ctx.label + ': ' + ctx.raw.toLocaleString() + ' units'; },
                    },
                },
            },
        },
    });
}

async function loadStockMovementChart() {
    const canvas = document.getElementById('stock-movement-chart');
    const emptyEl = document.getElementById('stock-movement-chart-empty');
    if (!canvas) return;

    const data = await DashboardAPI.getRecentTransactions(100).catch(function() { return []; });
    const activities = Array.isArray(data) ? data : [];

    const days = [];
    const receipts = {};
    const issues = {};
    for (let i = 6; i >= 0; i--) {
        const d = new Date();
        d.setDate(d.getDate() - i);
        const key = d.toISOString().slice(0, 10);
        const label = d.toLocaleDateString('en-IN', { month: 'short', day: 'numeric' });
        days.push({ key: key, label: label });
        receipts[key] = 0;
        issues[key] = 0;
    }

    activities.forEach(function(act) {
        const key = (act.created_at || '').slice(0, 10);
        if (!Object.prototype.hasOwnProperty.call(receipts, key)) return;
        const action = (act.action || '').toLowerCase();
        const qty = Math.abs(act.quantity || 0);
        if (action.includes('receipt') || action.includes('return')) receipts[key] += qty;
        else if (action.includes('issue') || action.includes('scrap')) issues[key] += qty;
    });

    const hasData = days.some(function(d) { return receipts[d.key] > 0 || issues[d.key] > 0; });
    if (!hasData) {
        canvas.style.display = 'none';
        if (emptyEl) emptyEl.style.display = '';
        return;
    }

    if (_stockMovementChart) { _stockMovementChart.destroy(); _stockMovementChart = null; }
    const isDark = document.documentElement.classList.contains('dark-mode');
    const gridColor = isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)';
    const textColor = isDark ? '#c0c8e0' : '#374151';

    _stockMovementChart = new Chart(canvas, {
        type: 'bar',
        data: {
            labels: days.map(function(d) { return d.label; }),
            datasets: [
                {
                    label: 'Receipts',
                    data: days.map(function(d) { return receipts[d.key]; }),
                    backgroundColor: 'rgba(16,185,129,0.75)',
                    borderRadius: 4,
                },
                {
                    label: 'Issues',
                    data: days.map(function(d) { return issues[d.key]; }),
                    backgroundColor: 'rgba(239,68,68,0.75)',
                    borderRadius: 4,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: {
                    grid: { color: gridColor },
                    ticks: { color: textColor, font: { family: 'Inter', size: 11 } },
                },
                y: {
                    beginAtZero: true,
                    grid: { color: gridColor },
                    ticks: { color: textColor, font: { family: 'Inter', size: 11 } },
                },
            },
            plugins: {
                legend: {
                    labels: { color: textColor, font: { family: 'Inter', size: 12 } },
                },
            },
        },
    });
}

// ============================================================
// PREMIUM FEATURE: CSV TABLE EXPORT
// ============================================================

function exportTableToCSV(tableId, filename) {
    const table = document.getElementById(tableId);
    if (!table) { showToast('No data to export', 'info'); return; }

    const rows = [];
    const headers = Array.from(table.querySelectorAll('thead th')).map(function(th) {
        return escapeSpreadsheetCSV(th.textContent.trim());
    });
    if (headers.length) rows.push(headers.join(','));

    table.querySelectorAll('tbody tr').forEach(function(tr) {
        const cells = Array.from(tr.querySelectorAll('td')).map(function(td) {
            const text = ((td.innerText || td.textContent || '').trim().replace(/\s+/g, ' '));
            return escapeSpreadsheetCSV(text);
        });
        if (cells.length) rows.push(cells.join(','));
    });

    if (rows.length <= 1) { showToast('No data rows to export', 'info'); return; }

    const csvContent = '\uFEFF' + rows.join('\n');
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename || 'export.csv';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    showToast('Exported ' + (rows.length - 1) + ' row(s) to ' + filename, 'success');
}

async function exportPurchaseRegisterXLSX() {
    try {
        showToast('Preparing purchase register workbook...', 'info');

        const params = new URLSearchParams();
        const locationId = document.getElementById('stock-location-filter')?.value;
        if (locationId) params.append('location_id', locationId);

        const token = TokenStorage.getAccessToken();
        const query = params.toString();
        const response = await API._fetch(`${API_BASE_URL}/reports/purchase-register/export${query ? '?' + query : ''}`, {
            method: 'GET',
            headers: token ? { Authorization: `Bearer ${token}` } : {},
        }, true);

        if (!response.ok) {
            let message = 'Export failed';
            try {
                const body = await response.json();
                message = body.error?.message || body.detail || message;
            } catch (_) { /* non-JSON error response */ }
            throw new Error(message);
        }

        const blob = await response.blob();
        const disposition = response.headers.get('content-disposition') || '';
        const filenameMatch = disposition.match(/filename="?([^"]+)"?/i);
        const filename = filenameMatch ? filenameMatch[1] : `purchase_register_${new Date().toISOString().slice(0, 10)}.xlsx`;

        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);

        showToast('Purchase register workbook exported', 'success');
    } catch (error) {
        showToast('Export failed: ' + error.message, 'error');
    }
}

// ============================================================
// PREMIUM FEATURE: ENHANCED KEYBOARD SHORTCUTS
// ============================================================

document.addEventListener('keydown', function(e) {
    const tag = document.activeElement && document.activeElement.tagName ? document.activeElement.tagName.toLowerCase() : '';
    if (['input', 'textarea', 'select'].includes(tag)) return;

    if (e.key === 'Escape') {
        if (_notifPanelOpen) { closeNotificationsPanel(); return; }
        closeModal();
        return;
    }

    if (e.altKey && !e.ctrlKey && !e.metaKey) {
        const navMap = {
            d: 'dashboard', i: 'items', s: 'stock', l: 'locations',
            t: 'transfers', c: 'compliance', a: 'assets', p: 'personal',
            u: 'users', j: 'jobs',
        };
        const key = e.key.toLowerCase();
        if (navMap[key]) {
            e.preventDefault();
            navigateTo(navMap[key]);
            return;
        }
        if (key === 'n') {
            e.preventDefault();
            document.getElementById('global-search') && document.getElementById('global-search').focus();
            return;
        }
        if (key === 'b') {
            e.preventDefault();
            toggleNotificationsPanel();
            return;
        }
        if (key === 'm') {
            e.preventDefault();
            toggleDarkMode();
            return;
        }
    }
});

// ============================================================
// PREMIUM INIT — called after login / on app init
// ============================================================

function premiumInit() {
    initDarkMode();
    startNotificationPolling();
}


function updateJobStats() {
    document.getElementById('jobs-total-count').textContent = allJobs.length;
    document.getElementById('jobs-hold-count').textContent = allJobs.filter(j => j.status === 'hold').length;
    document.getElementById('jobs-progress-count').textContent = allJobs.filter(j => j.status === 'in_progress').length;
    document.getElementById('jobs-completed-count').textContent = allJobs.filter(j => j.status === 'completed' || j.status === 'verified').length;
}

function filterJobs() {
    const search = (document.getElementById('jobs-search')?.value || '').toLowerCase();
    const statusFilter = document.getElementById('jobs-status-filter')?.value || '';
    const methodFilter = document.getElementById('jobs-method-filter')?.value || '';

    let filtered = allJobs;

    if (search) {
        filtered = filtered.filter(j =>
            (j.customer || '').toLowerCase().includes(search) ||
            (j.job_name || '').toLowerCase().includes(search) ||
            (j.person_name || '').toLowerCase().includes(search) ||
            (j.job_number || '').toLowerCase().includes(search)
        );
    }
    if (statusFilter) {
        filtered = filtered.filter(j => j.status === statusFilter);
    }
    if (methodFilter) {
        filtered = filtered.filter(j => j.method === methodFilter);
    }

    renderJobsTable(filtered);
}

function renderJobsTable(jobs) {
    const tbody = document.getElementById('jobs-table-body');
    if (!tbody) return;
    const perms = getUserPermissions();

    if (!jobs.length) {
        tbody.innerHTML = '<tr><td colspan="11" class="text-center">No jobs found</td></tr>';
        return;
    }

    tbody.innerHTML = jobs.map(job => {
        const statusBadge = `<span class="badge ${JOB_STATUS_BADGES[job.status] || 'badge-secondary'}">${JOB_STATUS_LABELS[job.status] || job.status}</span>`;
        const methodLabel = JOB_METHOD_LABELS[job.method] || job.method || '-';
        const jobDate = job.job_date ? new Date(job.job_date).toLocaleDateString() : '-';

        let actions = `<button class="btn-icon" title="View" onclick="viewJob('${job.id}')"><i class="fas fa-eye"></i></button>`;

        if (job.status === 'hold' || job.status === 'in_progress') {
            if (perms.canManage) {
                actions += ` <button class="btn-icon" title="Edit" onclick="editJob('${job.id}')"><i class="fas fa-edit"></i></button>`;
            }
            actions += ` <button class="btn-icon text-success" title="Mark Done" onclick="showCompleteJobModal('${job.id}')"><i class="fas fa-check"></i></button>`;
        }
        if (job.status === 'completed' && !job.is_validated && perms.canManage) {
            actions += ` <button class="btn-icon text-primary" title="Validate" onclick="validateJob('${job.id}')"><i class="fas fa-clipboard-check"></i></button>`;
        }
        if (perms.isAdmin) {
            actions += ` <button class="btn-icon text-danger" title="Delete" onclick="deleteJob('${job.id}')"><i class="fas fa-trash"></i></button>`;
        }

        return `<tr>
            <td>${job.job_number || '-'}</td>
            <td>${jobDate}</td>
            <td>${escapeHtml(job.customer || '-')}</td>
            <td>${escapeHtml(job.job_name || '-')}</td>
            <td>${methodLabel}</td>
            <td>${job.quantity ?? '-'}</td>
            <td>${escapeHtml(job.coverage || '-')}</td>
            <td>${job.total ?? '-'}</td>
            <td>${escapeHtml(job.person_name || '-')}</td>
            <td>${statusBadge}</td>
            <td class="actions-cell">${actions}</td>
        </tr>`;
    }).join('');
}

function showCreateJobModal() {
    const locationOptions = activeRecords(locations).map(l => `<option value="${l.id}">${escapeHtml(l.name)}</option>`).join('');

    const html = `
        <form id="create-job-form" onsubmit="submitCreateJob(event)">
            <div class="form-grid">
                <div class="form-group">
                    <label for="job-date">Date *</label>
                    <input type="date" id="job-date" required value="${localDateInputValue()}">
                </div>
                <div class="form-group">
                    <label for="job-customer">Customer *</label>
                    <input type="text" id="job-customer" required placeholder="Customer name">
                </div>
                <div class="form-group">
                    <label for="job-name">Job *</label>
                    <input type="text" id="job-name" required placeholder="Job name/description">
                </div>
                <div class="form-group">
                    <label for="job-method">Method *</label>
                    <select id="job-method" required>
                        <option value="">Select Method</option>
                        <option value="rt">RT</option>
                        <option value="ut">UT</option>
                        <option value="mt">MT</option>
                        <option value="pt">PT</option>
                        <option value="vt">VT</option>
                        <option value="et">ET</option>
                        <option value="other">Other</option>
                    </select>
                </div>
                <div class="form-group">
                    <label for="job-quantity">Quantity *</label>
                    <input type="number" id="job-quantity" required min="1" placeholder="Qty">
                </div>
                <div class="form-group">
                    <label for="job-coverage">Coverage</label>
                    <input type="text" id="job-coverage" placeholder="Coverage details">
                </div>
                <div class="form-group">
                    <label for="job-total">Total *</label>
                    <input type="number" id="job-total" required min="0" placeholder="Total">
                </div>
                <div class="form-group">
                    <label for="job-person">Person Name *</label>
                    <input type="text" id="job-person" required placeholder="Person assigned">
                </div>
                <div class="form-group">
                    <label for="job-location">Location</label>
                    <select id="job-location">
                        <option value="">Select Location</option>
                        ${locationOptions}
                    </select>
                </div>
                <div class="form-group full-width">
                    <label for="job-notes">Notes</label>
                    <textarea id="job-notes" rows="2" placeholder="Optional notes"></textarea>
                </div>
            </div>
            <div class="form-actions">
                <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                <button type="submit" class="btn btn-primary">Create Job</button>
            </div>
        </form>
    `;

    openModal('New Job (Hold)', html);
}

async function submitCreateJob(e) {
    e.preventDefault();

    const data = {
        job_date: document.getElementById('job-date').value,
        customer: document.getElementById('job-customer').value,
        job_name: document.getElementById('job-name').value,
        method: document.getElementById('job-method').value,
        quantity: parseInt(document.getElementById('job-quantity').value),
        coverage: document.getElementById('job-coverage').value || null,
        total: parseInt(document.getElementById('job-total').value),
        person_name: document.getElementById('job-person').value,
        location_id: document.getElementById('job-location').value || null,
        notes: document.getElementById('job-notes').value || null
    };

    try {
        await JobsAPI.create(data);
        closeModal();
        showToast('Job created successfully', 'success');
        await loadJobs();
    } catch (error) {
        showToast(error.message || 'Failed to create job', 'error');
    }
}

async function viewJob(id) {
    try {
        const job = await JobsAPI.getById(id);
        const jobDate = job.job_date ? new Date(job.job_date).toLocaleDateString() : '-';
        const methodLabel = JOB_METHOD_LABELS[job.method] || job.method || '-';
        const statusBadge = `<span class="badge ${JOB_STATUS_BADGES[job.status] || 'badge-secondary'}">${JOB_STATUS_LABELS[job.status] || job.status}</span>`;

        let completionHtml = '';
        if (job.status === 'completed' || job.status === 'verified') {
            completionHtml = `
                <h4 style="margin-top: 16px; margin-bottom: 8px;">Completion Details</h4>
                <div class="detail-grid">
                    <div class="detail-item"><span class="detail-label">Completed By</span><span class="detail-value">${escapeHtml(job.completed_by_name || '-')}</span></div>
                    <div class="detail-item"><span class="detail-label">Completed At</span><span class="detail-value">${job.completed_at ? new Date(job.completed_at).toLocaleString() : '-'}</span></div>
                    <div class="detail-item"><span class="detail-label">Total</span><span class="detail-value">${job.total ?? '-'}</span></div>
                    <div class="detail-item"><span class="detail-label">Accepted</span><span class="detail-value">${job.accepted ?? '-'}</span></div>
                    <div class="detail-item"><span class="detail-label">Reshoot</span><span class="detail-value">${job.reshoot ?? '-'}</span></div>
                    <div class="detail-item"><span class="detail-label">Cut Films</span><span class="detail-value">${escapeHtml(job.cut_films || '-')}</span></div>
                    <div class="detail-item"><span class="detail-label">Validated</span><span class="detail-value">${job.is_validated ? '<span class="badge badge-success">Yes</span>' : '<span class="badge badge-warning">No</span>'}</span></div>
                </div>
            `;
        }

        const html = `
            <div class="detail-grid">
                <div class="detail-item"><span class="detail-label">Job #</span><span class="detail-value">${escapeHtml(job.job_number || '-')}</span></div>
                <div class="detail-item"><span class="detail-label">Date</span><span class="detail-value">${jobDate}</span></div>
                <div class="detail-item"><span class="detail-label">Customer</span><span class="detail-value">${escapeHtml(job.customer || '-')}</span></div>
                <div class="detail-item"><span class="detail-label">Job</span><span class="detail-value">${escapeHtml(job.job_name || '-')}</span></div>
                <div class="detail-item"><span class="detail-label">Method</span><span class="detail-value">${methodLabel}</span></div>
                <div class="detail-item"><span class="detail-label">Quantity</span><span class="detail-value">${job.quantity ?? '-'}</span></div>
                <div class="detail-item"><span class="detail-label">Coverage</span><span class="detail-value">${escapeHtml(job.coverage || '-')}</span></div>
                <div class="detail-item"><span class="detail-label">Total</span><span class="detail-value">${job.total ?? '-'}</span></div>
                <div class="detail-item"><span class="detail-label">Person</span><span class="detail-value">${escapeHtml(job.person_name || '-')}</span></div>
                <div class="detail-item"><span class="detail-label">Location</span><span class="detail-value">${escapeHtml(job.location_name || '-')}</span></div>
                <div class="detail-item"><span class="detail-label">Status</span><span class="detail-value">${statusBadge}</span></div>
                <div class="detail-item"><span class="detail-label">Notes</span><span class="detail-value">${escapeHtml(job.notes || '-')}</span></div>
            </div>
            ${completionHtml}
            <div class="form-actions" style="margin-top: 16px;">
                <button class="btn btn-secondary" onclick="closeModal()">Close</button>
            </div>
        `;

        openModal(`Job Details - ${escapeHtml(job.job_number || '')}`, html);
    } catch (error) {
        showToast('Failed to load job details', 'error');
    }
}

async function editJob(id) {
    try {
        const job = await JobsAPI.getById(id);
        const locationOptions = activeRecords(locations)
            .map(l =>
            `<option value="${l.id}" ${l.id === job.location_id ? 'selected' : ''}>${escapeHtml(l.name)}</option>`
        ).join('');

        const html = `
            <form id="edit-job-form" onsubmit="submitEditJob(event, ${job.id})">
                <div class="form-grid">
                    <div class="form-group">
                        <label for="edit-job-date">Date *</label>
                        <input type="date" id="edit-job-date" required value="${job.job_date || ''}">
                    </div>
                    <div class="form-group">
                        <label for="edit-job-customer">Customer *</label>
                        <input type="text" id="edit-job-customer" required value="${escapeHtml(job.customer || '')}">
                    </div>
                    <div class="form-group">
                        <label for="edit-job-name">Job *</label>
                        <input type="text" id="edit-job-name" required value="${escapeHtml(job.job_name || '')}">
                    </div>
                    <div class="form-group">
                        <label for="edit-job-method">Method *</label>
                        <select id="edit-job-method" required>
                            <option value="">Select Method</option>
                            <option value="rt" ${job.method === 'rt' ? 'selected' : ''}>RT</option>
                            <option value="ut" ${job.method === 'ut' ? 'selected' : ''}>UT</option>
                            <option value="mt" ${job.method === 'mt' ? 'selected' : ''}>MT</option>
                            <option value="pt" ${job.method === 'pt' ? 'selected' : ''}>PT</option>
                            <option value="vt" ${job.method === 'vt' ? 'selected' : ''}>VT</option>
                            <option value="et" ${job.method === 'et' ? 'selected' : ''}>ET</option>
                            <option value="other" ${job.method === 'other' ? 'selected' : ''}>Other</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label for="edit-job-quantity">Quantity *</label>
                        <input type="number" id="edit-job-quantity" required min="1" value="${job.quantity || ''}">
                    </div>
                    <div class="form-group">
                        <label for="edit-job-coverage">Coverage</label>
                        <input type="text" id="edit-job-coverage" value="${escapeHtml(job.coverage || '')}">
                    </div>
                    <div class="form-group">
                        <label for="edit-job-total">Total *</label>
                        <input type="number" id="edit-job-total" required min="0" value="${job.total || ''}">
                    </div>
                    <div class="form-group">
                        <label for="edit-job-person">Person Name *</label>
                        <input type="text" id="edit-job-person" required value="${escapeHtml(job.person_name || '')}">
                    </div>
                    <div class="form-group">
                        <label for="edit-job-location">Location</label>
                        <select id="edit-job-location">
                            <option value="">Select Location</option>
                            ${locationOptions}
                        </select>
                    </div>
                    <div class="form-group full-width">
                        <label for="edit-job-notes">Notes</label>
                        <textarea id="edit-job-notes" rows="2">${escapeHtml(job.notes || '')}</textarea>
                    </div>
                </div>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary">Update Job</button>
                </div>
            </form>
        `;

        openModal(`Edit Job - ${escapeHtml(job.job_number || '')}`, html);
    } catch (error) {
        showToast('Failed to load job for editing', 'error');
    }
}

async function submitEditJob(e, id) {
    e.preventDefault();

    const data = {
        job_date: document.getElementById('edit-job-date').value,
        customer: document.getElementById('edit-job-customer').value,
        job_name: document.getElementById('edit-job-name').value,
        method: document.getElementById('edit-job-method').value,
        quantity: parseInt(document.getElementById('edit-job-quantity').value),
        coverage: document.getElementById('edit-job-coverage').value || null,
        total: parseInt(document.getElementById('edit-job-total').value),
        person_name: document.getElementById('edit-job-person').value,
        location_id: document.getElementById('edit-job-location').value || null,
        notes: document.getElementById('edit-job-notes').value || null
    };

    try {
        await JobsAPI.update(id, data);
        closeModal();
        showToast('Job updated successfully', 'success');
        await loadJobs();
    } catch (error) {
        showToast(error.message || 'Failed to update job', 'error');
    }
}

function showCompleteJobModal(id) {
    const job = allJobs.find(j => j.id === id);
    if (!job) return;

    const html = `
        <form id="complete-job-form" onsubmit="submitCompleteJob(event, ${id})">
            <p style="margin-bottom: 12px;">Mark job <strong>${escapeHtml(job.job_number || '')}</strong> for <strong>${escapeHtml(job.customer || '')}</strong> as done.</p>
            <div class="form-grid">
                <div class="form-group">
                    <label>Total (from job)</label>
                    <input type="number" id="complete-job-total" value="${job.total}" readonly class="input-readonly">
                </div>
                <div class="form-group">
                    <label for="complete-job-accepted">Accepted *</label>
                    <input type="number" id="complete-job-accepted" required min="0" value="0" oninput="updateCompletionSum(${job.total})">
                </div>
                <div class="form-group">
                    <label for="complete-job-reshoot">Reshoot *</label>
                    <input type="number" id="complete-job-reshoot" required min="0" value="0" oninput="updateCompletionSum(${job.total})">
                </div>
                <div class="form-group">
                    <label for="complete-job-cutfilms">Cut Films *</label>
                    <input type="text" id="complete-job-cutfilms" required placeholder="Enter cut films count/details" oninput="updateCompletionSum(${job.total})">
                </div>
            </div>
            <div id="completion-sum-info" style="margin: 12px 0; padding: 8px 12px; border-radius: 6px; background: var(--bg-secondary, #f0f0f0);">
                <span>Sum: <strong id="completion-sum-value">0</strong> / Total: <strong>${job.total}</strong></span>
                <span id="completion-match-icon" style="margin-left: 8px;"></span>
            </div>
            <div class="form-actions">
                <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                <button type="submit" class="btn btn-success" id="complete-job-submit-btn">Mark as Done</button>
            </div>
        </form>
    `;

    openModal('Complete Job', html);
}

function updateCompletionSum(total) {
    const accepted = parseInt(document.getElementById('complete-job-accepted')?.value) || 0;
    const reshoot = parseInt(document.getElementById('complete-job-reshoot')?.value) || 0;
    const cutFilmsVal = document.getElementById('complete-job-cutfilms')?.value || '0';
    const cutFilmsNum = parseInt(cutFilmsVal) || 0;
    const sum = accepted + reshoot + cutFilmsNum;

    const sumEl = document.getElementById('completion-sum-value');
    const iconEl = document.getElementById('completion-match-icon');
    if (sumEl) sumEl.textContent = sum;
    if (iconEl) {
        if (sum === total) {
            iconEl.innerHTML = '<i class="fas fa-check-circle" style="color: var(--success-color, green);"></i> Match';
        } else {
            iconEl.innerHTML = '<i class="fas fa-times-circle" style="color: var(--danger-color, red);"></i> Mismatch';
        }
    }
}

async function submitCompleteJob(e, id) {
    e.preventDefault();

    const accepted = parseInt(document.getElementById('complete-job-accepted').value) || 0;
    const reshoot = parseInt(document.getElementById('complete-job-reshoot').value) || 0;
    const cutFilms = document.getElementById('complete-job-cutfilms').value;

    const job = allJobs.find(j => j.id === id);
    const cutFilmsNum = parseInt(cutFilms) || 0;
    const sum = accepted + reshoot + cutFilmsNum;

    if (job && sum !== job.total) {
        showToast(`Sum (${sum}) does not match Total (${job.total}). Accepted + Reshoot + Cut Films must equal Total.`, 'error');
        return;
    }

    try {
        await JobsAPI.complete(id, { accepted, reshoot, cut_films: cutFilms });
        closeModal();
        showToast('Job marked as done successfully', 'success');
        await loadJobs();
    } catch (error) {
        showToast(error.message || 'Failed to complete job', 'error');
    }
}

async function validateJob(id) {
    if (!confirm('Validate this job? This will verify the completion totals match.')) return;

    try {
        await JobsAPI.validate(id);
        showToast('Job validated successfully', 'success');
        await loadJobs();
    } catch (error) {
        showToast(error.message || 'Job validation failed - totals may not match', 'error');
    }
}

async function deleteJob(id) {
    if (!confirm('Are you sure you want to delete this job?')) return;

    try {
        await JobsAPI.delete(id);
        showToast('Job deleted successfully', 'success');
        await loadJobs();
    } catch (error) {
        showToast(error.message || 'Failed to delete job', 'error');
    }
}
