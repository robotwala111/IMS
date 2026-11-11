/**
 * Scientech-IMS — Reactive State Store
 *
 * Simple observable state management for the application.
 * Provides subscribe/notify pattern for UI reactivity.
 */

class Store {
    constructor(initialState = {}) {
        this._state = { ...initialState };
        this._listeners = new Map();
    }

    /**
     * Get the full state or a specific key.
     * @param {string} [key] - Optional state key
     * @returns {*} State value
     */
    get(key) {
        if (key) return this._state[key];
        return { ...this._state };
    }

    /**
     * Update one or more state keys. Notifies subscribers.
     * @param {string|Object} keyOrObj - Key name or { key: value } object
     * @param {*} [value] - Value (when keyOrObj is a string)
     */
    set(keyOrObj, value) {
        if (typeof keyOrObj === 'string') {
            const oldValue = this._state[keyOrObj];
            this._state[keyOrObj] = value;
            this._notify(keyOrObj, value, oldValue);
        } else {
            Object.entries(keyOrObj).forEach(([k, v]) => {
                const oldValue = this._state[k];
                this._state[k] = v;
                this._notify(k, v, oldValue);
            });
        }
    }

    /**
     * Subscribe to changes on a specific key.
     * @param {string} key - State key to watch
     * @param {Function} callback - (newValue, oldValue) => void
     * @returns {Function} Unsubscribe function
     */
    subscribe(key, callback) {
        if (!this._listeners.has(key)) {
            this._listeners.set(key, new Set());
        }
        this._listeners.get(key).add(callback);

        // Return unsubscribe function
        return () => this._listeners.get(key)?.delete(callback);
    }

    /**
     * Notify subscribers of a state change.
     */
    _notify(key, newValue, oldValue) {
        const listeners = this._listeners.get(key);
        if (listeners) {
            listeners.forEach(cb => {
                try {
                    cb(newValue, oldValue);
                } catch (e) {
                    console.error(`[Store] Listener error for "${key}":`, e);
                }
            });
        }
    }

    /**
     * Reset state to initial values.
     */
    reset(initialState = {}) {
        this._state = { ...initialState };
        this._listeners.clear();
    }
}

// Singleton application store
const appStore = new Store({
    currentPage: 'dashboard',
    user: null,
    isAuthenticated: false,
    categories: [],
    locations: [],
    sidebarCollapsed: false,
});

export { Store };
export default appStore;
