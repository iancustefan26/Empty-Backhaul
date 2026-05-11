import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/** Standard `cn()` helper used by all dispatch components. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
