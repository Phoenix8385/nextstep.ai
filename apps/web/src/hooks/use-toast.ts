/**
 * Minimal toast store. `toast({...})` from anywhere; `<Toaster />` renders them.
 * Toasts can carry one inline action button (used for "Mark as Applied").
 */

import { create } from "zustand";

export interface ToastAction {
  label: string;
  onClick: () => void | Promise<void>;
}

export interface ToastOptions {
  title: string;
  description?: string;
  action?: ToastAction;
  variant?: "default" | "success" | "error";
  /** Milliseconds before auto-dismiss; `0` keeps it open until closed. */
  duration?: number;
}

export interface ToastItem extends ToastOptions {
  id: string;
  open: boolean;
}

interface ToastState {
  toasts: ToastItem[];
  add: (options: ToastOptions) => string;
  dismiss: (id: string) => void;
  remove: (id: string) => void;
}

const MAX_TOASTS = 4;
let counter = 0;

export const useToastStore = create<ToastState>((set) => ({
  toasts: [],
  add: (options) => {
    const id = `toast-${++counter}`;
    set((state) => ({
      toasts: [...state.toasts, { id, open: true, duration: 8000, ...options }].slice(-MAX_TOASTS),
    }));
    return id;
  },
  dismiss: (id) =>
    set((state) => ({
      toasts: state.toasts.map((t) => (t.id === id ? { ...t, open: false } : t)),
    })),
  remove: (id) => set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) })),
}));

/** Show a toast; returns its id so it can be dismissed programmatically. */
export function toast(options: ToastOptions): string {
  return useToastStore.getState().add(options);
}

export function dismissToast(id: string): void {
  useToastStore.getState().dismiss(id);
}
