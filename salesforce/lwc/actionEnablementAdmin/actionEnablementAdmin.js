import { LightningElement, track, wire, api } from "lwc";
import { ShowToastEvent } from "lightning/platformShowToastEvent";
import { refreshApex } from "@salesforce/apex";
import getActionEnablements from "@salesforce/apex/ActionEnablementController.getActionEnablements";
import updateActionEnablement from "@salesforce/apex/ActionEnablementController.updateActionEnablement";
import testAction from "@salesforce/apex/ActionEnablementController.testAction";

const COLUMNS = [
  {
    label: "Action Name",
    fieldName: "ActionName__c",
    type: "text",
    editable: false,
  },
  {
    label: "Enabled",
    fieldName: "Enabled__c",
    type: "boolean",
    editable: true,
  },
  {
    label: "Max Per User Per Day",
    fieldName: "MaxPerUserPerDay__c",
    type: "number",
    editable: true,
  },
  {
    label: "Override Active",
    fieldName: "HasOverride",
    type: "boolean",
    editable: false,
  },
  {
    label: "Requires Confirmation",
    fieldName: "RequiresConfirm__c",
    type: "boolean",
    editable: false,
  },
  {
    label: "Flow Name",
    fieldName: "FlowName__c",
    type: "text",
    editable: false,
  },
];

export default class ActionEnablementAdmin extends LightningElement {
  @api title;
  @track actions = [];
  @track draftValues = [];
  @track isLoading = false;
  @track selectedActionName = "";
  wiredActionsResult;

  columns = COLUMNS;

  @wire(getActionEnablements)
  wiredActions(result) {
    this.wiredActionsResult = result;
    const { error, data } = result;

    if (data) {
      this.actions = data.map((action) => ({
        ...action,
        Id: action.ActionName__c, // Use ActionName as unique identifier
      }));
      this.isLoading = false;
    } else if (error) {
      this.showToast(
        "Error",
        "Failed to load action enablements: " +
        (error.body?.message || error.message),
        "error",
      );
      this.isLoading = false;
    }
  }

  handleSave(event) {
    this.isLoading = true;
    const draftValues = event.detail.draftValues;

    // Process each draft value
    const updatePromises = draftValues.map((draft) => {
      const actionToUpdate = {
        ActionName__c: draft.Id, // Use ActionName__c instead of DeveloperName
      };

      // Only include fields that were actually edited (not undefined)
      if (draft.Enabled__c !== undefined) {
        actionToUpdate.Enabled__c = draft.Enabled__c;
      }

      if (draft.MaxPerUserPerDay__c !== undefined) {
        actionToUpdate.MaxPerUserPerDay__c = draft.MaxPerUserPerDay__c;
      }

      return updateActionEnablement({ actionData: actionToUpdate });
    });

    Promise.all(updatePromises)
      .then((results) => {
        // Check for success
        const allSuccessful = results.every((r) => r.success);

        if (allSuccessful) {
          this.showToast(
            "Success",
            "Action enablement settings updated successfully. Changes take effect immediately.",
            "success",
          );
        } else {
          const failedResults = results.filter((r) => !r.success);
          this.showToast(
            "Partial Success",
            "Some updates failed: " +
            failedResults.map((r) => r.message).join(", "),
            "warning",
          );
        }

        this.draftValues = [];
        // Refresh the data
        return refreshApex(this.wiredActionsResult);
      })
      .then(() => {
        this.isLoading = false;
      })
      .catch((error) => {
        const errorMessage =
          error.body?.message || error.message || "Unknown error";
        this.showToast(
          "Error",
          "Failed to update action enablements: " + errorMessage,
          "error",
        );
        this.isLoading = false;
      });
  }

  handleRowSelection(event) {
    const selectedRows = event.detail.selectedRows;
    if (selectedRows.length > 0) {
      this.selectedActionName = selectedRows[0].ActionName__c;
    } else {
      this.selectedActionName = "";
    }
  }

  handleTestAction() {
    if (!this.selectedActionName) {
      this.showToast("Warning", "Please select an action to test", "warning");
      return;
    }

    this.isLoading = true;
    testAction({ actionName: this.selectedActionName })
      .then((result) => {
        if (result.success) {
          this.showToast(
            "Success",
            "Action test completed successfully: " + result.message,
            "success",
          );
        } else {
          this.showToast("Test Failed", result.message, "warning");
        }
        this.isLoading = false;
      })
      .catch((error) => {
        this.showToast(
          "Error",
          "Failed to test action: " + (error.body?.message || error.message),
          "error",
        );
        this.isLoading = false;
      });
  }

  get isTestDisabled() {
    return !this.selectedActionName || this.isLoading;
  }

  showToast(title, message, variant, mode = "dismissable") {
    const event = new ShowToastEvent({
      title: title,
      message: message,
      variant: variant,
      mode: mode,
    });
    this.dispatchEvent(event);
  }
}
