import { useQuery } from "@tanstack/react-query";
import { api, type ItemsResponse } from "@/lib/api";

export function useItems() {
  return useQuery<ItemsResponse>({
    queryKey: ["items"],
    queryFn: () => api.items(),
  });
}
