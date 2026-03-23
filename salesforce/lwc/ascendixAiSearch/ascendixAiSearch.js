import { LightningElement, api, track } from 'lwc';
import { ShowToastEvent } from 'lightning/platformShowToastEvent';
import { NavigationMixin } from 'lightning/navigation';
import callAnswerEndpoint from '@salesforce/apex/AscendixAISearchController.callAnswerEndpoint';
import previewWriteProposal from '@salesforce/apex/AscendixAISearchController.previewWriteProposal';
import callActionEndpoint from '@salesforce/apex/AscendixAISearchController.callActionEndpoint';
import getCurrentUserId from '@salesforce/apex/AscendixAISearchController.getCurrentUserId';

const MAX_CONVERSATION_TURNS = 10;
const MAX_CONVERSATION_CHARS = 15000;
const MAX_CONVERSATION_QUERY_CHARS = 500;
const MAX_CONVERSATION_ANSWER_CHARS = 2000;

export default class AscendixAiSearch extends NavigationMixin(LightningElement) {

    constructor() {
        super();
        this._recordId = null;
        this.queryText = '';
        this.answer = '';
        this.citations = [];
        this.conversationHistory = [];
        this.isStreaming = false;
        this.showAnswerSection = false;
        this.showCitationsDrawer = false;
        this.showCitationPreview = false;
        this.selectedCitation = null;
        this.errorMessage = '';
        this.showRetryButton = false;
        this.clarificationOptions = [];
        this.selectedFilters = {
            region: null,
            businessUnit: null,
            quarter: null
        };
        this.showWriteProposalDiff = false;
        this.showWriteProposalForm = false;
        this.writeProposalPreviewData = null;
        this.writeProposalErrorMessage = '';
        this.writeProposalSuccessMessage = '';
        this.writeProposalSuccessRecordId = null;
        this.writeProposalSuccessRecordLabel = '';
        this.isLoadingWriteProposal = false;
        this.showActionPreview = false;
        this.actionPreviewData = null;
        this.isExecutingAction = false;
        this.actionResultMessage = '';
        this.actionResultRecordIds = [];
        this.sessionId = null;
        this.currentAbortController = null;
        this.currentUserId = null;
        this.streamingChunkBuffer = '';
        this.lastRequestBody = null;
        this.lastExchange = null;
        this._pendingPriorContext = null;
        this.selectedModelId = '';
        this.lastModelUsed = '';
    }

    _recordId = null;
    @track queryText = '';
    @api answer = '';
    @track citations = [];
    @track conversationHistory = [];
    @track isStreaming = false;
    @track showAnswerSection = false;
    @track showCitationsDrawer = false;
    @track showCitationPreview = false;
    @track selectedCitation = null;
    @track errorMessage = '';
    @track showRetryButton = false;
    @track clarificationOptions = [];
    @track selectedFilters = {
        region: null,
        businessUnit: null,
        quarter: null
    };
    showWriteProposalDiff = false;
    showWriteProposalForm = false;
    @track writeProposalPreviewData = null;
    @track writeProposalDraftValues = {};
    writeProposalErrorMessage = '';
    writeProposalSuccessMessage = '';
    writeProposalSuccessRecordId = null;
    writeProposalSuccessRecordLabel = '';
    isLoadingWriteProposal = false;

    // Phase 2: Action preview and confirmation
    @api showActionPreview = false;
    @track actionPreviewData = null;
    @api isExecutingAction = false;
    @track actionResultMessage = '';
    @api actionResultRecordIds = [];

    sessionId = null;
    currentAbortController = null;
    currentUserId = null;
    streamingChunkBuffer = '';
    lastRequestBody = null;
    lastExchange = null;
    _pendingPriorContext = null;
    @track selectedModelId = '';
    @track lastModelUsed = '';
    requestSequence = 0;
    activeRequestToken = null;

    @api
    get recordId() {
        return this._recordId;
    }

    set recordId(value) {
        const normalizedValue = value || null;
        const previousRecordId = this._recordId;
        this._recordId = normalizedValue;

        if (previousRecordId && previousRecordId !== normalizedValue) {
            this._resetConversation();
        }
    }

    get modelOptions() {
        return [
            { label: 'Default (Haiku 4.5)', value: '' },
            { label: 'Claude Sonnet 4.6', value: 'us.anthropic.claude-sonnet-4-6' },
            { label: 'Claude Sonnet 4.5', value: 'us.anthropic.claude-sonnet-4-5-20250929-v1:0' },
            { label: 'Claude Sonnet 4', value: 'us.anthropic.claude-sonnet-4-20250514-v1:0' },
            { label: 'Claude Haiku 4.5', value: 'us.anthropic.claude-haiku-4-5-20251001-v1:0' },
            { label: 'Amazon Nova Pro', value: 'us.amazon.nova-pro-v1:0' },
            { label: 'Amazon Nova Lite', value: 'us.amazon.nova-lite-v1:0' },
            { label: 'Mistral Large 3', value: 'mistral.mistral-large-3-675b-instruct' },
            { label: 'Mistral Pixtral Large', value: 'us.mistral.pixtral-large-2502-v1:0' },
            { label: 'MiniMax M2.5', value: 'minimax.minimax-m2.5' },
            { label: 'DeepSeek V3.2', value: 'deepseek.v3.2' },
            { label: 'GLM-5', value: 'zai.glm-5' },
        ];
    }

    handleModelChange(event) {
        this.selectedModelId = event.detail.value;
    }

    renderedCallback() {
        this.ensureFilterAttributes();
        this.ensureButtonLabelAttributes();
    }

    // Computed properties
    get isSubmitDisabled() {
        return !this.queryText || this.queryText.trim().length === 0 || this.isStreaming;
    }

    get hasCitations() {
        return this.citations && this.citations.length > 0;
    }

    get citationsButtonLabel() {
        return 'View Citations (' + this.citations.length + ')';
    }

    /**
     * Check if any citations came from graph traversal (Task 12.3)
     */
    get hasGraphResults() {
        return this.citations && this.citations.some(c => c.fromGraph);
    }

    /**
     * Get count of graph-traversed results (Task 12.3)
     */
    get graphResultCount() {
        if (!this.citations) return 0;
        return this.citations.filter(c => c.fromGraph).length;
    }

    /**
     * Get relationship summary for display (Task 12.3)
     */
    get relationshipSummary() {
        if (!this.hasGraphResults) return null;
        
        const graphCitations = this.citations.filter(c => c.fromGraph);
        const objectTypes = [...new Set(graphCitations.map(c => c.sobject))];
        
        return {
            count: graphCitations.length,
            objectTypes: objectTypes.join(', '),
            message: `Found ${graphCitations.length} result${graphCitations.length !== 1 ? 's' : ''} via relationship traversal across ${objectTypes.length} object type${objectTypes.length !== 1 ? 's' : ''}.`
        };
    }

    get hasClarificationOptions() {
        return this.clarificationOptions && this.clarificationOptions.length > 0;
    }

    get isRecordPage() {
        return !!this._recordId;
    }

    get showConversationThread() {
        return this.isRecordPage && Array.isArray(this.conversationHistory) && this.conversationHistory.length > 1;
    }

    /** Prior exchanges (all except the latest, which is shown in the Answer section).
     *  Each exchange gets a truncated, markdown-stripped answer preview. */
    get priorExchanges() {
        if (!Array.isArray(this.conversationHistory) || this.conversationHistory.length < 2) return [];
        return this.conversationHistory.slice(0, -1).map((ex, idx) => ({
            ...ex,
            turnNumber: idx + 1,
            truncatedAnswer: this._stripAndTruncate(ex.answer, 160)
        }));
    }

    get priorExchangeLabel() {
        const n = this.priorExchanges.length;
        return n === 1 ? '1 prior exchange' : `${n} prior exchanges`;
    }

    /** Strip markdown syntax and truncate for thread preview. */
    _stripAndTruncate(text, maxLen) {
        if (!text) return '';
        let s = text;
        s = s.replace(/^#{1,4}\s+/gm, '');
        s = s.replace(/\*{1,2}(.*?)\*{1,2}/g, '$1');
        s = s.replace(/\|[-:\s|]+\|/g, '');
        s = s.replace(/\|\s*/g, ' ').replace(/\s*\|/g, ' ');
        s = s.replace(/^---+$/gm, '');
        s = s.replace(/\n+/g, ' ').replace(/\s{2,}/g, ' ').trim();
        if (s.length > maxLen) {
            s = s.substring(0, maxLen).replace(/\s+\S*$/, '') + '…';
        }
        return s;
    }

    get formattedAnswer() {
        if (!this.answer) return '';

        let formatted = this.answer;

        // ===== MARKDOWN TO HTML CONVERSION =====

        // Convert headers
        formatted = formatted.replace(/^###\s+(.*?)$/gm, '<h4>$1</h4>');
        formatted = formatted.replace(/^##\s+(.*?)$/gm, '<h3>$1</h3>');
        formatted = formatted.replace(/^#\s+(.*?)$/gm, '<h3>$1</h3>');

        // Convert bold text
        formatted = formatted.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');

        // Convert italic text (single asterisk, avoiding conflicts with bold)
        formatted = formatted.replace(/(?<!\*)\*(?!\*)([^*]+)\*(?!\*)/g, '<em>$1</em>');

        // Convert lists (unified state machine for both numbered and bullet)
        {
            const lines = formatted.split('\n');
            const processedLines = [];
            let listState = null; // null | 'ol' | 'ul'

            for (let i = 0; i < lines.length; i++) {
                const line = lines[i];
                const numberedMatch = line.match(/^(\d+)\.\s+(.*)$/);
                const bulletMatch = line.match(/^-\s+(.*)$/);

                if (numberedMatch) {
                    if (listState === 'ul') processedLines.push('</ul>');
                    if (listState !== 'ol') { processedLines.push('<ol>'); listState = 'ol'; }
                    processedLines.push('<li>' + numberedMatch[2] + '</li>');
                } else if (bulletMatch) {
                    if (listState === 'ol') processedLines.push('</ol>');
                    if (listState !== 'ul') { processedLines.push('<ul>'); listState = 'ul'; }
                    processedLines.push('<li>' + bulletMatch[1] + '</li>');
                } else {
                    if (listState === 'ol') processedLines.push('</ol>');
                    else if (listState === 'ul') processedLines.push('</ul>');
                    listState = null;
                    processedLines.push(line);
                }
            }
            if (listState === 'ol') processedLines.push('</ol>');
            if (listState === 'ul') processedLines.push('</ul>');
            formatted = processedLines.join('\n');
        }

        // ===== MARKDOWN TABLE CONVERSION =====
        formatted = this._convertMarkdownTables(formatted);

        // ===== HYPERLINK CONVERSION (for record names) =====

        // Build name-to-ID map from citations
        const nameToId = {};
        const nameToSObject = {};

        if (this.citations && this.citations.length > 0) {
            const sortedCitations = [...this.citations].sort((a, b) => {
                const scoreA = parseFloat(b.score) || 0;
                const scoreB = parseFloat(a.score) || 0;
                return scoreB - scoreA;
            });

            sortedCitations.forEach(citation => {
                if (citation.title && citation.recordId) {
                    const normalizedTitle = citation.title.trim();
                    if (!nameToId[normalizedTitle]) {
                        nameToId[normalizedTitle] = citation.recordId;
                        nameToSObject[normalizedTitle] = citation.sobject || 'Record';
                    }
                }
            });
        }

        // Replace record names with hyperlinks
        // Sort by length (longest first) to avoid partial matches
        const sortedNames = Object.keys(nameToId).sort((a, b) => b.length - a.length);

        sortedNames.forEach(name => {
            const recordId = nameToId[name];
            const sobject = nameToSObject[name];
            const escapedName = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

            // Case-insensitive matching without strict word boundaries for better flexibility
            const regex = new RegExp('(?<!<[^>]*?)(' + escapedName + ')(?![^<]*?>)', 'gi');

            // lightning-formatted-rich-text only allows absolute URLs (http/https protocol).
            // Relative URLs like /lightning/r/xxx/view get stripped during sanitization.
            // Use window.location.origin to build a full absolute URL.
            const baseUrl = window.location.origin;
            const recordUrl = baseUrl + '/lightning/r/' + recordId + '/view';
            formatted = formatted.replace(regex, (match) => {
                return '<a href="' + recordUrl + '" target="_blank" title="View ' + sobject + ': ' + name + '">' + match + '</a>';
            });
        });

        // Remove any [Source: xxx] patterns
        formatted = formatted.replace(/\[Source:\s*[^\]]+\]/g, '');

        // Wrap paragraphs: split by double newlines, then wrap in <p> tags
        const paragraphs = formatted.split(/\n\n+/);
        formatted = paragraphs.map(para => {
            const trimmed = para.trim();
            if (!trimmed) return '';

            // Don't wrap if already a block element (opening or closing tag)
            if (trimmed.match(/^<(h[1-6]|ul|ol|div|table)/) ||
                trimmed.match(/<\/(ul|ol|h[1-6]|table)>/)) {
                return trimmed;
            }

            // Convert single newlines within paragraph to <br/>
            const withBreaks = trimmed.replace(/\n/g, '<br/>');
            return '<p>' + withBreaks + '</p>';
        }).filter(p => p).join('\n');

        // Clean up extra breaks after block elements
        formatted = formatted.replace(/<\/(h[1-6]|ul|ol|table)><br\/>/g, '</$1>');
        formatted = formatted.replace(/<br\/><(h[1-6]|ul|ol|table)/g, '<$1');
        formatted = formatted.replace(/<\/p>\n<(h[1-6]|ul|ol|table)/g, '</p><$1');
        formatted = formatted.replace(/<\/(h[1-6]|ul|ol|table)>\n<p>/g, '</$1><p>');

        return formatted;
    }

    // Filter UI is hidden — /query endpoint does not accept filter params.
    // Set to true when backend supports filters to re-enable the UI.
    get isFilterUIEnabled() {
        return false;
    }

    get hasActiveFilters() {
        return Boolean(
            this.selectedFilters.region ||
            this.selectedFilters.businessUnit ||
            this.selectedFilters.quarter
        );
    }

    get actionConfirmLabel() {
        return this.isExecutingAction ? 'Executing...' : 'Confirm';
    }

    get actionPreviewTitle() {
        if (!this.actionPreviewData) return '';
        const actionName = this.actionPreviewData.actionName || '';
        return actionName.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
    }

    get actionPreviewFields() {
        if (!this.actionPreviewData || !this.actionPreviewData.inputs) return [];

        return Object.entries(this.actionPreviewData.inputs).map(([key, value]) => {
            return {
                key: key,
                label: key.replace(/([A-Z])/g, ' $1').trim().replace(/^./, str => str.toUpperCase()),
                value: this.formatFieldValue(value),
                rawValue: value
            };
        });
    }

    get hasActionResultRecords() {
        return this.actionResultRecordIds && this.actionResultRecordIds.length > 0;
    }

    get hasWriteProposalDiff() {
        return this.showWriteProposalDiff && this.writeProposalPreviewData && Array.isArray(this.writeProposalPreviewData.fields) && this.writeProposalPreviewData.fields.length > 0;
    }

    get hasWriteProposalForm() {
        return this.showWriteProposalForm && this.writeProposalPreviewData;
    }

    get writeProposalFields() {
        if (!this.writeProposalPreviewData || !Array.isArray(this.writeProposalPreviewData.fields)) {
            return [];
        }
        return this.writeProposalPreviewData.fields.map(field => ({
            ...field,
            proposedValue: Object.prototype.hasOwnProperty.call(this.writeProposalDraftValues, field.apiName)
                ? this.writeProposalDraftValues[field.apiName]
                : field.proposedValue
        }));
    }

    get writeProposalFormTitle() {
        if (!this.writeProposalPreviewData) {
            return 'Edit Proposal';
        }
        const label = this.writeProposalPreviewData.recordLabel || this.writeProposalPreviewData.objectLabel || 'record';
        return `Edit ${label}`;
    }

    get writeProposalDiffTitle() {
        if (!this.writeProposalPreviewData) {
            return 'Review Proposed Changes';
        }
        const label = this.writeProposalPreviewData.recordLabel || this.writeProposalPreviewData.objectLabel || 'record';
        return `Review proposed changes for ${label}`;
    }

    get hasWriteProposalSummary() {
        return !!(this.writeProposalPreviewData && this.writeProposalPreviewData.summary);
    }

    get writeProposalSummary() {
        return this.writeProposalPreviewData && this.writeProposalPreviewData.summary
            ? this.writeProposalPreviewData.summary
            : '';
    }

    get writeProposalRecordId() {
        return this.writeProposalPreviewData ? this.writeProposalPreviewData.recordId : null;
    }

    get writeProposalObjectApiName() {
        return this.writeProposalPreviewData ? this.writeProposalPreviewData.objectApiName : null;
    }

    get regionOptions() {
        return [
            { label: 'None', value: '' },
            { label: 'AMER', value: 'AMER' },
            { label: 'EMEA', value: 'EMEA' },
            { label: 'APAC', value: 'APAC' },
            { label: 'LATAM', value: 'LATAM' }
        ];
    }

    get businessUnitOptions() {
        return [
            { label: 'None', value: '' },
            { label: 'Enterprise', value: 'Enterprise' },
            { label: 'Commercial', value: 'Commercial' },
            { label: 'SMB', value: 'SMB' }
        ];
    }

    get quarterOptions() {
        const currentYear = new Date().getFullYear();
        return [
            { label: 'None', value: '' },
            { label: `Q1 ${currentYear}`, value: `${currentYear}-Q1` },
            { label: `Q2 ${currentYear}`, value: `${currentYear}-Q2` },
            { label: `Q3 ${currentYear}`, value: `${currentYear}-Q3` },
            { label: `Q4 ${currentYear}`, value: `${currentYear}-Q4` },
            { label: `Q1 ${currentYear + 1}`, value: `${currentYear + 1}-Q1` },
            { label: `Q2 ${currentYear + 1}`, value: `${currentYear + 1}-Q2` }
        ];
    }

    // Lifecycle hooks
    connectedCallback() {
        // Generate a session ID for multi-turn conversations
        this.sessionId = this.generateSessionId();

        // Get current user ID
        this.loadCurrentUserId();
    }

    async loadCurrentUserId() {
        try {
            this.currentUserId = await getCurrentUserId();
        } catch (error) {
            console.error('Error loading user ID:', error);
            this.currentUserId = null;
        }
    }

    disconnectedCallback() {
        // Clean up any active streaming connections
        if (this.currentAbortController) {
            this.currentAbortController.abort();
        }
    }

    // Event handlers
    handleQueryChange(event) {
        this.queryText = event.target.value;
    }

    handleKeyDown(event) {
        // Submit on Ctrl+Enter or Cmd+Enter
        if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
            event.preventDefault();
            this.handleSubmit();
        }

        // Close modals on Escape
        if (event.key === 'Escape') {
            if (this.showWriteProposalForm) {
                this.closeWriteProposalForm();
                return;
            }
            if (this.showWriteProposalDiff) {
                this.closeWriteProposalDiff();
                return;
            }
            if (this.showCitationsDrawer) {
                this.toggleCitationsDrawer();
            }
            if (this.showCitationPreview) {
                this.closeCitationPreview();
            }
            if (this.showActionPreview) {
                this.closeActionPreview();
            }
        }
    }

    handleSubmit() {
        if (this.isSubmitDisabled) return;

        // Reset state
        this.answer = '';
        this.citations = [];
        this.clarificationOptions = [];
        if (!this.isRecordPage) {
            this.lastExchange = null;
        }
        this.errorMessage = '';
        this.showRetryButton = false;
        this.showAnswerSection = true;
        this.isStreaming = true;
        this._resetWriteProposalState();

        // Call the answer endpoint
        this.streamAnswer();
    }

    handleClearChat() {
        this._resetConversation();
    }

    handleClarificationClick(event) {
        const query = event.currentTarget.dataset.query;
        if (query) {
            this._pendingPriorContext = this.isRecordPage
                ? null
                : (this.lastExchange
                    ? { query: this.lastExchange.query, answer: this.lastExchange.answer }
                    : null);
            this.queryText = query;
            this.clarificationOptions = [];
            this.handleSubmit();
        }
    }

    handleRetry() {
        // Retry the last request
        if (this.lastRequestBody) {
            this.errorMessage = '';
            this.showRetryButton = false;
            this.isStreaming = true;
            this.showAnswerSection = true;

            this.runAnswerRequest(this.lastRequestBody);
        }
    }

    toggleCitationsDrawer() {
        this.showCitationsDrawer = !this.showCitationsDrawer;
    }

    handleCitationClick(event) {
        // Get citationId from parent citation-item div
        const citationItem = event.target.closest('.citation-item[data-citationid]');
        const citationId = citationItem ? citationItem.dataset.citationid : null;
        const citation = this.citations.find(c => c.id === citationId);

        if (citation) {
            this.openCitationPreview(citation);
        }
    }

    handleAnswerLinkClick(event) {
        // Check if clicked element is a record link
        const recordLink = event.target.closest('.record-link');
        if (recordLink) {
            event.preventDefault();
            event.stopPropagation();

            const recordId = recordLink.dataset.recordid;
            const sobject = recordLink.dataset.sobject;
            const openInNewTab = event.ctrlKey || event.metaKey || event.shiftKey;

            if (recordId) {
                console.log(`Navigating to ${sobject} record: ${recordId}`);
                this.navigateToRecord(recordId, openInNewTab);
            }
        }

        // Also handle old-style citation reference links
        const citationRef = event.target.closest('.citation-reference');
        if (citationRef && citationRef.dataset.recordid) {
            event.preventDefault();
            this.navigateToRecord(citationRef.dataset.recordid);
        }
    }

    handleFilterChange(event) {
        const filterName = event.target.name;
        const filterValue = event.detail.value;

        this.selectedFilters = {
            ...this.selectedFilters,
            [filterName]: filterValue || null
        };
    }

    handleRemoveRegion() {
        this.selectedFilters = {
            ...this.selectedFilters,
            region: null
        };
    }

    handleRemoveBusinessUnit() {
        this.selectedFilters = {
            ...this.selectedFilters,
            businessUnit: null
        };
    }

    handleRemoveQuarter() {
        this.selectedFilters = {
            ...this.selectedFilters,
            quarter: null
        };
    }

    handleClearAllFilters() {
        this.selectedFilters = {
            region: null,
            businessUnit: null,
            quarter: null
        };
    }

    // Core functionality methods
    async streamAnswer() {
        const requestBody = {
            query: this.queryText,
            sessionId: this.sessionId,
            ...(this.recordId ? { recordId: this.recordId } : {}),
            ...(this.selectedModelId ? { modelId: this.selectedModelId } : {}),
            ...(this.isRecordPage && this.conversationHistory.length > 0
                ? { conversationHistory: this.buildConversationHistoryPayload() }
                : {}),
            ...(this._pendingPriorContext ? { priorContext: this._pendingPriorContext } : {})
        };

        // Store for retry
        this.lastRequestBody = requestBody;
        this._pendingPriorContext = null;

        await this.runAnswerRequest(requestBody);
    }

    async runAnswerRequest(requestBody) {
        const requestToken = this.beginRequest();

        try {
            await this.callAnswerEndpoint(requestBody, requestToken);
        } catch (error) {
            if (this.isActiveRequest(requestToken)) {
                this.handleError(error);
            }
        } finally {
            if (this.isActiveRequest(requestToken)) {
                this.isStreaming = false;
                this.currentAbortController = null;
                this.activeRequestToken = null;
            }
        }
    }

    async callAnswerEndpoint(requestBody, requestToken) {
        try {
            // Since Salesforce doesn't support true SSE streaming in LWC,
            // we'll simulate streaming by chunking the response
            const requestBodyJson = JSON.stringify(requestBody);

            // Show skeleton loading state
            this.isStreaming = true;

            // Call Apex method
            const response = await callAnswerEndpoint({ requestBodyJson });

            // Process the response
            if (response && this.isActiveRequest(requestToken)) {
                // Extract answer and citations
                const answerText = response.answer || '';
                const citationsData = response.citations || [];

                // Process citations first so UI elements depending on them render immediately
                this.processCitations(citationsData);

                // Simulate streaming by displaying answer in chunks
                await this.simulateStreaming(answerText, requestToken);
                if (!this.isActiveRequest(requestToken)) {
                    return;
                }

                // Capture model used for display
                if (response.modelId) {
                    this.lastModelUsed = response.modelId;
                }

                // Process clarification options if present
                if (response.clarificationOptions) {
                    this.clarificationOptions = response.clarificationOptions.map((opt, idx) => ({
                        key: 'clarify-' + idx,
                        label: opt.label,
                        query: opt.query
                    }));
                }

                if (this.isRecordPage) {
                    this.conversationHistory = [
                        ...this.conversationHistory,
                        {
                            id: `exchange-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
                            query: requestBody.query,
                            answer: answerText
                        }
                    ];
                    this.queryText = '';
                }

                this.lastExchange = {
                    query: requestBody.query,
                    answer: answerText
                };

                if (response.writeProposal) {
                    await this.prepareWriteProposal(response.writeProposal);
                }

                // Check for special cases
                if (response.reason === 'no_accessible_results') {
                    this.showToast('No Results', 'No results found that you have access to.', 'info');
                } else if (response.reason === 'guardrails_violation') {
                    this.showToast('Policy Violation', 'I cannot provide an answer to that query.', 'warning');
                }
            }

        } catch (error) {
            throw error;
        }
    }

    async simulateStreaming(fullText, requestToken = null) {
        // Simulate streaming by revealing text in chunks
        const chunkSize = 10; // words per chunk
        const words = fullText.split(' ');

        for (let i = 0; i < words.length; i += chunkSize) {
            if (requestToken && !this.isActiveRequest(requestToken)) {
                return;
            }

            const chunk = words.slice(i, i + chunkSize).join(' ');
            this.answer += (this.answer ? ' ' : '') + chunk;

            // Small delay to simulate streaming
            await this.delay(50);
        }
    }

    processCitations(citationsData) {
        console.log('Processing citations:', JSON.stringify(citationsData, null, 2));

        this.citations = citationsData.map((citation, index) => {
            // Process relationship path if present (Task 12.1)
            const relationshipPath = citation.relationshipPath || citation.path || null;
            const hasRelationshipPath = relationshipPath && Array.isArray(relationshipPath) && relationshipPath.length > 1;
            
            // Build path nodes for display
            let relationshipPathNodes = [];
            if (hasRelationshipPath) {
                relationshipPathNodes = relationshipPath.map((pathNode, pathIndex) => {
                    const nodeId = pathNode.nodeId || pathNode.recordId || pathNode.id;
                    const nodeType = pathNode.type || pathNode.sobject || 'Record';
                    const displayName = pathNode.displayName || pathNode.title || pathNode.name || nodeType;
                    
                    return {
                        key: `${index}-path-${pathIndex}`,
                        recordId: nodeId,
                        sobject: nodeType,
                        displayName: this.truncatePathNodeName(displayName),
                        tooltip: `${nodeType}: ${displayName}`,
                        isFirst: pathIndex === 0,
                        isLast: pathIndex === relationshipPath.length - 1
                    };
                });
            }

            // Build display-friendly snippet from available data.
            // /query citations carry only {id, name} from the backend; enrich
            // the snippet from the title so the drawer is not blank.
            const displayTitle = citation.title || citation.name || citation.recordId || citation.id || 'Unknown';
            const displaySnippet = citation.snippet || citation.text
                || (displayTitle !== 'Unknown' ? `Record: ${displayTitle}` : 'No preview available');

            const processed = {
                id: citation.id || 'citation-' + index,
                title: displayTitle,
                recordId: citation.recordId || citation.id,
                sobject: citation.metadata?.sobject || citation.sobject || 'Record',
                score: citation.score ? Number(citation.score).toFixed(2) : null,
                snippet: displaySnippet,
                previewUrl: citation.previewUrl || null,
                // Phase 3: Relationship path data (Task 12.1)
                fromGraph: citation.fromGraph || citation.graphTraversal || hasRelationshipPath,
                hasRelationshipPath: hasRelationshipPath,
                relationshipPathNodes: relationshipPathNodes,
                relationshipPathString: hasRelationshipPath 
                    ? relationshipPathNodes.map(n => n.displayName).join(' → ') 
                    : null
            };
            console.log('Processed citation:', processed.title, '→', processed.recordId, 
                hasRelationshipPath ? `(path: ${processed.relationshipPathString})` : '');
            return processed;
        });

        console.log('Total citations:', this.citations.length);
    }

    async prepareWriteProposal(writeProposal) {
        if (!writeProposal) {
            return;
        }

        this.isLoadingWriteProposal = true;
        this.writeProposalErrorMessage = '';

        try {
            const sanitizedPreview = await previewWriteProposal({
                proposalJson: JSON.stringify(writeProposal)
            });

            if (!sanitizedPreview || !sanitizedPreview.fields || sanitizedPreview.fields.length === 0) {
                throw new Error('Write proposal did not contain any supported fields.');
            }

            this.writeProposalPreviewData = {
                ...sanitizedPreview,
                fields: sanitizedPreview.fields.map(field => ({ ...field }))
            };
            this.writeProposalDraftValues = this.buildWriteProposalDraftValues(this.writeProposalPreviewData.fields);
            this.writeProposalSuccessMessage = '';
            this.writeProposalSuccessRecordId = null;
            this.writeProposalSuccessRecordLabel = '';
            this.showWriteProposalDiff = true;
            this.showWriteProposalForm = false;
        } catch (error) {
            const message = this.extractErrorMessage(error) || 'The proposed edit could not be reviewed.';
            this.showToast('Write Proposal Rejected', message, 'error');
            this._resetWriteProposalState();
        } finally {
            this.isLoadingWriteProposal = false;
        }
    }

    handleWriteProposalEditInForm() {
        if (!this.writeProposalPreviewData) {
            return;
        }

        this.writeProposalErrorMessage = '';
        this.showWriteProposalDiff = false;
        this.showWriteProposalForm = true;
    }

    buildWriteProposalDraftValues(fields) {
        return (Array.isArray(fields) ? fields : []).reduce((draftValues, field) => {
            draftValues[field.apiName] = field.proposedValue;
            return draftValues;
        }, {});
    }

    handleWriteProposalDiffCancel() {
        this._resetWriteProposalState();
    }

    closeWriteProposalDiff() {
        this._resetWriteProposalState();
    }

    handleWriteProposalFormCancel() {
        if (!this.writeProposalPreviewData) {
            this._resetWriteProposalState();
            return;
        }

        this.writeProposalErrorMessage = '';
        this.showWriteProposalForm = false;
        this.showWriteProposalDiff = true;
    }

    closeWriteProposalForm() {
        this._resetWriteProposalState();
    }

    handleWriteProposalFieldChange(event) {
        const apiName = event.target?.dataset?.apiName;
        if (!apiName) {
            return;
        }

        const nextValue = event.detail && Object.prototype.hasOwnProperty.call(event.detail, 'value')
            ? event.detail.value
            : event.target.value;

        this.writeProposalDraftValues = {
            ...this.writeProposalDraftValues,
            [apiName]: nextValue
        };
    }

    handleWriteProposalSubmit(event) {
        event.preventDefault();
        this.writeProposalErrorMessage = '';

        const submittedFields = event.detail?.fields || {};
        const mergedFields = {
            ...submittedFields
        };

        this.writeProposalFields.forEach(field => {
            mergedFields[field.apiName] = Object.prototype.hasOwnProperty.call(this.writeProposalDraftValues, field.apiName)
                ? this.writeProposalDraftValues[field.apiName]
                : field.proposedValue;
        });

        event.target.submit(mergedFields);
    }

    handleWriteProposalSuccess(event) {
        const savedRecordId = event?.detail?.id || this.writeProposalPreviewData?.recordId;
        const recordLabel = this.writeProposalPreviewData?.recordLabel || this.writeProposalPreviewData?.objectLabel || 'record';
        const confirmationMessage = `Confirmed update saved for ${recordLabel}.`;

        this.writeProposalErrorMessage = '';
        this.showWriteProposalForm = false;
        this.showWriteProposalDiff = false;
        this.writeProposalPreviewData = null;
        this.writeProposalDraftValues = {};
        this.writeProposalSuccessRecordId = savedRecordId;
        this.writeProposalSuccessRecordLabel = recordLabel;
        this.writeProposalSuccessMessage = `Successfully updated ${recordLabel}.`;
        this.appendWriteProposalConfirmation(confirmationMessage);

        this.showToast('Record Updated', this.writeProposalSuccessMessage, 'success');
    }

    handleWriteProposalError(event) {
        const message = this.extractWriteProposalError(event) || 'Unable to save the proposed changes.';
        this.writeProposalErrorMessage = message;
        this.showToast('Save Failed', message, 'error');
    }

    handleWriteProposalSuccessRecordClick() {
        if (this.writeProposalSuccessRecordId) {
            this.navigateToRecord(this.writeProposalSuccessRecordId);
        }
    }

    extractWriteProposalError(event) {
        if (!event) {
            return '';
        }

        if (event.detail) {
            if (event.detail.message) {
                return event.detail.message;
            }
            if (event.detail.output && event.detail.output.errors && event.detail.output.errors.length > 0) {
                return event.detail.output.errors[0].message;
            }
            if (event.detail.detail && event.detail.detail.message) {
                return event.detail.detail.message;
            }
        }

        if (event.message) {
            return event.message;
        }

        return '';
    }

    appendWriteProposalConfirmation(message) {
        if (!message) {
            return;
        }

        const nextAnswer = this.answer
            ? `${this.answer}\n\n${message}`
            : message;

        this.answer = nextAnswer;
        this.showAnswerSection = true;

        if (this.lastExchange) {
            this.lastExchange = {
                ...this.lastExchange,
                answer: nextAnswer
            };
        }

        if (this.isRecordPage && Array.isArray(this.conversationHistory) && this.conversationHistory.length > 0) {
            const updatedHistory = [...this.conversationHistory];
            const lastIndex = updatedHistory.length - 1;
            updatedHistory[lastIndex] = {
                ...updatedHistory[lastIndex],
                answer: nextAnswer
            };
            this.conversationHistory = updatedHistory;
        }
    }

    /**
     * Truncate path node name for display (Task 12.1)
     */
    truncatePathNodeName(name) {
        if (!name) return 'Unknown';
        const maxLength = 25;
        if (name.length <= maxLength) return name;
        return name.substring(0, maxLength - 3) + '...';
    }

    /**
     * Handle click on a relationship path node (Task 12.2)
     */
    handlePathNodeClick(event) {
        event.preventDefault();
        event.stopPropagation();
        
        const recordId = event.target.dataset.recordid;
        const sobject = event.target.dataset.sobject;
        const openInNewTab = event.ctrlKey || event.metaKey || event.shiftKey;
        
        if (recordId) {
            console.log(`Navigating to path node: ${sobject} - ${recordId}`);
            this.navigateToRecord(recordId, openInNewTab);
        }
    }

    delay(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    openCitationPreview(citation) {
        this.selectedCitation = citation;

        // If there's a presigned S3 URL, show preview panel
        if (citation.previewUrl) {
            this.showCitationPreview = true;
        } else {
            // Otherwise, navigate directly to the Salesforce record
            this.navigateToRecord(citation.recordId);
        }
    }

    closeCitationPreview() {
        this.showCitationPreview = false;
        this.selectedCitation = null;
    }

    handleViewInSalesforce() {
        if (this.selectedCitation && this.selectedCitation.recordId) {
            this.navigateToRecord(this.selectedCitation.recordId);
        }
    }

    _parseTableRow(line) {
        // Parse a pipe-delimited markdown table row into cells.
        // Trims leading/trailing pipes and whitespace per cell.
        if (!line || !line.includes('|')) return null;
        const stripped = line.replace(/^\|/, '').replace(/\|$/, '');
        return stripped.split('|').map(cell => cell.trim());
    }

    _convertMarkdownTables(text) {
        const lines = text.split('\n');
        const output = [];
        let i = 0;

        while (i < lines.length) {
            // Detect table: current line has pipes and next line is a separator row
            if (
                i + 1 < lines.length &&
                lines[i].includes('|') &&
                lines[i + 1].match(/^\|?[\s-:|]+\|[\s-:|]*\|?$/)
            ) {
                const headerCells = this._parseTableRow(lines[i]);
                if (!headerCells || headerCells.length < 2) {
                    output.push(lines[i]);
                    i++;
                    continue;
                }

                // Skip header and separator rows
                i += 2;

                // Collect data rows
                const dataRows = [];
                while (i < lines.length && lines[i].includes('|')) {
                    const cells = this._parseTableRow(lines[i]);
                    if (cells && cells.length >= 2) {
                        dataRows.push(cells);
                    }
                    i++;
                }

                // Emit HTML table
                let tableHtml = '<table><thead><tr>';
                headerCells.forEach(h => {
                    tableHtml += '<th>' + h + '</th>';
                });
                tableHtml += '</tr></thead><tbody>';
                dataRows.forEach(row => {
                    tableHtml += '<tr>';
                    // Pad or truncate to match header count
                    for (let c = 0; c < headerCells.length; c++) {
                        tableHtml += '<td>' + (row[c] || '') + '</td>';
                    }
                    tableHtml += '</tr>';
                });
                tableHtml += '</tbody></table>';
                output.push(tableHtml);
            } else {
                output.push(lines[i]);
                i++;
            }
        }

        return output.join('\n');
    }

    navigateToRecord(recordId, openInNewTab = false) {
        // Direct absolute URL navigation — bypasses NavigationMixin which
        // fails inside custom Lightning Apps (Ascendix Search).
        if (!recordId) {
            console.warn('navigateToRecord called with empty recordId');
            return;
        }
        const url = `${window.location.origin}/lightning/r/${recordId}/view`;
        window.open(url, '_blank');
    }

    handleCitationReferenceClick(event) {
        // Handle clicks on inline citation references in the answer text
        event.preventDefault();
        const recordId = event.target.dataset.recordid;

        if (recordId) {
            const citation = this.citations.find(c => c.recordId === recordId);
            if (citation) {
                this.openCitationPreview(citation);
            } else {
                // If citation not found in list, navigate directly
                this.navigateToRecord(recordId);
            }
        }
    }

    // Helper methods
    generateSessionId() {
        return `session_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    }

    beginRequest() {
        this.invalidateActiveRequest(false);

        if (typeof AbortController !== 'undefined') {
            this.currentAbortController = new AbortController();
        } else {
            this.currentAbortController = null;
        }

        this.requestSequence += 1;
        this.activeRequestToken = this.requestSequence;
        return this.activeRequestToken;
    }

    invalidateActiveRequest(clearStreamingState = true) {
        this.activeRequestToken = null;

        if (this.currentAbortController) {
            this.currentAbortController.abort();
            this.currentAbortController = null;
        }

        if (clearStreamingState) {
            this.isStreaming = false;
        }
    }

    isActiveRequest(requestToken) {
        return requestToken !== null && requestToken === this.activeRequestToken;
    }

    trimConversationText(text, maxLength) {
        const trimmed = typeof text === 'string' ? text.trim() : '';
        if (!trimmed) return '';
        if (trimmed.length <= maxLength) return trimmed;
        return trimmed.slice(0, maxLength) + '...';
    }

    buildConversationHistoryPayload() {
        const normalizedReversed = [];
        let totalChars = 0;

        for (let i = this.conversationHistory.length - 1; i >= 0; i -= 1) {
            const exchange = this.conversationHistory[i] || {};
            const query = this.trimConversationText(exchange.query, MAX_CONVERSATION_QUERY_CHARS);
            const answer = this.trimConversationText(exchange.answer, MAX_CONVERSATION_ANSWER_CHARS);

            if (!query || !answer) {
                continue;
            }

            const exchangeChars = query.length + answer.length;
            if (totalChars + exchangeChars > MAX_CONVERSATION_CHARS) {
                break;
            }

            normalizedReversed.push({ query, answer });
            totalChars += exchangeChars;

            if (normalizedReversed.length >= MAX_CONVERSATION_TURNS) {
                break;
            }
        }

        normalizedReversed.reverse();
        return normalizedReversed;
    }

    _resetConversation() {
        this.invalidateActiveRequest();
        this.conversationHistory = [];
        this.answer = '';
        this.citations = [];
        this.clarificationOptions = [];
        this.lastExchange = null;
        this.lastRequestBody = null;
        this._pendingPriorContext = null;
        this.errorMessage = '';
        this.showRetryButton = false;
        this.showAnswerSection = false;
        this.queryText = '';
        this.sessionId = this.generateSessionId();
        this.streamingChunkBuffer = '';
        this.lastModelUsed = '';
        this.showCitationsDrawer = false;
        this.showCitationPreview = false;
        this._resetWriteProposalState();
    }

    _resetWriteProposalState() {
        this.showWriteProposalDiff = false;
        this.showWriteProposalForm = false;
        this.writeProposalPreviewData = null;
        this.writeProposalDraftValues = {};
        this.writeProposalErrorMessage = '';
        this.writeProposalSuccessMessage = '';
        this.writeProposalSuccessRecordId = null;
        this.writeProposalSuccessRecordLabel = '';
        this.isLoadingWriteProposal = false;
    }

    getUserId() {
        // Return the loaded user ID
        return this.currentUserId;
    }

    getActiveFilters() {
        const filters = {};

        if (this.selectedFilters.region) {
            filters.region = this.selectedFilters.region;
        }
        if (this.selectedFilters.businessUnit) {
            filters.businessUnit = this.selectedFilters.businessUnit;
        }
        if (this.selectedFilters.quarter) {
            filters.quarter = this.selectedFilters.quarter;
        }

        return Object.keys(filters).length > 0 ? filters : null;
    }

    ensureFilterAttributes() {
        const combos = this.template.querySelectorAll('lightning-combobox[data-filter-name]');
        combos.forEach(combo => {
            const filterName = combo.dataset.filterName;
            if (filterName && combo.getAttribute('name') !== filterName) {
                combo.setAttribute('name', filterName);
            }
        });
    }

    ensureButtonLabelAttributes() {
        const buttons = this.template.querySelectorAll('lightning-button');
        buttons.forEach(button => {
            if (button.label) {
                button.setAttribute('label', button.label);
            }
        });
    }

    extractErrorMessage(error) {
        if (!error) {
            return '';
        }

        if (error.body) {
            if (error.body.message) {
                return error.body.message;
            }
            if (typeof error.body === 'string') {
                return error.body;
            }
        }

        if (error.message) {
            return error.message;
        }

        return '';
    }



    handleError(error) {
        console.error('Error in AI Search:', error);

        let title = 'Error';
        let message = 'An unexpected error occurred. Please try again.';
        let variant = 'error';
        let showRetry = false;

        let rawErrorMessage = '';

        // Extract error message from various possible locations in Apex response
        if (error && error.body) {
            if (error.body.message) {
                rawErrorMessage = error.body.message;
            } else if (error.body.output && error.body.output.errors && error.body.output.errors.length > 0) {
                rawErrorMessage = error.body.output.errors[0].message;
            } else if (typeof error.body === 'string') {
                rawErrorMessage = error.body;
            }
        } else if (error && error.message) {
            rawErrorMessage = error.message;
        }

        if (rawErrorMessage) {
            message = rawErrorMessage; // Use the raw message for debugging
            const errorMsgLower = rawErrorMessage.toLowerCase();

            if (errorMsgLower.includes('access denied')) {
                title = 'Access Denied';
                message = "You don't have permission to view these records.";
                showRetry = false;
            } else if (errorMsgLower.includes('timeout') || errorMsgLower.includes('timed out')) {
                title = 'Request Timeout';
                message = 'The request took too long. Please try again.';
                variant = 'warning';
                showRetry = true;
            } else if (errorMsgLower.includes('no_accessible_results') || errorMsgLower.includes('no results')) {
                title = 'No Results';
                message = 'No results found that you have access to. Try adjusting your query or filters.';
                variant = 'info';
                showRetry = false;
            } else if (errorMsgLower.includes('rate limit')) {
                title = 'Rate Limit Exceeded';
                message = 'Too many requests. Please wait a moment and try again.';
                variant = 'warning';
                showRetry = true;
            } else if (errorMsgLower.includes('network') || errorMsgLower.includes('connection')) {
                title = 'Connection Error';
                message = 'Unable to connect to the service. Please check your connection and try again.';
                variant = 'error';
                showRetry = true;
            } else {
                showRetry = true; // For any other raw error message, still allow retry
            }
        } else {
            // No specific error message found, use generic
            showRetry = true;
        }

        this.errorMessage = message;
        this.showRetryButton = showRetry;
        this.showAnswerSection = false;
        this.showToast(title, message, variant);
    }

    showToast(title, message, variant) {
        const event = new ShowToastEvent({
            title: title,
            message: message,
            variant: variant
        });
        this.dispatchEvent(event);
    }

    // Phase 2: Action preview and confirmation methods

    /**
     * Parse action suggestions from agent responses
     * Expected format in answer: [ACTION:create_opportunity|Name:ACME Deal|Amount:500000|...]
     */
    parseActionSuggestions(answerText) {
        if (!answerText) return null;

        // Look for action markers in the answer
        const actionPattern = /\ \[ACTION:([^\\\]]+)\]/g;
        const matches = answerText.matchAll(actionPattern);

        for (const match of matches) {
            const actionString = match[1];
            const parts = actionString.split('|');

            if (parts.length === 0) continue;

            const actionName = parts[0];
            const inputs = {};

            // Parse key:value pairs
            for (let i = 1; i < parts.length; i++) {
                const [key, ...valueParts] = parts[i].split(':');
                if (key && valueParts.length > 0) {
                    inputs[key] = valueParts.join(':').trim();
                }
            }

            // Return first action found
            return {
                actionName: actionName,
                inputs: inputs
            };
        }

        return null;
    }

    /**
     * Show action preview modal with proposed changes
     */
    @api
    showActionPreviewModal(actionData) {
        if (!actionData || !actionData.actionName || !actionData.inputs) {
            console.error('Invalid action data for preview');
            return;
        }

        this.actionPreviewData = {
            actionName: actionData.actionName,
            inputs: actionData.inputs,
            confirmationToken: this.generateConfirmationToken(actionData.actionName, actionData.inputs)
        };
        this.showActionPreview = true;
    }

    /**
     * Close action preview modal
     */
    closeActionPreview() {
        this.showActionPreview = false;
        this.actionPreviewData = null;
        this.isExecutingAction = false;
    }

    /**
     * Handle cancel button in action preview
     */
    handleActionCancel() {
        this.closeActionPreview();
        this.showToast('Action Cancelled', 'The proposed action was not executed.', 'info');
    }

    /**
     * Generate confirmation token (hash of action + inputs + timestamp)
     */
    @api
    generateConfirmationToken(actionName, inputs) {
        const timestamp = Date.now();
        const data = JSON.stringify({ actionName, inputs, timestamp });

        // Simple hash for POC - production should use proper signing
        let hash = 0;
        for (let i = 0; i < data.length; i++) {
            const char = data.charCodeAt(i);
            hash = ((hash << 5) - hash) + char;
            hash = hash & hash; // Convert to 32bit integer
        }

        return `token_${Math.abs(hash)}_${timestamp}`;
    }

    /**
     * Format field value for display
     */
    formatFieldValue(value) {
        if (value === null || value === undefined) {
            return '(empty)';
        }

        if (typeof value === 'boolean') {
            return value ? 'Yes' : 'No';
        }

        if (typeof value === 'number') {
            // Format currency if it looks like a money amount
            if (value >= 1000) {
                return new Intl.NumberFormat('en-US', {
                    style: 'currency',
                    currency: 'USD'
                }).format(value);
            }
            return value.toString();
        }

        if (typeof value === 'object') {
            return JSON.stringify(value, null, 2);
        }

        return String(value);
    }

    /**
     * Handle action confirmation - call /action endpoint with token
     */
    async handleActionConfirm() {
        if (!this.actionPreviewData) {
            this.showToast('Error', 'No action data available', 'error');
            return;
        }

        this.isExecutingAction = true;
        this.actionResultMessage = '';
        this.actionResultRecordIds = [];

        try {
            const actionName = this.actionPreviewData.actionName;
            const requestBody = {
                actionName: actionName,
                inputs: this.actionPreviewData.inputs,
                salesforceUserId: this.getUserId(),
                sessionId: this.sessionId,
                confirmationToken: this.actionPreviewData.confirmationToken
            };

            const requestBodyJson = JSON.stringify(requestBody);

            // Call the /action endpoint via Apex
            const response = await callActionEndpoint({ requestBodyJson });

            // Handle success
            if (response && response.success) {
                const recordIds = response.recordIds || [];
                this.actionResultRecordIds = recordIds;

                // Close preview modal
                this.closeActionPreview();

                // Show success message with record links
                this.handleActionSuccess(recordIds, actionName);
            } else {
                // Unexpected response format
                throw new Error('Invalid response from action endpoint');
            }

        } catch (error) {
            this.handleActionError(error);
        } finally {
            this.isExecutingAction = false;
        }
    }

    /**
     * Handle successful action execution
     */
    handleActionSuccess(recordIds, actionName) {
        const safeName = actionName || 'action';
        const actionTitle = safeName.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());

        if (recordIds && recordIds.length > 0) {
            // Show success toast with record link
            const recordId = recordIds[0];
            const message = `Successfully executed ${actionTitle}. Record ID: ${recordId}`;

            this.showToast('Action Completed', message, 'success');

            // Store record IDs for potential navigation
            this.actionResultRecordIds = recordIds;

            // Optionally navigate to the created/updated record
            if (recordIds.length === 1) {
                this.navigateToRecord(recordId);
            }
        } else {
            this.showToast('Action Completed', `Successfully executed ${actionTitle}`, 'success');
        }
    }

    /**
     * Handle action execution error
     */
    handleActionError(error) {
        console.error('Error executing action:', error);

        let title = 'Action Failed';
        let message = 'An error occurred while executing the action.';
        let showRetry = false;

        if (error.message) {
            const errorMsg = error.message.toLowerCase();

            if (errorMsg.includes('rate limit') || errorMsg.includes('daily limit')) {
                title = 'Rate Limit Exceeded';
                message = error.message;
                showRetry = false;

                // Extract rate limit info if available
                const match = errorMsg.match(/limit of (\d+)/);
                if (match) {
                    const limit = match[1];
                    message = `You've reached the daily limit of ${limit} for this action. Try again tomorrow.`;
                }
            } else if (errorMsg.includes('temporarily unavailable') || errorMsg.includes('disabled')) {
                title = 'Action Unavailable';
                message = 'This action is temporarily unavailable. Please try again later.';
                showRetry = false;
            } else if (errorMsg.includes('validation')) {
                title = 'Validation Error';
                message = error.message;
                showRetry = false;
            } else if (errorMsg.includes('permission') || errorMsg.includes('access denied')) {
                title = 'Permission Denied';
                message = 'You don\'t have permission to execute this action.';
                showRetry = false;
            } else if (errorMsg.includes('timeout')) {
                title = 'Timeout';
                message = 'The action took too long to execute. Please try again.';
                showRetry = true;
            } else {
                message = error.message;
                showRetry = true;
            }
        }

        this.actionResultMessage = message;
        this.showToast(title, message, 'error');

        // Keep modal open on error so user can see what went wrong
        // They can retry or cancel
    }

    /**
     * Handle viewing an action result record
     */
    handleViewActionRecord(event) {
        // Get recordId from parent span element
        const spanElement = event.target.closest('span[data-recordid]');
        const recordId = spanElement ? spanElement.dataset.recordid : null;
        if (recordId) {
            this.navigateToRecord(recordId);
        }
    }

    /**
     * Navigate to a Salesforce record (with optional object type hint).
     */
    navigateToRecordWithObjectType(recordId, objectApiName) {
        // Reuse the direct-URL approach for consistency
        this.navigateToRecord(recordId);
    }
}
