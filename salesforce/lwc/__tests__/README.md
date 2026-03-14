# LWC Jest Tests

This directory contains Jest tests for the Ascendix AI Search Lightning Web Component.

## Test Coverage

The test suite covers the following requirements:

### 1. Query Submission and Response Handling (Requirement 1.1)
- Submit button state management (enabled/disabled based on query text)
- Query submission via button click
- Keyboard shortcut support (Ctrl+Enter)
- Streaming answer display
- Loading skeleton during answer generation
- Answer text rendering

### 2. Citation Drawer Interactions (Requirement 6.1)
- Citations button visibility when citations are available
- Toggle citations drawer open/close
- Display citation details (title, sobject, score, snippet)
- Citation count display
- Keyboard navigation (Escape to close)
- Citation preview functionality

### 3. Facet Filter Application (Requirement 7.1)
- Display filter options (Region, Business Unit, Quarter)
- Apply selected filters to queries
- Display active filter chips
- Remove individual filter chips
- Clear all filters at once
- Filter values included in API requests

### 4. Error Message Display (Requirement 11.4)
- Access denied errors (no retry)
- Timeout errors (with retry)
- No results errors (info message)
- Rate limit errors (with retry)
- Network errors (with retry)
- Retry functionality
- Toast notifications for errors

## Running Tests

### Prerequisites

Install dependencies:
```bash
cd salesforce/lwc
npm install
```

### Run All Tests
```bash
npm test
```

### Run Tests with Coverage
```bash
npm run test:coverage
```

### Run Tests in Watch Mode
```bash
npm run test:watch
```

### Debug Tests
```bash
npm run test:debug
```

## Test Structure

### Mock Files
- `__mocks__/lightning/platformShowToastEvent.js` - Mock for toast notifications
- `__mocks__/lightning/navigation.js` - Mock for navigation service
- `jest.setup.js` - Global test setup and polyfills

### Test File
- `ascendixAiSearch/__tests__/ascendixAiSearch.test.js` - Main test suite

## Test Patterns

### Async Operations
Tests use `flushPromises()` helper to wait for async operations:
```javascript
const flushPromises = () => new Promise(resolve => setImmediate(resolve));
await flushPromises();
```

### Mocking Apex Methods
Apex methods are mocked using Jest:
```javascript
jest.mock('@salesforce/apex/AscendixAISearchController.callAnswerEndpoint', () => {
    return { default: jest.fn() };
}, { virtual: true });
```

### Simulating User Interactions
```javascript
// Change input value
textarea.dispatchEvent(new CustomEvent('change', {
    detail: { value: 'Test query' }
}));

// Click button
button.click();

// Keyboard events
const keyEvent = new KeyboardEvent('keydown', {
    key: 'Enter',
    ctrlKey: true
});
element.dispatchEvent(keyEvent);
```

## Coverage Goals

Target coverage: 75% for branches, functions, lines, and statements

Current coverage areas:
- ✅ Query submission and validation
- ✅ Answer streaming and display
- ✅ Citation drawer interactions
- ✅ Filter application and management
- ✅ Error handling and retry logic
- ✅ Keyboard navigation
- ✅ Toast notifications

## Known Limitations

1. **True Streaming**: Tests simulate streaming behavior since Salesforce LWC doesn't support true SSE streaming
2. **Navigation**: Navigation is mocked and doesn't actually navigate in tests
3. **Apex Callouts**: All Apex methods are mocked - integration tests should be performed in a Salesforce org

## Troubleshooting

### Tests Timing Out
If tests timeout, increase the Jest timeout:
```javascript
jest.setTimeout(10000); // 10 seconds
```

### Mock Not Working
Ensure mocks are defined before importing the component:
```javascript
jest.mock('@salesforce/apex/...', () => {...}, { virtual: true });
```

### DOM Not Updating
Use `flushPromises()` and `await` to ensure async operations complete:
```javascript
await flushPromises();
await new Promise(resolve => setTimeout(resolve, 100));
```

## Contributing

When adding new tests:
1. Follow existing test patterns
2. Use descriptive test names
3. Test both success and error scenarios
4. Verify accessibility features
5. Update this README with new coverage areas
