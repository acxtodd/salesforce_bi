// Jest setup file for LWC tests

// Polyfill for setImmediate if not available
if (typeof setImmediate === 'undefined') {
    global.setImmediate = (callback) => setTimeout(callback, 0);
}

// Mock console methods to reduce noise in tests
global.console = {
    ...console,
    error: jest.fn(),
    warn: jest.fn(),
    log: jest.fn()
};
