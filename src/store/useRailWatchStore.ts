import { useStore } from "zustand";
import { railwatchStore, type RailWatchStore } from "./railwatchStore";

export function useRailWatchStore<T>(selector: (state: RailWatchStore) => T): T {
  return useStore(railwatchStore, selector);
}
