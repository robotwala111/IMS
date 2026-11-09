/**
 * Scientech-IMS — Domain API Services
 *
 * Each service encapsulates API calls for a specific domain.
 * All services use the centralized HttpClient.
 */

import HttpClient from '../core/http.js';

// =========================================================================
// Helper — build query string from params object
// =========================================================================
function qs(params = {}) {
    const filtered = Object.entries(params)
        .filter(([, v]) => v != null && v !== '');
    if (!filtered.length) return '';
    return '?' + new URLSearchParams(filtered).toString();
}

// =========================================================================
// Dashboard
// =========================================================================
export const DashboardService = {
    getSummary: ()              => HttpClient.get('/dashboard/summary'),
    getStockByLocation: ()      => HttpClient.get('/dashboard/stock-by-location'),
    getStockByCategory: ()      => HttpClient.get('/dashboard/stock-by-category'),
    getLowStockItems: (limit=10) => HttpClient.get(`/dashboard/low-stock-items?limit=${limit}`),
    getRecentActivity: (limit=10)=> HttpClient.get(`/dashboard/recent-activity?limit=${limit}`),
    getCalibrationAlerts: (days=15) => HttpClient.get(`/dashboard/calibration-alerts?days=${days}`),
    getLocationStockSummary: (locationId) =>
        HttpClient.get(`/dashboard/location-stock-summary${locationId ? '?location_id=' + locationId : ''}`),
};

// =========================================================================
// Items
// =========================================================================
export const ItemsService = {
    list:     (params = {}) => HttpClient.get(`/items${qs({ is_active: true, ...params })}`),
    getById:  (id)     => HttpClient.get(`/items/${id}`),
    getBySku: (sku)    => HttpClient.get(`/items/sku/${sku}`),
    getSummary: (categoryId) => HttpClient.get(`/items/summary${categoryId ? '?category_id=' + categoryId : ''}`),
    create:   (data)   => HttpClient.post('/items', data),
    update:   (id, data) => HttpClient.patch(`/items/${id}`, data),
    delete:   (id)     => HttpClient.delete(`/items/${id}`),
};

// =========================================================================
// Stock
// =========================================================================
export const StockService = {
    list:       (params) => HttpClient.get(`/stock${qs(params)}`),
    adjust:     (data)   => HttpClient.post('/stock/adjustments', data),
    issue:      (data)   => HttpClient.post('/stock/issue', data),
    getLowStock:()       => HttpClient.get('/stock?low_stock_only=true'),
    sendAlert:  ()       => HttpClient.post('/stock/send-low-stock-alert', {}),
};

// =========================================================================
// Categories
// =========================================================================
export const CategoriesService = {
    list:    (params) => HttpClient.get(`/categories${qs(params)}`),
    getSummary: ()    => HttpClient.get('/categories/summary'),
    getById: (id)     => HttpClient.get(`/categories/${id}`),
    create:  (data)   => HttpClient.post('/categories', data),
    update:  (id, data)=> HttpClient.patch(`/categories/${id}`, data),
    delete:  (id)     => HttpClient.delete(`/categories/${id}`),
};

export const CategoryTypesService = {
    list:   (params) => HttpClient.get(`/categories/types${qs(params)}`),
    create: (data)   => HttpClient.post('/categories/types', data),
    update: (id, data)=> HttpClient.patch(`/categories/types/${id}`, data),
};

// =========================================================================
// Locations
// =========================================================================
export const LocationsService = {
    list:    (params)  => HttpClient.get(`/locations${qs(params)}`),
    getById: (id)      => HttpClient.get(`/locations/${id}`),
    create:  (data)    => HttpClient.post('/locations', data),
    update:  (id, data)=> HttpClient.patch(`/locations/${id}`, data),
    delete:  (id)      => HttpClient.delete(`/locations/${id}`),
};

// =========================================================================
// Transfers
// =========================================================================
export const TransfersService = {
    list:     (params)  => HttpClient.get(`/transfers${qs(params)}`),
    getById:  (id)      => HttpClient.get(`/transfers/${id}`),
    getEquipmentOverview: (params) => HttpClient.get(`/transfers/equipment-overview${qs(params)}`),
    create:   (data)    => HttpClient.post('/transfers', data),
    approve:  (id)      => HttpClient.patch(`/transfers/${id}/approve`, { approved: true }),
    ship:     (id, data={}) => HttpClient.patch(`/transfers/${id}/ship`, data),
    receive:  (id, data)=> HttpClient.patch(`/transfers/${id}/receive`, data),
    cancel:   (id)      => HttpClient.patch(`/transfers/${id}/cancel`, {}),
    updateReturnDate: (id, data) => HttpClient.patch(`/transfers/${id}/return-date`, data),
};

// =========================================================================
// Transactions
// =========================================================================
export const TransactionsService = {
    list:    (params) => HttpClient.get(`/transactions${qs(params)}`),
    getById: (id)     => HttpClient.get(`/transactions/${id}`),
    receipt: (data)   => HttpClient.post('/transactions/receipt', data),
    issue:   (data)   => HttpClient.post('/transactions/issue', data),
    return:  (data)   => HttpClient.post('/transactions/return', data),
};

// =========================================================================
// Assets
// =========================================================================
export const AssetsService = {
    list:       (params)  => HttpClient.get(`/assets${qs(params)}`),
    getById:    (id)      => HttpClient.get(`/assets/${id}`),
    getBySerial:(serial)  => HttpClient.get(`/assets/serial/${serial}`),
    create:     (data)    => HttpClient.post('/assets', data),
    update:     (id, data)=> HttpClient.patch(`/assets/${id}`, data),
    updateStatus:(id, status) => HttpClient.patch(`/assets/${id}/status`, { status }),
    addCalibration: (id, data) => HttpClient.post(`/calibration/assets/${id}/records`, data),
};

// =========================================================================
// Users
// =========================================================================
export const UsersService = {
    list:    (params)  => HttpClient.get(`/users${qs(params)}`),
    getById: (id)      => HttpClient.get(`/users/${id}`),
    create:  (data)    => HttpClient.post('/users', data),
    update:  (id, data)=> HttpClient.patch(`/users/${id}`, data),
    delete:  (id)      => HttpClient.delete(`/users/${id}`),
};

// =========================================================================
// Employee Records
// =========================================================================
export const EmployeeRecordsService = {
    list:    (params)  => HttpClient.get(`/employee-records${qs(params)}`),
    getById: (id)      => HttpClient.get(`/employee-records/${id}`),
    create:  (data)    => HttpClient.post('/employee-records', data),
    update:  (id, data)=> HttpClient.patch(`/employee-records/${id}`, data),
    delete:  (id)      => HttpClient.delete(`/employee-records/${id}`),
};

// =========================================================================
// Jobs
// =========================================================================
export const JobsService = {
    list:     (params) => HttpClient.get(`/jobs${qs(params)}`),
    getById:  (id)     => HttpClient.get(`/jobs/${id}`),
    create:   (data)   => HttpClient.post('/jobs', data),
    update:   (id, data)=> HttpClient.patch(`/jobs/${id}`, data),
    complete: (id, data)=> HttpClient.patch(`/jobs/${id}/complete`, data),
    validate: (id)     => HttpClient.patch(`/jobs/${id}/validate`),
    canIssue: (name)   => HttpClient.get(`/jobs/can-issue?person_name=${encodeURIComponent(name)}`),
    delete:   (id)     => HttpClient.delete(`/jobs/${id}`),
};

// =========================================================================
// Audit Logs
// =========================================================================
export const AuditService = {
    list: (params) => HttpClient.get(`/audit${qs(params)}`),
};

// =========================================================================
// Notifications
// =========================================================================
export const NotificationsService = {
    list:     (params) => HttpClient.get(`/notifications${qs(params)}`),
    markRead: (ids)    => HttpClient.post('/notifications/mark-read', { notification_ids: ids }),
};
