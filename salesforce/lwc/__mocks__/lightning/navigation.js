const NAVIGATE_SYMBOL = Symbol.for('lightning/navigation:Navigate');

export const NavigationMixin = (Base) => {
    return class extends Base {
        [NAVIGATE_SYMBOL](pageReference, replace) {
            // Mock implementation
            this._navigatePageReference = pageReference;
            this._navigateReplace = replace;
        }
    };
};

NavigationMixin.Navigate = NAVIGATE_SYMBOL;
