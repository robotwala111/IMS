/**
 * Scientech-IMS API Client
 * Handles all API communication with the backend
 */

const API_BASE_URL = window.__NDT_IMS_API_BASE_URL__ || '/api/v1';
const API_REQUEST_TIMEOUT_MS = 45000;
const API_GET_RETRY_DELAYS_MS = [500, 1500, 3500];
const API_TRANSIENT_STATUSES = new Set([408, 425, 429, 500, 502, 503, 504]);

function delay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

function retryDelay(response, attempt) {
    const retryAfter = response?.headers?.get('retry-after');
    if (retryAfter) {
        const seconds = Number(retryAfter);
        if (Number.isFinite(seconds)) return Math.min(seconds * 1000, 10000);
        const retryAt = Date.parse(retryAfter);
        if (Number.isFinite(retryAt)) {
            return Math.min(Math.max(0, retryAt - Date.now()), 10000);
        }
    }
    const base = API_GET_RETRY_DELAYS_MS[attempt] || 3500;
    return base + Math.floor(Math.random() * 250);
}

function friendlyNetworkError(error) {
    if (error?.name === 'AbortError') {
        return new Error('The server took too long to respond. Please try again.');
    }
    if (typeof navigator !== 'undefined' && navigator.onLine === false) {
        return new Error('You appear to be offline. Check your internet connection and try again.');
    }
    if (error instanceof TypeError || error?.message === 'Failed to fetch') {
        return new Error('Unable to reach the server. Please check your connection and try again.');
    }
    return error;
}

// Token storage
const TokenStorage = {
    getAccessToken: () => localStorage.getItem('access_token'),
    getRefreshToken: () => localStorage.getItem('refresh_token'),
    setTokens: (access, refresh) => {
        localStorage.setItem('access_token', access);
        localStorage.setItem('refresh_token', refresh);
    },
    clearTokens: () => {
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
        localStorage.removeItem('user');
    },
    getUser: () => {
        const user = localStorage.getItem('user');
        return user ? JSON.parse(user) : null;
    },
    setUser: (user) => {
        localStorage.setItem('user', JSON.stringify(user));
    }
};

function formatApiErrorDetail(detail) {
    if (!detail) return '';

    if (typeof detail === 'string') {
        return detail;
    }

    if (Array.isArray(detail)) {
        return detail
            .map(formatApiErrorDetail)
            .filter(Boolean)
            .join('; ');
    }

    if (typeof detail === 'object') {
        const message = detail.msg || detail.message || detail.error;
        if (message) {
            const location = Array.isArray(detail.loc)
                ? detail.loc.filter(part => part !== 'body').join('.')
                : '';
            return location ? `${location}: ${message}` : String(message);
        }

        try {
            return JSON.stringify(detail);
        } catch {
            return String(detail);
        }
    }

    return String(detail);
}

// API Client
const API = {
    // Singleton promise to prevent concurrent token refresh race conditions
    _refreshPromise: null,
    _inflightGets: new Map(),

    async _fetch(url, options = {}, retrySafeRead = false) {
        const attempts = retrySafeRead ? API_GET_RETRY_DELAYS_MS.length + 1 : 1;
        let lastError;

        for (let attempt = 0; attempt < attempts; attempt += 1) {
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), API_REQUEST_TIMEOUT_MS);
            const callerSignal = options.signal;
            const abortFromCaller = () => controller.abort();
            if (callerSignal) callerSignal.addEventListener('abort', abortFromCaller, { once: true });

            try {
                const response = await fetch(url, {
                    cache: 'no-store',
                    ...options,
                    signal: controller.signal
                });
                const transient = API_TRANSIENT_STATUSES.has(response.status);
                if (!transient || attempt === attempts - 1) return response;
                lastError = new Error(`Server temporarily unavailable (${response.status})`);
                lastError.retryDelay = retryDelay(response, attempt);
            } catch (error) {
                if (callerSignal?.aborted) throw error;
                lastError = error;
                if (attempt === attempts - 1) throw friendlyNetworkError(error);
            } finally {
                clearTimeout(timeoutId);
                if (callerSignal) callerSignal.removeEventListener('abort', abortFromCaller);
            }

            await delay(lastError?.retryDelay ?? retryDelay(null, attempt));
        }

        throw friendlyNetworkError(lastError);
    },

    /**
     * Make an API request
     */
    async request(endpoint, options = {}) {
        const url = `${API_BASE_URL}${endpoint}`;
        const token = TokenStorage.getAccessToken();
        
        const headers = {
            'Content-Type': 'application/json',
            ...options.headers
        };
        
        if (token) {
            headers['Authorization'] = `Bearer ${token}`;
        }
        
        try {
            const response = await this._fetch(url, {
                ...options,
                headers
            }, options.method === 'GET');
            
            // Handle 401 — use a singleton refresh to prevent race conditions
            // when multiple parallel requests all hit 401 at the same time
            if (response.status === 401 && TokenStorage.getRefreshToken()) {
                if (!this._refreshPromise) {
                    this._refreshPromise = this._doRefresh().finally(() => {
                        this._refreshPromise = null;
                    });
                }
                const refreshed = await this._refreshPromise;
                if (refreshed) {
                    // Retry with fresh token
                    headers['Authorization'] = `Bearer ${TokenStorage.getAccessToken()}`;
                    const retryResponse = await this._fetch(
                        url,
                        { ...options, headers },
                        options.method === 'GET'
                    );
                    return this.handleResponse(retryResponse);
                } else {
                    // Refresh failed — force logout
                    TokenStorage.clearTokens();
                    if (typeof showLoginPage === 'function') showLoginPage();
                    throw new Error('Session expired. Please log in again.');
                }
            }
            
            return this.handleResponse(response);
        } catch (error) {
            if (!error.message?.includes('Session expired')) {
                console.error('API Error:', error);
            }
            throw friendlyNetworkError(error);
        }
    },
    
    async handleResponse(response) {
        const contentType = response.headers.get('content-type');
        
        if (!response.ok) {
            let errorMessage = 'An error occurred';
            if (contentType && contentType.includes('application/json')) {
                const errorData = await response.json();
                errorMessage = (
                    formatApiErrorDetail(errorData.error?.message) ||
                    formatApiErrorDetail(errorData.detail) ||
                    errorMessage
                );
            }
            const err = new Error(errorMessage);
            err.status = response.status;
            throw err;
        }
        
        if (contentType && contentType.includes('application/json')) {
            return response.json();
        }
        
        return response.text();
    },
    
    async _doRefresh() {
        try {
            const refreshToken = TokenStorage.getRefreshToken();
            if (!refreshToken) return false;
            const response = await this._fetch(`${API_BASE_URL}/auth/refresh`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ refresh_token: refreshToken })
            });
            
            if (response.ok) {
                const data = await response.json();
                TokenStorage.setTokens(data.access_token, data.refresh_token);
                return true;
            }
            return false;
        } catch {
            return false;
        }
    },

    async refreshToken() {
        return this._doRefresh();
    },
    
    // GET request
    get(endpoint) {
        if (!this._inflightGets.has(endpoint)) {
            const request = this.request(endpoint, { method: 'GET' })
                .finally(() => this._inflightGets.delete(endpoint));
            this._inflightGets.set(endpoint, request);
        }
        return this._inflightGets.get(endpoint);
    },
    
    // POST request
    post(endpoint, data) {
        return this.request(endpoint, {
            method: 'POST',
            body: JSON.stringify(data)
        });
    },
    
    // PUT request
    put(endpoint, data) {
        return this.request(endpoint, {
            method: 'PUT',
            body: JSON.stringify(data)
        });
    },
    
    // PATCH request
    patch(endpoint, data) {
        return this.request(endpoint, {
            method: 'PATCH',
            body: JSON.stringify(data)
        });
    },
    
    // DELETE request
    delete(endpoint) {
        return this.request(endpoint, { method: 'DELETE' });
    }
};

// Auth API
const AuthAPI = {
    async login(email, password) {
        const response = await API._fetch(`${API_BASE_URL}/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password })
        });
        
        if (!response.ok) {
            let msg = 'Login failed';
            let detail = null;
            try {
                const body = await response.json();
                // API returns { error: { code, message, details } }
                if (body.error) {
                    msg = body.error.message || msg;
                    detail = body.error;
                } else if (Array.isArray(body.detail)) {
                    msg = body.detail.map(d => d.msg || d).join('; ');
                } else if (typeof body.detail === 'string') {
                    msg = body.detail;
                }
            } catch (_) { /* response not JSON */ }
            const err = new Error(msg);
            err.detail = detail;
            err.status = response.status;
            throw err;
        }
        
        const data = await response.json();
        TokenStorage.setTokens(data.access_token, data.refresh_token);
        TokenStorage.setUser(data.user);
        
        return data.user;
    },
    
    async logout() {
        try {
            if (TokenStorage.getAccessToken()) {
                await API.post('/auth/logout', {});
            }
        } finally {
            TokenStorage.clearTokens();
        }
    },

    resetPassword(token, newPassword, confirmPassword) {
        return API.post('/auth/reset-password', {
            token,
            new_password: newPassword,
            confirm_password: confirmPassword,
        });
    },
    
    isAuthenticated() {
        return !!TokenStorage.getAccessToken();
    },
    
    getUser() {
        return TokenStorage.getUser();
    }
};

// Items API
const ItemsAPI = {
    getAll(params = {}) {
        const requestParams = { is_active: true, ...params };
        const filteredParams = Object.fromEntries(
            Object.entries(requestParams).filter(([, value]) => value !== undefined && value !== null && value !== '')
        );
        const query = new URLSearchParams(filteredParams).toString();
        return API.get(`/items${query ? '?' + query : ''}`);
    },

    async getAllPages(params = {}) {
        const pageSize = 100;
        const firstPage = await this.getAll({ ...params, page: 1, page_size: pageSize });
        if (Array.isArray(firstPage)) return firstPage;

        const allItems = [...(firstPage.items || [])];
        const totalPages = Math.max(1, Number(firstPage.pages) || 1);
        for (let page = 2; page <= totalPages; page++) {
            const response = await this.getAll({ ...params, page, page_size: pageSize });
            allItems.push(...(Array.isArray(response) ? response : (response.items || [])));
        }
        return allItems;
    },
    
    getById(id) {
        return API.get(`/items/${id}`);
    },

    getDuplicateSuggestions({ name, manufacturer, model, excludeItemId } = {}) {
        const query = new URLSearchParams({
            name: name || '',
            ...(manufacturer ? { manufacturer } : {}),
            ...(model ? { model } : {}),
            ...(excludeItemId ? { exclude_item_id: excludeItemId } : {})
        }).toString();
        return API.get(`/items/duplicate-suggestions?${query}`);
    },
    
    create(data) {
        return API.post('/items', data);
    },
    
    update(id, data) {
        return API.patch(`/items/${id}`, data);
    },
    
    delete(id) {
        return API.delete(`/items/${id}`);
    },

    permanentDelete(id) {
        return API.delete(`/items/${id}/permanent`);
    }
};

// Stock API
const StockAPI = {
    getAll(params = {}) {
        const query = new URLSearchParams(params).toString();
        return API.get(`/stock${query ? '?' + query : ''}`);
    },

    getAvailable(itemId, locationId) {
        return API.get(`/stock/available?item_id=${encodeURIComponent(itemId)}&location_id=${encodeURIComponent(locationId)}`);
    },

    getTransferOptions(locationId) {
        return API.get(`/stock/transfer-options?location_id=${encodeURIComponent(locationId)}`);
    },
    
    getByLocation(locationId) {
        return API.get(`/stock/by-location/${locationId}`);
    },

    updateThresholds(stockId, data) {
        return API.patch(`/stock/${stockId}/thresholds`, data);
    },

    correctLocation(stockId, data) {
        return API.patch(`/stock/${stockId}/location`, data);
    },
    
    adjust(data) {
        return API.post('/stock/adjustments', data);
    },
    
    issue(data) {
        return API.post('/stock/issue', data);
    },

    documentedIssue(data) {
        return API.post('/stock/documented-issue', data);
    },
    
    sendLowStockAlert() {
        return API.post('/stock/send-low-stock-alert', {});
    },
    
    getLowStock() {
        return API.get('/stock?low_stock_only=true');
    },

    delete(id) {
        return API.delete(`/stock/${id}`);
    },

    permanentDelete(id, force = false) {
        return API.delete(`/stock/${id}/permanent${force ? '?force=true' : ''}`);
    }
};

// Transactions API
const TransactionsAPI = {
    getAll(params = {}) {
        const query = new URLSearchParams(params).toString();
        return API.get(`/transactions${query ? '?' + query : ''}`);
    },

    getById(id) {
        return API.get(`/transactions/${id}`);
    },

    receipt(data) {
        return API.post('/transactions/receipt', data);
    },

    issue(data) {
        return API.post('/transactions/issue', data);
    },

    returnStock(data) {
        return API.post('/transactions/return', data);
    }
};

// Locations API
const LocationsAPI = {
    getAll(params = {}) {
        const query = new URLSearchParams(params).toString();
        return API.get(`/locations${query ? '?' + query : ''}`);
    },
    
    getById(id) {
        return API.get(`/locations/${id}`);
    },

    getTransferDestinations() {
        return API.get('/locations/transfer-destinations');
    },

    getTransferSources() {
        return API.get('/locations/transfer-sources');
    },
    
    create(data) {
        return API.post('/locations', data);
    },
    
    update(id, data) {
        return API.patch(`/locations/${id}`, data);
    },
    
    delete(id) {
        return API.delete(`/locations/${id}`);
    },

    permanentDelete(id) {
        return API.delete(`/locations/${id}/permanent`);
    }
};

// Categories API
const CategoriesAPI = {
    getAll(params = {}) {
        const query = new URLSearchParams(params).toString();
        return API.get(`/categories${query ? '?' + query : ''}`);
    },
    
    getSummary() {
        return API.get('/categories/summary');
    },
    
    getById(id) {
        return API.get(`/categories/${id}`);
    },
    
    create(data) {
        return API.post('/categories', data);
    },
    
    update(id, data) {
        return API.patch(`/categories/${id}`, data);
    },
    
    delete(id) {
        return API.delete(`/categories/${id}`);
    },

    permanentDelete(id, force = false) {
        return API.delete(`/categories/${id}/permanent${force ? '?force=true' : ''}`);
    }
};

const CategoryTypesAPI = {
    getAll(params = {}) {
        const query = new URLSearchParams(params).toString();
        return API.get(`/categories/types${query ? '?' + query : ''}`);
    },

    create(data) {
        return API.post('/categories/types', data);
    },

    update(id, data) {
        return API.patch(`/categories/types/${id}`, data);
    }
};

// Transfers API
const TransfersAPI = {
    getAll(params = {}) {
        const query = new URLSearchParams(params).toString();
        return API.get(`/transfers${query ? '?' + query : ''}`);
    },

    getMyRequests(params = {}) {
        const q = new URLSearchParams({ ...params, requested_by_me: true, page_size: 500 }).toString();
        return API.get(`/transfers?${q}`);
    },

    getForMyAction(params = {}) {
        const q = new URLSearchParams({ ...params, assigned_to_me: true, page_size: 500 }).toString();
        return API.get(`/transfers?${q}`);
    },

    getEquipmentOverview(params = {}) {
        const query = new URLSearchParams(params).toString();
        return API.get(`/transfers/equipment-overview${query ? '?' + query : ''}`);
    },
    
    getById(id) {
        return API.get(`/transfers/${id}`);
    },
    
    create(data) {
        return API.post('/transfers', data);
    },
    
    approve(id, data = {}) {
        return API.patch(`/transfers/${id}/approve`, { approved: true, ...data });
    },

    reject(id, data = {}) {
        return API.patch(`/transfers/${id}/approve`, { approved: false, ...data });
    },
    
    ship(id, data = {}) {
        return API.patch(`/transfers/${id}/ship`, data);
    },
    
    receive(id, data) {
        return API.patch(`/transfers/${id}/receive`, data);
    },
    
    cancel(id) {
        return API.patch(`/transfers/${id}/cancel`, {});
    },

    permanentDelete(id) {
        return API.delete(`/transfers/${id}/permanent`);
    },

    updateReturnDate(id, data) {
        return API.patch(`/transfers/${id}/return-date`, data);
    },

    getDeliveryChallan(id) {
        return API.get(`/transfers/${id}/dc`);
    },

    async exportCSV(params = {}) {
        const query = new URLSearchParams(params).toString();
        const url = `${API_BASE_URL}/transfers/export${query ? '?' + query : ''}`;
        const token = TokenStorage.getAccessToken();
        const resp = await API._fetch(url, {
            headers: { 'Authorization': `Bearer ${token}` }
        }, true);
        if (!resp.ok) throw new Error('Export failed');
        return resp.blob();
    }
};

// Purchase Indents API
const PurchaseIndentsAPI = {
    getAll(params = {}) {
        const query = new URLSearchParams(params).toString();
        return API.get(`/purchase-indents${query ? '?' + query : ''}`);
    },

    getById(id) {
        return API.get(`/purchase-indents/${id}`);
    },

    create(data) {
        return API.post('/purchase-indents', data);
    },

    approve(id, data) {
        return API.patch(`/purchase-indents/${id}/approve`, data);
    },

    cancel(id) {
        return API.patch(`/purchase-indents/${id}/cancel`, {});
    },

    getDocument(id) {
        return API.get(`/purchase-indents/${id}/document`);
    }
};

// Assets API
const AssetsAPI = {
    getAll(params = {}) {
        const query = new URLSearchParams(params).toString();
        return API.get(`/assets${query ? '?' + query : ''}`);
    },

    async getAllPages(params = {}) {
        const pageSize = 100;
        const assetsById = new Map();
        let page = 1;
        let totalPages = 1;
        let expectedTotal = 0;

        do {
            const response = await this.getAll({ ...params, page, page_size: pageSize });
            const pageItems = Array.isArray(response) ? response : (response.items || []);
            pageItems.forEach(asset => assetsById.set(asset.id, asset));

            if (Array.isArray(response)) break;
            expectedTotal = Math.max(expectedTotal, Number(response.total) || 0);
            totalPages = Math.max(totalPages, Number(response.pages) || 1);
            page += 1;
        } while (page <= totalPages);

        if (assetsById.size < expectedTotal) {
            throw new Error(`Could not load all products (${assetsById.size} of ${expectedTotal}). Please refresh.`);
        }

        return [...assetsById.values()];
    },
    
    getById(id) {
        return API.get(`/assets/${id}`);
    },
    
    getBySerial(serialNumber) {
        return API.get(`/assets/serial/${serialNumber}`);
    },
    
    create(data) {
        return API.post('/assets', data);
    },

    createProduct(data) {
        return API.post('/assets/products', data);
    },
    
    update(id, data) {
        return API.patch(`/assets/${id}`, data);
    },
    
    updateStatus(id, status) {
        return API.patch(`/assets/${id}/status`, { status });
    },
    
    addCalibration(id, data) {
        return API.post(`/calibration/assets/${id}/records`, data);
    },

    delete(id) {
        return API.delete(`/assets/${id}`);
    },

    permanentDelete(id) {
        return API.delete(`/assets/${id}/permanent`);
    }
};

// Calibration API
const CalibrationAPI = {
    getRecords(params = {}) {
        const query = new URLSearchParams(params).toString();
        return API.get(`/calibration/records${query ? '?' + query : ''}`);
    },

    getAssetHistory(assetId) {
        return API.get(`/calibration/assets/${assetId}/records`);
    },

    create(assetId, data) {
        return API.post(`/calibration/assets/${assetId}/records`, data);
    },

    getById(id) {
        return API.get(`/calibration/records/${id}`);
    },

    getSupplierTransactions(params = {}) {
        const query = new URLSearchParams(params).toString();
        return API.get(`/calibration/supplier-transactions${query ? '?' + query : ''}`);
    },

    createSupplierTransaction(data) {
        return API.post('/calibration/supplier-transactions', data);
    },
};

const BrandingAPI = {
    get() {
        return API.get('/branding');
    },

    update(data) {
        return API.put('/branding', data);
    }
};

// Maintenance API
const MaintenanceAPI = {
    getRecords(params = {}) {
        const query = new URLSearchParams(params).toString();
        return API.get(`/maintenance/records${query ? '?' + query : ''}`);
    },

    getAssetHistory(assetId) {
        return API.get(`/maintenance/assets/${assetId}/records`);
    },

    create(assetId, data) {
        return API.post(`/maintenance/assets/${assetId}/records`, data);
    },

    update(recordId, data) {
        return API.patch(`/maintenance/records/${recordId}`, data);
    },

    getById(id) {
        return API.get(`/maintenance/records/${id}`);
    },
};

// Users API
const UsersAPI = {
    getAll(params = {}) {
        const query = new URLSearchParams(params).toString();
        return API.get(`/users${query ? '?' + query : ''}`);
    },
    
    getByLocation(locationId) {
        return API.get(`/users/by-location?location_id=${encodeURIComponent(locationId)}`);
    },
    
    getById(id) {
        return API.get(`/users/${id}`);
    },
    
    create(data) {
        return API.post('/users', data);
    },
    
    update(id, data) {
        return API.patch(`/users/${id}`, data);
    },
    
    delete(id) {
        return API.delete(`/users/${id}`);
    },

    permanentDelete(id, force = false) {
        return API.delete(`/users/${id}/permanent${force ? '?force=true' : ''}`);
    }
};

// Employee Records API
const EmployeeRecordsAPI = {
    getAll(params = {}) {
        const query = new URLSearchParams(params).toString();
        return API.get(`/employee-records${query ? '?' + query : ''}`);
    },

    getById(id) {
        return API.get(`/employee-records/${id}`);
    },

    create(data) {
        return API.post('/employee-records', data);
    },

    update(id, data) {
        return API.patch(`/employee-records/${id}`, data);
    },

    delete(id) {
        return API.delete(`/employee-records/${id}`);
    }
};

// Employees API (non-login staff)
const EmployeesAPI = {
    getAll(params = {}) {
        const query = new URLSearchParams(params).toString();
        return API.get(`/employees${query ? '?' + query : ''}`);
    },

    getById(id) {
        return API.get(`/employees/${id}`);
    },

    create(data) {
        return API.post('/employees', data);
    },

    update(id, data) {
        return API.patch(`/employees/${id}`, data);
    },

    delete(id) {
        return API.delete(`/employees/${id}`);
    }
};

// Audit / Logs API
const AuditAPI = {
    getAll(params = {}) {
        const query = new URLSearchParams(params).toString();
        return API.get(`/audit${query ? '?' + query : ''}`);
    }
};

// Dashboard API
const DashboardAPI = {
    getStats() {
        return API.get('/dashboard/summary');
    },
    
    getLocationStockSummary(locationId = null) {
        const query = locationId ? `?location_id=${locationId}` : '';
        return API.get(`/dashboard/location-stock-summary${query}`);
    },
    
    getStockByLocation() {
        return API.get('/dashboard/stock-by-location');
    },
    
    getStockByCategory() {
        return API.get('/dashboard/stock-by-category');
    },
    
    getLowStockItems(limit = 10) {
        return API.get(`/dashboard/low-stock-items?limit=${limit}`);
    },
    
    getRecentTransactions(limit = 10) {
        return API.get(`/dashboard/recent-activity?limit=${limit}`);
    },

    getCalibrationAlerts(days = 365) {
        return API.get(`/dashboard/calibration-alerts?days=${days}`);
    }
};

// Jobs API
const JobsAPI = {
    getAll(params = {}) {
        const query = new URLSearchParams();
        if (params.status) query.append('status', params.status);
        if (params.method) query.append('method', params.method);
        if (params.search) query.append('search', params.search);
        if (params.page) query.append('page', params.page);
        if (params.page_size) query.append('page_size', params.page_size);
        if (params.limit) query.append('page_size', params.limit);
        const qs = query.toString();
        return API.get(`/jobs${qs ? '?' + qs : ''}`);
    },

    getById(id) {
        return API.get(`/jobs/${id}`);
    },

    create(data) {
        return API.post('/jobs', data);
    },

    update(id, data) {
        return API.patch(`/jobs/${id}`, data);
    },

    complete(id, data) {
        return API.patch(`/jobs/${id}/complete`, data);
    },

    validate(id) {
        return API.patch(`/jobs/${id}/validate`);
    },

    canIssue(personName) {
        return API.get(`/jobs/can-issue?person_name=${encodeURIComponent(personName)}`);
    },

    delete(id) {
        return API.delete(`/jobs/${id}`);
    }
};

// Notifications API
const NotificationsAPI = {
    getAll(params = {}) {
        const query = new URLSearchParams();
        if (params.is_read !== undefined) query.append('unread_only', !params.is_read);
        if (params.is_read !== undefined) query.append('is_read', params.is_read);
        if (params.page_size) query.append('page_size', params.page_size);
        if (params.page) query.append('page', params.page);
        const qs = query.toString();
        return API.get(`/notifications${qs ? '?' + qs : ''}`);
    },

    getUnreadCount() {
        return API.get('/notifications/unread-count');
    },

    getById(id) {
        return API.get(`/notifications/${id}`);
    },

    markRead(ids) {
        // ids: array of notification IDs
        return API.post('/notifications/mark-read', { notification_ids: ids });
    },

    markAllRead() {
        return API.patch('/notifications/mark-all-read', {});
    },

    delete(id) {
        return API.delete(`/notifications/${id}`);
    },

    deleteAll() {
        return API.delete('/notifications');
    }
};
