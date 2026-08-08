import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "sonner";

import App from "./App";
import { queryClient } from "./lib/queryClient";
import { ThemeProvider } from "./components/theme-provider";
import { ErrorBoundary } from "./components/ErrorBoundary";
import "./index.css";

const root = document.getElementById("root");
if (!root) throw new Error("Missing #root element");
const showQueryDevtools = import.meta.env.VITE_SHOW_QUERY_DEVTOOLS === "true";

ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <ErrorBoundary>
          <App />
        </ErrorBoundary>
        <Toaster richColors closeButton position="top-right" />
        {showQueryDevtools ? <QueryDevtools /> : null}
      </QueryClientProvider>
    </ThemeProvider>
  </React.StrictMode>,
);

function QueryDevtools() {
  const Devtools = React.lazy(() =>
    import("@tanstack/react-query-devtools").then((m) => ({
      default: m.ReactQueryDevtools,
    })),
  );
  return (
    <React.Suspense fallback={null}>
      <Devtools initialIsOpen={false} buttonPosition="bottom-left" />
    </React.Suspense>
  );
}
