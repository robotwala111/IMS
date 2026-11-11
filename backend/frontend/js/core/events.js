/**
 * Scientech-IMS — Event Bus
 *
 * Application-wide event system for loose coupling between modules.
 * Supports namespaced events and one-time listeners.
 */

class EventBus {
    constructor() {
        this._handlers = new Map();
    }

    /**
     * Subscribe to an event.
     * @param {string} event - Event name (e.g., 'item:created', 'auth:logout')
     * @param {Function} handler - Event handler
     * @returns {Function} Unsubscribe function
     */
    on(event, handler) {
        if (!this._handlers.has(event)) {
            this._handlers.set(event, new Set());
        }
        this._handlers.get(event).add(handler);
        return () => this.off(event, handler);
    }

    /**
     * Subscribe to an event once — auto-removes after first call.
     */
    once(event, handler) {
        const wrapper = (...args) => {
            this.off(event, wrapper);
            handler(...args);
        };
        return this.on(event, wrapper);
    }

    /**
     * Unsubscribe from an event.
     */
    off(event, handler) {
        this._handlers.get(event)?.delete(handler);
    }

    /**
     * Emit an event with optional data.
     * @param {string} event - Event name
     * @param {*} data - Event data
     */
    emit(event, data) {
        const handlers = this._handlers.get(event);
        if (handlers) {
            handlers.forEach(handler => {
                try {
                    handler(data);
                } catch (e) {
                    console.error(`[EventBus] Error in handler for "${event}":`, e);
                }
            });
        }
    }

    /**
     * Remove all handlers for an event, or all events.
     */
    clear(event) {
        if (event) {
            this._handlers.delete(event);
        } else {
            this._handlers.clear();
        }
    }
}

// Singleton
const eventBus = new EventBus();
export default eventBus;
