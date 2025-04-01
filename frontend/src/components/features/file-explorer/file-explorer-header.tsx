import { useTranslation } from "react-i18next";
import { I18nKey } from "#/i18n/declaration";
import { cn } from "#/utils/utils";
import { ExplorerActions } from "./file-explorer-actions";

interface FileExplorerHeaderProps {
  isOpen: boolean;
  onToggle: () => void;
  onRefreshWorkspace: () => void;
  workspacePath?: string; // Added prop for dynamic path
}

export function FileExplorerHeader({
  isOpen,
  onToggle,
  onRefreshWorkspace,
  workspacePath, // Destructure new prop
}: FileExplorerHeaderProps) {
  const { t } = useTranslation();

  return (
    <div
      className={cn(
        "sticky top-0 bg-base-secondary",
        "flex items-center",
        !isOpen ? "justify-center" : "justify-between",
      )}
    >
      {/* Display dynamic path if available and open, otherwise default label */}
      {isOpen && (
        <div className="text-neutral-300 font-bold text-sm truncate" title={workspacePath}>
          {workspacePath ? workspacePath : t(I18nKey.EXPLORER$LABEL_WORKSPACE)}
        </div>
      )}
      <ExplorerActions
        isHidden={!isOpen}
        toggleHidden={onToggle}
        onRefresh={onRefreshWorkspace}
      />
    </div>
  );
}
