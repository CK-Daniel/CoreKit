import React from "react";
import { useSelector } from "react-redux";
import { useTranslation } from "react-i18next";
import { RUNTIME_INACTIVE_STATES } from "#/types/agent-state";
import { ExplorerTree } from "#/components/features/file-explorer/explorer-tree";
import toast from "#/utils/toast";
import { RootState } from "#/store";
import { I18nKey } from "#/i18n/declaration";
import { useListFiles } from "#/hooks/query/use-list-files";
import { cn } from "#/utils/utils";
import { FileExplorerHeader } from "./file-explorer-header";
import { useVSCodeUrl } from "#/hooks/query/use-vscode-url";
import { useConversation } from "#/context/conversation-context"; // Import the context hook
import { useUserConversation } from "#/hooks/query/use-user-conversation"; // Import hook to fetch conversation data
import { BrandButton } from "../settings/brand-button";
import VSCodeIcon from "#/assets/vscode-alt.svg?react";

interface FileExplorerProps {
  isOpen: boolean;
  onToggle: () => void;
}

export function FileExplorer({ isOpen, onToggle }: FileExplorerProps) {
  const { t } = useTranslation();
  const { conversationId } = useConversation(); // Get conversationId from context
  const { data: conversationData } = useUserConversation(conversationId); // Fetch conversation details

  const { curAgentState } = useSelector((state: RootState) => state.agent);

  const { data: paths, refetch, error } = useListFiles();
  const { data: vscodeUrl } = useVSCodeUrl({
    enabled: !RUNTIME_INACTIVE_STATES.includes(curAgentState),
  });

  const handleOpenVSCode = () => {
    if (vscodeUrl?.vscode_url) {
      window.open(vscodeUrl.vscode_url, "_blank");
    } else if (vscodeUrl?.error) {
      toast.error(
        `open-vscode-error-${new Date().getTime()}`,
        t(I18nKey.EXPLORER$VSCODE_SWITCHING_ERROR_MESSAGE, {
          error: vscodeUrl.error,
        }),
      );
    }
  };

  const refreshWorkspace = () => {
    if (!RUNTIME_INACTIVE_STATES.includes(curAgentState)) {
      refetch();
    }
  };

  React.useEffect(() => {
    refreshWorkspace();
  }, [curAgentState]);

  return (
    <div data-testid="file-explorer" className="relative h-full">
      <div
        className={cn(
          "bg-base-secondary h-full border-r-1 border-r-neutral-600 flex flex-col",
          !isOpen ? "w-12" : "w-60",
        )}
      >
        <div className="flex flex-col relative h-full px-3 py-2 overflow-hidden">
          <FileExplorerHeader
            isOpen={isOpen}
            onToggle={onToggle}
            onRefreshWorkspace={refreshWorkspace}
            workspacePath={conversationData?.host_conversation_path} // Pass the fetched path
          />
          {!error && (
            <div className="overflow-auto flex-grow min-h-0">
              <div style={{ display: !isOpen ? "none" : "block" }}>
                <ExplorerTree files={paths || []} />
              </div>
            </div>
          )}
          {error && (
            <div className="flex flex-col items-center justify-center h-full">
              <p className="text-neutral-300 text-sm">{error.message}</p>
            </div>
          )}
          {isOpen && (
            <BrandButton
              testId="open-vscode-button"
              type="button"
              variant="secondary"
              className="w-full text-content border-content"
              isDisabled={RUNTIME_INACTIVE_STATES.includes(curAgentState)}
              onClick={handleOpenVSCode}
              startContent={<VSCodeIcon width={20} height={20} />}
            >
              {t(I18nKey.VSCODE$OPEN)}
            </BrandButton>
          )}
        </div>
      </div>
    </div>
  );
}
