import { createElement } from 'lwc';
import AscendixAiSearch from 'c/ascendixAiSearch';
import callAnswerEndpoint from '@salesforce/apex/AscendixAISearchController.callAnswerEndpoint';
import callActionEndpoint from '@salesforce/apex/AscendixAISearchController.callActionEndpoint';
import getCurrentUserId from '@salesforce/apex/AscendixAISearchController.getCurrentUserId';
import { ShowToastEventName } from 'lightning/platformShowToastEvent';
import { NavigationMixin } from 'lightning/navigation';

// Mock Apex methods
jest.mock(
    '@salesforce/apex/AscendixAISearchController.callAnswerEndpoint',
    () => {
        return {
            default: jest.fn()
        };
    },
    { virtual: true }
);

jest.mock(
    '@salesforce/apex/AscendixAISearchController.callActionEndpoint',
    () => {
        return {
            default: jest.fn()
        };
    },
    { virtual: true }
);

jest.mock(
    '@salesforce/apex/AscendixAISearchController.getCurrentUserId',
    () => {
        return {
            default: jest.fn()
        };
    },
    { virtual: true }
);

// Helper to wait for async operations
const flushPromises = () => new Promise(resolve => setTimeout(resolve, 0));

const createDeferred = () => {
    let resolve;
    let reject;
    const promise = new Promise((res, rej) => {
        resolve = res;
        reject = rej;
    });
    return { promise, resolve, reject };
};

const createSearchComponent = (recordId = null) => {
    const element = createElement('c-ascendix-ai-search', {
        is: AscendixAiSearch
    });

    if (recordId) {
        element.recordId = recordId;
    }

    document.body.appendChild(element);
    return element;
};

describe('c-ascendix-ai-search', () => {
    afterEach(() => {
        // Clean up DOM
        while (document.body.firstChild) {
            document.body.removeChild(document.body.firstChild);
        }
        // Clear all mocks
        jest.clearAllMocks();
    });

    describe('Query Submission and Response Handling', () => {
        it('should disable submit button when query is empty', () => {
            const element = createElement('c-ascendix-ai-search', {
                is: AscendixAiSearch
            });
            document.body.appendChild(element);

            const submitButton = element.shadowRoot.querySelector('.submit-button');
            expect(submitButton.disabled).toBe(true);
        });

        it('should enable submit button when query has text', async () => {
            const element = createElement('c-ascendix-ai-search', {
                is: AscendixAiSearch
            });
            document.body.appendChild(element);

            const textarea = element.shadowRoot.querySelector('lightning-textarea');
            textarea.value = 'Show open opportunities';
            textarea.dispatchEvent(new CustomEvent('change', {
                detail: { value: 'Show open opportunities' }
            }));

            await flushPromises();

            const submitButton = element.shadowRoot.querySelector('.submit-button');
            expect(submitButton.disabled).toBe(false);
        });

        it('should submit query and display streaming answer', async () => {
            // Mock successful response
            const mockResponse = {
                answer: 'Based on the data, there are 5 open opportunities totaling $3.2M.',
                citations: [
                    {
                        id: 'Opportunity/006xx1/chunk-0',
                        recordId: '006xx000001X8UzAAK',
                        title: 'ACME Renewal',
                        sobject: 'Opportunity',
                        score: 0.92,
                        snippet: 'ACME renewal valued at $1.2M...'
                    }
                ]
            };
            callAnswerEndpoint.mockResolvedValue(mockResponse);
            getCurrentUserId.mockResolvedValue('005xx000001X8UzAAK');

            const element = createElement('c-ascendix-ai-search', {
                is: AscendixAiSearch
            });
            document.body.appendChild(element);

            await flushPromises();

            // Enter query
            const textarea = element.shadowRoot.querySelector('lightning-textarea');
            textarea.value = 'Show open opportunities';
            textarea.dispatchEvent(new CustomEvent('change', {
                detail: { value: 'Show open opportunities' }
            }));

            await flushPromises();

            // Submit query
            const submitButton = element.shadowRoot.querySelector('.submit-button');
            submitButton.click();

            await flushPromises();

            // Wait for streaming simulation to complete
            await new Promise(resolve => setTimeout(resolve, 100));

            // Verify answer is displayed
            const answerDisplay = element.shadowRoot.querySelector('[data-id="answer-display"]');
            expect(answerDisplay).toBeTruthy();
            expect(element.answer).toContain('Based on the data');
        });

        it('should handle Ctrl+Enter keyboard shortcut for submission', async () => {
            getCurrentUserId.mockResolvedValue('005xx000001X8UzAAK');
            callAnswerEndpoint.mockResolvedValue({
                answer: 'Test answer',
                citations: []
            });

            const element = createElement('c-ascendix-ai-search', {
                is: AscendixAiSearch
            });
            document.body.appendChild(element);

            await flushPromises();

            // Enter query
            const textarea = element.shadowRoot.querySelector('lightning-textarea');
            textarea.value = 'Test query';
            textarea.dispatchEvent(new CustomEvent('change', {
                detail: { value: 'Test query' }
            }));

            await flushPromises();

            // Trigger Ctrl+Enter
            const keydownEvent = new KeyboardEvent('keydown', {
                key: 'Enter',
                ctrlKey: true,
                bubbles: true
            });
            textarea.dispatchEvent(keydownEvent);

            await flushPromises();

            // Verify callAnswerEndpoint was called
            expect(callAnswerEndpoint).toHaveBeenCalled();
        });

        it('should display loading skeleton during streaming', async () => {
            // Mock delayed response
            callAnswerEndpoint.mockImplementation(() => 
                new Promise(resolve => setTimeout(() => resolve({
                    answer: 'Test answer',
                    citations: []
                }), 100))
            );
            getCurrentUserId.mockResolvedValue('005xx000001X8UzAAK');

            const element = createElement('c-ascendix-ai-search', {
                is: AscendixAiSearch
            });
            document.body.appendChild(element);

            await flushPromises();

            // Submit query
            const textarea = element.shadowRoot.querySelector('lightning-textarea');
            textarea.value = 'Test query';
            textarea.dispatchEvent(new CustomEvent('change', {
                detail: { value: 'Test query' }
            }));

            await flushPromises();

            const submitButton = element.shadowRoot.querySelector('.submit-button');
            submitButton.click();

            await flushPromises();

            // Verify skeleton is displayed
            const skeleton = element.shadowRoot.querySelector('.skeleton-container');
            expect(skeleton).toBeTruthy();

            const spinner = element.shadowRoot.querySelector('lightning-spinner');
            expect(spinner).toBeTruthy();
        });
    });

    describe('Citation Drawer Interactions', () => {
        it('should show citations button when citations are available', async () => {
            const mockResponse = {
                answer: 'Test answer',
                citations: [
                    {
                        id: 'citation-1',
                        recordId: '006xx1',
                        title: 'Test Record',
                        sobject: 'Opportunity',
                        score: 0.9,
                        snippet: 'Test snippet'
                    }
                ]
            };
            callAnswerEndpoint.mockResolvedValue(mockResponse);
            getCurrentUserId.mockResolvedValue('005xx000001X8UzAAK');

            const element = createElement('c-ascendix-ai-search', {
                is: AscendixAiSearch
            });
            document.body.appendChild(element);

            await flushPromises();

            // Submit query
            const textarea = element.shadowRoot.querySelector('lightning-textarea');
            textarea.value = 'Test query';
            textarea.dispatchEvent(new CustomEvent('change', {
                detail: { value: 'Test query' }
            }));

            await flushPromises();

            const submitButton = element.shadowRoot.querySelector('.submit-button');
            submitButton.click();

            await flushPromises();
            await new Promise(resolve => setTimeout(resolve, 100));

            // Verify citations button is displayed
            const citationsButton = element.shadowRoot.querySelector('lightning-button[label*="View Citations"]');
            expect(citationsButton).toBeTruthy();
            expect(citationsButton.label).toContain('(1)');
            expect(element.shadowRoot.querySelector('.conversation-thread')).toBeFalsy();
        });

        it('should handle minimal citations from /query endpoint (id + title only)', async () => {
            // Real /query returns citations with only {recordId, title, id}
            // after Apex transforms {id, name} from the backend.
            // No sobject, score, or snippet fields.
            const mockResponse = {
                answer: 'Test answer mentioning Tower One',
                citations: [
                    {
                        id: 'a0x000001',
                        recordId: 'a0x000001',
                        title: 'Tower One'
                        // No sobject, score, snippet, previewUrl
                    }
                ]
            };
            callAnswerEndpoint.mockResolvedValue(mockResponse);
            getCurrentUserId.mockResolvedValue('005xx000001X8UzAAK');

            const element = createElement('c-ascendix-ai-search', {
                is: AscendixAiSearch
            });
            document.body.appendChild(element);

            await flushPromises();

            const textarea = element.shadowRoot.querySelector('lightning-textarea');
            textarea.value = 'Find Tower One';
            textarea.dispatchEvent(new CustomEvent('change', {
                detail: { value: 'Find Tower One' }
            }));

            await flushPromises();

            const submitButton = element.shadowRoot.querySelector('.submit-button');
            submitButton.click();

            await flushPromises();
            await new Promise(resolve => setTimeout(resolve, 100));

            const citationsButton = element.shadowRoot.querySelector('lightning-button[label*="View Citations"]');
            expect(citationsButton).toBeTruthy();

            citationsButton.click();
            await flushPromises();

            const citationEntry = element.shadowRoot.querySelector('.citation-item');
            expect(citationEntry).toBeTruthy();
            expect(citationEntry.textContent).toContain('Tower One');
            expect(citationEntry.textContent).toContain('Record');
        });

        it('should toggle citations drawer when button is clicked', async () => {
            const mockResponse = {
                answer: 'Test answer',
                citations: [
                    {
                        id: 'citation-1',
                        recordId: '006xx1',
                        title: 'Test Record',
                        sobject: 'Opportunity',
                        score: 0.9,
                        snippet: 'Test snippet'
                    }
                ]
            };
            callAnswerEndpoint.mockResolvedValue(mockResponse);
            getCurrentUserId.mockResolvedValue('005xx000001X8UzAAK');

            const element = createElement('c-ascendix-ai-search', {
                is: AscendixAiSearch
            });
            document.body.appendChild(element);

            await flushPromises();

            // Submit query and wait for response
            const textarea = element.shadowRoot.querySelector('lightning-textarea');
            textarea.value = 'Test query';
            textarea.dispatchEvent(new CustomEvent('change', {
                detail: { value: 'Test query' }
            }));

            await flushPromises();

            const submitButton = element.shadowRoot.querySelector('.submit-button');
            submitButton.click();

            await flushPromises();
            await new Promise(resolve => setTimeout(resolve, 100));

            // Click citations button
            const citationsButton = element.shadowRoot.querySelector('lightning-button[label*="View Citations"]');
            citationsButton.click();

            await flushPromises();

            // Verify drawer is open
            let drawer = element.shadowRoot.querySelector('.slds-modal');
            expect(drawer).toBeTruthy();
            expect(drawer.classList.contains('slds-fade-in-open')).toBe(true);

            // Click again to close
            const closeButton = element.shadowRoot.querySelector('.slds-modal__close');
            closeButton.click();

            await flushPromises();

            // Verify drawer is closed
            drawer = element.shadowRoot.querySelector('.slds-modal');
            expect(drawer).toBeFalsy();
        });

        it('should display citation details in drawer', async () => {
            const mockResponse = {
                answer: 'Test answer',
                citations: [
                    {
                        id: 'citation-1',
                        recordId: '006xx1',
                        title: 'ACME Renewal',
                        sobject: 'Opportunity',
                        score: 0.92,
                        snippet: 'ACME renewal valued at $1.2M...'
                    },
                    {
                        id: 'citation-2',
                        recordId: '006xx2',
                        title: 'Global Corp Deal',
                        sobject: 'Opportunity',
                        score: 0.85,
                        snippet: 'Global Corp expansion opportunity...'
                    }
                ]
            };
            callAnswerEndpoint.mockResolvedValue(mockResponse);
            getCurrentUserId.mockResolvedValue('005xx000001X8UzAAK');

            const element = createElement('c-ascendix-ai-search', {
                is: AscendixAiSearch
            });
            document.body.appendChild(element);

            await flushPromises();

            // Submit query
            const textarea = element.shadowRoot.querySelector('lightning-textarea');
            textarea.value = 'Test query';
            textarea.dispatchEvent(new CustomEvent('change', {
                detail: { value: 'Test query' }
            }));

            await flushPromises();

            const submitButton = element.shadowRoot.querySelector('.submit-button');
            submitButton.click();

            await flushPromises();
            await new Promise(resolve => setTimeout(resolve, 100));

            // Open citations drawer
            const citationsButton = element.shadowRoot.querySelector('lightning-button[label*="View Citations"]');
            citationsButton.click();

            await flushPromises();

            // Verify citation items are displayed
            const citationItems = element.shadowRoot.querySelectorAll('.citation-item');
            expect(citationItems.length).toBe(2);

            // Verify citation content
            const firstCitation = citationItems[0];
            expect(firstCitation.textContent).toContain('ACME Renewal');
            expect(firstCitation.textContent).toContain('Opportunity');
            expect(firstCitation.textContent).toContain('0.92');
        });

        it('should close drawer with Escape key', async () => {
            const mockResponse = {
                answer: 'Test answer',
                citations: [{ id: 'citation-1', recordId: '006xx1', title: 'Test', sobject: 'Opportunity', score: 0.9, snippet: 'Test' }]
            };
            callAnswerEndpoint.mockResolvedValue(mockResponse);
            getCurrentUserId.mockResolvedValue('005xx000001X8UzAAK');

            const element = createElement('c-ascendix-ai-search', {
                is: AscendixAiSearch
            });
            document.body.appendChild(element);

            await flushPromises();

            // Submit query
            const textarea = element.shadowRoot.querySelector('lightning-textarea');
            textarea.value = 'Test query';
            textarea.dispatchEvent(new CustomEvent('change', {
                detail: { value: 'Test query' }
            }));

            await flushPromises();

            const submitButton = element.shadowRoot.querySelector('.submit-button');
            submitButton.click();

            await flushPromises();
            await new Promise(resolve => setTimeout(resolve, 100));

            // Open drawer
            const citationsButton = element.shadowRoot.querySelector('lightning-button[label*="View Citations"]');
            citationsButton.click();

            await flushPromises();

            // Press Escape
            const escapeEvent = new KeyboardEvent('keydown', {
                key: 'Escape',
                bubbles: true
            });
            textarea.dispatchEvent(escapeEvent);

            await flushPromises();

            // Verify drawer is closed
            const drawer = element.shadowRoot.querySelector('.slds-modal');
            expect(drawer).toBeFalsy();
        });
    });

    describe('Filter UI Hidden (deferred — /query does not support filters)', () => {
        it('should NOT display filter comboboxes when filter UI is disabled', () => {
            const element = createElement('c-ascendix-ai-search', {
                is: AscendixAiSearch
            });
            document.body.appendChild(element);

            // Filter comboboxes should not be rendered since isFilterUIEnabled is false
            const regionFilter = element.shadowRoot.querySelector('lightning-combobox[name="region"]');
            const buFilter = element.shadowRoot.querySelector('lightning-combobox[name="businessUnit"]');
            const quarterFilter = element.shadowRoot.querySelector('lightning-combobox[name="quarter"]');

            expect(regionFilter).toBeFalsy();
            expect(buFilter).toBeFalsy();
            expect(quarterFilter).toBeFalsy();
        });

        it('should submit simplified request payload (query + sessionId only)', async () => {
            callAnswerEndpoint.mockResolvedValue({
                answer: 'Test answer',
                citations: []
            });
            getCurrentUserId.mockResolvedValue('005xx000001X8UzAAK');

            const element = createElement('c-ascendix-ai-search', {
                is: AscendixAiSearch
            });
            document.body.appendChild(element);

            await flushPromises();

            // Submit query
            const textarea = element.shadowRoot.querySelector('lightning-textarea');
            textarea.value = 'Find Class A properties';
            textarea.dispatchEvent(new CustomEvent('change', {
                detail: { value: 'Find Class A properties' }
            }));

            await flushPromises();

            const submitButton = element.shadowRoot.querySelector('.submit-button');
            submitButton.click();

            await flushPromises();

            // Verify simplified payload: only query and sessionId
            expect(callAnswerEndpoint).toHaveBeenCalled();
            const callArgs = callAnswerEndpoint.mock.calls[0][0];
            const payload = JSON.parse(callArgs.requestBodyJson);
            expect(payload.query).toBe('Find Class A properties');
            expect(payload.sessionId).toBeTruthy();
            expect(payload.priorContext).toBeUndefined();
            // No legacy fields in payload
            expect(payload.salesforceUserId).toBeUndefined();
            expect(payload.topK).toBeUndefined();
            expect(payload.policy).toBeUndefined();
            expect(payload.filters).toBeUndefined();
            expect(payload.recordContext).toBeUndefined();
        });

        it('should preserve filter JS helpers for future reactivation', () => {
            const element = createElement('c-ascendix-ai-search', {
                is: AscendixAiSearch
            });
            document.body.appendChild(element);

            // Filter helper methods should still exist in the component
            expect(typeof element.getActiveFilters).toBe('undefined'); // private method
            // Verify isFilterUIEnabled getter returns false
            expect(element.isFilterUIEnabled).toBeFalsy();
        });
    });

    describe('Error Message Display', () => {
        it('should display access denied error', async () => {
            const accessDeniedError = new Error('Access denied: You do not have permission');
            callAnswerEndpoint.mockRejectedValue(accessDeniedError);
            getCurrentUserId.mockResolvedValue('005xx000001X8UzAAK');

            const element = createElement('c-ascendix-ai-search', {
                is: AscendixAiSearch
            });
            document.body.appendChild(element);

            await flushPromises();

            // Mock toast event handler
            const toastHandler = jest.fn();
            element.addEventListener(ShowToastEventName, toastHandler);

            // Submit query
            const textarea = element.shadowRoot.querySelector('lightning-textarea');
            textarea.value = 'Test query';
            textarea.dispatchEvent(new CustomEvent('change', {
                detail: { value: 'Test query' }
            }));

            await flushPromises();

            const submitButton = element.shadowRoot.querySelector('.submit-button');
            submitButton.click();

            await flushPromises();

            // Verify error message is displayed
            const errorMessage = element.shadowRoot.querySelector('.error-message');
            expect(errorMessage).toBeTruthy();
            expect(errorMessage.textContent).toContain("don't have permission");

            // Verify no retry button for access denied
            const retryButton = element.shadowRoot.querySelector('lightning-button[label="Retry"]');
            expect(retryButton).toBeFalsy();
        });

        it('should display timeout error with retry button', async () => {
            const timeoutError = new Error('Request timeout: The request took too long');
            callAnswerEndpoint.mockRejectedValue(timeoutError);
            getCurrentUserId.mockResolvedValue('005xx000001X8UzAAK');

            const element = createElement('c-ascendix-ai-search', {
                is: AscendixAiSearch
            });
            document.body.appendChild(element);

            await flushPromises();

            // Submit query
            const textarea = element.shadowRoot.querySelector('lightning-textarea');
            textarea.value = 'Test query';
            textarea.dispatchEvent(new CustomEvent('change', {
                detail: { value: 'Test query' }
            }));

            await flushPromises();

            const submitButton = element.shadowRoot.querySelector('.submit-button');
            submitButton.click();

            await flushPromises();

            // Verify error message and retry button
            const errorMessage = element.shadowRoot.querySelector('.error-message');
            expect(errorMessage).toBeTruthy();
            expect(errorMessage.textContent).toContain('took too long');

            const retryButton = element.shadowRoot.querySelector('lightning-button[label="Retry"]');
            expect(retryButton).toBeTruthy();
        });

        it('should display no results error', async () => {
            const mockResponse = {
                answer: null,
                citations: [],
                reason: 'no_accessible_results'
            };
            callAnswerEndpoint.mockResolvedValue(mockResponse);
            getCurrentUserId.mockResolvedValue('005xx000001X8UzAAK');

            const element = createElement('c-ascendix-ai-search', {
                is: AscendixAiSearch
            });
            document.body.appendChild(element);

            await flushPromises();

            // Mock toast event handler
            const toastHandler = jest.fn();
            element.addEventListener(ShowToastEventName, toastHandler);

            // Submit query
            const textarea = element.shadowRoot.querySelector('lightning-textarea');
            textarea.value = 'Test query';
            textarea.dispatchEvent(new CustomEvent('change', {
                detail: { value: 'Test query' }
            }));

            await flushPromises();

            const submitButton = element.shadowRoot.querySelector('.submit-button');
            submitButton.click();

            await flushPromises();
            await new Promise(resolve => setTimeout(resolve, 100));

            // Verify toast was shown
            expect(toastHandler).toHaveBeenCalled();
            const toastEvent = toastHandler.mock.calls[0][0];
            expect(toastEvent.detail.title).toBe('No Results');
            expect(toastEvent.detail.variant).toBe('info');
        });

        it('should retry failed request when retry button is clicked', async () => {
            // First call fails, second succeeds
            callAnswerEndpoint
                .mockRejectedValueOnce(new Error('Network error'))
                .mockResolvedValueOnce({
                    answer: 'Success after retry',
                    citations: []
                });
            getCurrentUserId.mockResolvedValue('005xx000001X8UzAAK');

            const element = createElement('c-ascendix-ai-search', {
                is: AscendixAiSearch
            });
            document.body.appendChild(element);

            await flushPromises();

            // Submit query (will fail)
            const textarea = element.shadowRoot.querySelector('lightning-textarea');
            textarea.value = 'Test query';
            textarea.dispatchEvent(new CustomEvent('change', {
                detail: { value: 'Test query' }
            }));

            await flushPromises();

            const submitButton = element.shadowRoot.querySelector('.submit-button');
            submitButton.click();

            await flushPromises();

            // Verify error and retry button
            let errorMessage = element.shadowRoot.querySelector('.error-message');
            expect(errorMessage).toBeTruthy();

            const retryButton = element.shadowRoot.querySelector('lightning-button[label="Retry"]');
            expect(retryButton).toBeTruthy();

            // Click retry
            retryButton.click();

            await flushPromises();
            await new Promise(resolve => setTimeout(resolve, 100));

            // Verify success
            expect(callAnswerEndpoint).toHaveBeenCalledTimes(2);
            expect(element.answer).toContain('Success after retry');

            // Verify error message is cleared
            errorMessage = element.shadowRoot.querySelector('.error-message');
            expect(errorMessage).toBeFalsy();
        });

        it('should display rate limit error', async () => {
            const rateLimitError = new Error('Rate limit exceeded: Too many requests');
            callAnswerEndpoint.mockRejectedValue(rateLimitError);
            getCurrentUserId.mockResolvedValue('005xx000001X8UzAAK');

            const element = createElement('c-ascendix-ai-search', {
                is: AscendixAiSearch
            });
            document.body.appendChild(element);

            await flushPromises();

            // Submit query
            const textarea = element.shadowRoot.querySelector('lightning-textarea');
            textarea.value = 'Test query';
            textarea.dispatchEvent(new CustomEvent('change', {
                detail: { value: 'Test query' }
            }));

            await flushPromises();

            const submitButton = element.shadowRoot.querySelector('.submit-button');
            submitButton.click();

            await flushPromises();

            // Verify error message
            const errorMessage = element.shadowRoot.querySelector('.error-message');
            expect(errorMessage).toBeTruthy();
            expect(errorMessage.textContent).toContain('Too many requests');

            // Verify retry button is available
            const retryButton = element.shadowRoot.querySelector('lightning-button[label="Retry"]');
            expect(retryButton).toBeTruthy();
        });
    });

    describe('Action Preview Modal Display', () => {
        it('should display action preview modal with create_opportunity action', async () => {
            const element = createElement('c-ascendix-ai-search', {
                is: AscendixAiSearch
            });
            document.body.appendChild(element);

            // Simulate showing action preview
            const actionData = {
                actionName: 'create_opportunity',
                inputs: {
                    Name: 'ACME Deal',
                    Amount: 500000,
                    CloseDate: '2025-12-31',
                    StageName: 'Prospecting'
                }
            };

            element.showActionPreviewModal(actionData);
            await flushPromises();

            // Verify modal is displayed
            const modal = element.shadowRoot.querySelector('.action-preview-modal');
            expect(modal).toBeTruthy();
            expect(element.showActionPreview).toBe(true);

            // Verify action title
            const title = element.shadowRoot.querySelector('.action-preview-title');
            expect(title.textContent).toContain('Create Opportunity');

            // Verify field values are displayed
            const fields = element.shadowRoot.querySelectorAll('.action-field');
            expect(fields.length).toBe(4);
        });

        it('should display action preview modal with update_opportunity_stage action', async () => {
            const element = createElement('c-ascendix-ai-search', {
                is: AscendixAiSearch
            });
            document.body.appendChild(element);

            const actionData = {
                actionName: 'update_opportunity_stage',
                inputs: {
                    OpportunityId: '006xx000001X8UzAAK',
                    StageName: 'Closed Won',
                    Probability: 100
                }
            };

            element.showActionPreviewModal(actionData);
            await flushPromises();

            // Verify modal is displayed
            expect(element.showActionPreview).toBe(true);

            // Verify action title
            const title = element.shadowRoot.querySelector('.action-preview-title');
            expect(title.textContent).toContain('Update Opportunity Stage');

            // Verify field values
            const fields = element.shadowRoot.querySelectorAll('.action-field');
            expect(fields.length).toBe(3);
        });

        it('should format currency values in action preview', async () => {
            const element = createElement('c-ascendix-ai-search', {
                is: AscendixAiSearch
            });
            document.body.appendChild(element);

            const actionData = {
                actionName: 'create_opportunity',
                inputs: {
                    Name: 'Test Deal',
                    Amount: 1250000
                }
            };

            element.showActionPreviewModal(actionData);
            await flushPromises();

            // Verify currency formatting
            const amountField = Array.from(element.shadowRoot.querySelectorAll('.action-field'))
                .find(field => field.textContent.includes('Amount'));
            
            expect(amountField).toBeTruthy();
            expect(amountField.textContent).toContain('$1,250,000');
        });

        it('should display confirmation and cancel buttons', async () => {
            const element = createElement('c-ascendix-ai-search', {
                is: AscendixAiSearch
            });
            document.body.appendChild(element);

            const actionData = {
                actionName: 'create_opportunity',
                inputs: { Name: 'Test' }
            };

            element.showActionPreviewModal(actionData);
            await flushPromises();

            // Verify buttons are present
            const confirmButton = element.shadowRoot.querySelector('lightning-button[label="Confirm"]');
            const cancelButton = element.shadowRoot.querySelector('lightning-button[label="Cancel"]');

            expect(confirmButton).toBeTruthy();
            expect(cancelButton).toBeTruthy();
        });

        it('should close modal when cancel button is clicked', async () => {
            const element = createElement('c-ascendix-ai-search', {
                is: AscendixAiSearch
            });
            document.body.appendChild(element);

            const actionData = {
                actionName: 'create_opportunity',
                inputs: { Name: 'Test' }
            };

            element.showActionPreviewModal(actionData);
            expect(element.showActionPreview).toBe(true);

            // Click cancel button
            const cancelButton = element.shadowRoot.querySelector('lightning-button[label="Cancel"]');
            cancelButton.click();

            await flushPromises();

            // Verify modal is closed
            expect(element.showActionPreview).toBe(false);
            const modal = element.shadowRoot.querySelector('.action-preview-modal');
            expect(modal).toBeFalsy();
        });

        it('should close modal with Escape key', async () => {
            const element = createElement('c-ascendix-ai-search', {
                is: AscendixAiSearch
            });
            document.body.appendChild(element);

            const actionData = {
                actionName: 'create_opportunity',
                inputs: { Name: 'Test' }
            };

            element.showActionPreviewModal(actionData);
            expect(element.showActionPreview).toBe(true);

            // Press Escape key
            const escapeEvent = new KeyboardEvent('keydown', {
                key: 'Escape',
                bubbles: true
            });
            const textarea = element.shadowRoot.querySelector('lightning-textarea');
            textarea.dispatchEvent(escapeEvent);

            await flushPromises();

            // Verify modal is closed
            expect(element.showActionPreview).toBe(false);
        });
    });

    describe('Action Confirmation Flow', () => {
        // Mock the callActionEndpoint method
        let callActionEndpoint;

        beforeEach(() => {
            callActionEndpoint = require('@salesforce/apex/AscendixAISearchController.callActionEndpoint').default;
        });

        it('should execute action with valid confirmation token', async () => {
            const mockResponse = {
                success: true,
                recordIds: ['006xx000001X8UzAAK']
            };
            callActionEndpoint.mockResolvedValue(mockResponse);
            getCurrentUserId.mockResolvedValue('005xx000001X8UzAAK');

            const element = createElement('c-ascendix-ai-search', {
                is: AscendixAiSearch
            });
            document.body.appendChild(element);

            await flushPromises();

            // Show action preview
            const actionData = {
                actionName: 'create_opportunity',
                inputs: {
                    Name: 'ACME Deal',
                    Amount: 500000
                }
            };

            element.showActionPreviewModal(actionData);

            // Mock toast handler
            const toastHandler = jest.fn();
            element.addEventListener(ShowToastEventName, toastHandler);

            // Click confirm button
            const confirmButton = element.shadowRoot.querySelector('lightning-button[label="Confirm"]');
            confirmButton.click();

            await flushPromises();

            // Verify action endpoint was called
            expect(callActionEndpoint).toHaveBeenCalled();
            const callArgs = callActionEndpoint.mock.calls[0][0];
            const requestBody = JSON.parse(callArgs.requestBodyJson);

            expect(requestBody.actionName).toBe('create_opportunity');
            expect(requestBody.inputs.Name).toBe('ACME Deal');
            expect(requestBody.confirmationToken).toBeTruthy();

            // Verify success toast
            expect(toastHandler).toHaveBeenCalled();
            const toastEvent = toastHandler.mock.calls[0][0];
            expect(toastEvent.detail.title).toBe('Action Completed');
            expect(toastEvent.detail.variant).toBe('success');

            // Verify modal is closed
            expect(element.showActionPreview).toBe(false);
        });

        it('should generate unique confirmation tokens', () => {
            const element = createElement('c-ascendix-ai-search', {
                is: AscendixAiSearch
            });
            document.body.appendChild(element);

            const inputs1 = { Name: 'Deal 1' };
            const inputs2 = { Name: 'Deal 2' };

            const token1 = element.generateConfirmationToken('create_opportunity', inputs1);
            const token2 = element.generateConfirmationToken('create_opportunity', inputs2);

            expect(token1).toBeTruthy();
            expect(token2).toBeTruthy();
            expect(token1).not.toBe(token2);
        });

        it('should include confirmation token in action request', async () => {
            callActionEndpoint.mockResolvedValue({
                success: true,
                recordIds: ['006xx1']
            });
            getCurrentUserId.mockResolvedValue('005xx000001X8UzAAK');

            const element = createElement('c-ascendix-ai-search', {
                is: AscendixAiSearch
            });
            document.body.appendChild(element);

            await flushPromises();

            const actionData = {
                actionName: 'update_opportunity_stage',
                inputs: {
                    OpportunityId: '006xx1',
                    StageName: 'Closed Won'
                }
            };

            element.showActionPreviewModal(actionData);

            // Confirm action
            const confirmButton = element.shadowRoot.querySelector('lightning-button[label="Confirm"]');
            confirmButton.click();

            await flushPromises();

            // Verify confirmation token was sent
            expect(callActionEndpoint).toHaveBeenCalled();
            const requestBody = JSON.parse(callActionEndpoint.mock.calls[0][0].requestBodyJson);
            expect(requestBody.confirmationToken).toMatch(/^token_\d+_\d+$/);
        });

        it('should disable confirm button while action is executing', async () => {
            // Mock delayed response
            callActionEndpoint.mockImplementation(() =>
                new Promise(resolve => setTimeout(() => resolve({
                    success: true,
                    recordIds: ['006xx1']
                }), 100))
            );
            getCurrentUserId.mockResolvedValue('005xx000001X8UzAAK');

            const element = createElement('c-ascendix-ai-search', {
                is: AscendixAiSearch
            });
            document.body.appendChild(element);

            await flushPromises();

            const actionData = {
                actionName: 'create_opportunity',
                inputs: { Name: 'Test' }
            };

            element.showActionPreviewModal(actionData);

            // Click confirm
            const confirmButton = element.shadowRoot.querySelector('lightning-button[label="Confirm"]');
            confirmButton.click();

            await flushPromises();

            // Verify button is disabled during execution
            expect(element.isExecutingAction).toBe(true);

            // Wait for completion
            await new Promise(resolve => setTimeout(resolve, 150));

            // Verify execution completed
            expect(element.isExecutingAction).toBe(false);
        });
    });

    describe('Action Error Handling', () => {
        let callActionEndpoint;

        beforeEach(() => {
            callActionEndpoint = require('@salesforce/apex/AscendixAISearchController.callActionEndpoint').default;
        });

        it('should display rate limit error', async () => {
            const rateLimitError = new Error('Rate limit exceeded: You have reached the daily limit of 20 for this action');
            callActionEndpoint.mockRejectedValue(rateLimitError);
            getCurrentUserId.mockResolvedValue('005xx000001X8UzAAK');

            const element = createElement('c-ascendix-ai-search', {
                is: AscendixAiSearch
            });
            document.body.appendChild(element);

            await flushPromises();

            const actionData = {
                actionName: 'create_opportunity',
                inputs: { Name: 'Test' }
            };

            element.showActionPreviewModal(actionData);

            // Mock toast handler
            const toastHandler = jest.fn();
            element.addEventListener(ShowToastEventName, toastHandler);

            // Confirm action
            const confirmButton = element.shadowRoot.querySelector('lightning-button[label="Confirm"]');
            confirmButton.click();

            await flushPromises();

            // Verify error toast
            expect(toastHandler).toHaveBeenCalled();
            const toastEvent = toastHandler.mock.calls[0][0];
            expect(toastEvent.detail.title).toBe('Rate Limit Exceeded');
            expect(toastEvent.detail.variant).toBe('error');
            expect(toastEvent.detail.message).toContain('daily limit');

            // Verify modal stays open on error
            expect(element.showActionPreview).toBe(true);
        });

        it('should display disabled action error', async () => {
            const disabledError = new Error('Action temporarily unavailable: This action is disabled');
            callActionEndpoint.mockRejectedValue(disabledError);
            getCurrentUserId.mockResolvedValue('005xx000001X8UzAAK');

            const element = createElement('c-ascendix-ai-search', {
                is: AscendixAiSearch
            });
            document.body.appendChild(element);

            await flushPromises();

            const actionData = {
                actionName: 'create_opportunity',
                inputs: { Name: 'Test' }
            };

            element.showActionPreviewModal(actionData);

            const toastHandler = jest.fn();
            element.addEventListener(ShowToastEventName, toastHandler);

            // Confirm action
            const confirmButton = element.shadowRoot.querySelector('lightning-button[label="Confirm"]');
            confirmButton.click();

            await flushPromises();

            // Verify error toast
            expect(toastHandler).toHaveBeenCalled();
            const toastEvent = toastHandler.mock.calls[0][0];
            expect(toastEvent.detail.title).toBe('Action Unavailable');
            expect(toastEvent.detail.message).toContain('temporarily unavailable');
        });

        it('should display validation error', async () => {
            const validationError = new Error('Validation error: Required field Name is missing');
            callActionEndpoint.mockRejectedValue(validationError);
            getCurrentUserId.mockResolvedValue('005xx000001X8UzAAK');

            const element = createElement('c-ascendix-ai-search', {
                is: AscendixAiSearch
            });
            document.body.appendChild(element);

            await flushPromises();

            const actionData = {
                actionName: 'create_opportunity',
                inputs: { Amount: 500000 }
            };

            element.showActionPreviewModal(actionData);

            const toastHandler = jest.fn();
            element.addEventListener(ShowToastEventName, toastHandler);

            // Confirm action
            const confirmButton = element.shadowRoot.querySelector('lightning-button[label="Confirm"]');
            confirmButton.click();

            await flushPromises();

            // Verify error toast
            expect(toastHandler).toHaveBeenCalled();
            const toastEvent = toastHandler.mock.calls[0][0];
            expect(toastEvent.detail.title).toBe('Validation Error');
            expect(toastEvent.detail.message).toContain('Required field');
        });

        it('should display permission denied error', async () => {
            const permissionError = new Error('Permission denied: You do not have access to create opportunities');
            callActionEndpoint.mockRejectedValue(permissionError);
            getCurrentUserId.mockResolvedValue('005xx000001X8UzAAK');

            const element = createElement('c-ascendix-ai-search', {
                is: AscendixAiSearch
            });
            document.body.appendChild(element);

            await flushPromises();

            const actionData = {
                actionName: 'create_opportunity',
                inputs: { Name: 'Test' }
            };

            element.showActionPreviewModal(actionData);

            const toastHandler = jest.fn();
            element.addEventListener(ShowToastEventName, toastHandler);

            // Confirm action
            const confirmButton = element.shadowRoot.querySelector('lightning-button[label="Confirm"]');
            confirmButton.click();

            await flushPromises();

            // Verify error toast
            expect(toastHandler).toHaveBeenCalled();
            const toastEvent = toastHandler.mock.calls[0][0];
            expect(toastEvent.detail.title).toBe('Permission Denied');
            expect(toastEvent.detail.message).toContain('permission');
        });

        it('should handle timeout error with retry option', async () => {
            const timeoutError = new Error('Timeout: The action took too long to execute');
            callActionEndpoint.mockRejectedValue(timeoutError);
            getCurrentUserId.mockResolvedValue('005xx000001X8UzAAK');

            const element = createElement('c-ascendix-ai-search', {
                is: AscendixAiSearch
            });
            document.body.appendChild(element);

            await flushPromises();

            const actionData = {
                actionName: 'create_opportunity',
                inputs: { Name: 'Test' }
            };

            element.showActionPreviewModal(actionData);

            const toastHandler = jest.fn();
            element.addEventListener(ShowToastEventName, toastHandler);

            // Confirm action
            const confirmButton = element.shadowRoot.querySelector('lightning-button[label="Confirm"]');
            confirmButton.click();

            await flushPromises();

            // Verify error toast
            expect(toastHandler).toHaveBeenCalled();
            const toastEvent = toastHandler.mock.calls[0][0];
            expect(toastEvent.detail.title).toBe('Timeout');
            expect(toastEvent.detail.message).toContain('took too long');

            // Modal should stay open for retry
            expect(element.showActionPreview).toBe(true);
        });
    });

    describe('Action Result Navigation', () => {
        let callActionEndpoint;

        beforeEach(() => {
            callActionEndpoint = require('@salesforce/apex/AscendixAISearchController.callActionEndpoint').default;
        });

        it('should navigate to created record after successful action', async () => {
            const mockResponse = {
                success: true,
                recordIds: ['006xx000001X8UzAAK']
            };
            callActionEndpoint.mockResolvedValue(mockResponse);
            getCurrentUserId.mockResolvedValue('005xx000001X8UzAAK');

            const element = createElement('c-ascendix-ai-search', {
                is: AscendixAiSearch
            });
            document.body.appendChild(element);

            await flushPromises();

            // Mock NavigationMixin
            const navigateSpy = jest.fn();
            element[NavigationMixin.Navigate] = navigateSpy;

            const actionData = {
                actionName: 'create_opportunity',
                inputs: { Name: 'Test Deal' }
            };

            element.showActionPreviewModal(actionData);

            // Confirm action
            const confirmButton = element.shadowRoot.querySelector('lightning-button[label="Confirm"]');
            confirmButton.click();

            await flushPromises();

            // Wait for navigation delay
            await new Promise(resolve => setTimeout(resolve, 1600));

            // Verify navigation was called
            expect(navigateSpy).toHaveBeenCalledWith({
                type: 'standard__recordPage',
                attributes: {
                    recordId: '006xx000001X8UzAAK',
                    actionName: 'view'
                }
            });
        });

        it('should display success toast with record ID', async () => {
            const mockResponse = {
                success: true,
                recordIds: ['006xx000001X8UzAAK']
            };
            callActionEndpoint.mockResolvedValue(mockResponse);
            getCurrentUserId.mockResolvedValue('005xx000001X8UzAAK');

            const element = createElement('c-ascendix-ai-search', {
                is: AscendixAiSearch
            });
            document.body.appendChild(element);

            await flushPromises();

            const actionData = {
                actionName: 'create_opportunity',
                inputs: { Name: 'Test Deal' }
            };

            element.showActionPreviewModal(actionData);

            const toastHandler = jest.fn();
            element.addEventListener(ShowToastEventName, toastHandler);

            // Confirm action
            const confirmButton = element.shadowRoot.querySelector('lightning-button[label="Confirm"]');
            confirmButton.click();

            await flushPromises();

            // Verify success toast
            expect(toastHandler).toHaveBeenCalled();
            const toastEvent = toastHandler.mock.calls[0][0];
            expect(toastEvent.detail.title).toBe('Action Completed');
            expect(toastEvent.detail.message).toContain('006xx000001X8UzAAK');
            expect(toastEvent.detail.variant).toBe('success');
        });

        it('should handle multiple record IDs in response', async () => {
            const mockResponse = {
                success: true,
                recordIds: ['006xx1', '006xx2', '006xx3']
            };
            callActionEndpoint.mockResolvedValue(mockResponse);
            getCurrentUserId.mockResolvedValue('005xx000001X8UzAAK');

            const element = createElement('c-ascendix-ai-search', {
                is: AscendixAiSearch
            });
            document.body.appendChild(element);

            await flushPromises();

            const actionData = {
                actionName: 'create_opportunity',
                inputs: { Name: 'Test' }
            };

            element.showActionPreviewModal(actionData);

            const toastHandler = jest.fn();
            element.addEventListener(ShowToastEventName, toastHandler);

            // Confirm action
            const confirmButton = element.shadowRoot.querySelector('lightning-button[label="Confirm"]');
            confirmButton.click();

            await flushPromises();

            // Verify success toast
            expect(toastHandler).toHaveBeenCalled();
            const toastEvent = toastHandler.mock.calls[0][0];
            expect(toastEvent.detail.variant).toBe('success');

            // Verify record IDs are stored
            expect(element.actionResultRecordIds).toEqual(['006xx1', '006xx2', '006xx3']);
        });

        it('should not navigate when multiple records are created', async () => {
            const mockResponse = {
                success: true,
                recordIds: ['006xx1', '006xx2']
            };
            callActionEndpoint.mockResolvedValue(mockResponse);
            getCurrentUserId.mockResolvedValue('005xx000001X8UzAAK');

            const element = createElement('c-ascendix-ai-search', {
                is: AscendixAiSearch
            });
            document.body.appendChild(element);

            await flushPromises();

            // Mock NavigationMixin
            const navigateSpy = jest.fn();
            element[NavigationMixin.Navigate] = navigateSpy;

            const actionData = {
                actionName: 'create_opportunity',
                inputs: { Name: 'Test' }
            };

            element.showActionPreviewModal(actionData);

            // Confirm action
            const confirmButton = element.shadowRoot.querySelector('lightning-button[label="Confirm"]');
            confirmButton.click();

            await flushPromises();
            await new Promise(resolve => setTimeout(resolve, 1600));

            // Verify navigation was NOT called (multiple records)
            expect(navigateSpy).not.toHaveBeenCalled();
        });
    });

    // Phase 3: Relationship Path Display Tests (Task 12)
    describe('Relationship Path Display', () => {
        it('should display relationship path when citation has path data', async () => {
            const mockResponse = {
                answer: 'Found properties with expiring leases.',
                citations: [
                    {
                        id: 'citation-1',
                        recordId: '006xx1',
                        title: 'ACME Property',
                        sobject: 'ascendix__Property__c',
                        score: 0.95,
                        snippet: 'Property with expiring lease',
                        fromGraph: true,
                        relationshipPath: [
                            { nodeId: 'a0Ixx1', type: 'ascendix__Property__c', displayName: 'ACME Property' },
                            { nodeId: 'a0Jxx1', type: 'ascendix__Lease__c', displayName: 'Lease 2024-001' },
                            { nodeId: 'a0Kxx1', type: 'Account', displayName: 'Tenant Corp' }
                        ]
                    }
                ]
            };
            callAnswerEndpoint.mockResolvedValue(mockResponse);
            getCurrentUserId.mockResolvedValue('005xx000001X8UzAAK');

            const element = createElement('c-ascendix-ai-search', {
                is: AscendixAiSearch
            });
            document.body.appendChild(element);

            await flushPromises();

            // Submit query
            const textarea = element.shadowRoot.querySelector('lightning-textarea');
            textarea.value = 'Properties with expiring leases';
            textarea.dispatchEvent(new CustomEvent('change', {
                detail: { value: 'Properties with expiring leases' }
            }));

            await flushPromises();

            const submitButton = element.shadowRoot.querySelector('.submit-button');
            submitButton.click();

            await flushPromises();
            await new Promise(resolve => setTimeout(resolve, 100));

            // Open citations drawer
            const citationsButton = element.shadowRoot.querySelector('lightning-button[label*="View Citations"]');
            if (citationsButton) {
                citationsButton.click();
                await flushPromises();

                // Verify relationship path is displayed
                const relationshipPath = element.shadowRoot.querySelector('.relationship-path');
                expect(relationshipPath).toBeTruthy();

                // Verify path nodes are displayed
                const pathNodes = element.shadowRoot.querySelectorAll('.path-node-link');
                expect(pathNodes.length).toBe(3);

                // Verify arrows are displayed between nodes
                const arrows = element.shadowRoot.querySelectorAll('.path-arrow');
                expect(arrows.length).toBe(2);
            }
        });

        it('should not display relationship path when citation has no path data', async () => {
            const mockResponse = {
                answer: 'Found opportunities.',
                citations: [
                    {
                        id: 'citation-1',
                        recordId: '006xx1',
                        title: 'Test Opportunity',
                        sobject: 'Opportunity',
                        score: 0.9,
                        snippet: 'Test snippet'
                        // No relationshipPath
                    }
                ]
            };
            callAnswerEndpoint.mockResolvedValue(mockResponse);
            getCurrentUserId.mockResolvedValue('005xx000001X8UzAAK');

            const element = createElement('c-ascendix-ai-search', {
                is: AscendixAiSearch
            });
            document.body.appendChild(element);

            await flushPromises();

            // Submit query
            const textarea = element.shadowRoot.querySelector('lightning-textarea');
            textarea.value = 'Show opportunities';
            textarea.dispatchEvent(new CustomEvent('change', {
                detail: { value: 'Show opportunities' }
            }));

            await flushPromises();

            const submitButton = element.shadowRoot.querySelector('.submit-button');
            submitButton.click();

            await flushPromises();
            await new Promise(resolve => setTimeout(resolve, 100));

            // Open citations drawer
            const citationsButton = element.shadowRoot.querySelector('lightning-button[label*="View Citations"]');
            if (citationsButton) {
                citationsButton.click();
                await flushPromises();

                // Verify relationship path is NOT displayed
                const relationshipPath = element.shadowRoot.querySelector('.relationship-path');
                expect(relationshipPath).toBeFalsy();
            }
        });

        it('should display graph indicator for citations from graph traversal', async () => {
            const mockResponse = {
                answer: 'Found related records.',
                citations: [
                    {
                        id: 'citation-1',
                        recordId: '006xx1',
                        title: 'Graph Result',
                        sobject: 'Account',
                        score: 0.88,
                        snippet: 'Found via graph',
                        fromGraph: true
                    }
                ]
            };
            callAnswerEndpoint.mockResolvedValue(mockResponse);
            getCurrentUserId.mockResolvedValue('005xx000001X8UzAAK');

            const element = createElement('c-ascendix-ai-search', {
                is: AscendixAiSearch
            });
            document.body.appendChild(element);

            await flushPromises();

            // Submit query
            const textarea = element.shadowRoot.querySelector('lightning-textarea');
            textarea.value = 'Related accounts';
            textarea.dispatchEvent(new CustomEvent('change', {
                detail: { value: 'Related accounts' }
            }));

            await flushPromises();

            const submitButton = element.shadowRoot.querySelector('.submit-button');
            submitButton.click();

            await flushPromises();
            await new Promise(resolve => setTimeout(resolve, 100));

            // Open citations drawer
            const citationsButton = element.shadowRoot.querySelector('lightning-button[label*="View Citations"]');
            if (citationsButton) {
                citationsButton.click();
                await flushPromises();

                // Verify graph indicator is displayed
                const graphIndicator = element.shadowRoot.querySelector('.graph-indicator');
                expect(graphIndicator).toBeTruthy();
            }
        });

        it('should display relationship context summary when graph results exist', async () => {
            const mockResponse = {
                answer: 'Found properties with related leases.',
                citations: [
                    {
                        id: 'citation-1',
                        recordId: 'a0Ixx1',
                        title: 'Property A',
                        sobject: 'ascendix__Property__c',
                        score: 0.95,
                        snippet: 'Property with lease',
                        fromGraph: true
                    },
                    {
                        id: 'citation-2',
                        recordId: 'a0Jxx1',
                        title: 'Lease 001',
                        sobject: 'ascendix__Lease__c',
                        score: 0.90,
                        snippet: 'Related lease',
                        fromGraph: true
                    }
                ]
            };
            callAnswerEndpoint.mockResolvedValue(mockResponse);
            getCurrentUserId.mockResolvedValue('005xx000001X8UzAAK');

            const element = createElement('c-ascendix-ai-search', {
                is: AscendixAiSearch
            });
            document.body.appendChild(element);

            await flushPromises();

            // Submit query
            const textarea = element.shadowRoot.querySelector('lightning-textarea');
            textarea.value = 'Properties with leases';
            textarea.dispatchEvent(new CustomEvent('change', {
                detail: { value: 'Properties with leases' }
            }));

            await flushPromises();

            const submitButton = element.shadowRoot.querySelector('.submit-button');
            submitButton.click();

            await flushPromises();
            await new Promise(resolve => setTimeout(resolve, 100));

            // Verify relationship context is displayed
            const relationshipContext = element.shadowRoot.querySelector('.relationship-context');
            expect(relationshipContext).toBeTruthy();

            // Verify summary message
            const summaryMessage = element.shadowRoot.querySelector('.relationship-summary');
            expect(summaryMessage).toBeTruthy();
        });

        it('should truncate long path node names in display', async () => {
            const longName = 'This is a very long property name that exceeds the limit';
            const mockResponse = {
                answer: 'Found properties.',
                citations: [
                    {
                        id: 'citation-1',
                        recordId: 'a0Ixx1',
                        title: 'Test Property',
                        sobject: 'ascendix__Property__c',
                        score: 0.95,
                        snippet: 'Test',
                        fromGraph: true,
                        relationshipPath: [
                            { nodeId: 'a0Ixx1', type: 'ascendix__Property__c', displayName: longName }
                        ]
                    }
                ]
            };
            callAnswerEndpoint.mockResolvedValue(mockResponse);
            getCurrentUserId.mockResolvedValue('005xx000001X8UzAAK');

            const element = createElement('c-ascendix-ai-search', {
                is: AscendixAiSearch
            });
            document.body.appendChild(element);

            await flushPromises();

            // Submit query
            const textarea = element.shadowRoot.querySelector('lightning-textarea');
            textarea.value = 'Test query';
            textarea.dispatchEvent(new CustomEvent('change', {
                detail: { value: 'Test query' }
            }));

            await flushPromises();

            const submitButton = element.shadowRoot.querySelector('.submit-button');
            submitButton.click();

            await flushPromises();
            await new Promise(resolve => setTimeout(resolve, 100));

            // Open citations drawer to verify truncation in rendered output
            const citationsButton = element.shadowRoot.querySelector('lightning-button[label*="View Citations"]');
            if (citationsButton) {
                citationsButton.click();
                await flushPromises();

                // Verify path node text is truncated (contains ellipsis or is short)
                const pathNode = element.shadowRoot.querySelector('.path-node-link');
                if (pathNode) {
                    const displayText = pathNode.textContent;
                    expect(displayText.length).toBeLessThanOrEqual(25);
                }
            }
        });

        it('should handle path node click and navigate to record', async () => {
            const mockResponse = {
                answer: 'Found properties.',
                citations: [
                    {
                        id: 'citation-1',
                        recordId: 'a0Ixx1',
                        title: 'Test Property',
                        sobject: 'ascendix__Property__c',
                        score: 0.95,
                        snippet: 'Test',
                        fromGraph: true,
                        relationshipPath: [
                            { nodeId: 'a0Ixx1', type: 'ascendix__Property__c', displayName: 'Property A' },
                            { nodeId: 'a0Jxx1', type: 'ascendix__Lease__c', displayName: 'Lease 001' }
                        ]
                    }
                ]
            };
            callAnswerEndpoint.mockResolvedValue(mockResponse);
            getCurrentUserId.mockResolvedValue('005xx000001X8UzAAK');

            const element = createElement('c-ascendix-ai-search', {
                is: AscendixAiSearch
            });
            
            // Mock navigation
            const navigateSpy = jest.fn();
            element[NavigationMixin.Navigate] = navigateSpy;
            
            document.body.appendChild(element);

            await flushPromises();

            // Submit query
            const textarea = element.shadowRoot.querySelector('lightning-textarea');
            textarea.value = 'Properties with leases';
            textarea.dispatchEvent(new CustomEvent('change', {
                detail: { value: 'Properties with leases' }
            }));

            await flushPromises();

            const submitButton = element.shadowRoot.querySelector('.submit-button');
            submitButton.click();

            await flushPromises();
            await new Promise(resolve => setTimeout(resolve, 100));

            // Open citations drawer
            const citationsButton = element.shadowRoot.querySelector('lightning-button[label*="View Citations"]');
            if (citationsButton) {
                citationsButton.click();
                await flushPromises();

                // Click on a path node
                const pathNode = element.shadowRoot.querySelector('.path-node-link');
                if (pathNode) {
                    pathNode.click();
                    await flushPromises();

                    // Verify navigation was called
                    expect(navigateSpy).toHaveBeenCalledWith({
                        type: 'standard__recordPage',
                        attributes: {
                            recordId: expect.any(String),
                            actionName: 'view'
                        }
                    });
                }
            }
        });
    });

    // Task 4.12.4: Answer Formatting Tests
    describe('Answer Formatting', () => {
        async function createComponentAndSetAnswer(answerText) {
            const element = createElement('c-ascendix-ai-search', {
                is: AscendixAiSearch
            });
            document.body.appendChild(element);
            element.answer = answerText;
            await flushPromises();
            return element;
        }

        it('should convert markdown headers to HTML', async () => {
            const element = await createComponentAndSetAnswer('## Main Title\n### Sub Title');
            const html = element.formattedAnswer;
            expect(html).toContain('<h3>Main Title</h3>');
            expect(html).toContain('<h4>Sub Title</h4>');
        });

        it('should convert bullet lists to ul/li', async () => {
            const element = await createComponentAndSetAnswer('- Item A\n- Item B\n- Item C');
            const html = element.formattedAnswer;
            expect(html).toContain('<ul>');
            expect(html).toContain('<li>Item A</li>');
            expect(html).toContain('<li>Item B</li>');
            expect(html).toContain('<li>Item C</li>');
            expect(html).toContain('</ul>');
        });

        it('should convert numbered lists to ol/li', async () => {
            const element = await createComponentAndSetAnswer('1. First\n2. Second\n3. Third');
            const html = element.formattedAnswer;
            expect(html).toContain('<ol>');
            expect(html).toContain('<li>First</li>');
            expect(html).toContain('<li>Second</li>');
            expect(html).toContain('</ol>');
        });

        it('should handle mixed list types', async () => {
            const element = await createComponentAndSetAnswer('1. First\n2. Second\n\n- Bullet A\n- Bullet B');
            const html = element.formattedAnswer;
            expect(html).toContain('<ol>');
            expect(html).toContain('</ol>');
            expect(html).toContain('<ul>');
            expect(html).toContain('</ul>');
        });

        it('should convert markdown tables to HTML tables', async () => {
            const tableText = '| Name | City |\n|---|---|\n| Tower One | Dallas |\n| Park Place | Austin |';
            const element = await createComponentAndSetAnswer(tableText);
            const html = element.formattedAnswer;
            expect(html).toContain('<table>');
            expect(html).toContain('<thead>');
            expect(html).toContain('<th>Name</th>');
            expect(html).toContain('<th>City</th>');
            expect(html).toContain('<tbody>');
            expect(html).toContain('<td>Tower One</td>');
            expect(html).toContain('<td>Dallas</td>');
            expect(html).toContain('</table>');
        });

        it('should fall back gracefully for invalid table-like text', async () => {
            const notATable = 'This has a | pipe but is not a table';
            const element = await createComponentAndSetAnswer(notATable);
            const html = element.formattedAnswer;
            expect(html).not.toContain('<table>');
            expect(html).toContain('pipe');
        });

        it('should wrap plain text in paragraphs', async () => {
            const element = await createComponentAndSetAnswer('First paragraph.\n\nSecond paragraph.');
            const html = element.formattedAnswer;
            expect(html).toContain('<p>First paragraph.</p>');
            expect(html).toContain('<p>Second paragraph.</p>');
        });

        it('should not double-wrap block elements in paragraphs', async () => {
            const element = await createComponentAndSetAnswer('## Header\n\nSome text.');
            const html = element.formattedAnswer;
            // Header should not be inside a <p> tag
            expect(html).not.toContain('<p><h3>');
            expect(html).toContain('<h3>Header</h3>');
        });

        it('should preserve bold and italic formatting', async () => {
            const element = await createComponentAndSetAnswer('This is **bold** and *italic* text.');
            const html = element.formattedAnswer;
            expect(html).toContain('<strong>bold</strong>');
            expect(html).toContain('<em>italic</em>');
        });

        it('should preserve citation hyperlinks in formatted answer', async () => {
            const element = createElement('c-ascendix-ai-search', {
                is: AscendixAiSearch
            });
            document.body.appendChild(element);

            // Set citations first so hyperlink map builds
            element.citations = [{
                id: 'a0x1',
                title: 'Tower One',
                recordId: 'a0x1',
                sobject: 'Property'
            }];
            element.answer = 'The property Tower One is in Dallas.';
            await flushPromises();

            const html = element.formattedAnswer;
            expect(html).toContain('Tower One');
            // Should contain an anchor tag for the record
            expect(html).toContain('<a href=');
        });
    });

    // Task 4.13.1f: Clarification UX Tests
    describe('Clarification Options', () => {
        it('should display clarification pills when options are present', async () => {
            const mockResponse = {
                answer: 'Which metric did you mean?',
                citations: [],
                clarificationOptions: [
                    { label: 'By deal count', query: 'Top 5 markets by deal count' },
                    { label: 'By revenue', query: 'Top 5 markets by revenue' }
                ]
            };
            callAnswerEndpoint.mockResolvedValue(mockResponse);
            getCurrentUserId.mockResolvedValue('005xx000001X8UzAAK');

            const element = createElement('c-ascendix-ai-search', {
                is: AscendixAiSearch
            });
            document.body.appendChild(element);

            await flushPromises();

            const textarea = element.shadowRoot.querySelector('lightning-textarea');
            textarea.value = 'Top markets';
            textarea.dispatchEvent(new CustomEvent('change', {
                detail: { value: 'Top markets' }
            }));

            await flushPromises();

            const submitButton = element.shadowRoot.querySelector('.submit-button');
            submitButton.click();

            await flushPromises();
            await new Promise(resolve => setTimeout(resolve, 100));

            // Verify clarification options are set
            const pills = element.shadowRoot.querySelectorAll('.clarification-options lightning-button');
            expect(pills).toHaveLength(2);
            expect(pills[0].label).toBe('By deal count');
        });

        it('should clear clarification options on new submit', async () => {
            const element = createElement('c-ascendix-ai-search', {
                is: AscendixAiSearch
            });
            document.body.appendChild(element);

            // Set initial clarification options
            element.clarificationOptions = [
                { key: 'c-0', label: 'Option A', query: 'query A' }
            ];

            callAnswerEndpoint.mockResolvedValue({
                answer: 'Direct answer',
                citations: []
            });
            getCurrentUserId.mockResolvedValue('005xx000001X8UzAAK');

            await flushPromises();

            const textarea = element.shadowRoot.querySelector('lightning-textarea');
            textarea.value = 'New query';
            textarea.dispatchEvent(new CustomEvent('change', {
                detail: { value: 'New query' }
            }));

            await flushPromises();

            const submitButton = element.shadowRoot.querySelector('.submit-button');
            submitButton.click();

            await flushPromises();

            // Clarification options should be cleared
            expect(element.shadowRoot.querySelector('.clarification-options')).toBeFalsy();
        });

        it('should resubmit with clarification query on pill click', async () => {
            callAnswerEndpoint
                .mockResolvedValueOnce({
                    answer: 'Which metric did you mean?',
                    citations: [],
                    clarificationOptions: [
                        { label: 'By deal count', query: 'Top 5 markets by deal count' },
                        { label: 'By revenue', query: 'Top 5 markets by revenue' }
                    ]
                })
                .mockResolvedValueOnce({
                    answer: 'Here are the top 5 markets by deal count.',
                    citations: []
                });
            getCurrentUserId.mockResolvedValue('005xx000001X8UzAAK');

            const element = createElement('c-ascendix-ai-search', {
                is: AscendixAiSearch
            });
            document.body.appendChild(element);

            await flushPromises();

            const textarea = element.shadowRoot.querySelector('lightning-textarea');
            textarea.value = 'Top markets';
            textarea.dispatchEvent(new CustomEvent('change', {
                detail: { value: 'Top markets' }
            }));

            await flushPromises();

            const submitButton = element.shadowRoot.querySelector('.submit-button');
            submitButton.click();

            await flushPromises();
            await new Promise(resolve => setTimeout(resolve, 100));

            expect(callAnswerEndpoint).toHaveBeenCalledTimes(1);
            const clarifyButtons = element.shadowRoot.querySelectorAll('.clarification-options lightning-button');
            expect(clarifyButtons).toHaveLength(2);

            clarifyButtons[0].dispatchEvent(new CustomEvent('click', { bubbles: true }));

            await flushPromises();
            await new Promise(resolve => setTimeout(resolve, 100));

            expect(callAnswerEndpoint).toHaveBeenCalledTimes(2);
            const callArgs = callAnswerEndpoint.mock.calls[1][0];
            const payload = JSON.parse(callArgs.requestBodyJson);
            expect(payload.query).toBe('Top 5 markets by deal count');
            expect(payload.priorContext).toEqual({
                query: 'Top markets',
                answer: 'Which metric did you mean?'
            });
            expect(payload.conversationHistory).toBeUndefined();
        });
    });

    describe('Record Page Conversation History', () => {
        it('should accumulate history, render a thread, and send conversationHistory on follow-up', async () => {
            callAnswerEndpoint
                .mockResolvedValueOnce({
                    answer: 'The property has two active leases.',
                    citations: [],
                    clarificationOptions: [
                        { label: 'Compare rent rates', query: 'Compare their rent rates.' }
                    ]
                })
                .mockResolvedValueOnce({
                    answer: 'The first lease is priced higher than the second.',
                    citations: []
                });
            getCurrentUserId.mockResolvedValue('005xx000001X8UzAAK');

            const element = createSearchComponent('001xx0000000001AAA');
            await flushPromises();

            const textarea = element.shadowRoot.querySelector('lightning-textarea');
            textarea.value = 'Tell me about this record';
            textarea.dispatchEvent(new CustomEvent('change', {
                detail: { value: 'Tell me about this record' }
            }));

            await flushPromises();
            element.shadowRoot.querySelector('.submit-button').click();

            await flushPromises();
            await new Promise(resolve => setTimeout(resolve, 100));

            let thread = element.shadowRoot.querySelector('.conversation-thread');
            expect(thread).toBeTruthy();
            expect(thread.textContent).toContain('Tell me about this record');
            expect(thread.textContent).toContain('The property has two active leases.');

            const clarifyButton = element.shadowRoot.querySelector('.clarification-options lightning-button');
            expect(clarifyButton).toBeTruthy();
            clarifyButton.dispatchEvent(new CustomEvent('click', { bubbles: true }));

            await flushPromises();
            await new Promise(resolve => setTimeout(resolve, 100));

            expect(callAnswerEndpoint).toHaveBeenCalledTimes(2);
            const secondCallArgs = callAnswerEndpoint.mock.calls[1][0];
            const secondPayload = JSON.parse(secondCallArgs.requestBodyJson);
            expect(secondPayload.conversationHistory).toEqual([
                {
                    query: 'Tell me about this record',
                    answer: 'The property has two active leases.'
                }
            ]);
            expect(secondPayload.priorContext).toBeUndefined();
            thread = element.shadowRoot.querySelector('.conversation-thread');
            expect(thread.textContent).toContain('Compare their rent rates.');
            expect(thread.textContent).toContain('The first lease is priced higher than the second.');
        });

        it('should preserve prior history when a record-page request fails', async () => {
            callAnswerEndpoint
                .mockResolvedValueOnce({
                    answer: 'The record has one active lease.',
                    citations: []
                })
                .mockRejectedValueOnce(new Error('Request timed out after 29s'));
            getCurrentUserId.mockResolvedValue('005xx000001X8UzAAK');

            const element = createSearchComponent('001xx0000000002BBB');
            await flushPromises();

            const textarea = element.shadowRoot.querySelector('lightning-textarea');
            textarea.value = 'Tell me about this record';
            textarea.dispatchEvent(new CustomEvent('change', {
                detail: { value: 'Tell me about this record' }
            }));

            await flushPromises();
            element.shadowRoot.querySelector('.submit-button').click();

            await flushPromises();
            await new Promise(resolve => setTimeout(resolve, 100));

            textarea.value = 'What about the second lease?';
            textarea.dispatchEvent(new CustomEvent('change', {
                detail: { value: 'What about the second lease?' }
            }));

            await flushPromises();
            element.shadowRoot.querySelector('.submit-button').click();

            await flushPromises();
            await new Promise(resolve => setTimeout(resolve, 100));

            const secondCallArgs = callAnswerEndpoint.mock.calls[1][0];
            const secondPayload = JSON.parse(secondCallArgs.requestBodyJson);
            expect(secondPayload.conversationHistory).toEqual([
                {
                    query: 'Tell me about this record',
                    answer: 'The record has one active lease.'
                }
            ]);
            expect(element.shadowRoot.querySelector('.conversation-thread')).toBeTruthy();
            const errorMessage = element.shadowRoot.querySelector('.error-message');
            expect(errorMessage).toBeTruthy();
            expect(errorMessage.textContent).toContain('Please try again');
            expect(element.shadowRoot.querySelector('lightning-button[label="Retry"]')).toBeTruthy();
        });

        it('should clear record-page history and session state when the recordId changes', async () => {
            callAnswerEndpoint.mockResolvedValue({
                answer: 'The record has an active lease.',
                citations: []
            });
            getCurrentUserId.mockResolvedValue('005xx000001X8UzAAK');

            const element = createSearchComponent('001xx0000000001AAA');
            await flushPromises();

            const textarea = element.shadowRoot.querySelector('lightning-textarea');
            textarea.value = 'Tell me about this record';
            textarea.dispatchEvent(new CustomEvent('change', {
                detail: { value: 'Tell me about this record' }
            }));

            await flushPromises();
            element.shadowRoot.querySelector('.submit-button').click();

            await flushPromises();
            await new Promise(resolve => setTimeout(resolve, 100));

            const firstPayload = JSON.parse(callAnswerEndpoint.mock.calls[0][0].requestBodyJson);

            element.recordId = '001xx0000000002BBB';
            await flushPromises();

            expect(element.shadowRoot.querySelector('.conversation-thread')).toBeFalsy();
            expect(element.shadowRoot.querySelector('[data-id="answer-display"]')).toBeFalsy();
            expect(textarea.value).toBe('');

            textarea.value = 'Tell me about the new record';
            textarea.dispatchEvent(new CustomEvent('change', {
                detail: { value: 'Tell me about the new record' }
            }));

            await flushPromises();
            element.shadowRoot.querySelector('.submit-button').click();

            await flushPromises();
            await new Promise(resolve => setTimeout(resolve, 100));

            const secondPayload = JSON.parse(callAnswerEndpoint.mock.calls[1][0].requestBodyJson);
            expect(secondPayload.sessionId).toBeTruthy();
            expect(secondPayload.sessionId).not.toBe(firstPayload.sessionId);
            expect(secondPayload.conversationHistory).toBeUndefined();
        });

        it('should clear record-page history when Clear Chat is clicked', async () => {
            callAnswerEndpoint.mockResolvedValue({
                answer: 'The record has an active lease.',
                citations: []
            });
            getCurrentUserId.mockResolvedValue('005xx000001X8UzAAK');

            const element = createSearchComponent('001xx0000000003CCC');
            await flushPromises();

            const textarea = element.shadowRoot.querySelector('lightning-textarea');
            textarea.value = 'Tell me about this record';
            textarea.dispatchEvent(new CustomEvent('change', {
                detail: { value: 'Tell me about this record' }
            }));

            await flushPromises();
            element.shadowRoot.querySelector('.submit-button').click();

            await flushPromises();
            await new Promise(resolve => setTimeout(resolve, 100));

            const firstPayload = JSON.parse(callAnswerEndpoint.mock.calls[0][0].requestBodyJson);

            element.shadowRoot.querySelector('.conversation-thread__clear').click();
            await flushPromises();

            expect(element.shadowRoot.querySelector('.conversation-thread')).toBeFalsy();
            expect(element.shadowRoot.querySelector('[data-id="answer-display"]')).toBeFalsy();
            expect(textarea.value).toBe('');

            textarea.value = 'Start over on this record';
            textarea.dispatchEvent(new CustomEvent('change', {
                detail: { value: 'Start over on this record' }
            }));

            await flushPromises();
            element.shadowRoot.querySelector('.submit-button').click();

            await flushPromises();
            await new Promise(resolve => setTimeout(resolve, 100));

            const secondPayload = JSON.parse(callAnswerEndpoint.mock.calls[1][0].requestBodyJson);
            expect(secondPayload.sessionId).toBeTruthy();
            expect(secondPayload.sessionId).not.toBe(firstPayload.sessionId);
            expect(secondPayload.conversationHistory).toBeUndefined();
        });

        it('should ignore stale responses after the user switches records mid-request', async () => {
            const pendingResponse = createDeferred();
            callAnswerEndpoint
                .mockReturnValueOnce(pendingResponse.promise)
                .mockResolvedValueOnce({
                    answer: 'Fresh answer for the new record.',
                    citations: []
                });
            getCurrentUserId.mockResolvedValue('005xx000001X8UzAAK');

            const element = createSearchComponent('001xx0000000001AAA');
            await flushPromises();

            let textarea = element.shadowRoot.querySelector('lightning-textarea');
            textarea.value = 'Tell me about record A';
            textarea.dispatchEvent(new CustomEvent('change', {
                detail: { value: 'Tell me about record A' }
            }));

            await flushPromises();
            element.shadowRoot.querySelector('.submit-button').click();

            await flushPromises();
            element.recordId = '001xx0000000002BBB';
            await flushPromises();

            pendingResponse.resolve({
                answer: 'Stale answer from record A.',
                citations: []
            });

            await flushPromises();
            await new Promise(resolve => setTimeout(resolve, 100));

            expect(element.shadowRoot.querySelector('.conversation-thread')).toBeFalsy();
            expect(element.shadowRoot.querySelector('[data-id="answer-display"]')).toBeFalsy();

            textarea = element.shadowRoot.querySelector('lightning-textarea');
            textarea.value = 'Tell me about record B';
            textarea.dispatchEvent(new CustomEvent('change', {
                detail: { value: 'Tell me about record B' }
            }));

            await flushPromises();
            element.shadowRoot.querySelector('.submit-button').click();

            await flushPromises();
            await new Promise(resolve => setTimeout(resolve, 100));

            expect(callAnswerEndpoint).toHaveBeenCalledTimes(2);
            const payload = JSON.parse(callAnswerEndpoint.mock.calls[1][0].requestBodyJson);
            expect(payload.recordId).toBe('001xx0000000002BBB');
            expect(payload.conversationHistory).toBeUndefined();

            const thread = element.shadowRoot.querySelector('.conversation-thread');
            expect(thread).toBeTruthy();
            expect(thread.textContent).toContain('Tell me about record B');
            expect(thread.textContent).not.toContain('Stale answer from record A.');
        });

        it('should ignore stale responses after Clear Chat during an in-flight request', async () => {
            const pendingResponse = createDeferred();
            callAnswerEndpoint
                .mockResolvedValueOnce({
                    answer: 'Established answer before clearing.',
                    citations: []
                })
                .mockReturnValueOnce(pendingResponse.promise)
                .mockResolvedValueOnce({
                    answer: 'Fresh answer after clearing chat.',
                    citations: []
                });
            getCurrentUserId.mockResolvedValue('005xx000001X8UzAAK');

            const element = createSearchComponent('001xx0000000004DDD');
            await flushPromises();

            let textarea = element.shadowRoot.querySelector('lightning-textarea');
            textarea.value = 'Establish some history';
            textarea.dispatchEvent(new CustomEvent('change', {
                detail: { value: 'Establish some history' }
            }));

            await flushPromises();
            element.shadowRoot.querySelector('.submit-button').click();

            await flushPromises();
            await new Promise(resolve => setTimeout(resolve, 100));

            textarea = element.shadowRoot.querySelector('lightning-textarea');
            textarea.value = 'Start a long request';
            textarea.dispatchEvent(new CustomEvent('change', {
                detail: { value: 'Start a long request' }
            }));

            await flushPromises();
            element.shadowRoot.querySelector('.submit-button').click();

            await flushPromises();
            element.shadowRoot.querySelector('.conversation-thread__clear').click();
            await flushPromises();

            pendingResponse.resolve({
                answer: 'Stale answer from before clear.',
                citations: []
            });

            await flushPromises();
            await new Promise(resolve => setTimeout(resolve, 100));

            expect(callAnswerEndpoint).toHaveBeenCalledTimes(2);
            expect(element.shadowRoot.querySelector('.conversation-thread')).toBeFalsy();
            expect(element.shadowRoot.querySelector('[data-id="answer-display"]')).toBeFalsy();

            textarea = element.shadowRoot.querySelector('lightning-textarea');
            textarea.value = 'Start over cleanly';
            textarea.dispatchEvent(new CustomEvent('change', {
                detail: { value: 'Start over cleanly' }
            }));

            await flushPromises();
            element.shadowRoot.querySelector('.submit-button').click();

            await flushPromises();
            await new Promise(resolve => setTimeout(resolve, 100));

            const payload = JSON.parse(callAnswerEndpoint.mock.calls[2][0].requestBodyJson);
            expect(payload.conversationHistory).toBeUndefined();
            expect(element.shadowRoot.querySelector('.conversation-thread').textContent).toContain('Start over cleanly');
            expect(element.shadowRoot.querySelector('.conversation-thread').textContent).not.toContain('Stale answer from before clear.');
        });

        it('should prune record-page conversation history before sending it upstream', async () => {
            const longAnswer = 'A'.repeat(2500);
            callAnswerEndpoint.mockResolvedValue({
                answer: longAnswer,
                citations: []
            });
            getCurrentUserId.mockResolvedValue('005xx000001X8UzAAK');

            const element = createSearchComponent('001xx0000000005EEE');
            await flushPromises();

            for (let i = 0; i < 11; i += 1) {
                const textarea = element.shadowRoot.querySelector('lightning-textarea');
                textarea.value = `Question ${i}`;
                textarea.dispatchEvent(new CustomEvent('change', {
                    detail: { value: `Question ${i}` }
                }));

                await flushPromises();
                element.shadowRoot.querySelector('.submit-button').click();
                await flushPromises();
                await new Promise(resolve => setTimeout(resolve, 100));
            }

            const finalTextarea = element.shadowRoot.querySelector('lightning-textarea');
            finalTextarea.value = 'Follow-up question';
            finalTextarea.dispatchEvent(new CustomEvent('change', {
                detail: { value: 'Follow-up question' }
            }));

            await flushPromises();
            element.shadowRoot.querySelector('.submit-button').click();

            await flushPromises();
            await new Promise(resolve => setTimeout(resolve, 100));

            const payload = JSON.parse(callAnswerEndpoint.mock.calls[11][0].requestBodyJson);
            expect(Array.isArray(payload.conversationHistory)).toBe(true);
            expect(payload.conversationHistory.length).toBeLessThanOrEqual(10);
            expect(payload.conversationHistory[0].query).toBe('Question 4');
            expect(payload.conversationHistory[payload.conversationHistory.length - 1].query).toBe('Question 10');
            expect(payload.conversationHistory.every(entry => entry.answer.length === 2003)).toBe(true);
            const totalChars = payload.conversationHistory.reduce(
                (sum, entry) => sum + entry.query.length + entry.answer.length,
                0
            );
            expect(totalChars).toBeLessThanOrEqual(15000);
        });
    });
});
