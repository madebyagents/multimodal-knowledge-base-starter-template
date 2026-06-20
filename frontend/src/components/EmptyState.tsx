import { type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

interface EmptyStateProps {
  icon?: LucideIcon;
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "surface-card flex flex-col items-center justify-center rounded-lg border border-dashed bg-muted/30 px-6 py-12 text-center",
        className,
      )}
    >
      {Icon && (
        <div className="mb-3 rounded-full border border-primary/20 bg-primary/10 p-3 shadow-sm">
          <Icon className="h-6 w-6 text-primary" />
        </div>
      )}
      <h3 className="max-w-full break-words text-sm font-semibold">{title}</h3>
      {description && (
        <p className="mt-1 max-w-sm break-words text-sm text-muted-foreground">
          {description}
        </p>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
