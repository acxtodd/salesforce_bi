const { jestConfig } = require('@salesforce/sfdx-lwc-jest/config');

module.exports = {
    ...jestConfig,
    moduleNameMapper: {
        '^@salesforce/apex$': '<rootDir>/lwc/__mocks__/@salesforce/apex',
        '^@salesforce/apex/(.+)$': '<rootDir>/lwc/__mocks__/@salesforce/apex/$1',
        '^lightning/platformShowToastEvent$': '<rootDir>/lwc/__mocks__/lightning/platformShowToastEvent',
        '^lightning/navigation$': '<rootDir>/lwc/__mocks__/lightning/navigation',
        '^c/(.+)$': '<rootDir>/lwc/$1/$1'
    },
    testMatch: ['**/lwc/**/__tests__/**/*.test.js'],
    collectCoverageFrom: [
        'lwc/**/*.js',
        '!lwc/**/__tests__/**',
        '!lwc/**/__mocks__/**',
        '!**/node_modules/**'
    ],
    coverageThreshold: {
        global: {
            branches: 75,
            functions: 75,
            lines: 75,
            statements: 75
        }
    },
    testEnvironment: 'jsdom',
    setupFilesAfterEnv: ['<rootDir>/lwc/jest.setup.js']
};
