import { useLocation } from "react-router";
import { useTranslation } from "react-i18next";
import React from "react";
import posthog from "posthog-js";
import { I18nKey } from "#/i18n/declaration";
import { organizeModelsAndProviders } from "#/utils/organize-models-and-providers";
import { DangerModal } from "../confirmation-modals/danger-modal";
import { extractSettings } from "#/utils/settings-utils";
import { useEndSession } from "#/hooks/use-end-session";
import { ModalBackdrop } from "../modal-backdrop";
import { ModelSelector } from "./model-selector";
import { Settings } from "#/types/settings";
import { BrandButton } from "#/components/features/settings/brand-button";
import { KeyStatusIcon } from "#/components/features/settings/key-status-icon";
import { SettingsInput } from "#/components/features/settings/settings-input";
import { HelpLink } from "#/components/features/settings/help-link";
import { useSaveSettings } from "#/hooks/mutation/use-save-settings";

interface SettingsFormProps {
  settings: Settings;
  models: string[];
  onClose: () => void;
}

export function SettingsForm({ settings, models, onClose }: SettingsFormProps) {
  const { mutate: saveUserSettings } = useSaveSettings();
  const endSession = useEndSession();

  const location = useLocation();
  const { t } = useTranslation();

  const formRef = React.useRef<HTMLFormElement>(null);

  const [confirmEndSessionModalOpen, setConfirmEndSessionModalOpen] =
    React.useState(false);

  const resetOngoingSession = () => {
    if (location.pathname.startsWith("/conversations/")) {
      endSession();
    }
  };

  const handleFormSubmission = async (formData: FormData) => {
    const newSettings = extractSettings(formData);

    await saveUserSettings(newSettings, {
      onSuccess: () => {
        onClose();
        resetOngoingSession();

        posthog.capture("settings_saved", {
          LLM_MODEL: newSettings.LLM_MODEL,
          LLM_API_KEY: newSettings.LLM_API_KEY ? "SET" : "UNSET",
          REMOTE_RUNTIME_RESOURCE_FACTOR:
            newSettings.REMOTE_RUNTIME_RESOURCE_FACTOR,
        });
      },
    });
  };

  const handleConfirmEndSession = () => {
    const formData = new FormData(formRef.current ?? undefined);
    handleFormSubmission(formData);
  };

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);

    if (location.pathname.startsWith("/conversations/")) {
      setConfirmEndSessionModalOpen(true);
    } else {
      handleFormSubmission(formData);
    }
  };

  const isLLMKeySet = settings.LLM_API_KEY === "**********";

  return (
    <div>
      <form
        ref={formRef}
        data-testid="settings-form"
        className="flex flex-col gap-6"
        onSubmit={handleSubmit}
      >
        <div className="flex flex-col gap-4">
          <ModelSelector
            models={organizeModelsAndProviders(models)}
            currentModel={settings.LLM_MODEL}
          />

          <SettingsInput
            testId="llm-api-key-input"
            name="llm-api-key-input"
            label="API Key"
            type="password"
            className="w-[680px]"
            placeholder={isLLMKeySet ? "<hidden>" : ""}
            startContent={isLLMKeySet && <KeyStatusIcon isSet={isLLMKeySet} />}
          />

          <HelpLink
            testId="llm-api-key-help-anchor"
            text="Don't know your API key?"
            linkText="Click here for instructions"
            href="https://docs.all-hands.dev/modules/usage/installation#getting-an-api-key"
          />
        </div>

        {/* Workspace Base Directory Input */}
        <div className="flex flex-col gap-4 border-t border-neutral-600 pt-4">
          <SettingsInput
            testId="workspace-base-input"
            name="workspace-base-input"
            label="Workspaces Base Directory"
            type="text"
            className="w-[680px]"
            placeholder="e.g., /path/to/your/openhands_workspaces"
            defaultValue={settings.WORKSPACE_BASE || ""}
          />
           <HelpLink
            testId="workspace-base-help-anchor"
            text="This is the parent directory where folders for each conversation will be created."
            linkText=""
            href=""
          />
        </div>

        <div className="flex flex-col gap-2">
          <BrandButton
            testId="save-settings-button"
            type="submit"
            variant="primary"
            className="w-full"
          >
            {t(I18nKey.BUTTON$SAVE)}
          </BrandButton>
        </div>
      </form>

      {confirmEndSessionModalOpen && (
        <ModalBackdrop>
          <DangerModal
            title={t(I18nKey.MODAL$END_SESSION_TITLE)}
            description={t(I18nKey.MODAL$END_SESSION_MESSAGE)}
            buttons={{
              danger: {
                text: t(I18nKey.BUTTON$END_SESSION),
                onClick: handleConfirmEndSession,
              },
              cancel: {
                text: t(I18nKey.BUTTON$CANCEL),
                onClick: () => setConfirmEndSessionModalOpen(false),
              },
            }}
          />
        </ModalBackdrop>
      )}
    </div>
  );
}
