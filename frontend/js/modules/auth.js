/**
 * Scientech-IMS — Auth Module
 *
 * Handles login, logout, and session management.
 */

import appStore from '../core/store.js';
import eventBus from '../core/events.js';
import { showToast } from '../core/ui.js';

const AUTH_KEYS = {
    ACCESS_TOKEN: 'access_token',
    REFRESH_TOKEN: 'refresh_token',
    USER: 'user',
};

const Auth = {
    /**
     * Attempt login with email/password.
     * @returns {Object} user data on success
     */
    async login(email, password) {
        const response = await fetch('/api/v1/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password }),
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.error?.message || 'Login failed');
        }

        const data = await response.json();
        localStorage.setItem(AUTH_KEYS.ACCESS_TOKEN, data.access_token);
        localStorage.setItem(AUTH_KEYS.REFRESH_TOKEN, data.refresh_token);
        localStorage.setItem(AUTH_KEYS.USER, JSON.stringify(data.user));

        appStore.set({
            user: data.user,
            isAuthenticated: true,
        });

        eventBus.emit('auth:login', data.user);
        return data.user;
    },

    /**
     * Logout — clear tokens and state.
     */
    logout() {
        localStorage.removeItem(AUTH_KEYS.ACCESS_TOKEN);
        localStorage.removeItem(AUTH_KEYS.REFRESH_TOKEN);
        localStorage.removeItem(AUTH_KEYS.USER);

        appStore.set({
            user: null,
            isAuthenticated: false,
        });

        eventBus.emit('auth:logout');
    },

    /**
     * Refresh the access token using the refresh token.
     * @returns {boolean} true if refresh succeeded
     */
    async refreshToken() {
        const refreshToken = localStorage.getItem(AUTH_KEYS.REFRESH_TOKEN);
        if (!refreshToken) return false;

        try {
            const response = await fetch('/api/v1/auth/refresh', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ refresh_token: refreshToken }),
            });

            if (!response.ok) {
                this.logout();
                return false;
            }

            const data = await response.json();
            localStorage.setItem(AUTH_KEYS.ACCESS_TOKEN, data.access_token);
            localStorage.setItem(AUTH_KEYS.REFRESH_TOKEN, data.refresh_token);
            return true;
        } catch {
            this.logout();
            return false;
        }
    },

    /**
     * Check if user is currently authenticated.
     */
    isAuthenticated() {
        return !!localStorage.getItem(AUTH_KEYS.ACCESS_TOKEN);
    },

    /**
     * Get the current user from localStorage.
     */
    getUser() {
        const raw = localStorage.getItem(AUTH_KEYS.USER);
        return raw ? JSON.parse(raw) : null;
    },

    /**
     * Get access token.
     */
    getToken() {
        return localStorage.getItem(AUTH_KEYS.ACCESS_TOKEN);
    },

    /**
     * Check if current user has a specific role.
     */
    hasRole(...roles) {
        const user = this.getUser();
        return user && roles.includes(user.role);
    },

    /**
     * Restore session from localStorage on app start.
     */
    restoreSession() {
        if (this.isAuthenticated()) {
            const user = this.getUser();
            appStore.set({
                user,
                isAuthenticated: true,
            });
            return true;
        }
        return false;
    },
};

export default Auth;
