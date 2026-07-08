import { useQuery } from "@tanstack/react-query";
import { api, type Stats } from "@/lib/api";

export function useStats() {
  return useQuery<Stats>({
    queryKey: ["stats"],
    queryFn: api.stats,
    refetchInterval: (query) => (query.state.data ? false : 2_000),
    refetchOnWindowFocus: true,
    retry: 3,
  });
}
