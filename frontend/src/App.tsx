import {
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { MessageSquare, FolderOpen, Network, Search } from "lucide-react";
import { Sidebar } from "@/components/Sidebar";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { SearchPanel, type SearchPanelHandle } from "@/components/SearchPanel";
import { ChatPanel } from "@/components/ChatPanel";
import { LibraryPanel } from "@/components/LibraryPanel";
import { GraphPanel } from "@/components/GraphPanel";
import { useChatWorkspace } from "@/hooks/useChatWorkspace";

type TabKey = "search" | "chat" | "library" | "graph";

const SIDEBAR_WIDTH_KEY = "dante-dashboard-sidebar-width";

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function readStoredNumber(key: string, fallback: number, min: number, max: number) {
  if (typeof window === "undefined") return fallback;
  const stored = Number(window.localStorage.getItem(key));
  return Number.isFinite(stored) ? clamp(stored, min, max) : fallback;
}

export default function App() {
  const [tab, setTab] = useState<TabKey>("search");
  const [sidebarWidth, setSidebarWidth] = useState(() =>
    readStoredNumber(SIDEBAR_WIDTH_KEY, 320, 260, 480),
  );
  const searchRef = useRef<SearchPanelHandle>(null);
  const chatWorkspace = useChatWorkspace();

  useEffect(() => {
    window.localStorage.setItem(SIDEBAR_WIDTH_KEY, String(sidebarWidth));
  }, [sidebarWidth]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setTab("search");
        // focus after the tab is mounted
        setTimeout(() => searchRef.current?.focus(), 0);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const startSidebarResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (window.innerWidth < 768) return;
    event.preventDefault();

    const startX = event.clientX;
    const startWidth = sidebarWidth;

    const onMove = (moveEvent: PointerEvent) => {
      const nextWidth = startWidth + moveEvent.clientX - startX;
      setSidebarWidth(clamp(nextWidth, 260, 480));
    };

    const onUp = () => {
      document.body.classList.remove("is-resizing-panel");
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };

    document.body.classList.add("is-resizing-panel");
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  };

  return (
    <div className="app-shell flex h-screen flex-col overflow-hidden bg-background md:flex-row">
      <Sidebar
        width={sidebarWidth}
        onResizeStart={startSidebarResize}
        workspace={chatWorkspace}
      />
      <main className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
        <Tabs
          value={tab}
          defaultValue="search"
          onValueChange={(v) => setTab(v as TabKey)}
          className="flex h-full min-w-0 flex-col gap-0"
        >
          <div className="app-topbar app-window-drag comfortable-scrollbar flex items-center justify-between gap-3 overflow-x-auto border-b px-4 py-3 md:px-6">
            <TabsList>
              <TabsTrigger value="search">
                <Search className="h-4 w-4" /> Search
              </TabsTrigger>
              <TabsTrigger value="chat">
                <MessageSquare className="h-4 w-4" /> Chat
              </TabsTrigger>
              <TabsTrigger value="library">
                <FolderOpen className="h-4 w-4" /> Library
              </TabsTrigger>
              <TabsTrigger value="graph">
                <Network className="h-4 w-4" /> Graph
              </TabsTrigger>
            </TabsList>
            <div className="hidden text-xs text-muted-foreground sm:block">
              <kbd className="rounded border bg-muted px-1.5 py-0.5 font-mono text-[10px]">
                ⌘K
              </kbd>{" "}
              to focus search
            </div>
          </div>

          <div className="app-content comfortable-scrollbar flex-1 overflow-y-auto p-4 md:p-6">
            <TabsContent value="search" className="h-full">
              <SearchPanel ref={searchRef} />
            </TabsContent>
            <TabsContent value="chat" className="h-full">
              <ChatPanel workspace={chatWorkspace} />
            </TabsContent>
            <TabsContent value="library" className="h-full">
              <LibraryPanel />
            </TabsContent>
            <TabsContent value="graph" className="h-full">
              <GraphPanel />
            </TabsContent>
          </div>
        </Tabs>
      </main>
    </div>
  );
}
