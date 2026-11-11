/**
 * Scientech-IMS — Application Bootstrap
 *
 * Entry point for the modular ES module application.
 * Initializes auth, router, event listeners, and page modules.
 *
 * Architecture:
 *   index.html (shell)
 *     └── main.js (this file — bootstrap)
 *           ├── core/store.js     — Reactive state
 *           ├── core/router.js    — Hash router
 *           ├── core/events.js    — Event bus
 *           ├── core/http.js      — API client
 *           ├── core/ui.js        — UI utilities
 *           ├── modules/auth.js   — Authentication
 *           └── services/index.js — Domain API services
 */

import Router from './core/router.js';
import appStore from './core/store.js';
import eventBus from './core/events.js';
import Auth from './modules/auth.js';
import { showToast } from './core/ui.js';

// =========================================================================
// Application Initialization
// =========================================================================

document.addEventListener('DOMContentLoaded', () => {
    console.log('[Scientech-IMS] Initializing application...');

    // Restore session from localStorage
    const hasSession = Auth.restoreSession();

    if (hasSession) {
        showApp();
        initRouter();
    } else {
        showLoginPage();
    }

    // Bind global event listeners
    bindLoginForm();
    bindSidebarNavigation();
    bindLogout();

    // Listen for auth events
    eventBus.on('auth:logout', () => {
        showLoginPage();
        showToast('You have been logged out', 'info');
    });

    console.log('[Scientech-IMS] Application ready');
});

// =========================================================================
// Page Visibility
// =========================================================================

function showLoginPage() {
    const loginPage = document.getElementById('login-page');
    const appShell = document.getElementById('app');

    if (loginPage) loginPage.classList.remove('hidden');
    if (appShell) appShell.classList.add('hidden');
}

function showApp() {
    const loginPage = document.getElementById('login-page');
    const appShell = document.getElementById('app');

    if (loginPage) loginPage.classList.add('hidden');
    if (appShell) appShell.classList.remove('hidden');

    // Update UI with user info
    const user = Auth.getUser();
    if (user) {
        const nameEl = document.getElementById('user-name');
        const roleEl = document.getElementById('user-role');
        if (nameEl) nameEl.textContent = user.name || user.email;
        if (roleEl) roleEl.textContent = formatRole(user.role);

        // Show/hide admin-only nav items
        updateNavVisibility(user.role);
    }
}

function formatRole(role) {
    const map = {
        admin: 'Administrator',
        head_office_manager: 'General Manager',
        location_manager: 'Location Manager',
    };
    return map[role] || role;
}

function updateNavVisibility(role) {
    const adminOnlyItems = document.querySelectorAll('[data-role="admin"]');
    const managerItems = document.querySelectorAll('[data-role="manager"]');

    const isAdmin = role === 'admin';
    const isManager = ['admin', 'head_office_manager', 'location_manager'].includes(role);

    adminOnlyItems.forEach(el => el.style.display = isAdmin ? '' : 'none');
    managerItems.forEach(el => el.style.display = isManager ? '' : 'none');
}

// =========================================================================
// Login Form
// =========================================================================

function bindLoginForm() {
    const form = document.getElementById('login-form');
    if (!form) return;

    form.addEventListener('submit', async (e) => {
        e.preventDefault();

        const email = form.querySelector('#login-email')?.value?.trim();
        const password = form.querySelector('#login-password')?.value;
        const submitBtn = form.querySelector('button[type="submit"]');
        const errorEl = document.getElementById('login-error');

        if (!email || !password) {
            if (errorEl) {
                errorEl.textContent = 'Please enter email and password';
                errorEl.classList.remove('hidden');
            }
            return;
        }

        // Disable button
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Signing in...';
        }

        try {
            await Auth.login(email, password);
            if (errorEl) errorEl.classList.add('hidden');
            form.reset();
            showApp();
            initRouter();
            showToast('Welcome back!', 'success');
        } catch (error) {
            if (errorEl) {
                errorEl.textContent = error.message;
                errorEl.classList.remove('hidden');
            }
        } finally {
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.innerHTML = '<i class="fas fa-sign-in-alt"></i> Sign In';
            }
        }
    });
}

// =========================================================================
// Sidebar Navigation
// =========================================================================

function bindSidebarNavigation() {
    const navItems = document.querySelectorAll('.nav-item[data-page]');

    navItems.forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            const page = item.getAttribute('data-page');
            if (page) {
                Router.navigate(page);
                setActiveNavItem(page);
            }
        });
    });

    // Sidebar collapse toggle
    const collapseBtn = document.getElementById('sidebar-toggle');
    if (collapseBtn) {
        collapseBtn.addEventListener('click', () => {
            const sidebar = document.querySelector('.sidebar');
            const isCollapsed = sidebar?.classList.toggle('collapsed');
            appStore.set('sidebarCollapsed', isCollapsed);
        });
    }
}

function setActiveNavItem(page) {
    document.querySelectorAll('.nav-item').forEach(item => {
        item.classList.toggle('active', item.getAttribute('data-page') === page);
    });

    // Update page title
    const titleEl = document.getElementById('page-title');
    if (titleEl) {
        const titles = {
            dashboard: 'Dashboard',
            items: 'Products & Items',
            stock: 'Stock Levels',
            locations: 'Locations',
            categories: 'Categories',
            transfers: 'Transfers',
            compliance: 'Equipment Compliance',
            logs: 'Audit Logs',
            assets: 'Assets',
            users: 'User Management',
            personnel: 'Personnel Records',
            jobs: 'Jobs',
        };
        titleEl.textContent = titles[page] || page;
    }
}

// =========================================================================
// Logout
// =========================================================================

function bindLogout() {
    const logoutBtn = document.getElementById('logout-btn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', (e) => {
            e.preventDefault();
            Auth.logout();
        });
    }
}

// =========================================================================
// Router Setup
// =========================================================================

function initRouter() {
    // Show/hide page sections based on route
    const showSection = (sectionId) => {
        document.querySelectorAll('.page-section').forEach(section => {
            section.classList.add('hidden');
        });
        const target = document.getElementById(sectionId);
        if (target) {
            target.classList.remove('hidden');
        }
    };

    // Register routes — each route shows its section and calls the
    // corresponding load function from the legacy app.js
    const routeMap = {
        dashboard:  'dashboard-section',
        items:      'products-section',
        stock:      'stock-section',
        locations:  'locations-section',
        categories: 'categories-section',
        transfers:  'transfers-section',
        compliance: 'compliance-section',
        logs:       'logs-section',
        assets:     'assets-section',
        users:      'users-section',
        personnel:  'personnel-section',
        jobs:       'jobs-section',
    };

    Object.entries(routeMap).forEach(([route, sectionId]) => {
        Router.register(route, async () => {
            showSection(sectionId);
            setActiveNavItem(route);

            // Call the page loader from existing app.js if available
            const loaderName = `load${route.charAt(0).toUpperCase() + route.slice(1)}`;
            if (typeof window[loaderName] === 'function') {
                try {
                    await window[loaderName]();
                } catch (err) {
                    console.error(`[Router] Error loading ${route}:`, err);
                }
            }
        });
    });

    // Auth guard
    Router.beforeEach((to) => {
        if (to === 'login') return true;
        return Auth.isAuthenticated();
    });

    Router.init();
}

// Export for global access if needed
window.ScienceTechIMS = {
    Auth,
    Router,
    Store: appStore,
    EventBus: eventBus,
};
