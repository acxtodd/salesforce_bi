export const ShowToastEventName = 'lightning__showtoast';

export class ShowToastEvent extends CustomEvent {
    constructor(config) {
        super(ShowToastEventName, {
            composed: true,
            cancelable: true,
            bubbles: true,
            detail: config
        });
    }
}
