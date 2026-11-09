/**
 * Scientech-IMS — HTTP Client Module
 *
 * Centralized API client with automatic token handling,
 * retry on 401, and consistent error responses.
 */

import Auth from '../modules/auth.js';

const API_BASE = window.__NDT_IMS_API_BASE_URL__ || '/api/v1';

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

const HttpClient = {
    /**
     * Make an authenticated API request.
     * @param {string} endpoint - API path (e.g., '/items')
     * @param {Object} options - Fetch options
     * @returns {Promise<*>} Parsed response
     */
    async request(endpoint, options = {}) {
        const url = `${API_BASE}${endpoint}`;
        const token = Auth.getToken();

        const headers = {
            'Content-Type': 'application/json',
            ...options.headers,
        };

        if (token) {
            headers['Authorization'] = `Bearer ${token}`;
        }

        try {
            let response = await fetch(url, { ...options, headers });

            // If 401, try refreshing the token once
            if (response.status === 401 && Auth.isAuthenticated()) {
                const refreshed = await Auth.refreshToken();
                if (refreshed) {
                    headers['Authorization'] = `Bearer ${Auth.getToken()}`;
                    response = await fetch(url, { ...options, headers });
                } else {
                    // Refresh failed — force logout
                    Auth.logout();
                    window.location.hash = '#/login';
                    throw new Error('Session expired. Please log in again.');
                }
            }

            return await this._handleResponse(response);
        } catch (error) {
            if (error instanceof ApiError) throw error;
            console.error('[HttpClient] Request failed:', error);
            throw error;
        }
    },

    async _handleResponse(response) {
        const contentType = response.headers.get('content-type') || '';

        if (!response.ok) {
            let message = `Request failed (${response.status})`;
            let errorCode = 'UNKNOWN';
            let details = null;

            if (contentType.includes('application/json')) {
                const data = await response.json();
                message = (
                    formatApiErrorDetail(data.error?.message) ||
                    formatApiErrorDetail(data.detail) ||
                    message
                );
                errorCode = data.error?.code || errorCode;
                details = data.error?.details || null;
            }

            throw new ApiError(message, response.status, errorCode, details);
        }

        if (contentType.includes('application/json')) {
            return response.json();
        }

        return response.text();
    },

    // Convenience methods

    get(endpoint) {
        return this.request(endpoint, { method: 'GET' });
    },

    post(endpoint, data) {
        return this.request(endpoint, {
            method: 'POST',
            body: JSON.stringify(data),
        });
    },

    put(endpoint, data) {
        return this.request(endpoint, {
            method: 'PUT',
            body: JSON.stringify(data),
        });
    },

    patch(endpoint, data) {
        return this.request(endpoint, {
            method: 'PATCH',
            body: JSON.stringify(data),
        });
    },

    delete(endpoint) {
        return this.request(endpoint, { method: 'DELETE' });
    },
};

/**
 * Custom API error class with status and code.
 */
class ApiError extends Error {
    constructor(message, status, code, details) {
        super(message);
        this.name = 'ApiError';
        this.status = status;
        this.code = code;
        this.details = details;
    }
}

export { ApiError };
export default HttpClient;
