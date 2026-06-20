import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, apiErrorMessage, type ItemsResponse } from "@/lib/api";

export function useDeleteItem() {
  const qc = useQueryClient();
  return useMutation<
    { deleted: number },
    Error,
    string,
    { prev: ItemsResponse | undefined }
  >({
    mutationFn: (fileId) => api.deleteItem(fileId),
    onMutate: async (fileId) => {
      await qc.cancelQueries({ queryKey: ["items"] });
      const prev = qc.getQueryData<ItemsResponse>(["items"]);
      qc.setQueryData<ItemsResponse>(["items"], (old) =>
        old
          ? {
              ...old,
              items: old.items.filter((i) => i.file_id !== fileId),
              returned: Math.max(0, old.returned - 1),
              total: Math.max(0, old.total - 1),
            }
          : old,
      );
      return { prev };
    },
    onError: (err, _id, ctx) => {
      if (ctx?.prev) qc.setQueryData(["items"], ctx.prev);
      toast.error(`Delete failed: ${apiErrorMessage(err)}`);
    },
    onSuccess: () => {
      toast.success("Deleted");
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["items"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
    },
  });
}
