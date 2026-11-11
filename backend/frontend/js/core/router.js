/**
 * Scientech-IMS — Application Router
 *
 * Hash-based SPA router with route guards and lazy page loading.
 * Provides clean navigation without full page reloads.
 */

const Router = {
    routes: {},
    currentRoute: null,
    beforeEachGuard: null,

    /**
     * Register a route with its handler.
     * @param {string} path - Route path (e.g., 'dashboard', 'items')
     * @param {Function} handler - Async function that renders the page
     */
    register(path, handler) {
        this.routes[path] = handler;
    },

    /**
     * Set a global navigation guard (e.g., auth check).
     * @param {Function} guard - (to, from) => boolean
     */
    beforeEach(guard) {
        this.beforeEachGuard = guard;
    },

    /**
     * Navigate to a route.
     * @param {string} path - Route path
     * @param {Object} params - Optional parameters
     */
    async navigate(path, params = {}) {
        const from = this.currentRoute;
        const to = path;

        // Run guard
        if (this.beforeEachGuard) {
            const allowed = this.beforeEachGuard(to, from);
            if (!allowed) return;
        }

        // Find handler
        const handler = this.routes[path];
        if (!handler) {
            console.warn(`[Router] No handler for route: ${path}`);
            return;
        }

        this.currentRoute = path;
        window.location.hash = `#/${path}`;

        try {
            await handler(params);
        } catch (error) {
            console.error(`[Router] Error rendering route "${path}":`, error);
        }

        // Dispatch custom event
        window.dispatchEvent(new CustomEvent('route-changed', {
            detail: { path, params, from }
        }));
    },

    /**
     * Initialize the router — listen for hash changes.
     */
    init() {
        window.addEventListener('hashchange', () => {
            const path = window.location.hash.replace('#/', '') || 'dashboard';
            if (path !== this.currentRoute) {
                this.navigate(path);
            }
        });

        // Handle initial route
        const initialPath = window.location.hash.replace('#/', '') || 'dashboard';
        this.navigate(initialPath);
    },
};

export default Router;
